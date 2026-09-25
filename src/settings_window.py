"""
settings_window.py

Full Stem2AAF preferences window using PyObjC + WKWebView.
Presents a System Settings-style sidebar window with four sections:
  General, Categories, How to Use, About.

Usage:
    win = SettingsWindow(config, on_save=my_callback)
    win.show()

`config` is a dict with keys:
    watch_folder   : str   — path to the watched stem folder
    output_folder  : str   — path for AAF output
    group_by_cat   : bool  — group stems by category
    delete_stems   : bool  — delete stems after conversion (the panel shows
                             this inverted, as "Keep stems after conversion")
    auto_convert   : bool  — convert automatically when stems arrive
    categories     : list  — [{name, enabled, keywords:[str]}, ...]

Changes apply live (System Settings style): `on_save` is called with the full
updated config dict after every change the user makes. There is no Save button;
the window is dismissed with its close button.
"""

import json
import os

import objc
from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSMakeRect,
    NSOpenPanel,
    NSPanel,
)
from Foundation import NSBundle, NSObject
from WebKit import WKUserContentController, WKWebView, WKWebViewConfiguration

_TITLED    = 1   # NSWindowStyleMaskTitled
_CLOSABLE  = 2   # NSWindowStyleMaskClosable
_RESIZABLE = 8   # NSWindowStyleMaskResizable

# NSWindowStyleMaskNonactivatingPanel (128) is deliberately NOT used. It was
# tried to make the close button respond to a single click, but it stops the
# panel from activating the app, and WKWebView needs a key/active window to
# route mouse events reliably — clicks on small targets (the enable dot) and
# press-drag-release gestures (category reordering) were being dropped.
# canBecomeKeyWindow below is what actually fixes the close button, and
# _WebView.acceptsFirstMouse_ handles the first click into the content.


class _SettingsPanel(NSPanel):
    """NSPanel that can take key focus. An accessory (menu-bar) app has no
    main window, so without this the panel never becomes key and its title-bar
    controls need a throwaway activating click first."""

    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return False


class _WebView(WKWebView):
    """Delivers the first click into the page instead of spending it on
    activating the window."""

    def acceptsFirstMouse_(self, event):
        return True

# Web-content size of the panel. This is passed as the window's content
# rect, so it is the area the page gets; the title bar sits above it.
#
# Sized so no section has to scroll. The old 510 was set when General held
# two groups; it now has three, and the tallest section (How to Use) needs
# 689px at this width, so General arrived with a scrollbar down the side.
# Measured heights at 720 wide: How to Use 750, General 642, About 438.
# The 40px over the tallest is deliberate slack: these numbers come from a
# browser, and WKWebView's text metrics need not agree to the pixel.
# The window is resizable as well, so this only has to be a good default.
_W, _H = 720, 790

# Imported here rather than at the very top so the window-size block above
# stays one readable unit with its measurements.
from config import AUTO_CONVERT_QUIET_SECONDS  # noqa: E402
from version import BUILD, VERSION  # noqa: E402

# Single source of truth: the converter's keyword table is what actually runs
# at conversion time, so the UI derives its defaults from it rather than
# keeping a second hand-maintained copy that can silently drift. This matters
# for the Reset buttons — they must restore what the converter really uses.
try:
    from converter import _CATEGORY_KEYWORDS as _CONV_KW

    DEFAULT_CATEGORIES = [
        {"name": name, "enabled": True, "keywords": list(kws)}
        for name, kws in _CONV_KW
    ]
except Exception:  # converter unavailable (e.g. standalone UI testing)
    DEFAULT_CATEGORIES = []

# ── HTML template ─────────────────────────────────────────────────────────────
# __STATE__ is replaced at runtime with a JSON-encoded initial state object.

def _web_path(filename: str) -> str:
    """
    Locates a file from src/web/ at runtime.

    Inside a packaged .app the files listed in setup.py's DATA_FILES land in
    Contents/Resources, found via NSBundle rather than __file__ because
    py2app can relocate the script itself. Falls back to the source tree so
    the app still runs unbuilt.
    """
    resource_path = NSBundle.mainBundle().resourcePath()
    if resource_path:
        candidate = os.path.join(resource_path, filename)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", filename)


