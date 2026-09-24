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
from Foundation import NSObject
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

from config import AUTO_CONVERT_QUIET_SECONDS
from version import VERSION, BUILD

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

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#FFFFFF;--bg-2:#F2F2F7;--bg-3:#E5E5EA;--bg-el:#FFFFFF;
  --sidebar:#EBEBF0;--t1:#000000;--t2:#6C6C70;--t3:#AEAEB2;
  /* Disabled-category outline and label. Separate from --t3 because --t3 is a
     placeholder grey that goes very dark in dark mode, where an off checkbox
     still has to be clearly visible as an empty box rather than fade out. */
  --off:#AEAEB2;
  --green:#34C759;--red:#FF3B30;
  --sep:rgba(0,0,0,.09);--sep-s:rgba(0,0,0,.16);
  --chip-bg:rgba(0,0,0,.055);--chip-b:rgba(0,0,0,.11);
  --tog-off:#D1D1D6;
  --font:-apple-system,BlinkMacSystemFont,'SF Pro Text',system-ui,sans-serif;
  --font-d:-apple-system,BlinkMacSystemFont,'SF Pro Display',system-ui,sans-serif;
}
@media(prefers-color-scheme:dark){:root{
  --bg:#1C1C1E;--bg-2:#2C2C2E;--bg-3:#3A3A3C;--bg-el:#2C2C2E;
  --sidebar:#252527;--t1:#FFFFFF;--t2:#8E8E93;--t3:#48484A;
  --off:#7C7C82;
  --sep:rgba(255,255,255,.09);--sep-s:rgba(255,255,255,.16);
  --chip-bg:rgba(255,255,255,.08);--chip-b:rgba(255,255,255,.13);
  --tog-off:#3A3A3C;
}}
html,body{width:100%;height:100%;font-family:var(--font);background:var(--bg);color:var(--t1);
  -webkit-font-smoothing:antialiased;-webkit-user-select:none;user-select:none}

/* ── Layout ── */
.win-body{display:flex;height:100vh}


/* ── Sidebar ── */
.sidebar{width:182px;flex-shrink:0;background:var(--sidebar);border-right:1px solid var(--sep-s);
  display:flex;flex-direction:column;padding:8px 0 12px;overflow-y:auto}
.sb-group-label{font-size:10px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;
  color:var(--t3);padding:8px 14px 4px}
.sb-row{display:flex;align-items:center;gap:9px;padding:6px 10px 6px 12px;cursor:pointer;
  margin:0 4px;border-radius:7px;transition:background .08s;border:1px solid transparent}
.sb-row:hover{background:var(--chip-bg)}
.sb-row.active{background:rgba(0,0,0,.06);border:1px solid rgba(0,0,0,.18)}
/* SF Symbols-style glyphs rather than emoji. Emoji arrive at different
   weights, colours and optical sizes, so the column reads as ragged and
   the set can never be completed consistently - there was no emoji for
   "How to Use", which is why that one was a hand-built span. These are
   one stroke weight, one size, and take their colour from the row. The
   22px box is kept so the layout is unchanged; only its fill is gone. */
.sb-icon{width:22px;height:22px;display:flex;align-items:center;
  justify-content:center;flex-shrink:0;background:none;color:var(--t2)}
.sb-icon svg{display:block}
.sb-row.active .sb-icon{color:var(--t1)}
.sb-name{font-size:13px;font-weight:500;color:var(--t1)}
.change-btn.danger{color:var(--red)}
.sb-row.active .sb-name{color:var(--t1)}

/* ── Detail pane ── */
.detail{flex:1;overflow-y:auto;padding:20px}
.sec-label{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;
  color:var(--t3);margin-bottom:8px;margin-top:20px}
.sec-label:first-child{margin-top:0}

