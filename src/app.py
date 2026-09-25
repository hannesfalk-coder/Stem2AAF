"""
Stem2AAF menu bar app (macOS only), stems-only.

Runs quietly in the menu bar. Watches one folder for stem exports
(File -> Export Audio...) and, when you click "Convert to AAF", batches
whatever has arrived into an .aaf file. Conversions are written to the
watched folder by default, or to a separate output folder if one is set
in Settings.

Conversion normally happens when you click it. Auto-convert, off by
default, will also fire once the number of waiting stems has held steady
long enough - see _poll_folder. Either path refuses to build an AAF from
a batch where any file is still being written, so an incomplete export
produces an error rather than an AAF quietly missing tracks.

Build into a double-clickable .app with `python3 setup.py py2app` (see
setup.py in this folder) - that step must be run on a Mac. To remove it
later, use Settings -> Application -> Uninstall, which runs the uninstall
script bundled in Contents/Resources.
"""

import datetime
import os
import subprocess

import rumps
from AppKit import NSBundle

import config
from config import AUTO_CONVERT_QUIET_SECONDS
from settings_window import DEFAULT_CATEGORIES, SettingsWindow
from watcher import Watcher

LOG_FILENAME = "Stem2AAF_log.txt"

# How often the menu-bar app looks at the watched folder, in seconds. Drives
# both the "(N waiting)" label and the auto-convert quiet check.
POLL_SECONDS = 2

UNINSTALL_SCRIPT_NAME = "uninstall.sh"

BUNDLE_ID = "com.local.stem2aaf"
LAUNCH_AGENT_PATH = os.path.expanduser(f"~/Library/LaunchAgents/{BUNDLE_ID}.plist")


def _append_conversion_log(folder: str, success: bool, label: str, message: str):
    """
    Always writes every conversion attempt to a plain text file inside the
    watched folder, regardless of whether the on-screen notification
    actually appears. macOS can silently drop notifications from an
    unsigned app without ever raising an error on our end, so this file is
    the one reliable way to see what actually happened - especially for
    failures, where the notification is the only other place the reason
    would otherwise show up.
    """
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "OK" if success else "FAILED"
        line = f"[{timestamp}] {status} - {label} - {message}\n"
        with open(os.path.join(folder, LOG_FILENAME), "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass  # logging is best-effort; never let it block the real result


def _find_asset_path(filename: str):
    """
    Locates a bundled image asset by filename. Inside a packaged .app,
    data files declared in setup.py's DATA_FILES land in
    Contents/Resources - found reliably via NSBundle rather than
    __file__, since py2app can relocate the script itself into a
    different structure than its source layout. Falls back to the
    source-tree location for running directly from source
    (python3 src/app.py) without building first.
    """
    resource_path = NSBundle.mainBundle().resourcePath()
    if resource_path:
        candidate = os.path.join(resource_path, filename)
        if os.path.exists(candidate):
            return candidate

    dev_candidate = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", filename)
    if os.path.exists(dev_candidate):
        return dev_candidate

    return None


def _ensure_single_instance():
    """
    Prevents two copies of the app running side by side. If another instance
    is already running, bring it to the front and exit this one immediately.
    macOS normally handles this for signed apps, but unsigned py2app builds
    can launch a second instance instead of focusing the existing one.
    """
    from AppKit import NSRunningApplication
    running = NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE_ID)
    # Filter out this process itself
    import os as _os
    my_pid = _os.getpid()
    others = [app for app in running if app.processIdentifier() != my_pid]
    if others:
        # Bring the existing instance to the front and exit
        others[0].activateWithOptions_(0)
        import sys
        sys.exit(0)