def _read_page() -> str:
    """
    Assembles the settings page from src/web/settings.{html,css,js}.

    Those three used to be one 918-line string literal in this module, which
    meant no syntax highlighting, no linting, and no way to run the
    JavaScript anywhere but inside the built app. They are separate files now
    so the editor and the tooling can see them.

    They are still INLINED into one document here rather than left as <link>
    and <script src> tags, because the page goes to WKWebView through
    loadHTMLString with no base URL, so relative paths would not resolve.
    loadFileURL would allow real separate requests, but it trades a load path
    that is known to work for one that depends on getting bundle paths right,
    and buys nothing the editor can see - the files are already separate on
    disk, which was the whole point.
    """
    def read(filename):
        with open(_web_path(filename), encoding="utf-8") as f:
            return f.read()

    html = read("settings.html")
    css = read("settings.css")
    js = read("settings.js")
    js = (js.replace("${VERSION}", VERSION)
            .replace("${BUILD}", BUILD)
            .replace("__QUIET_SECONDS__", str(AUTO_CONVERT_QUIET_SECONDS)))
    return (html
            .replace('<link rel="stylesheet" href="settings.css">',
                     "<style>\n" + css + "\n</style>")
            .replace('<script src="settings.js"></script>',
                     "<script>\n" + js + "</script>"))



# ── Message handler ───────────────────────────────────────────────────────────

def _clean_presets(raw) -> dict:
    """
    Coerces the presets map coming back from the page into plain Python.

    Everything crossing the JS bridge arrives as Objective-C bridged types,
    and this ends up in config.json, so it is normalised here rather than
    trusted: names become str, keyword lists become lists of str, and
    anything malformed is dropped instead of being written out.
    """
    out = {}
    if not hasattr(raw, "items"):
        return out
    for name, cats in raw.items():
        try:
            clean = [
                {
                    "name":     str(c.get("name", "")),
                    "enabled":  bool(c.get("enabled", True)),
                    "keywords": [str(k) for k in c.get("keywords", [])],
                }
                for c in cats
            ]
        except Exception:  # noqa: BLE001 - a malformed preset is skipped, not fatal
            continue
        if clean:
            out[str(name)] = clean
    return out


class _MessageHandler(NSObject):
    """Bridges JS postMessage calls into Python."""

    def init(self):
        self = objc.super(_MessageHandler, self).init()
        self._callback = None
        return self

    def userContentController_didReceiveScriptMessage_(self, controller, message):
        if self._callback is None:
            return
        try:
            body = message.body()
            self._callback({str(k): v for k, v in body.items()})
        except Exception:
            pass


# ── Main class ────────────────────────────────────────────────────────────────

