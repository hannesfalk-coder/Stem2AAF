"""
category_panel.py

Native macOS "Category Order & Keywords" panel — a floating NSPanel that
contains a WKWebView with full keyword management:

Left column (always visible):
  - Drag to reorder categories
  - Toggle to enable/skip a category
  - Click grip (≡) to open keyword editor
  - Add / rename / delete categories (max 15)

Right column (slides in from right when grip clicked):
  - Add / delete keywords for the selected category (max 50)
  - Drag keyword chips onto category rows to move them between categories

On Done, posts the full custom keyword map back to Python so the converter
no longer needs to fall back to its hardcoded defaults.

Python injects the current state as JS constants; the page posts back via
window.webkit.messageHandlers.stem2aaf when the user clicks Done,
or sends {action:'expand'} / {action:'collapse'} messages so Python can
animate the NSPanel width.
"""

import json

import objc
from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSMakeRect,
    NSPanel,
)
from Foundation import NSObject
from WebKit import WKUserContentController, WKWebView, WKWebViewConfiguration

from converter import _CATEGORY_KEYWORDS

# Raw integer masks for broadest macOS compatibility
_TITLED   = 1   # NSWindowStyleMaskTitled
_CLOSABLE = 2   # NSWindowStyleMaskClosable

_PANEL_W_COLLAPSED = 320
_PANEL_W_EXPANDED  = 640
_PANEL_H           = 660

_MAX_CATS = 15
_MAX_KWS  = 50

DEFAULT_CATEGORIES = [
    {"name": "Drums",      "enabled": True},
    {"name": "Bass",       "enabled": True},
    {"name": "Guitar",     "enabled": True},
    {"name": "Keys",       "enabled": True},
    {"name": "Orchestral", "enabled": True},
    {"name": "Synth",      "enabled": True},
    {"name": "Strings",    "enabled": True},
    {"name": "Vocal",      "enabled": True},
    {"name": "Sends",      "enabled": True},
]

# Default keyword map built from the converter's source of truth
_DEFAULT_KW_MAP = {cat: list(kws) for cat, kws in _CATEGORY_KEYWORDS}