class Stem2AAFApp(rumps.App):
    # Once the fill completes, all five bars blink white against orange
    # this many times, then settle back to the solid orange logo:
    #
    #     all white -> back to orange -> all white -> back to orange
    #
    # The flash starts on WHITE deliberately. Progress ends at 100%, which
    # is already the solid orange icon, so opening the flash on orange
    # would repaint what is already on screen and waste the first step -
    # the count would look short by one. Starting on white makes every
    # step a visible change. Each blink is a white step followed by an
    # orange one, and the final orange step lands on the resting icon, so
    # there is no extra frame between the flash and rest.
    _FLASH_BLINKS = 2
    _FLASH_STEPS = _FLASH_BLINKS * 2

    # How long each bar is shown before the next one lights.
    #
    # The bars are an ELAPSED-TIME meter, not a progress bar. Reported
    # progress turned out to be useless as a direct index: a handful of
    # stems converts almost instantly, so it went 0 -> 1 between two ticks
    # and the fill jumped straight from 0 bars to 5, invisible. Driving it
    # off progress with a speed limit instead just moved the problem - the
    # icon then kept animating for a second after the AAF had already
    # landed, which is worse than uninformative, it is wrong.
    #
    # So the bars simply say how long this has been running, and the
    # completion flash says it is done. That makes every case read
    # correctly with no special handling:
    #
    #   fast   bar 1 blinks, then the flash cuts in - done in under 2 s
    #   normal bar after bar lights as it goes
    #   slow   reaches bar 5 at 6 s and blinks there until it finishes
    #
    # Bar 5 is terminal on purpose: it never claims to know how much is
    # left, only that work is still happening. And because completion
    # interrupts at whatever bar it has reached, the icon is never behind
    # the actual result.
    _BAR_SECONDS = 1.5
    _TICK_SECONDS = 0.15
    _TICKS_PER_BAR = int(_BAR_SECONDS / _TICK_SECONDS)  # 10
    # Solid bars cap here so the fifth is always the one blinking.
    _MAX_SOLID_BARS = 4

    def __init__(self):
        icon_path = _find_asset_path("icon.png")
        # rumps forces every status bar icon into a fixed 20x20 square
        # (confirmed from its source - App never exposes a dimensions
        # option the way individual MenuItems do), so the icon here is a
        # square-compatible glyph rather than a wide wordmark.
        super().__init__("Stem2AAF", icon=icon_path, quit_button=None)
        self.cfg = config.load()

        self.convert_now_item = rumps.MenuItem("Convert to AAF", callback=self.convert_now)
        self.settings_item    = rumps.MenuItem("Settings",        callback=self.open_settings)
        # Uninstall lives in Settings -> Application, not here. It is a rare,
        # destructive action and doesn't belong one slip of the mouse away
        # from "Convert to AAF" in a menu opened many times a session.
        self.menu = [
            self.convert_now_item,
            None,
            self.settings_item,
            None,
            rumps.MenuItem("Quit Stem2AAF", callback=rumps.quit_application),
        ]

        self.watcher = Watcher(
            self.watch_folder, self.output_folder,
            self.on_conversion_result, self.on_conversion_progress,
        )
        self.watcher.start()
        self._settings_win = None  # kept alive to prevent GC

        # One timer, not two. The pending-count refresh and the
        # auto-convert check both used to run on their own 2-second timer,
        # each doing a full directory scan, so an idle app listed the
        # watched folder twice every two seconds forever. They now share a
        # single scan per tick.
        self._auto_count_last = 0
        self._auto_quiet_ticks = 0
        self._poll_timer = rumps.Timer(self._poll_folder, POLL_SECONDS)
        self._poll_timer.start()

        # Drives the icon animation. The whole sequence reads as one idea:
        # the moment stems appear the logo goes WHITE, and orange is the
        # progress that fills it back in, bar by bar, left to right.
        #
        #   stems detected   white logo, leftmost bar blinking orange
        #   converting       orange fills left to right as real progress
        #                    arrives; the next unearned bar keeps blinking
        #                    so there is always visible motion
        #   done             all five orange, flashing against all-white
        #   at rest          the plain orange logo
        #
        # Progress is real, not a timer guessing at duration - see
        # converter.py's on_progress and watcher.py's _convert_batch.
        #
        # _prog_icons is indexed by "how many bars are orange", so index 0
        # is the all-white logo and index 5 is the ordinary orange one.
        # Those two ends are the existing assets; 1-4 are generated from
        # them, so all six share one geometry.
        self._resting_icon = icon_path
        self._prog_icons = [
            _find_asset_path("icon_flash_white.png"),  # 0 orange - all white
            _find_asset_path("icon_prog_1.png"),
            _find_asset_path("icon_prog_2.png"),
            _find_asset_path("icon_prog_3.png"),
            _find_asset_path("icon_prog_4.png"),
            icon_path,                                 # 5 orange - the logo
        ]
        # "idle"    - nothing waiting, plain logo, timer stopped
        # "waiting" - stems detected but not converting yet
        # "filling" - conversion running, orange climbing with progress
        # "flashing"- conversion finished, the all-bars orange/white flash
        self._icon_state = "idle"
        self._progress = 0.0
        self._blink_index = 0  # drives the next-bar blink while waiting/filling
        self._flash_index = 0  # drives the fixed-length completion flash
        self._shown_bars = 0   # displayed bar count, chases real progress
        self._bar_ticks = 0    # ticks the current bar has been held
        # Started when there is something to show and stopped by
        # _animate_icon once the icon is back at rest, rather than waking
        # the app ~7x a second all day on a menu-bar app that mostly idles.
        self._icon_timer = rumps.Timer(self._animate_icon, 0.15)

    # -- Folders ------------------------------------------------------------

    @property
    def watch_folder(self) -> str:
        """The folder the DAW exports stems into."""
        return self.cfg.get("folder") or os.path.expanduser("~/Documents/Stem2AAF")

    @property
    def output_folder(self) -> str:
        """
        Where "<project> Converted vN" folders are written.

        An empty setting means "next to the stems", which is the original
        single-folder behaviour and stays the default. The Settings panel
        has always offered a separate output folder; the app used to throw
        that value away and write beside the stems no matter what was
        chosen there.
        """
        return self.cfg.get("output_folder") or self.watch_folder

    # -- Settings -----------------------------------------------------------

    def _build_settings_config(self) -> dict:
        """
        Convert the app's legacy config format into the dict that
        SettingsWindow expects.  Runs every time Settings is opened so
        the panel always reflects the latest saved state.
        """
        # Build category list from the old separate keys:
        #   "category_order"  → [{name, enabled}, ...]
        #   "custom_keywords" → {name: [kw, ...]}
        cat_order  = self.cfg.get("category_order")  or []
        custom_kws = self.cfg.get("custom_keywords") or {}

        # DEFAULT_CATEGORIES is itself derived from converter._CATEGORY_KEYWORDS,
        # so this is the converter's own table — one source of truth.
        default_kw_map = {c["name"]: c["keywords"] for c in DEFAULT_CATEGORIES}

        if cat_order:
            categories = []
            for cat in cat_order:
                name    = cat["name"] if isinstance(cat, dict) else str(cat)
                enabled = cat.get("enabled", True) if isinstance(cat, dict) else True
                kws     = custom_kws.get(name) or default_kw_map.get(name) or []
                categories.append({"name": name, "enabled": enabled, "keywords": list(kws)})
        else:
            # No saved order yet — use the SettingsWindow defaults which
            # include the keywords baked in.
            categories = [dict(c) for c in DEFAULT_CATEGORIES]

        return {
            "watch_folder":  self.watch_folder,
            # Shown blank-as-"same as watch folder" is confusing in a path
            # field, so the panel always shows the folder actually in use.
            "output_folder": self.output_folder,
            "group_by_cat":  self.cfg.get("group_stems_by_category",       False),
            "delete_stems":  self.cfg.get("delete_stems_after_conversion", False),
            "auto_convert":  self.cfg.get("auto_convert",                  False),
            "launch_at_login": self.cfg.get("launch_at_login",             False),
            "categories":    categories,
            "category_presets": self.cfg.get("category_presets") or {},
            "active_preset":    self.cfg.get("active_preset") or "Default Keywords",
        }

    def open_settings(self, _):
        """
        Opens the unified Settings window, or brings the existing one
        forward if it's already open.

        Without the reuse check, every click built a second panel and
        dropped the reference to the first, leaving an orphaned window on
        screen that still wrote to the same config.
        """
        if self._settings_win is not None and self._settings_win.is_open():
            self._settings_win.show()
            return
        settings_cfg = self._build_settings_config()
        self._settings_win = SettingsWindow(
            settings_cfg,
            on_save=self._on_settings_save,
            on_uninstall=lambda: self.launch_uninstaller(None),
        )
        self._settings_win.show()

    def _on_settings_save(self, new_cfg: dict):
        """
        Called by SettingsWindow after every change the user makes (the panel
        applies live — there is no Save button). Maps the new-format config
        dict back into the app's legacy key layout so that config.py,
        watcher.py, and the converter all continue to work without changes.

        Because this now fires on every toggle and every keyword edit, the
        watcher is only restarted when the folder actually changed — a restart
        tears down and rebuilds the filesystem observer, which would otherwise
        happen dozens of times per settings session and could drop events
        mid-export.
        """
        old_watch  = self.watch_folder
        old_output = self.output_folder

        self.cfg["folder"] = new_cfg.get("watch_folder") or old_watch

        # Store the output folder only when it actually differs from the
        # watched one, so the common "both the same" case keeps working
        # even if the user later moves the watched folder.
        chosen_output = new_cfg.get("output_folder") or ""
        self.cfg["output_folder"] = "" if chosen_output == self.cfg["folder"] else chosen_output

        # Toggle flags — direct mapping.
        self.cfg["group_stems_by_category"]       = new_cfg.get("group_by_cat",  False)
        self.cfg["delete_stems_after_conversion"] = new_cfg.get("delete_stems", False)
        self.cfg["auto_convert"]                  = new_cfg.get("auto_convert", False)

        # Launch at login is applied immediately, not just recorded: the
        # LaunchAgent plist has to be written or removed for the checkbox
        # to mean anything. Nothing called _set_launch_at_login before, so
        # the setting existed in config and did nothing at all.
        want_login = bool(new_cfg.get("launch_at_login", False))
        if want_login != bool(self.cfg.get("launch_at_login", False)):
            _set_launch_at_login(want_login)
        self.cfg["launch_at_login"] = want_login

        # Persist categories in the old two-key format so existing builds
        # reading category_order / custom_keywords keep working.
        cats = new_cfg.get("categories", [])
        self.cfg["category_order"]  = [{"name": c["name"], "enabled": c["enabled"]} for c in cats]
        self.cfg["custom_keywords"] = {c["name"]: c["keywords"] for c in cats}
        self.cfg.pop("disabled_keywords", None)  # remove legacy key if present

        # Saved category sets. Stored whole rather than folded into
        # category_order/custom_keywords, because a preset is a snapshot of
        # both at once and splitting it would make them impossible to
        # reassemble reliably.
        self.cfg["category_presets"] = new_cfg.get("category_presets") or {}
        self.cfg["active_preset"]    = new_cfg.get("active_preset") or "Default Keywords"

        config.save(self.cfg)

        if self.watch_folder != old_watch or self.output_folder != old_output:
            self.watcher.restart(self.watch_folder, self.output_folder)

    # -- Uninstaller --------------------------------------------------------

    def launch_uninstaller(self, _):
        """
        Confirms, then hands off to the uninstall script bundled in this
        app's own Contents/Resources and quits.

        Reached from Settings -> Application -> Uninstall.

        This used to launch a whole second .app built by its own py2app
        run: a complete copy of Python and PyObjC, about 20 MB, whose
        entire job was to show one dialog and delete two folders. It also
        left a stray copy of itself in /Applications when the nested copy
        was the one that ran. The script does the same work, is a few
        kilobytes, and can safely delete this app because it outlives it.
        """
        script = _find_asset_path(UNINSTALL_SCRIPT_NAME)
        if not script:
            rumps.alert(
                title="Couldn't uninstall",
                message="The uninstall script is missing from this app bundle. "
                        "Drag Stem2AAF.app to the Trash to remove it by hand.",
                ok="OK",
            )
            return

        confirmed = rumps.alert(
            title="Uninstall Stem2AAF?",
            message="This removes the app, its settings, and its login-item entry.\n\n"
                    "Your project folder and any .wav/.aaf files in it are NOT touched - "
                    "only the app's own code and settings are removed.",
            ok="Uninstall",
            cancel="Cancel",
        )
        if confirmed != 1:
            return

        bundle_path = NSBundle.mainBundle().bundlePath() or ""
        subprocess.Popen(
            ["/bin/bash", script, bundle_path, config.CONFIG_DIR, LAUNCH_AGENT_PATH],
            start_new_session=True,
        )
        rumps.quit_application()

    # -- Folder polling -----------------------------------------------------

    def _poll_folder(self, _timer):
        """
        One directory scan per tick, feeding both the menu label and the
        auto-convert check.

        Auto-convert waits for the waiting-stem count to hold completely
        steady for AUTO_CONVERT_QUIET_SECONDS rather than for a single
        tick. Bitwig can take well over two seconds between finishing one
        track and creating the next when a track has a heavy plugin chain,
        and the old single-tick check read that gap as "the export is
        done" and converted mid-export.
        """
        count = self.watcher.pending_stems_count()

        if count > 0:
            self.convert_now_item.title = f"Convert to AAF ({count} waiting)"
        else:
            self.convert_now_item.title = "Convert to AAF"

        # Stems appearing is itself worth showing: the logo goes white with
        # the first bar blinking orange, before any conversion starts. Only
        # "idle" is promoted, so a running conversion or its completion
        # flash is never interrupted by the poll.
        if count > 0 and self._icon_state == "idle":
            self._progress = 0.0
            self._blink_index = 0
            self._shown_bars = 0
            self._bar_ticks = 0
            self._icon_state = "waiting"
            self._start_icon_timer()
        elif count == 0 and self._icon_state == "waiting":
            # They were converted or removed without us doing it.
            self._icon_state = "idle"
            self.icon = self._resting_icon

        if not self.cfg.get("auto_convert", False) or count == 0:
            self._auto_count_last = count
            self._auto_quiet_ticks = 0
            return

        # Never start a second conversion while one is already running.
        if self._icon_state == "filling":
            return

        if count != self._auto_count_last:
            self._auto_count_last = count
            self._auto_quiet_ticks = 0
            return

        self._auto_quiet_ticks += 1
        if self._auto_quiet_ticks * POLL_SECONDS < AUTO_CONVERT_QUIET_SECONDS:
            return

        self._auto_quiet_ticks = 0
        self._auto_count_last = 0
        self._begin_conversion()

    # -- Icon animation -----------------------------------------------------

    def _animate_icon(self, _timer):
        """
        Ticks only while there is something to animate.

        The timer used to run at 0.15 s forever, waking the app about
        seven times a second around the clock to decide it had nothing to
        draw - on a menu-bar app that sits idle all day that is pure
        battery cost. It now stops itself once the icon is back at rest
        and _begin_conversion restarts it.
        """
        if self._icon_state in ("waiting", "filling"):
            # One clock for the whole operation: it starts the moment
            # stems are detected and keeps running through the quiet wait
            # and the conversion, because from the outside that is all one
            # wait - stems land, and eventually an AAF appears.
            if self._shown_bars < self._MAX_SOLID_BARS:
                self._bar_ticks += 1
                if self._bar_ticks >= self._TICKS_PER_BAR:
                    self._shown_bars += 1
                    self._bar_ticks = 0
                    self._blink_index = 0  # restart the blink on the new bar

            # The bar after the solid ones blinks. At the cap that is the
            # fifth, which then blinks for as long as the work takes.
            bars = self._shown_bars
            self.icon = (
                self._prog_icons[bars + 1] if self._blink_index % 2 == 0
                else self._prog_icons[bars]
            )
            self._blink_index += 1
        elif self._icon_state == "flashing":
            if self._flash_index >= self._FLASH_STEPS:
                self._icon_state = "idle"
                self.icon = self._resting_icon
                self._stop_icon_timer()
                return
            # All five bars, alternating full white against full orange,
            # white first - see _FLASH_BLINKS for why the order matters.
            self.icon = (
                self._prog_icons[0] if self._flash_index % 2 == 0
                else self._prog_icons[5]
            )
            self._flash_index += 1
        else:
            # Idle: the icon is already at rest, so there is nothing to
            # draw and no reason to keep waking up.
            self._stop_icon_timer()

    def _stop_icon_timer(self):
        try:
            if self._icon_timer.is_alive():
                self._icon_timer.stop()
        except Exception:  # noqa: BLE001 - never let animation bookkeeping break a conversion
            pass

    def _begin_conversion(self):
        """Resets the progress animation and asks the watcher to convert."""
        self._progress = 0.0
        # Deliberately not resetting _blink_index, _shown_bars or
        # _bar_ticks: coming out of "waiting" the first bar is already
        # blinking, and restarting those counters would stutter it at the
        # exact moment the conversion begins. Convert-now from a cold
        # start has them at 0 already.
        self._icon_state = "filling"
        self._start_icon_timer()
        self.watcher.convert_pending_stems_now()

    def _start_icon_timer(self):
        """
        Starts the animation timer if it isn't already running.

        Only ever called from the main thread (a menu click or a rumps
        timer). The watcher's background thread must not start a timer,
        so on_conversion_result only sets plain values and relies on the
        timer already running.
        """
        try:
            if not self._icon_timer.is_alive():
                self._icon_timer.start()
        except Exception:  # noqa: BLE001
            pass

    # -- Conversion ---------------------------------------------------------

    def convert_now(self, _):
        """
        Converts whatever stems have arrived so far into an AAF.

        This is the reliable way to convert: click it once you can see
        from the menu label that every stem you expect has landed. The
        DAW's render time per track depends on that track's own plugin
        load and how much audio it contains, so no timer can tell "still
        rendering" from "finished" with certainty. Auto-convert, off by
        default, waits for the count to hold steady and is a convenience
        on top of this, not a replacement for it.

        Either way the watcher refuses to build an AAF from a batch where
        any file is still being written, so a mistimed conversion reports
        an error instead of quietly dropping tracks.
        """
        count = self.watcher.pending_stems_count()
        if count == 0:
            rumps.notification("Stem to AAF", "Nothing to convert", "No stems are currently waiting.")
            return
        self._begin_conversion()

    # -- Watcher callbacks (run on a background thread) --------------------

    def on_conversion_progress(self, fraction):
        self._progress = fraction

    def on_conversion_result(self, label, success, message, log_dir=None, skip_log=False):
        # Runs on the watcher's background thread, so this only ever sets
        # plain values. The icon timer is already running whenever a
        # conversion is in flight (see _begin_conversion), and it stops
        # itself on the main thread once the completion flash is done.
        #
        # Straight to the flash from whatever bar the meter had reached.
        # It deliberately does NOT run the bars out to five first: the AAF
        # exists now, and finishing the sweep would leave the icon saying
        # "working" for a second after the file had already appeared.
        self._flash_index = 0
        self._icon_state = "flashing"
        if not skip_log:
            _append_conversion_log(log_dir or self.watcher.watch_folder, success, label, message)
        try:
            if success:
                rumps.notification("Stem to AAF", f"Converted {label}", f"Saved {os.path.basename(message)}")
            else:
                rumps.notification("Stem to AAF", f"Failed to convert {label}", message)
        except Exception:
            # Notification delivery isn't guaranteed - e.g. an unsigned app
            # that was never granted notification permission can have this
            # silently fail. The log file above is the reliable record
            # regardless of whether this succeeds.
            pass


