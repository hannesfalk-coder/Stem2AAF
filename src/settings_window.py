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
    delete_stems   : bool  — delete stems after conversion
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

_TITLED        = 1    # NSWindowStyleMaskTitled
_CLOSABLE      = 2    # NSWindowStyleMaskClosable
_NONACTIVATING = 128  # NSWindowStyleMaskNonactivatingPanel


class _SettingsPanel(NSPanel):
    """NSPanel that accepts first-click on controls (incl. close button) without
    requiring the app to activate first, while still becoming key for WKWebView
    keyboard input."""

    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return False

_W, _H = 680, 510   # panel width × height (title bar + content + footer)

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
.sb-icon{width:22px;height:22px;border-radius:5px;display:flex;align-items:center;
  justify-content:center;flex-shrink:0;font-size:13px;background:var(--bg-2)}
.sb-row.active .sb-icon{background:rgba(0,0,0,.06)}
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
.cat-split{display:flex;gap:0;height:100%;min-height:340px}
.cat-list-pane{width:150px;flex-shrink:0;background:var(--bg-el);border:1px solid var(--sep);
  border-radius:10px;overflow:hidden;display:flex;flex-direction:column}
.cat-list-inner{flex:1;overflow-y:auto}
.cl-row{display:flex;align-items:center;gap:8px;padding:8px 10px;cursor:pointer;
  transition:background .08s;border-bottom:1px solid var(--sep)}