# ── HTML template ──────────────────────────────────────────────────────────────
# Placeholders replaced at runtime:
#   __DEFAULTS__        → JSON array of default categories
#   __DEFAULT_KW_MAP__  → JSON object {name: [kw, ...]} (defaults)
#   __CATEGORIES__      → JSON array of current categories
#   __CUSTOM_KEYWORDS__ → JSON object {name: [kw, ...]} (current state)
#   __MAX_CATS__        → integer (15)
#   __MAX_KWS__         → integer (50)

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --text:#1d1d1f;
  --text2:#6e6e73;
  --text-dim:#b0b0b5;
  --sep:rgba(0,0,0,.11);
  --hover:rgba(0,0,0,.04);
  --drag-bg:rgba(0,100,255,.06);
  --drag-line:rgba(0,100,255,.35);
  --tog-off:#d1d1d6;
  --tog-on:#e07b2c;
  --pin-bg:rgba(0,0,0,.03);
  --pin-text:#8e8e93;
  --btn:#e07b2c;
  --btn-h:#c96b1e;
  --chip-bg:rgba(0,0,0,.07);
  --chip-drop:rgba(224,123,44,.15);
  --chip-drop-border:rgba(224,123,44,.5);
  --kw-bg:rgba(0,0,0,.025);
  --kw-sep:rgba(0,0,0,.08);
  --del:#dd0055;
  --sel-row:rgba(224,123,44,.07);
}
@media(prefers-color-scheme:dark){
  :root{
    --text:#f5f5f5;
    --text2:#8e8e93;
    --text-dim:#55555a;
    --sep:rgba(255,255,255,.1);
    --hover:rgba(255,255,255,.05);
    --drag-bg:rgba(80,150,255,.1);
    --drag-line:rgba(80,150,255,.45);
    --tog-off:#48484a;
    --pin-bg:rgba(255,255,255,.04);
    --pin-text:#636366;
    --btn-h:#f08c3d;
    --chip-bg:rgba(255,255,255,.1);
    --chip-drop:rgba(224,123,44,.18);
    --chip-drop-border:rgba(224,123,44,.55);
    --kw-bg:rgba(255,255,255,.03);
    --kw-sep:rgba(255,255,255,.08);
    --del:#ff4488;
    --sel-row:rgba(224,123,44,.09);
  }
}
html,body{
  width:100%;height:100%;
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text",sans-serif;
  background:Canvas;color:var(--text);
  -webkit-font-smoothing:antialiased;
  -webkit-user-select:none;user-select:none;
  overflow:hidden;
}
/* ── Layout ── */
.panel-wrap{display:flex;width:100%;height:100%;overflow:hidden}
/* ── Left column ── */
.cat-col{
  width:320px;flex-shrink:0;
  display:flex;flex-direction:column;height:100%;
}
.desc{
  padding:12px 16px 0;
  font-size:12px;line-height:1.55;color:var(--text2);flex-shrink:0;
}
.list-wrap{
  margin-top:10px;
  border-top:1px solid var(--sep);
  overflow-y:auto;flex:1;
}
#cat-list{list-style:none}
/* Category row */
.row{
  display:flex;align-items:center;gap:10px;
  padding:0 14px;height:40px;
  border-bottom:1px solid var(--sep);
  cursor:grab;position:relative;
  transition:background .1s;
}
.row:last-child{border-bottom:none}
.row:hover:not(.pinned){background:var(--hover)}
.row.dragging{opacity:.4;cursor:grabbing}
.row.drag-over-before{background:var(--drag-bg)}
.row.drag-over-before::before{
  content:'';position:absolute;left:0;right:0;top:-1px;
  height:2px;background:var(--drag-line);border-radius:1px;z-index:1;
}
.row.drag-over-after{background:var(--drag-bg)}
.row.drag-over-after::after{
  content:'';position:absolute;left:0;right:0;bottom:-1px;
  height:2px;background:var(--drag-line);border-radius:1px;z-index:1;
}
.row.pinned{cursor:default;background:var(--pin-bg)}
.row.pinned:hover{background:var(--pin-bg)}
.row.kw-open{background:var(--sel-row)}
/* Chip drop target on row */
.row.chip-drop{
  background:var(--chip-drop);
  outline:1.5px dashed var(--chip-drop-border);
  outline-offset:-2px;
}
/* Grip */
.grip{
  display:flex;flex-direction:column;gap:2.5px;
  flex-shrink:0;opacity:.35;cursor:pointer;
  transition:opacity .15s;padding:5px 2px;
}
.row:hover:not(.pinned) .grip{opacity:.8}
.grip:hover{opacity:1 !important}
.row.kw-open .grip{opacity:1}
.grip span{
  display:block;width:16px;height:1.5px;
  background:var(--text-dim);border-radius:1px;
}
/* Category name */
.cat-name{
  flex:1;font-size:13px;font-weight:500;letter-spacing:-.005em;
  cursor:text;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}