def _set_launch_at_login(enabled: bool):
    """
    Registers/unregisters this app as a login item using a LaunchAgent plist.

    launchd needs the actual executable file inside the app bundle
    (Contents/MacOS/<name>), not the .app bundle path itself - so this
    reads NSBundle's executablePath at runtime rather than relying on any
    environment variable, which nothing sets and previously made this
    silently do nothing even when the checkbox was turned on.
    """
    label = BUNDLE_ID
    plist_path = LAUNCH_AGENT_PATH
    if enabled:
        executable_path = NSBundle.mainBundle().executablePath()
        if not executable_path:
            rumps.notification(
                "Stem to AAF",
                "Couldn't enable Launch at login",
                "Only works when running as a built .app, not from source.",
            )
            return
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{label}</string>
    <key>ProgramArguments</key><array><string>{executable_path}</string></array>
    <key>RunAtLoad</key><true/>
</dict>
</plist>
"""
        os.makedirs(os.path.dirname(plist_path), exist_ok=True)
        with open(plist_path, "w") as f:
            f.write(plist)
        subprocess.run(["launchctl", "load", plist_path], check=False)
    else:
        if os.path.exists(plist_path):
            subprocess.run(["launchctl", "unload", plist_path], check=False)
            os.remove(plist_path)


if __name__ == "__main__":
    _ensure_single_instance()
    Stem2AAFApp().run()