.cl-row:last-child{border-bottom:none}
.cl-row:hover{background:var(--chip-bg)}
.cl-row.active{background:rgba(0,0,0,.06)}
.cl-dot{width:9px;height:9px;border-radius:50%;background:#FF9500;flex-shrink:0;cursor:pointer;transition:opacity .1s}.cl-dot:hover{opacity:.7}
.cl-dot.off{background:var(--t3)}
.cl-row.active .cl-dot{background:#FF9500}
.cl-row.active .cl-dot.off{background:var(--t3)}
.cl-name{flex:1;font-size:13px;font-weight:500;color:var(--t1)}
.cl-row.active .cl-name{color:var(--t1)}
.cl-footer{padding:7px 10px;border-top:1px solid var(--sep);display:flex;gap:5px}
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

const XSvg = `<svg viewBox="0 0 8 8" width="8" height="8" fill="none"><path d="M1 1l6 6M7 1L1 7" stroke="white" stroke-width="1.5" stroke-linecap="round"/></svg>`;

// All user-entered text (category names, keywords) goes through esc() before
// reaching innerHTML — a keyword like "R&D" or "<8" would otherwise corrupt
// the markup or inject into it.
function esc(s) {
  return String(s).replace(/[&<>"']/g, ch => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]
  ));
}
let _dragKw = null; // {catIdx, kwIdx} — set during keyword drag

const SECTIONS = [
  {id:'general',    icon:'⚙️',  label:'General'},
  {id:'categories', icon:'🎛️',  label:'Categories'},
  {id:'help',       icon:'<span style="color:var(--t2);font-size:15px;font-weight:600;line-height:1">?</span>', label:'How to Use'},
  {id:'about',      icon:'ℹ️',  label:'About'},
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
          <div class="sr-title">Delete stems after conversion</div>
          <div class="sr-desc">Remove source audio files once the AAF is built. The AAF embeds all audio — stems aren't needed.</div>
        </div>
        <button class="tog${S.delete_stems?' on':''}" onclick="S.delete_stems=!S.delete_stems;this.classList.toggle('on',S.delete_stems);autoSave()"></button>
      </div>
      <div class="sr sr-toggle">
        <div class="sr-text" style="flex:1">
          <div class="sr-title">Auto-convert when stems arrive</div>
          <div class="sr-desc">Build an AAF once the number of waiting stems has held steady for 12 seconds. A batch where any file is still being written is never converted — you'll get an error instead of an AAF missing tracks.</div>
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
    <div class="cl-row${i===sel?' active':''}" data-idx="${i}" onclick="selCat(${i})">
      <span class="cl-dot${c.enabled?'':' off'}" onclick="event.stopPropagation();toggleCat(${i})" title="${c.enabled?'Click to disable':'Click to enable'}"></span>
      <span class="cl-name">${esc(c.name)}</span>
    </div>`).join('');

  const addRow = S.addingCat
    ? `<div class="cl-add-row"><input class="cl-add-input" id="cl-new" placeholder="Name…" onkeydown="addCatKey(event)"></div>`
    : '';

  const chips = cat.keywords.map((kw, ki) =>
    `<span class="kw-chip" onmousedown="kwDragStart(event,${sel},${ki})">${esc(kw)}<button class="chip-x" onclick="rmKw(${ki})">${XSvg}</button></span>`
  ).join('');

  return `
    <div class="sec-label">Category Keywords</div>
    <div class="cat-split">
      <div class="cat-list-pane">
        <div class="cat-list-inner">
          ${listRows}
          ${addRow}
        </div>
        <div class="cl-footer">
          <button class="cl-ft-btn" onclick="S.addingCat=true;renderDetail()">+</button>
          <button class="cl-ft-btn danger" onclick="rmCat(${sel})">−</button>
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

function selCat(i)    { S.selCat = i; renderDetail(); }
function toggleCat(i) { S.categories[i].enabled = !S.categories[i].enabled; S.selCat = i; renderDetail(); autoSave(); }
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
          <div class="step-title">Set your Watch Folder</div>
          <div class="step-desc">In General, point the Watch Folder at wherever your DAW exports its stems. Stem2AAF monitors this folder automatically — no action needed after setup.</div>
          <div class="step-tag">⚙️ General → Watch Folder</div>
        </div>
      </div>
      <div class="help-step">
        <div class="step-num">2</div>
        <div class="step-body">
          <div class="step-title">Export your stems</div>
          <div class="step-desc">From your DAW, export each track or group as a separate audio stem into the Watch Folder.</div>
          <div class="step-tag">🎛 Your DAW → Export stems</div>
        </div>
      </div>
      <div class="help-step">
        <div class="step-num">3</div>
        <div class="step-body">
          <div class="step-title">Click Convert to AAF</div>
          <div class="step-desc">Click the Stem2AAF icon in the menu bar and choose <strong>Convert to AAF</strong>. The app reads every stem in the Watch Folder and bundles them into a single .aaf file with embedded audio.</div>
          <div class="step-tag">⌘K  Convert to AAF</div>
        </div>
      </div>
      <div class="help-step">
        <div class="step-num">4</div>
        <div class="step-body">
          <div class="step-title">Import the AAF into your favourite app</div>
          <div class="step-desc">The finished .aaf appears in your Output Folder. Import it into your favourite app — all stems land on separate tracks, ready to mix.</div>
          <div class="step-tag">📂 Output Folder → Import into your favourite app</div>
        </div>
      </div>
    </div>
    <div class="help-tip">
      <div class="help-tip-title">Tip — Categories speed up mixing</div>
      <div class="help-tip-body">Enable <em>Group stems by category</em> in General and configure your keywords in Categories. Tracks are named and grouped automatically, so Drums, Bass, and Vocals each arrive on their own bus in your app.</div>
    </div>`;
}

// ── About ─────────────────────────────────────────────────────────────────────
function aboutHTML() {
  return `
    <div class="about-wrap">
      <div class="app-icon">
        <svg viewBox="0 0 40 40" width="48" height="48" fill="none">
          <rect x="8"  y="20" width="6" height="12" rx="2" fill="rgba(255,255,255,.9)"/>
          <rect x="17" y="14" width="6" height="18" rx="2" fill="rgba(255,255,255,.9)"/>
          <rect x="26" y="8"  width="6" height="24" rx="2" fill="rgba(255,255,255,.9)"/>
          <path d="M36 34L38 32L38 36z" fill="rgba(255,255,255,.75)"/>
          <path d="M34 34h6" stroke="rgba(255,255,255,.9)" stroke-width="1.5" stroke-linecap="round"/>
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
      delete_stems:  S.delete_stems,
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
_HTML = _HTML.replace("${VERSION}", VERSION).replace("${BUILD}", BUILD)


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
            "delete_stems":    config.get("delete_stems",    False),
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
        webview = WKWebView.alloc().initWithFrame_configuration_(frame, wk_config)
        webview.setValue_forKey_(False, "drawsBackground")
        self._webview = webview

        # Inject state and load HTML
        html = _HTML.replace("__STATE__", json.dumps(state)) \
                    .replace("__DEFAULT_CATS__", json.dumps(DEFAULT_CATEGORIES))
        webview.loadHTMLString_baseURL_(html, None)

        # NSPanel
        panel = _SettingsPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, _TITLED | _CLOSABLE | _NONACTIVATING, NSBackingStoreBuffered, False
        )
        panel.setTitle_("Stem2AAF Settings")
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