.cat-name.faded{color:var(--text-dim)}
.cat-name-edit{
  flex:1;font-family:inherit;font-size:13px;font-weight:500;
  background:none;border:none;
  border-bottom:1.5px solid var(--btn);
  color:var(--text);outline:none;
  padding:0;letter-spacing:-.005em;
  -webkit-user-select:text;user-select:text;
}
.pin-badge{font-size:11px;color:var(--pin-text)}
/* Toggle switch */
.toggle{
  position:relative;width:32px;height:19px;
  flex-shrink:0;cursor:pointer;
}
.toggle input{position:absolute;opacity:0;width:0;height:0}
.track{
  position:absolute;inset:0;
  background:var(--tog-off);border-radius:10px;
  transition:background .2s;
}
.toggle input:checked+.track{background:var(--tog-on)}
.thumb{
  position:absolute;top:2px;left:2px;
  width:15px;height:15px;
  background:#fff;border-radius:50%;
  box-shadow:0 1px 3px rgba(0,0,0,.25);
  transition:transform .2s cubic-bezier(.34,1.56,.64,1);
}
.toggle input:checked~.thumb{transform:translateX(13px)}
/* Add category area */
.add-cat-area{
  border-top:1px solid var(--sep);
  padding:7px 14px;flex-shrink:0;
}
.btn-add-cat{
  font-family:inherit;font-size:12px;font-weight:500;
  color:var(--text2);background:none;border:none;
  cursor:pointer;padding:2px 0;width:100%;text-align:left;
}
.btn-add-cat:hover{color:var(--btn)}
.btn-add-cat:disabled{color:var(--text-dim);cursor:default}
.add-cat-form{display:flex;gap:6px;align-items:center}
.add-cat-input{
  flex:1;font-family:inherit;font-size:12px;
  padding:4px 7px;border-radius:5px;
  border:1.5px solid var(--sep);background:Canvas;color:var(--text);
  outline:none;-webkit-user-select:text;user-select:text;
}
.add-cat-input:focus{border-color:var(--btn)}
.btn-add-confirm{
  font-family:inherit;font-size:12px;font-weight:600;
  padding:4px 9px;border-radius:5px;
  background:var(--btn);color:#fff;border:none;cursor:pointer;
}
.btn-add-confirm:hover{background:var(--btn-h)}
.btn-add-cancel{
  font-family:inherit;font-size:14px;color:var(--text2);
  background:none;border:none;cursor:pointer;
}
/* Footer */
.actions{
  display:flex;align-items:center;
  justify-content:space-between;
  padding:10px 14px 14px;
  flex-shrink:0;border-top:1px solid var(--sep);
}
.btn-reset{
  font-family:inherit;font-size:12px;font-weight:500;
  color:var(--text2);background:none;border:none;
  cursor:pointer;padding:4px 0;
}
.btn-reset:hover{color:var(--btn)}
.btn-done{
  font-family:inherit;font-size:13px;font-weight:600;
  color:#fff;background:var(--btn);
  border:none;border-radius:6px;
  padding:6px 18px;cursor:pointer;
}
.btn-done:hover{background:var(--btn-h)}
.btn-done:active{transform:scale(.97)}
/* ── Divider ── */
.divider{
  width:1px;background:var(--sep);flex-shrink:0;
  opacity:0;transition:opacity .2s;
}
.panel-wrap.kw-open .divider{opacity:1}
/* ── Right column ── */
.kw-col{
  flex:1;display:flex;flex-direction:column;
  background:var(--kw-bg);min-width:0;
  opacity:0;transform:translateX(10px);
  transition:opacity .18s .06s,transform .22s .04s cubic-bezier(.4,0,.2,1);
  pointer-events:none;
}
.panel-wrap.kw-open .kw-col{
  opacity:1;transform:translateX(0);pointer-events:all;
}
.kw-header{
  display:flex;align-items:center;justify-content:space-between;
  padding:13px 13px 0;flex-shrink:0;
}
.kw-title{font-size:13px;font-weight:600;color:var(--text)}
.kw-meta{display:flex;align-items:center;gap:8px}
.kw-count{font-size:11px;color:var(--text2)}
.btn-del-cat{
  font-family:inherit;font-size:11px;font-weight:500;
  color:var(--del);background:none;border:none;
  cursor:pointer;opacity:.55;transition:opacity .12s,color .12s;
}
.btn-del-cat:hover{opacity:1}
.btn-del-cat.armed{opacity:1;font-weight:700}
.kw-hint{
  padding:5px 13px 8px;
  font-size:11px;color:var(--text2);line-height:1.4;
  flex-shrink:0;border-bottom:1px solid var(--kw-sep);
}
.kw-chips{
  flex:1;overflow-y:auto;
  padding:10px 11px;
  display:flex;flex-wrap:wrap;gap:5px;
  align-content:flex-start;
}
.chip{
  font-size:11px;font-weight:500;
  padding:3px 8px 3px 9px;border-radius:12px;
  background:var(--chip-bg);color:var(--text);
  cursor:grab;display:flex;align-items:center;gap:4px;
  -webkit-user-select:none;user-select:none;
  transition:opacity .1s;
}
.chip:active{cursor:grabbing;opacity:.55}
.chip.dragging-chip{opacity:.3}
.chip-del{
  font-size:12px;color:var(--text2);
  cursor:pointer;opacity:.5;
  transition:opacity .1s;line-height:1;
}
.chip-del:hover{opacity:1;color:var(--del)}
.kw-add{
  padding:8px 11px 12px;
  display:flex;gap:6px;flex-shrink:0;
  border-top:1px solid var(--kw-sep);
}
.kw-input{
  flex:1;font-family:inherit;font-size:12px;
  padding:5px 7px;border-radius:5px;
  border:1.5px solid var(--sep);background:Canvas;color:var(--text);
  outline:none;-webkit-user-select:text;user-select:text;
}
.kw-input:focus{border-color:var(--btn)}
.kw-add-btn{
  font-family:inherit;font-size:12px;font-weight:600;
  padding:5px 10px;border-radius:5px;
  background:var(--btn);color:#fff;border:none;cursor:pointer;
}
.kw-add-btn:hover{background:var(--btn-h)}
/* Chip drag ghost */
#chip-ghost{
  position:fixed;pointer-events:none;z-index:999;
  font-size:11px;font-weight:500;
  padding:3px 9px;border-radius:12px;
  background:var(--btn);color:#fff;
  box-shadow:0 3px 10px rgba(0,0,0,.25);
  opacity:0;transform:translate(-50%,-50%);
  white-space:nowrap;
}
</style>
</head>
<body>
<div id="chip-ghost"></div>
<div class="panel-wrap" id="panel-wrap">

  <!-- Left: category list -->
  <div class="cat-col">
    <p class="desc">Drag to reorder · toggle to skip · click ≡ to edit keywords · double-click name to rename</p>
    <div class="list-wrap">
      <ul id="cat-list"></ul>
    </div>
    <div class="add-cat-area">
      <button class="btn-add-cat" id="btn-add-cat" onclick="showAddCat()">+ Add Category</button>
      <div class="add-cat-form" id="add-cat-form" hidden>
        <input class="add-cat-input" id="add-cat-input" placeholder="Category name…" maxlength="24">
        <button class="btn-add-confirm" onclick="confirmAddCat()">Add</button>
        <button class="btn-add-cancel" onclick="hideAddCat()">×</button>
      </div>
    </div>
    <div class="actions">
      <button class="btn-reset" onclick="restoreDefaults()">Restore Defaults</button>
      <button class="btn-done" onclick="done()">Done</button>
    </div>
  </div>

  <!-- Divider -->
  <div class="divider"></div>

  <!-- Right: keyword editor -->
  <div class="kw-col" id="kw-col">
    <div class="kw-header">
      <span class="kw-title" id="kw-title">—</span>
      <div class="kw-meta">
        <span class="kw-count" id="kw-count"></span>
        <button class="btn-del-cat" id="btn-del-cat" onclick="deleteCat()">Delete</button>
      </div>
    </div>
    <p class="kw-hint">Drag a keyword onto a category · × to remove</p>
    <div class="kw-chips" id="kw-chips"></div>
    <div class="kw-add">
      <input class="kw-input" id="kw-input" placeholder="Add keyword…" maxlength="32">
      <button class="kw-add-btn" onclick="addKw()">Add</button>
    </div>
  </div>

