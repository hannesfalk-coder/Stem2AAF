"""
Stem2AAF menu bar app (macOS only), stems-only.

Runs quietly in the menu bar. Watches one folder for stem exports
(File -> Export Audio...) and, when you click "Convert to AAF", batches
whatever has arrived into an .aaf file written into that same folder.
There's no automatic conversion - see convert_now() below for why.

Build into a double-clickable .app with `python3 setup.py py2app` (see
setup.py in this folder) - that step must be run on a Mac. To remove this
app later, use the separate Uninstaller app built alongside it (see
setup_uninstaller.py / uninstaller.py), rather than deleting it by hand.
"""

import datetime
import os
import subprocess
import traceback

import shutil

import rumps
from AppKit import NSOpenPanel, NSApp, NSBundle
from Foundation import NSURL

import config
from settings_window import SettingsWindow, DEFAULT_CATEGORIES
from watcher import Watcher

LOG_FILENAME = "Stem2AAF_log.txt"


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
    import subprocess
    from AppKit import NSRunningApplication
    bundle_id = "com.local.stem2aaf"
    running = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id)
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
    # How many alternations between white and orange the icon does once a
    # conversion finishes (all 5 bars are white by then) before settling
    # back to solid orange - 6 steps at the timer's tick rate is 3 full
    # white/orange cycles.
    _FLASH_STEPS = 6

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
        self.menu = [
            self.convert_now_item,
            None,
            self.settings_item,
            None,
            rumps.MenuItem("Quit Stem2AAF", callback=rumps.quit_application),
        ]

        # Use the legacy "folder" key as both watch and output folder.
        # The new SettingsWindow will migrate these to separate keys on first Save.
        folder = self.cfg.get("folder", os.path.expanduser("~/Documents/Stem2AAF"))
        self.watcher = Watcher(
            folder, folder, self.on_conversion_result, self.on_conversion_progress
        )
        self.watcher.start()
        self._settings_win = None  # kept alive to prevent GC
        self._install_uninstaller_if_needed()

        # Tracks pending-stem count across ticks to detect a "quiet"
        # period (no new files for ~2 s) before firing an auto-conversion.
        self._auto_count_last = 0
        self._auto_convert_timer = rumps.Timer(self._maybe_auto_convert, 2)
        self._auto_convert_timer.start()

        # Keeps the "Convert to AAF" label showing an accurate count of
        # files currently waiting, rather than leaving it as a guess - see
        # convert_now() for why this matters.
        self._pending_label_timer = rumps.Timer(self._refresh_pending_label, 2)
        self._pending_label_timer.start()

        # Drives the in-progress icon animation: from the instant of the
        # click, whichever bar is "next" blinks white/orange continuously
        # until real progress (see converter.py's on_progress and
        # watcher.py's _convert_batch - never a fixed timer guessing at
        # duration) actually earns it, at which point that bar goes solid
        # and the blink moves on to the next one - so there's continuous
        # visible motion the whole way through, never a dead gap where it
        # looks stopped. Once all 5 are solid, it flashes white/orange a
        # few times on completion, then rests back on the plain orange
        # icon. Runs continuously rather than being started/stopped per
        # conversion, since starting a fresh rumps.Timer from the
        # watcher's background thread (rather than this app's own main
        # thread) isn't a safe operation - this way the only things ever
        # touched from that other thread are plain numbers/strings, and
        # the timer itself (always running, always on the main thread)
        # just reads them on every tick.
        self._resting_icon = icon_path
        self._fill_icons = [
            icon_path,  # 0 bars filled - the plain resting icon
            _find_asset_path("icon_fill_1.png"),
            _find_asset_path("icon_fill_2.png"),
            _find_asset_path("icon_fill_3.png"),
            _find_asset_path("icon_fill_4.png"),
            _find_asset_path("icon_flash_white.png"),  # 5 bars filled - all white
        ]
        self._icon_state = "idle"  # "idle" | "filling" | "flashing"
        self._progress = 0.0
        self._blink_index = 0  # drives the continuous next-bar blink while "filling"
        self._flash_index = 0  # drives the fixed-length completion flash while "flashing"
        self._icon_timer = rumps.Timer(self._animate_icon, 0.15)
        self._icon_timer.start()

    # -- Settings -----------------------------------------------------------

    def _build_settings_config(self) -> dict:
        """
        Convert the app's legacy config format into the dict that
        SettingsWindow expects.  Runs every time Settings is opened so
        the panel always reflects the latest saved state.
        """
        folder = self.cfg.get("folder", os.path.expanduser("~/Documents/Stem2AAF"))

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
            "watch_folder":  folder,
            "output_folder": folder,
            "group_by_cat":  self.cfg.get("group_stems_by_category",     False),
            "delete_stems":  self.cfg.get("delete_stems_after_conversion", False),
            "auto_convert":  self.cfg.get("auto_convert",                 False),
            "categories":    categories,
        }

    def open_settings(self, _):
        """Opens the unified Settings window."""
        settings_cfg = self._build_settings_config()
        self._settings_win = SettingsWindow(settings_cfg, on_save=self._on_settings_save)
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
        old_folder = self.cfg.get("folder", "")
        folder     = new_cfg.get("watch_folder", old_folder)

        # Update legacy single-folder key (watcher still uses this).
        self.cfg["folder"] = folder

        # Toggle flags — direct mapping.
        self.cfg["group_stems_by_category"]       = new_cfg.get("group_by_cat",  False)
        self.cfg["delete_stems_after_conversion"] = new_cfg.get("delete_stems", False)
        self.cfg["auto_convert"]                  = new_cfg.get("auto_convert", False)

        # Persist categories in the old two-key format so existing builds
        # reading category_order / custom_keywords keep working.
        cats = new_cfg.get("categories", [])
        self.cfg["category_order"]  = [{"name": c["name"], "enabled": c["enabled"]} for c in cats]
        self.cfg["custom_keywords"] = {c["name"]: c["keywords"] for c in cats}
        self.cfg.pop("disabled_keywords", None)  # remove legacy key if present

        config.save(self.cfg)

        if folder != old_folder:
            self.watcher.restart(folder, folder)

    # -- Uninstaller --------------------------------------------------------

    def _install_uninstaller_if_needed(self):
        """
        Fallback: if the Uninstaller wasn't installed alongside the main app
        (e.g. copied manually rather than via the DMG), this copies it from
        inside this bundle to /Applications on first launch so it shows up
        in Launchpad/Spotlight. The DMG already includes both apps side by
        side, so this is rarely needed in practice.
        """
        target = "/Applications/Stem2AAF Uninstaller.app"
        if os.path.isdir(target):
            return
        resource_path = NSBundle.mainBundle().resourcePath()
        if not resource_path:
            return
        source = os.path.join(resource_path, "Stem2AAF Uninstaller.app")
        if not os.path.isdir(source):
            return
        try:
            shutil.copytree(source, target)
        except Exception:
            pass  # best-effort; the menu item fallback handles it if this fails

    def launch_uninstaller(self, _):
        """
        Launches Stem2AAF Uninstaller.app from /Applications - where
        build.sh and the DMG installer both place it alongside the main
        app. Falls back to a copy bundled inside this app's own
        Contents/Resources in case someone has an older build where the
        uninstaller was nested rather than installed separately.
        """
        candidate = "/Applications/Stem2AAF Uninstaller.app"
        if not os.path.isdir(candidate):
            resource_path = NSBundle.mainBundle().resourcePath()
            candidate = os.path.join(resource_path, "Stem2AAF Uninstaller.app") if resource_path else ""
        if not candidate or not os.path.isdir(candidate):
            rumps.notification(
                "Stem to AAF", "Uninstaller not found",
                "Stem2AAF Uninstaller.app wasn't found in /Applications.",
            )
            return
        subprocess.run(["open", candidate])

    # -- Auto-convert -------------------------------------------------------

    def _maybe_auto_convert(self, _timer):
        """
        Fires every 2 seconds. Converts automatically when: auto-convert
        is on, stems are waiting, and the pending count hasn't changed
        since the previous tick - meaning no new files have arrived in the
        last ~2 s and the DAW is likely done exporting. Count-stability
        rather than a fixed delay makes it robust across projects of any
        size: a 50-track project that takes 2 minutes is treated the same
        as a 4-track one.

        Enabled from Settings → General → "Auto-convert when stems arrive".
        """
        if not self.cfg.get("auto_convert", False):
            return
        count = self.watcher.pending_stems_count()
        if count == 0:
            self._auto_count_last = 0
            return
        if count != self._auto_count_last:
            self._auto_count_last = count
            return
        self._auto_count_last = 0
        self._progress = 0.0
        self._blink_index = 0
        self._icon_state = "filling"
        self.watcher.convert_pending_stems_now()

    # -- Label refresh & icon animation ------------------------------------

    def _refresh_pending_label(self, _timer):
        count = self.watcher.pending_stems_count()
        if count > 0:
            self.convert_now_item.title = f"Convert to AAF ({count} waiting)"
        else:
            self.convert_now_item.title = "Convert to AAF"

    def _animate_icon(self, _timer):
        if self._icon_state == "filling":
            bars_earned = min(5, max(0, int(self._progress * 5)))
            if bars_earned >= 5:
                self.icon = self._fill_icons[5]
            else:
                self.icon = (
                    self._fill_icons[bars_earned + 1] if self._blink_index % 2 == 0
                    else self._fill_icons[bars_earned]
                )
            self._blink_index += 1
        elif self._icon_state == "flashing":
            if self._flash_index >= self._FLASH_STEPS:
                self._icon_state = "idle"
                self.icon = self._resting_icon
                return
            self.icon = self._fill_icons[5] if self._flash_index % 2 == 0 else self._resting_icon
            self._flash_index += 1
        # "idle": nothing to do - the icon is already at rest.

    # -- Conversion ---------------------------------------------------------

    def convert_now(self, _):
        """
        Converts whatever stems have arrived so far into an AAF. This is
        the only way conversion ever happens - there's no automatic timer,
        since the DAW's render time per track depends on that track's own
        plugin load and how much audio it contains, which makes any fixed
        timeout an unreliable signal for "the export is actually done".
        Click this once you can see (from the menu label above) that every
        stem you expect has landed.
        """
        count = self.watcher.pending_stems_count()
        if count == 0:
            rumps.notification("Stem to AAF", "Nothing to convert", "No stems are currently waiting.")
            return
        self._progress = 0.0
        self._blink_index = 0
        self._icon_state = "filling"
        self.watcher.convert_pending_stems_now()

    # -- Watcher callbacks (run on a background thread) --------------------

    def on_conversion_progress(self, fraction):
        self._progress = fraction

    def on_conversion_result(self, label, success, message, log_dir=None, skip_log=False):
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
    label = "com.local.stem2aaf"
    plist_path = os.path.expanduser(f"~/Library/LaunchAgents/{label}.plist")
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