class SettingsWindow:
    """
    Full Stem2AAF preferences window.

    Parameters
    ----------
    config : dict
        Current app configuration. Expected keys:
            watch_folder, output_folder, group_by_cat, delete_stems, categories
    on_save : callable
        Called with the updated config dict when the user clicks Save.
    """

    def __init__(self, config: dict, on_save, on_uninstall=None):
        self._on_save = on_save
        self._on_uninstall = on_uninstall
        self._handler = None
        self._webview = None
        self._panel   = None
        self._build(config)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self, config: dict):
        # Ensure categories have a 'keywords' key (back-compat with old 'kws')
        # Fall back to DEFAULT_CATEGORIES keywords when the saved list is empty
        _default_kw_map = {c["name"]: c["keywords"] for c in DEFAULT_CATEGORIES}
        cats = []
        for c in config.get("categories", DEFAULT_CATEGORIES):
            name = c.get("name", "")
            kws  = c.get("keywords", c.get("kws", []))
            if not kws:
                kws = _default_kw_map.get(name, [])
            cats.append({
                "name":     name,
                "enabled":  c.get("enabled", True),
                "keywords": kws,
            })

        # Defaults here only matter when a key is missing entirely. They
        # match config.py's own defaults rather than inventing different
        # ones, which is how the panel used to show ~/Music/Stems for an
        # app that actually watches ~/Documents/Stem2AAF.
        _default_folder = os.path.expanduser("~/Documents/Stem2AAF")
        state = {
            "watch_folder":    config.get("watch_folder")  or _default_folder,
            "output_folder":   config.get("output_folder") or _default_folder,
            "group_by_cat":    config.get("group_by_cat",    False),
            # Presented to the UI the positive way round; see save() in the
            # page script, which inverts it back on the way out.
            "keep_stems":      not config.get("delete_stems", False),
            "auto_convert":    config.get("auto_convert",    False),
            "launch_at_login": config.get("launch_at_login", False),
            "categories":      cats,
            # Saved category sets, name -> [{name, enabled, keywords}].
            # "Default Keywords" is never stored: it always means the
            # converter's own table, so there is a way back that cannot be
            # deleted or edited away.
            "presets":         config.get("category_presets") or {},
            "activePreset":    config.get("active_preset") or "Default Keywords",
        }

        # Message handler
        handler = _MessageHandler.alloc().init()
        handler._callback = self._on_message
        self._handler = handler

        # WKWebView config
        controller = WKUserContentController.alloc().init()
        controller.addScriptMessageHandler_name_(handler, "stem2aaf")
        wk_config = WKWebViewConfiguration.alloc().init()
        wk_config.setUserContentController_(controller)

        # WKWebView
        frame = NSMakeRect(0, 0, _W, _H)
        webview = _WebView.alloc().initWithFrame_configuration_(frame, wk_config)
        webview.setValue_forKey_(False, "drawsBackground")
        self._webview = webview

        # Inject state and load HTML
        html = (_read_page()
                .replace("__STATE__", json.dumps(state))
                .replace("__DEFAULT_CATS__", json.dumps(DEFAULT_CATEGORIES)))
        webview.loadHTMLString_baseURL_(html, None)

        # NSPanel
        panel = _SettingsPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, _TITLED | _CLOSABLE | _RESIZABLE,
            NSBackingStoreBuffered, False
        )
        panel.setTitle_("Stem2AAF Settings")
        # Resizable, so the panel can adapt if a future section grows or a
        # display is short. The floor is the width the two-pane Categories
        # layout needs before its columns start crowding each other.
        panel.setContentMinSize_((620, 460))
        # The webview has to follow the window rather than staying at its
        # initial frame size.
        webview.setAutoresizingMask_(2 | 16)  # NSViewWidthSizable | NSViewHeightSizable
        panel.setContentView_(webview)
        panel.setReleasedWhenClosed_(False)
        # NSPanel defaults hidesOnDeactivate to YES, because a panel is meant
        # to be a floating tool palette - you do not want one hovering over
        # another app when you switch away. A Settings window is not that: it
        # vanished the moment you clicked another app and, in an accessory
        # app with no normal activation path back, never reappeared, so it
        # read as having closed itself. NSWindow, which Apple's own settings
        # windows use, defaults this to NO; this makes the panel behave the
        # same.
        panel.setHidesOnDeactivate_(False)
        panel.center()
        self._panel = panel

    # ── Public ────────────────────────────────────────────────────────────────

    def show(self):
        NSApp.activateIgnoringOtherApps_(True)
        self._panel.makeKeyAndOrderFront_(None)

    def is_open(self) -> bool:
        """
        Whether this panel is still on screen.

        The app uses this to bring an existing Settings window forward
        instead of building a second one. Without it, clicking Settings
        twice left an orphaned panel visible that still wrote to the same
        config file.
        """
        try:
            return bool(self._panel is not None and self._panel.isVisible())
        except Exception:  # noqa: BLE001 - a dead panel is simply not open
            return False

    # ── Message handling ──────────────────────────────────────────────────────

    def _on_message(self, body: dict):
        action = body.get("action")

        if action == "open_folder":
            self._open_folder(body.get("key", "watch_folder"))

        elif action == "update":
            raw = body.get("state", {})
            cats = []
            for c in raw.get("categories", []):
                cats.append({
                    "name":     str(c.get("name", "")),
                    "enabled":  bool(c.get("enabled", True)),
                    "keywords": [str(k) for k in c.get("keywords", [])],
                })
            config = {
                "watch_folder":    str(raw.get("watch_folder",  "")),
                "output_folder":   str(raw.get("output_folder", "")),
                "group_by_cat":    bool(raw.get("group_by_cat",    False)),
                "delete_stems":    bool(raw.get("delete_stems",    False)),
                "auto_convert":    bool(raw.get("auto_convert",    False)),
                "launch_at_login": bool(raw.get("launch_at_login", False)),
                "categories":      cats,
                "category_presets": _clean_presets(raw.get("presets")),
                "active_preset":    str(raw.get("active_preset") or "Default Keywords"),
            }
            # Live apply — the panel stays open; the close button dismisses it.
            self._on_save(config)

        # Handed back to the app, which owns the confirmation dialog and the
        # bundled uninstall script.
        elif action == "uninstall" and self._on_uninstall is not None:
            self._on_uninstall()

    def _open_folder(self, key: str):
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(False)
        panel.setCanChooseDirectories_(True)
        panel.setAllowsMultipleSelection_(False)
        panel.setCanCreateDirectories_(True)
        panel.setPrompt_("Choose")
        title = "Watch Folder" if key == "watch_folder" else "Output Folder"
        panel.setTitle_(title)

        result = panel.runModal()
        if result == 1:  # NSModalResponseOK
            url  = panel.URL()
            path = url.path() if url else None
            if path:
                js = f"updateFolderPath('{key}', {json.dumps(path)})"
                self._webview.evaluateJavaScript_completionHandler_(js, None)