</div>
<script>
var DEFAULTS       = __DEFAULTS__;
var DEFAULT_KW_MAP = __DEFAULT_KW_MAP__;
var cats           = __CATEGORIES__;
var customKeywords = __CUSTOM_KEYWORDS__;
var MAX_CATS       = __MAX_CATS__;
var MAX_KWS        = __MAX_KWS__;

var selectedCat  = null;
var panelOpen    = false;
var dragChip     = null;   // {kw, fromCat} when dragging a keyword chip
var delCatArmed  = false;
var delCatTimer  = null;
var chipGhost    = document.getElementById('chip-ghost');

// ── Helpers ───────────────────────────────────────────────────────────────
function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Panel expand / collapse ───────────────────────────────────────────────
function expandPanel() {
  if (panelOpen) return;
  panelOpen = true;
  document.getElementById('panel-wrap').classList.add('kw-open');
  window.webkit.messageHandlers.stem2aaf.postMessage({action:'expand'});
}
function collapsePanel() {
  if (!panelOpen) return;
  panelOpen = false;
  document.getElementById('panel-wrap').classList.remove('kw-open');
  window.webkit.messageHandlers.stem2aaf.postMessage({action:'collapse'});
}

// ── Render: category list ─────────────────────────────────────────────────
function renderCats() {
  var ul = document.getElementById('cat-list');
  ul.innerHTML = '';

  cats.forEach(function(c) {
    var li = document.createElement('li');
    li.className = 'row' + (c.name === selectedCat ? ' kw-open' : '');
    li.draggable = true;
    li.dataset.name = c.name;

    // Grip — click to open keyword editor
    var grip = document.createElement('div');
    grip.className = 'grip';
    grip.title = 'Edit keywords';
    for (var i = 0; i < 3; i++) grip.appendChild(document.createElement('span'));
    grip.addEventListener('click', (function(catName) {
      return function(e) {
        e.stopPropagation();
        if (selectedCat === catName) {
          selectedCat = null;
          collapsePanel();
          renderCats();
        } else {
          selectedCat = catName;
          expandPanel();
          resetDelArm();
          renderCats();
          renderKw();
        }
      };
    })(c.name));

    // Category name — double-click to rename
    var nameSpan = document.createElement('span');
    nameSpan.className = 'cat-name' + (c.enabled ? '' : ' faded');
    nameSpan.textContent = c.name;
    nameSpan.addEventListener('dblclick', (function(cat, span, row) {
      return function(e) {
        e.stopPropagation();
        startRename(cat, span, row);
      };
    })(c, nameSpan, li));

    // Toggle switch
    var label = document.createElement('label');
    label.className = 'toggle';
    label.innerHTML =
      '<input type="checkbox"' + (c.enabled ? ' checked' : '') + '>' +
      '<div class="track"></div><div class="thumb"></div>';
    label.querySelector('input').addEventListener('change', (function(cat, span) {
      return function(e) {
        cat.enabled = e.target.checked;
        span.classList.toggle('faded', !cat.enabled);
      };
    })(c, nameSpan));

    li.appendChild(grip);
    li.appendChild(nameSpan);
    li.appendChild(label);

    // Drop target: accept keyword chips from the kw panel
    li.addEventListener('dragover', (function(cat, row) {
      return function(e) {
        if (!dragChip) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        row.classList.add('chip-drop');
      };
    })(c, li));
    li.addEventListener('dragleave', (function(row) {
      return function() { row.classList.remove('chip-drop'); };
    })(li));
    li.addEventListener('drop', (function(cat, row) {
      return function(e) {
        e.preventDefault();
        row.classList.remove('chip-drop');
        if (!dragChip || dragChip.fromCat === cat.name) return;
        // Remove from source
        var fromKws = customKeywords[dragChip.fromCat];
        if (fromKws) {
          customKeywords[dragChip.fromCat] = fromKws.filter(function(k) {
            return k !== dragChip.kw;
          });
        }
        // Add to target
        if (!customKeywords[cat.name]) customKeywords[cat.name] = [];
        var tgt = customKeywords[cat.name];
        if (tgt.length < MAX_KWS && tgt.indexOf(dragChip.kw) === -1) {
          tgt.push(dragChip.kw);
        }
        dragChip = null;
        chipGhost.style.opacity = '0';
        renderKw();
      };
    })(c, li));

    ul.appendChild(li);
  });

  // Pinned "Other" — always last
  var pin = document.createElement('li');
  pin.className = 'row pinned';
  pin.innerHTML =
    '<div class="grip"><span></span><span></span><span></span></div>' +
    '<span class="cat-name faded">Other</span>' +
    '<span class="pin-badge">always last</span>';
  ul.appendChild(pin);

  // Update Add Category button state
  var addBtn = document.getElementById('btn-add-cat');
  addBtn.disabled = cats.length >= MAX_CATS;
  if (cats.length >= MAX_CATS) {
    addBtn.title = 'Maximum ' + MAX_CATS + ' categories reached';
  } else {
    addBtn.title = '';
  }

  initCatDrag(ul);
}