/* ── Settings group / row ── */
.sg{background:var(--bg-el);border-radius:10px;border:1px solid var(--sep);overflow:hidden;margin-bottom:8px}
.sr{display:flex;align-items:center;gap:14px;padding:0 16px;min-height:52px}
.sr+.sr{border-top:1px solid var(--sep)}
.sr-text{display:flex;flex-direction:column;gap:1px;flex:1;min-width:0}
.sr-title{font-size:13px;font-weight:500;color:var(--t1)}
.sr-value{font-size:11px;color:var(--t2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:350px}
.sr-desc{font-size:12px;color:var(--t2);line-height:1.4;margin-top:1px}

/* Change button */
.change-btn{flex-shrink:0;padding:4px 12px;background:rgba(0,0,0,.06);border:1px solid rgba(0,0,0,.18);
  border-radius:6px;font-size:12px;font-family:var(--font);color:var(--t1);cursor:pointer;white-space:nowrap}
.change-btn:hover{background:var(--bg-3)}
.change-btn:active{transform:scale(.97)}

/* Toggle */
.sr-toggle{flex-direction:row;padding:13px 16px;gap:14px;cursor:default;align-items:flex-start}
.sr-toggle .sr-text{padding-top:1px}
.tog{width:44px;height:26px;border-radius:13px;background:var(--tog-off);position:relative;
  border:none;outline:none;cursor:pointer;flex-shrink:0;transition:background .18s}
.tog.on{background:var(--green)}
.tog::after{content:'';position:absolute;top:3px;left:3px;width:20px;height:20px;
  border-radius:50%;background:white;box-shadow:0 1px 4px rgba(0,0,0,.25);
  transition:transform .2s cubic-bezier(.35,0,.25,1)}
.tog.on::after{transform:translateX(18px)}

/* ── Categories section ── */
/* flex:1 rather than height:100%. At 100% it claimed the detail pane's
   full content box while the CATEGORY KEYWORDS label sat above it, so the
   two together always overflowed by the height of that label and put a
   scrollbar on a pane whose columns already scroll internally. */
.cat-split{display:flex;gap:0;flex:1;min-height:340px}
.detail.split-mode{display:flex;flex-direction:column}
/* Column headers. One "Category Keywords" label named the pair but sat
   over only the left column, so "Keywords" pointed at nothing. Split in
   two, each word sits over the column it names. The widths mirror
   .cat-list-pane and .cat-detail-pane's margin so they stay aligned. */
.cat-heads{display:flex;flex-shrink:0}
.cat-heads .h-cat{width:176px;flex-shrink:0}
.cat-heads .h-kw{flex:1;margin-left:10px}
.cat-heads .sec-label{margin:0 0 8px}
.cat-list-pane{width:176px;flex-shrink:0;background:var(--bg-el);border:1px solid var(--sep);
  border-radius:10px;overflow:hidden;display:flex;flex-direction:column}
.cat-list-inner{flex:1;overflow-y:auto}
.cl-row{display:flex;align-items:center;gap:8px;padding:8px 10px;cursor:pointer;
  transition:background .08s;border-bottom:1px solid var(--sep)}
.cl-row:last-child{border-bottom:none}
.cl-row:hover{background:var(--chip-bg)}
.cl-row.active{background:rgba(0,0,0,.06)}
/* Category order is not cosmetic: it decides the order the groups appear
   in the AAF, and it breaks ties when a filename matches keywords from
   two categories. Rows are draggable, with the footer arrows as the
   discoverable, always-works alternative. */
.cl-row{cursor:grab}
.cl-row.dragging{opacity:.5;cursor:grabbing;background:rgba(0,122,255,.10)}
/* 9px is what you see, but a 9px click target is far too small to hit. The
   transparent border grows the hit area to 23px while background-clip keeps
   the paint at 9px, and the negative margin cancels the layout effect — so
   it looks identical and is ~6x easier to click. */
/* Calendar.app's sidebar pattern: the checkbox IS the colour swatch. Filled
   orange with a tick while the category is matching, hollow outline when it
   isn't — so the state differs by SHAPE as well as hue and stays readable in
   greyscale or with colour-vision deficiency, which a bare dot did not. */
.cl-check{position:relative;width:15px;height:15px;border-radius:4px;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;cursor:pointer;
  background:#FF9500;border:1.5px solid transparent;
  transition:background .12s,border-color .12s}
/* Transparent overlay widens the click target without moving anything.
   Generous vertically (nothing else shares the row's height), but tight
   horizontally — every pixel it takes sideways is a pixel of the row that
   toggles instead of selecting, which is the wrong gesture. */
.cl-check::before{content:'';position:absolute;inset:-6px -3px}
.cl-check:hover{opacity:.75}
.cl-check svg{display:block}
.cl-check.off{background:transparent;border-color:var(--off)}
.cl-check.off svg{display:none}
.cl-name{flex:1;font-size:13px;font-weight:500;color:var(--t1)}
.cl-row.active .cl-name{color:var(--t1)}
/* State reads from the whole row, not just the 15px box — matters when
   scanning nine categories for the one or two that are switched off. */
.cl-row.off .cl-name,.cl-row.active.off .cl-name{color:var(--off)}
.cl-footer{padding:7px 10px;border-top:1px solid var(--sep);display:flex;gap:4px}
.cl-ft-btn[disabled]{opacity:.35;cursor:default}
.cl-ft-btn{width:26px;height:20px;background:var(--bg-2);border:1px solid var(--sep-s);
  border-radius:4px;display:flex;align-items:center;justify-content:center;cursor:pointer;
  color:var(--t2);font-size:16px;line-height:1;font-family:var(--font);transition:all .1s}
.cl-ft-btn:hover{background:var(--bg-3)}
.cl-ft-btn.danger:hover{background:rgba(255,59,48,.1);color:var(--red);border-color:rgba(255,59,48,.25)}
.cl-add-row{padding:5px 8px}
.cl-add-input{width:100%;font-size:12px;font-family:var(--font);color:var(--t1);
  background:var(--bg-el);border:1px solid var(--sep-s);border-radius:5px;padding:3px 7px;outline:none}
.cl-add-input::placeholder{color:var(--t3)}
.cat-detail-pane{flex:1;background:var(--bg-el);border:1px solid var(--sep);border-radius:10px;
  overflow:hidden;display:flex;flex-direction:column;margin-left:10px}
.cd-header{padding:14px 16px 10px;border-bottom:1px solid var(--sep)}
.cd-name{font-size:15px;font-weight:700;letter-spacing:-.2px}
.cd-meta{font-size:12px;color:var(--t2);margin-top:2px}
.cd-body{flex:1;overflow-y:auto;padding:12px 16px;display:flex;flex-wrap:wrap;
  align-content:flex-start;gap:6px}
.kw-chip{display:flex;align-items:center;gap:3px;padding:2px 8px;background:var(--chip-bg);
  border:1px solid var(--chip-b);border-radius:10px;font-size:11px;color:var(--t1)}
.chip-x{width:14px;height:14px;border-radius:50%;background:var(--t3);border:none;cursor:pointer;
  display:flex;align-items:center;justify-content:center;padding:0;opacity:1;
  flex-shrink:0}
.kw-chip.dragging{opacity:.4;cursor:grabbing}
.kw-chip{cursor:grab}
.cl-row.drag-over{background:rgba(0,122,255,.12)!important;border-bottom-color:rgba(0,122,255,.25)}
.cd-add{display:flex;align-items:center;gap:7px;border-top:1px solid var(--sep);padding:10px 16px}
.cd-input{flex:1;font-size:13px;font-family:var(--font);color:var(--t1);background:var(--bg-2);
  border:1px solid var(--sep-s);border-radius:7px;padding:6px 10px;outline:none;
  -webkit-user-select:auto;user-select:auto}
.cd-input:focus{border-color:var(--sep-s);box-shadow:none}
.cd-input::placeholder{color:var(--t3)}
.cd-add-btn{padding:6px 14px;background:rgba(0,0,0,.06);color:var(--t1);
  border:1px solid rgba(0,0,0,.18);border-radius:7px;
  font-size:13px;font-weight:500;font-family:var(--font);cursor:pointer}
.cd-add-btn:hover{background:var(--bg-3)}
.cd-add-btn:active{transform:scale(.97)}

/* ── Help section ── */
.help-step{display:flex;gap:16px;padding:18px 20px;border-bottom:1px solid var(--sep)}
.help-step:last-child{border-bottom:none}
.step-num{width:28px;height:28px;border-radius:50%;background:var(--bg-3);color:var(--t2);font-size:13px;
  font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:1px}
.step-body{flex:1}
.step-title{font-size:13px;font-weight:600;color:var(--t1);margin-bottom:3px}
.step-desc{font-size:12px;color:var(--t2);line-height:1.55}
.step-tag{display:inline-flex;align-items:center;gap:4px;margin-top:6px;padding:2px 8px;
  background:var(--chip-bg);border:1px solid var(--chip-b);border-radius:5px;font-size:11px;color:var(--t2)}
.help-tip{margin:16px 0 0;padding:12px 14px;background:var(--bg-2);
  border:1px solid var(--sep);border-radius:9px}
.help-tip-title{font-size:12px;font-weight:600;color:var(--t2);margin-bottom:3px}
.help-tip-body{font-size:12px;color:var(--t2);line-height:1.55}
.help-tip.key{border-color:rgba(255,149,0,.45);background:rgba(255,149,0,.07)}
.help-tip.key .help-tip-title{color:var(--t1)}

/* ── About section ── */
.about-wrap{display:flex;flex-direction:column;align-items:center;padding:32px 20px;text-align:center}
.app-icon{width:80px;height:80px;background:#FF9500;border-radius:18px;display:flex;
  align-items:center;justify-content:center;margin-bottom:14px;
  box-shadow:0 4px 16px rgba(255,149,0,.35)}
.app-name{font-size:19px;font-weight:700;letter-spacing:-.3px;margin-bottom:4px}
.app-ver{font-size:13px;color:var(--t2);margin-bottom:16px}
.app-desc{font-size:13px;color:var(--t2);line-height:1.6;max-width:300px;margin-bottom:24px}
.about-links{display:flex;gap:8px;justify-content:center}
.about-link{padding:6px 14px;background:var(--bg-2);border:1px solid var(--sep-s);border-radius:7px;
  font-size:13px;color:var(--t2);font-family:var(--font);cursor:pointer;text-decoration:none}
.about-link:hover{background:var(--bg-3)}

</style>
</head>
<body>
<div class="win-body">
  <div class="sidebar" id="sidebar"></div>
  <div class="detail"  id="detail"></div>
</div>


<script>
// ── State (injected by Python) ────────────────────────────────────────────────
const S = __STATE__;
const DEFAULT_CATS = __DEFAULT_CATS__;
S.sec      = S.sec      || 'general';
S.selCat   = S.selCat   || 0;
S.addingCat = false;
S.dragCat   = -1;   // index of the category row currently being dragged

const XSvg = `<svg viewBox="0 0 8 8" width="8" height="8" fill="none"><path d="M1 1l6 6M7 1L1 7" stroke="white" stroke-width="1.5" stroke-linecap="round"/></svg>`;
const CheckSvg = `<svg viewBox="0 0 10 10" width="9" height="9" fill="none"><path d="M1.5 5.2l2.2 2.2L8.5 2.6" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

// All user-entered text (category names, keywords) goes through esc() before
// reaching innerHTML — a keyword like "R&D" or "<8" would otherwise corrupt
// the markup or inject into it.
function esc(s) {
  return String(s).replace(/[&<>"']/g, ch => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]
  ));
}
let _dragKw = null; // {catIdx, kwIdx} — set during keyword drag

// Drawn in SF Symbols' idiom: 16px grid, 1.5 stroke, currentColor, no
// fill. The size is a parameter so the sidebar (16px) and the step tags
// in How to Use (12px) draw from one set of paths rather than drifting.
const _sym = (d, px = 16) => `<svg width="${px}" height="${px}" viewBox="0 0 16 16"
  fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"
  stroke-linejoin="round">${d}</svg>`;

// gearshape — 8 even teeth, generated rather than hand-drawn so the
// spacing is exact; a hand-written path reads as lumpy at 16px.
const P_GEAR = `<path stroke-linejoin="round" d="M6.87 1.19 L9.13 1.19 L9.38 2.93 L10.61 3.44 L12.01 2.39 L13.61 3.99 L12.56 5.39 L13.07 6.62 L14.81 6.87 L14.81 9.13 L13.07 9.38 L12.56 10.61 L13.61 12.01 L12.01 13.61 L10.61 12.56 L9.38 13.07 L9.13 14.81 L6.87 14.81 L6.62 13.07 L5.39 12.56 L3.99 13.61 L2.39 12.01 L3.44 10.61 L2.93 9.38 L1.19 9.13 L1.19 6.87 L2.93 6.62 L3.44 5.39 L2.39 3.99 L3.99 2.39 L5.39 3.44 L6.62 2.93 Z"/><circle cx="8" cy="8" r="2.35"/>`;
// slider.horizontal.3
const P_SLIDERS = `<path d="M2 4.3h12M2 8h12M2 11.7h12"/><circle cx="5.6" cy="4.3" r="1.5" fill="currentColor" stroke="none"/><circle cx="10.4" cy="8" r="1.5" fill="currentColor" stroke="none"/><circle cx="6.4" cy="11.7" r="1.5" fill="currentColor" stroke="none"/>`;
// questionmark.circle
const P_QUESTION = `<circle cx="8" cy="8" r="6.3"/><path d="M6.35 6.25a1.7 1.7 0 1 1 1.95 1.8v1.1"/><circle cx="8.3" cy="11.3" r=".55" fill="currentColor" stroke="none"/>`;
// info.circle
const P_INFO = `<circle cx="8" cy="8" r="6.3"/><path d="M8 7.3v3.6"/><circle cx="8" cy="5.1" r=".55" fill="currentColor" stroke="none"/>`;
// square.and.arrow.up — the DAW export step
const P_EXPORT = `<path d="M8 1.7v7.1"/><path d="M5.5 4.2 8 1.7l2.5 2.5"/><path d="M3.1 9.3v3.4a1.3 1.3 0 0 0 1.3 1.3h7.2a1.3 1.3 0 0 0 1.3-1.3V9.3"/>`;
// menubar.rectangle — the menu bar step
const P_MENUBAR = `<rect x="1.5" y="3.2" width="13" height="9.6" rx="1.7"/><path d="M1.5 6.2h13"/><circle cx="12.2" cy="4.7" r=".5" fill="currentColor" stroke="none"/><circle cx="10.4" cy="4.7" r=".5" fill="currentColor" stroke="none"/>`;
// folder — where the AAF lands
const P_FOLDER = `<path d="M1.7 4.4a1.3 1.3 0 0 1 1.3-1.3h2.4l1.5 1.8h5.4a1.3 1.3 0 0 1 1.3 1.3v5.6a1.3 1.3 0 0 1-1.3 1.3H3a1.3 1.3 0 0 1-1.3-1.3z"/>`;

const IconGeneral    = _sym(P_GEAR);
const IconCategories = _sym(P_SLIDERS);
const IconHelp       = _sym(P_QUESTION);
const IconAbout      = _sym(P_INFO);

// 12px versions for the inline tags under each How to Use step.
const TagGear    = _sym(P_GEAR, 12);
const TagExport  = _sym(P_EXPORT, 12);
const TagMenubar = _sym(P_MENUBAR, 12);
const TagFolder  = _sym(P_FOLDER, 12);

const SECTIONS = [
  {id:'general',    icon:IconGeneral,    label:'General'},
  {id:'categories', icon:IconCategories, label:'Categories'},
  {id:'help',       icon:IconHelp,       label:'How to Use'},
  {id:'about',      icon:IconAbout,      label:'About'},
];

// ── Native bridge ─────────────────────────────────────────────────────────────
function post(msg) {
  window.webkit.messageHandlers.stem2aaf.postMessage(msg);
}

// Python calls this after the folder picker resolves
function updateFolderPath(key, path) {
  if (key === 'watch_folder')  S.watch_folder  = path;
  if (key === 'output_folder') S.output_folder = path;
  renderDetail();
  autoSave();
}

// ── Sidebar ───────────────────────────────────────────────────────────────────
function renderSidebar() {
  document.getElementById('sidebar').innerHTML =
    '<div class="sb-group-label">Stem2AAF</div>' +
    SECTIONS.map(s =>
      `<div class="sb-row${S.sec===s.id?' active':''}" onclick="nav('${s.id}')">
         <div class="sb-icon">${s.icon}</div>
         <span class="sb-name">${s.label}</span>
       </div>`
    ).join('');
}

function nav(sec) { S.sec = sec; renderSidebar(); renderDetail(); }

// ── Detail dispatcher ─────────────────────────────────────────────────────────
function renderDetail() {
  const el = document.getElementById('detail');
  // Categories is the one section laid out as two full-height columns;
  // it needs the detail pane to be a flex column so .cat-split can take
  // exactly the space the section label leaves over.
  el.classList.toggle('split-mode', S.sec === 'categories');
  if      (S.sec === 'general')    el.innerHTML = generalHTML();
  else if (S.sec === 'categories') { el.innerHTML = categoriesHTML(); if (S.addingCat) setTimeout(() => document.getElementById('cl-new')?.focus(), 0); }
  else if (S.sec === 'help')       el.innerHTML = helpHTML();
  else                             el.innerHTML = aboutHTML();
}

// ── General ───────────────────────────────────────────────────────────────────
function generalHTML() {
  return `
    <div class="sec-label">Folders</div>
    <div class="sg">
      <div class="sr">
        <div class="sr-text">
          <div class="sr-title">Watch Folder</div>
          <div class="sr-value">${esc(S.watch_folder)}</div>
        </div>
        <button class="change-btn" onclick="openFolder('watch_folder')">Change…</button>
      </div>
      <div class="sr">
        <div class="sr-text">
          <div class="sr-title">Output Folder</div>
          <div class="sr-value">${esc(S.output_folder)}</div>
        </div>
        <button class="change-btn" onclick="openFolder('output_folder')">Change…</button>
      </div>
    </div>

    <div class="sec-label">Conversion</div>
    <div class="sg">
      <div class="sr sr-toggle">
        <div class="sr-text" style="flex:1">
          <div class="sr-title">Group stems by category</div>
          <div class="sr-desc">Organise exported tracks into category folders in the AAF — Drums, Bass, Vocals…</div>
        </div>
        <button class="tog${S.group_by_cat?' on':''}" onclick="S.group_by_cat=!S.group_by_cat;this.classList.toggle('on',S.group_by_cat);autoSave()"></button>
      </div>
      <div class="sr sr-toggle">
        <div class="sr-text" style="flex:1">
          <div class="sr-title">Keep stems after conversion</div>
          <div class="sr-desc">Keep renamed stems next to converted AAF.</div>
        </div>
        <button class="tog${S.keep_stems?' on':''}" onclick="S.keep_stems=!S.keep_stems;this.classList.toggle('on',S.keep_stems);autoSave()"></button>
      </div>
      <div class="sr sr-toggle">
        <div class="sr-text" style="flex:1">
          <div class="sr-title">Auto-convert when stems arrive</div>
          <div class="sr-desc">Build an AAF once the number of waiting stems has held steady for __QUIET_SECONDS__ seconds. A batch where any file is still being written is never converted — you'll get an error instead of an AAF missing tracks.</div>
        </div>
        <button class="tog${S.auto_convert?' on':''}" onclick="S.auto_convert=!S.auto_convert;this.classList.toggle('on',S.auto_convert);autoSave()"></button>
      </div>
    </div>

    <div class="sec-label">Application</div>
    <div class="sg">
      <div class="sr sr-toggle">
        <div class="sr-text" style="flex:1">
          <div class="sr-title">Launch at login</div>
          <div class="sr-desc">Start Stem2AAF automatically when you log in, so the menu bar icon is always there.</div>
        </div>
        <button class="tog${S.launch_at_login?' on':''}" onclick="S.launch_at_login=!S.launch_at_login;this.classList.toggle('on',S.launch_at_login);autoSave()"></button>
      </div>
      <div class="sr">
        <div class="sr-text">
          <div class="sr-title">Uninstall Stem2AAF</div>
          <div class="sr-desc">Removes the app, its settings and its login item. Your project folder is left alone.</div>
        </div>
        <button class="change-btn danger" onclick="post({action:'uninstall'})">Uninstall…</button>
      </div>
    </div>`;
}

function openFolder(key) {
  post({action: 'open_folder', key: key});
}

// ── Categories ────────────────────────────────────────────────────────────────
function categoriesHTML() {
  const cats = S.categories;
  const sel  = S.selCat;
  const cat  = cats[sel] || cats[0];

  const listRows = cats.map((c, i) => `
    <div class="cl-row${i===sel?' active':''}${c.enabled?'':' off'}${i===S.dragCat?' dragging':''}" data-idx="${i}" onmousedown="catDragStart(event,${i})" onclick="selCat(${i})">
      <span class="cl-check${c.enabled?'':' off'}" onclick="event.stopPropagation();toggleCat(${i})" title="${c.enabled?'Stop matching this category':'Match this category again'}">${CheckSvg}</span>
      <span class="cl-name">${esc(c.name)}</span>
    </div>`).join('');

  const addRow = S.addingCat
    ? `<div class="cl-add-row"><input class="cl-add-input" id="cl-new" placeholder="Name…" onkeydown="addCatKey(event)"></div>`
    : '';

  const chips = cat.keywords.map((kw, ki) =>
    `<span class="kw-chip" onmousedown="kwDragStart(event,${sel},${ki})">${esc(kw)}<button class="chip-x" onclick="rmKw(${ki})">${XSvg}</button></span>`
  ).join('');

  return `
    <div class="cat-heads">
      <div class="h-cat"><div class="sec-label">Category</div></div>
      <div class="h-kw"><div class="sec-label">Keywords</div></div>
    </div>
    <div class="cat-split">
      <div class="cat-list-pane">
        <div class="cat-list-inner">
          ${listRows}
          ${addRow}
        </div>
        <div class="cl-footer">
          <button class="cl-ft-btn" onclick="S.addingCat=true;renderDetail()" title="Add a category">+</button>
          <button class="cl-ft-btn danger" onclick="rmCat(${sel})" title="Remove this category">−</button>
          <button class="cl-ft-btn" onclick="moveCat(-1)" title="Move up" ${sel<=0?'disabled':''} style="font-size:12px">↑</button>
          <button class="cl-ft-btn" onclick="moveCat(1)" title="Move down" ${sel>=cats.length-1?'disabled':''} style="font-size:12px">↓</button>
          <button class="cl-ft-btn" onclick="resetAllCats()" title="Reset all categories to defaults" style="margin-left:auto;font-size:13px">↺</button>
        </div>
      </div>
      <div class="cat-detail-pane">
        <div class="cd-header" style="display:flex;align-items:flex-start;justify-content:space-between">
          <div>
            <div class="cd-name">${esc(cat.name)}</div>
            <div class="cd-meta">${cat.keywords.length} keyword${cat.keywords.length!==1?'s':''} · ${cat.enabled?'Enabled':'Disabled'}</div>
          </div>
          ${DEFAULT_CATS.find(c=>c.name===cat.name) ? `<button class="cl-ft-btn" style="margin-top:2px;font-size:13px" onclick="resetCatKws(${sel})" title="Restore default keywords">↺</button>` : ''}
        </div>
        <div class="cd-body">
          ${chips || '<span style="font-size:13px;color:var(--t3)">No keywords — add one below</span>'}
        </div>
        <div class="cd-add">
          <input class="cd-input" id="cd-kwin" placeholder="Add keyword…" onkeydown="if(event.key==='Enter')addKw()">
          <button class="cd-add-btn" onclick="addKw()">Add</button>
        </div>
      </div>
    </div>`;
}

function selCat(i)    { if (_wasJustDragging()) return; S.selCat = i; renderDetail(); }
function toggleCat(i) {
  // Ignore the click that lands when a drag is released over a row, so
  // reordering never flips a category's enabled state by accident.
  if (_wasJustDragging()) return;
  // Deliberately does NOT touch S.selCat. The two gestures are separate:
  // clicking the row changes which category you are editing, clicking the
  // checkbox turns that category on or off. Selecting here as well meant
  // you could not toggle one category while reading another's keywords.
  S.categories[i].enabled = !S.categories[i].enabled;
  renderDetail(); autoSave();
}
function rmKw(ki)     { S.categories[S.selCat].keywords.splice(ki, 1); renderDetail(); autoSave(); }
function addKw() {
  const el = document.getElementById('cd-kwin');
  const v  = el?.value?.trim();
  if (v) { S.categories[S.selCat].keywords.push(v); renderDetail(); autoSave(); setTimeout(() => document.getElementById('cd-kwin')?.focus(), 0); }
}
function addCatKey(e) {
  if (e.key === 'Enter') {
    const el = document.getElementById('cl-new');
    const v  = el?.value?.trim();
    if (v) { S.categories.push({name: v, enabled: true, keywords: []}); S.selCat = S.categories.length - 1; }
    S.addingCat = false; renderDetail(); autoSave();
  }
  if (e.key === 'Escape') { S.addingCat = false; renderDetail(); }
}
function rmCat(i) {
  if (S.categories.length <= 1) return;
  S.categories.splice(i, 1);
  S.selCat = Math.min(i > 0 ? i - 1 : 0, S.categories.length - 1);
  renderDetail(); autoSave();
}
function resetCatKws(i) {
  const def = DEFAULT_CATS.find(c => c.name === S.categories[i].name);
  if (def) S.categories[i].keywords = [...def.keywords];
  renderDetail(); autoSave();
}
function resetAllCats() {
  S.categories = JSON.parse(JSON.stringify(DEFAULT_CATS));
  S.selCat = 0;
  renderDetail(); autoSave();
}

// ── Category reordering ──────────────────────────────────────────────────────
// Order matters to the converter twice over: it sets the order the groups
// appear in the AAF, and it decides the winner when a filename matches
// keywords from more than one category. There was no way to change it from
// here at all, despite the config storing it and the converter reading it.

function moveCat(delta) {
  const from = S.selCat, to = from + delta;
  if (to < 0 || to >= S.categories.length) return;
  S.categories.splice(to, 0, S.categories.splice(from, 1)[0]);
  S.selCat = to;
  renderDetail(); autoSave();
}

let _dragCat = null;      // {idx, startY, moved}
let _catDragEndedAt = 0;  // when the last real drag finished, see _catDragUp

function catDragStart(event, idx) {
  if (event.button !== 0) return;           // left button only
  if (event.target.closest('.cl-check')) return;  // that's the enable toggle
  _dragCat = {idx, startY: event.clientY, moved: false};
  document.addEventListener('mousemove', _catDragMove);
  document.addEventListener('mouseup',   _catDragUp);
}

function _catDragMove(event) {
  if (!_dragCat) return;
  // Only treat it as a drag past a small threshold, so an ordinary click
  // still selects the row instead of being eaten as a zero-distance drag.
  if (!_dragCat.moved) {
    if (Math.abs(event.clientY - _dragCat.startY) < 4) return;
    _dragCat.moved = true;
    S.dragCat = _dragCat.idx;
    renderDetail();
  }
  event.preventDefault();

  const rows = [...document.querySelectorAll('.cl-row')];
  if (!rows.length) return;
  let target = rows.findIndex(r => {
    const b = r.getBoundingClientRect();
    return event.clientY >= b.top && event.clientY <= b.bottom;
  });
  // Dragging past either end pins to that end rather than doing nothing.
  if (target < 0) {
    if (event.clientY < rows[0].getBoundingClientRect().top) target = 0;
    else if (event.clientY > rows[rows.length - 1].getBoundingClientRect().bottom) target = rows.length - 1;
    else return;
  }
  if (target === _dragCat.idx) return;

  // Keep the selection on whichever category it was on, by identity
  // rather than by index, since the indices are about to shift.
  const selected = S.categories[S.selCat];
  S.categories.splice(target, 0, S.categories.splice(_dragCat.idx, 1)[0]);
  S.selCat = S.categories.indexOf(selected);
  _dragCat.idx = target;
  S.dragCat = target;
  renderDetail();
}

function _catDragUp() {
  document.removeEventListener('mousemove', _catDragMove);
  document.removeEventListener('mouseup',   _catDragUp);
  const didMove = !!(_dragCat && _dragCat.moved);
  _dragCat = null;

  if (!didMove) {
    // Plain click, not a drag — and it is essential NOT to re-render here.
    // The click event has not been dispatched yet at mouseup time. Replacing
    // the list's DOM now destroys the row that was pressed, so the click has
    // no surviving target and onclick="selCat(i)" never fires. That is what
    // made selecting a category stop working entirely while the checkbox,
    // which never arms these listeners, kept working.
    return;
  }

  S.dragCat = -1;
  // Letting go over a row would otherwise also count as a click on it.
  // A timestamp rather than a one-shot capture listener: releasing outside
  // the list produces no click at all, which left that listener armed
  // indefinitely and ate some unrelated click much later.
  _catDragEndedAt = Date.now();
  renderDetail();
  autoSave();
}

function _wasJustDragging() { return Date.now() - _catDragEndedAt < 250; }

// ── Keyword drag-and-drop (mouse events — WKWebView safe) ────────────────────
function kwDragStart(event, catIdx, kwIdx) {
  if (event.target.closest('.chip-x')) return;
  _dragKw = {catIdx, kwIdx};
  event.currentTarget.classList.add('dragging');
  event.preventDefault();
  document.addEventListener('mousemove', _kwDragMove);
  document.addEventListener('mouseup',   _kwDragUp);
}
function _kwDragMove(event) {
  if (!_dragKw) return;
  document.querySelectorAll('.cl-row').forEach(r => r.classList.remove('drag-over'));
  const target = document.elementFromPoint(event.clientX, event.clientY);
  const row = target?.closest?.('[data-idx]');
  if (row && +row.dataset.idx !== _dragKw.catIdx) row.classList.add('drag-over');
}
function _kwDragUp(event) {
  document.removeEventListener('mousemove', _kwDragMove);
  document.removeEventListener('mouseup',   _kwDragUp);
  document.querySelectorAll('.kw-chip.dragging').forEach(c => c.classList.remove('dragging'));
  document.querySelectorAll('.cl-row.drag-over').forEach(r => r.classList.remove('drag-over'));
  if (!_dragKw) return;
  const target = document.elementFromPoint(event.clientX, event.clientY);
  const row = target?.closest?.('[data-idx]');
  if (row) {
    const targetIdx = +row.dataset.idx;
    if (targetIdx !== _dragKw.catIdx) {
      const kw = S.categories[_dragKw.catIdx].keywords.splice(_dragKw.kwIdx, 1)[0];
      S.categories[targetIdx].keywords.push(kw);
      renderDetail(); autoSave();
    }
  }
  _dragKw = null;
}

// ── Help ──────────────────────────────────────────────────────────────────────
function helpHTML() {
  return `
    <div class="sec-label">Workflow</div>
    <div class="sg">
      <div class="help-step">
        <div class="step-num">1</div>
        <div class="step-body">
          <div class="step-title">Choose your folders</div>
          <div class="step-desc">The <strong>Watch Folder</strong> is where your DAW exports stems. Set it once and leave it. The <strong>Output Folder</strong> is the project &mdash; its name becomes the project name, so point it at a new folder for each song.</div>
          <div class="step-tag">${TagGear} General &rarr; Watch Folder, Output Folder</div>
        </div>
      </div>
      <div class="help-step">
        <div class="step-num">2</div>
        <div class="step-body">
          <div class="step-title">Export every track in one pass</div>
          <div class="step-desc">Export all tracks together in a <strong>single</strong> operation. Track names decide the categories, so name them the way you want them sorted &mdash; a track called <em>Kick</em> lands in Drums.</div>
          <div class="step-tag">${TagExport} Your DAW &rarr; Export Audio to Watch Folder</div>
        </div>
      </div>
      <div class="help-step">
        <div class="step-num">3</div>
        <div class="step-body">
          <div class="step-title">Convert</div>
          <div class="step-desc">The menu bar counts what&rsquo;s waiting. When it matches what you exported, click <em>Convert to AAF</em>. Or turn on <em>Auto-convert</em> in General and it fires once the count holds steady for __QUIET_SECONDS__ seconds.</div>
          <div class="step-tag">${TagMenubar} Menu bar &rarr; Convert to AAF</div>
        </div>
      </div>
      <div class="help-step">
        <div class="step-num">4</div>
        <div class="step-body">
          <div class="step-title">Import the AAF</div>
          <div class="step-desc">Each conversion gets its own numbered folder holding the <em>.AAF</em>, a log, and your stems unless you&rsquo;ve turned off <em>Keep stems</em>.</div>
          <div class="step-tag">${TagFolder} Output Folder &rarr; &lt;project&gt; Converted v1</div>
        </div>
      </div>
    </div>
    <div class="help-tip key">
      <div class="help-tip-title">Nothing is converted halfway</div>
      <div class="help-tip-body">If any file is still being written, <strong>nothing</strong> is converted: you get an error naming the file, and no AAF. Wait for the export to finish, then convert again.</div>
    </div>
    <div class="help-tip">
      <div class="help-tip-title">Categories sort, they don&rsquo;t bus</div>
      <div class="help-tip-body">With <em>Group stems by category</em> on, tracks arrive ordered and named <em>Drums_Kick (01)</em>. It sorts and labels them; it does not create busses.</div>
    </div>`;
}

// ── About ─────────────────────────────────────────────────────────────────────
function aboutHTML() {
  return `
    <div class="about-wrap">
      <div class="app-icon">
        <!-- The app's own mark: five centred bars, short-tall-tallest-tall-short.
             Geometry traced from src/assets/app_icon_source.png and scaled from
             its 1024px canvas to this 40-unit viewBox, so the About panel shows
             the same logo as the Dock and menu bar rather than a different
             drawing. Colours are unchanged: white bars on the orange tile. -->
        <svg viewBox="0 0 40 40" width="48" height="48" fill="none" aria-label="Stem2AAF">
          <g fill="rgba(255,255,255,.9)">
            <rect x="5.59"  y="14.88" width="4.06" height="10.27" rx="2.03"/>
            <rect x="11.80" y="10.08" width="4.02" height="19.88" rx="2.01"/>
            <rect x="18.01" y="3.98"  width="4.02" height="32.07" rx="2.01"/>
            <rect x="24.22" y="10.08" width="4.02" height="19.88" rx="2.01"/>
            <rect x="30.39" y="14.88" width="4.06" height="10.27" rx="2.03"/>
          </g>
        </svg>
      </div>
      <div class="app-name">Stem2AAF</div>
      <div class="app-ver">Version ${VERSION} (${BUILD})</div>
      <div class="app-desc">Watches a folder for stem exports and converts them to AAF files ready for import into your favourite app.</div>
      <div class="app-desc" style="margin-top:10px">Every conversion writes a log next to its AAF. If something goes wrong, that file says what happened.</div>
    </div>`;
}

// ── Auto-save (fires on every state change) ───────────────────────────────────
function autoSave() {
  post({
    action: 'update',
    state: {
      watch_folder:  S.watch_folder,
      output_folder: S.output_folder,
      group_by_cat:  S.group_by_cat,
      // The UI asks "keep?", the config stores "delete?" — inverted here at
      // the boundary so app.py, watcher.py and existing config.json files
      // are untouched. The label is the honest one: off doesn't mean "do
      // nothing", it means the stems are archived beside the AAF.
      delete_stems:  !S.keep_stems,
      auto_convert:  S.auto_convert,
      launch_at_login: S.launch_at_login,
      categories:    S.categories,
    }
  });
}

// ── Boot ──────────────────────────────────────────────────────────────────────
renderSidebar();
renderDetail();
</script>
</body>
</html>"""

# Replace version string at load time
_HTML = (_HTML.replace("${VERSION}", VERSION)
              .replace("${BUILD}", BUILD)
              .replace("__QUIET_SECONDS__", str(AUTO_CONVERT_QUIET_SECONDS)))


# ── Message handler ───────────────────────────────────────────────────────────

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
        html = _HTML.replace("__STATE__", json.dumps(state)) \
                    .replace("__DEFAULT_CATS__", json.dumps(DEFAULT_CATEGORIES))
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
            }
            # Live apply — the panel stays open; the close button dismisses it.
            self._on_save(config)

        elif action == "uninstall":
            # Handed back to the app, which owns the confirmation dialog
            # and the bundled uninstall script.
            if self._on_uninstall is not None:
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