// ── Render: keyword chips ─────────────────────────────────────────────────
function renderKw() {
  if (!selectedCat) {
    document.getElementById('kw-chips').innerHTML = '';
    return;
  }
  var kws = customKeywords[selectedCat] || [];
  document.getElementById('kw-title').textContent = selectedCat;
  var countEl = document.getElementById('kw-count');
  countEl.textContent = kws.length + ' / ' + MAX_KWS;
  countEl.style.color = kws.length >= MAX_KWS ? 'var(--btn)' : '';

  var wrap = document.getElementById('kw-chips');
  wrap.innerHTML = '';
  kws.forEach(function(kw) {
    var chip = document.createElement('div');
    chip.className = 'chip';
    chip.draggable = true;
    chip.innerHTML =
      '<span>' + esc(kw) + '</span>' +
      '<span class="chip-del" title="Remove keyword">×</span>';

    chip.querySelector('.chip-del').addEventListener('click', (function(k) {
      return function(e) {
        e.stopPropagation();
        customKeywords[selectedCat] = (customKeywords[selectedCat] || [])
          .filter(function(x) { return x !== k; });
        renderKw();
      };
    })(kw));

    chip.addEventListener('dragstart', (function(k) {
      return function(e) {
        dragChip = {kw: k, fromCat: selectedCat};
        chipGhost.textContent = k;
        chipGhost.style.opacity = '1';
        chip.classList.add('dragging-chip');
        e.dataTransfer.effectAllowed = 'move';
      };
    })(kw));
    chip.addEventListener('dragend', function() {
      chip.classList.remove('dragging-chip');
      dragChip = null;
      chipGhost.style.opacity = '0';
    });

    wrap.appendChild(chip);
  });
}

// ── Rename category (double-click on name) ────────────────────────────────
function startRename(cat, nameSpan, li) {
  var inp = document.createElement('input');
  inp.className = 'cat-name-edit';
  inp.value = cat.name;
  inp.maxLength = 24;
  li.replaceChild(inp, nameSpan);
  inp.focus();
  inp.select();

  function commit() {
    var newName = inp.value.trim();
    var duplicate = cats.find(function(c) {
      return c.name === newName && c !== cat;
    });
    if (newName && !duplicate && newName !== cat.name) {
      // Move keywords to new key
      if (customKeywords[cat.name] !== undefined) {
        customKeywords[newName] = customKeywords[cat.name];
        delete customKeywords[cat.name];
      }
      if (selectedCat === cat.name) selectedCat = newName;
      cat.name = newName;
    }
    renderCats();
    if (selectedCat) renderKw();
  }

  inp.addEventListener('keydown', function(e) {
    if (e.key === 'Enter')  { e.preventDefault(); inp.blur(); }
    if (e.key === 'Escape') { e.preventDefault(); renderCats(); }
  });
  inp.addEventListener('blur', commit);
}

// ── Add category ──────────────────────────────────────────────────────────
function showAddCat() {
  document.getElementById('btn-add-cat').hidden = true;
  var form = document.getElementById('add-cat-form');
  form.hidden = false;
  document.getElementById('add-cat-input').value = '';
  document.getElementById('add-cat-input').focus();
}
function hideAddCat() {
  document.getElementById('btn-add-cat').hidden = false;
  document.getElementById('add-cat-form').hidden = true;
}
function confirmAddCat() {
  var name = document.getElementById('add-cat-input').value.trim();
  if (!name) return;
  if (cats.find(function(c) { return c.name === name; })) return;
  if (cats.length >= MAX_CATS) return;
  cats.push({name: name, enabled: true});
  customKeywords[name] = [];
  hideAddCat();
  // Open the new category in the keyword editor
  selectedCat = name;
  expandPanel();
  renderCats();
  renderKw();
}
document.getElementById('add-cat-input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter')  confirmAddCat();
  if (e.key === 'Escape') hideAddCat();
});

// ── Delete category (two-click confirm) ───────────────────────────────────
function resetDelArm() {
  clearTimeout(delCatTimer);
  delCatArmed = false;
  var btn = document.getElementById('btn-del-cat');
  if (btn) { btn.textContent = 'Delete'; btn.classList.remove('armed'); }
}
function deleteCat() {
  if (!selectedCat) return;
  var btn = document.getElementById('btn-del-cat');
  if (!delCatArmed) {
    delCatArmed = true;
    btn.textContent = 'Confirm?';
    btn.classList.add('armed');
    delCatTimer = setTimeout(resetDelArm, 2200);
    return;
  }
  clearTimeout(delCatTimer);
  delCatArmed = false;
  // Execute delete
  delete customKeywords[selectedCat];
  cats = cats.filter(function(c) { return c.name !== selectedCat; });
  selectedCat = null;
  collapsePanel();
  renderCats();
}

// ── Add keyword ───────────────────────────────────────────────────────────
function addKw() {
  var inp = document.getElementById('kw-input');
  var val = inp.value.trim().toLowerCase();
  if (!val || !selectedCat) return;
  var kws = customKeywords[selectedCat] || [];
  if (kws.length >= MAX_KWS) return;
  if (kws.indexOf(val) !== -1) { inp.select(); return; }
  kws.push(val);
  customKeywords[selectedCat] = kws;
  inp.value = '';
  renderKw();
  // Scroll chip area to bottom so new chip is visible
  var wrap = document.getElementById('kw-chips');
  wrap.scrollTop = wrap.scrollHeight;
}
document.getElementById('kw-input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') addKw();
});

// ── Category drag-to-reorder ──────────────────────────────────────────────
function clearDragOver(ul) {
  ul.querySelectorAll('.row').forEach(function(r) {
    r.classList.remove('drag-over-before', 'drag-over-after');
  });
}
function initCatDrag(ul) {
  var src = null;
  var insertBefore = false;
  ul.querySelectorAll('.row:not(.pinned)').forEach(function(row) {
    row.addEventListener('dragstart', function(e) {
      if (dragChip) { e.preventDefault(); return; }
      src = row;
      e.dataTransfer.effectAllowed = 'move';
      setTimeout(function() { if (src === row) row.classList.add('dragging'); }, 0);
      if (selectedCat !== null) {
        selectedCat = null;
        collapsePanel();
      }
    });
    row.addEventListener('dragend', function() {
      row.classList.remove('dragging');
      clearDragOver(ul);
      src = null;
    });
    row.addEventListener('dragover', function(e) {
      if (dragChip || !src || row === src) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      var rect = row.getBoundingClientRect();
      insertBefore = (e.clientY - rect.top) < rect.height / 2;
      clearDragOver(ul);
      row.classList.add(insertBefore ? 'drag-over-before' : 'drag-over-after');
    });
    row.addEventListener('drop', function(e) {
      e.preventDefault();
      clearDragOver(ul);
      if (!src || row === src || dragChip) return;
      if (insertBefore) row.before(src); else row.after(src);
      var names = Array.from(ul.querySelectorAll('.row:not(.pinned)'))
        .map(function(r) { return r.dataset.name; });
      cats = names.map(function(n) {
        return cats.find(function(c) { return c.name === n; });
      });
      renderCats();
    });
  });
}

// ── Chip ghost follows mouse ──────────────────────────────────────────────
document.addEventListener('mousemove', function(e) {
  if (!dragChip) return;
  chipGhost.style.left = e.clientX + 'px';
  chipGhost.style.top  = e.clientY + 'px';
});

// ── Restore defaults ──────────────────────────────────────────────────────
function restoreDefaults() {
  cats = JSON.parse(JSON.stringify(DEFAULTS));
  customKeywords = JSON.parse(JSON.stringify(DEFAULT_KW_MAP));
  selectedCat = null;
  collapsePanel();
  hideAddCat();
  renderCats();
}

// ── Done ──────────────────────────────────────────────────────────────────
function done() {
  window.webkit.messageHandlers.stem2aaf.postMessage({
    action: 'save',
    categories: cats,
    customKeywords: customKeywords
  });
}

// ── Init ──────────────────────────────────────────────────────────────────
renderCats();
</script>
</body>
</html>
"""


class _MessageHandler(NSObject):
    """Receives postMessage calls from the WKWebView JS context."""

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


class CategoryOrderPanel:
    """
    Floating NSPanel showing the full keyword management UI.

    Usage:
        panel = CategoryOrderPanel(
            current_categories, custom_keywords, on_save=my_callback
        )
        panel.show()

    on_save is called with:
        (categories: list[dict], custom_keywords: dict)
    where categories is [{"name": str, "enabled": bool}] and
    custom_keywords is {category_name: [kw, ...]}.
    """

    def __init__(self, categories: list, custom_keywords: dict, on_save):
        self._on_save = on_save
        self._handler = None
        self._webview = None
        self._panel = None
        self._build(categories, custom_keywords)

    def _build(self, categories: list, custom_keywords: dict):
        # ── Message handler ──
        handler = _MessageHandler.alloc().init()
        handler._callback = self._on_message
        self._handler = handler

        # ── WKWebView configuration ──
        controller = WKUserContentController.alloc().init()
        controller.addScriptMessageHandler_name_(handler, "stem2aaf")
        config = WKWebViewConfiguration.alloc().init()
        config.setUserContentController_(controller)

        # ── WKWebView (starts at collapsed width) ──
        frame = NSMakeRect(0, 0, _PANEL_W_COLLAPSED, _PANEL_H)
        webview = WKWebView.alloc().initWithFrame_configuration_(frame, config)
        webview.setValue_forKey_(False, "drawsBackground")
        self._webview = webview

        # ── Load HTML with injected data ──
        html = (
            _HTML
            .replace("__DEFAULTS__",        json.dumps(DEFAULT_CATEGORIES))
            .replace("__DEFAULT_KW_MAP__",  json.dumps(_DEFAULT_KW_MAP))
            .replace("__CATEGORIES__",      json.dumps(categories))
            .replace("__CUSTOM_KEYWORDS__", json.dumps(custom_keywords))
            .replace("__MAX_CATS__",        str(_MAX_CATS))
            .replace("__MAX_KWS__",         str(_MAX_KWS))
        )
        webview.loadHTMLString_baseURL_(html, None)

        # ── NSPanel (starts at collapsed width) ──
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, _TITLED | _CLOSABLE, NSBackingStoreBuffered, False
        )
        panel.setTitle_("Category Order")
        panel.setContentView_(webview)
        panel.setReleasedWhenClosed_(False)
        panel.center()
        self._panel = panel

    def show(self):
        NSApp.activateIgnoringOtherApps_(True)
        self._panel.makeKeyAndOrderFront_(None)

    def _resize(self, expanded: bool):
        """Animate the panel to its collapsed or expanded width."""
        frame = self._panel.frame()
        new_w = _PANEL_W_EXPANDED if expanded else _PANEL_W_COLLAPSED
        new_frame = NSMakeRect(
            frame.origin.x,
            frame.origin.y,
            new_w,
            _PANEL_H,
        )
        self._panel.setFrame_display_animate_(new_frame, True, True)

    def _on_message(self, body: dict):
        action = body.get("action")
        if action == "expand":
            self._resize(expanded=True)
        elif action == "collapse":
            self._resize(expanded=False)
        elif action == "save":
            cats = body.get("categories", [])
            custom_kws = body.get("customKeywords", {})
            # Convert ObjC proxy objects to plain Python types
            plain_cats = [
                {"name": str(c["name"]), "enabled": bool(c["enabled"])}
                for c in cats
            ]
            plain_kws = {
                str(k): [str(kw) for kw in v]
                for k, v in custom_kws.items()
            }
            self._on_save(plain_cats, plain_kws)
            self._panel.orderOut_(None)
