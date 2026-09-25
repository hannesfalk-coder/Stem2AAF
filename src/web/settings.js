// ── State (injected by Python) ────────────────────────────────────────────────
const S = __STATE__;
const DEFAULT_CATS = __DEFAULT_CATS__;
S.sec      = S.sec      || 'general';
S.selCat   = S.selCat   || 0;
S.addingCat = false;
S.presets      = S.presets || {};          // name -> categories
S.activePreset = S.activePreset || 'Default Keywords';
S.presetMenu   = false;                    // menu open? UI only, never saved
S.presetEdit   = null;                     // 'save' | 'rename' | null
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

// ── Presets ───────────────────────────────────────────────────────────────────
// A preset is the whole category list - names, order, enabled state and
// keywords - saved under a name. S.presets maps name -> categories.
// DEFAULT_NAME is not stored in there: it always means the converter's own
// table, so there is a way back that cannot be deleted or edited away.

const DEFAULT_PRESET = 'Default Keywords';

function presetBaseline() {
  return S.activePreset === DEFAULT_PRESET
    ? DEFAULT_CATS
    : (S.presets[S.activePreset] || DEFAULT_CATS);
}

// Compared as JSON rather than by a dirty flag: a flag has to be cleared
// everywhere the categories change, and one missed spot leaves the panel
// lying about whether your edits are saved.
function presetDirty() {
  return JSON.stringify(S.categories) !== JSON.stringify(presetBaseline());
}

function presetRowHTML() {
  if (S.presetEdit) {                      // naming a new one, or renaming
    return `
      <div class="preset-row">
        <span class="preset-lab">${S.presetEdit === 'rename' ? 'Rename to:' : 'Save as:'}</span>
        <input class="preset-input" id="preset-name" placeholder="Preset name…"
               value="${S.presetEdit === 'rename' ? esc(S.activePreset) : ''}"
               onkeydown="presetNameKey(event)">
      </div>`;
  }

  const names = Object.keys(S.presets).sort((a, b) => a.localeCompare(b));
  const dirty = presetDirty();
  const item  = n => `<div class="pm-item" onclick="applyPreset(${JSON.stringify(n).replace(/"/g,'&quot;')})">
      <span class="pm-tick">${n === S.activePreset ? '✓' : ''}</span>${esc(n)}</div>`;

  const menu = S.presetMenu ? `
    <div class="preset-menu" id="preset-menu">
      ${item(DEFAULT_PRESET)}
      ${names.length ? '<div class="pm-sep"></div>' + names.map(item).join('') : ''}
      <div class="pm-sep"></div>
      <div class="pm-item" onclick="startSavePreset()">Save Current Settings as Preset…</div>
      ${S.activePreset !== DEFAULT_PRESET
        ? `<div class="pm-item" onclick="startRenamePreset()">Rename Preset…</div>
           <div class="pm-item" onclick="deletePreset()">Delete Preset</div>`
        : `<div class="pm-item dim">Rename Preset…</div>
           <div class="pm-item dim">Delete Preset</div>`}
    </div>` : '';

  return `
    <div class="preset-row">
      <span class="preset-lab">Presets:</span>
      <button class="preset-pop" onclick="event.stopPropagation();togglePresetMenu()">
        <span>${esc(S.activePreset)}${dirty ? ' <span class="preset-mod">(Modified)</span>' : ''}</span>
        <span class="preset-chev"><i></i><i></i></span>
      </button>
      ${menu}
    </div>`;
}

function togglePresetMenu() {
  S.presetMenu = !S.presetMenu;
  renderDetail();
  // Click anywhere else to dismiss, the way a real pop-up behaves. Bound
  // on the next tick so the click that opened it doesn't close it again.
  if (S.presetMenu) setTimeout(() => document.addEventListener('click', _closePresetMenu), 0);
}
function _closePresetMenu() {
  document.removeEventListener('click', _closePresetMenu);
  if (S.presetMenu) { S.presetMenu = false; renderDetail(); }
}

function applyPreset(name) {
  S.presetMenu = false;
  S.activePreset = name;
  // Deep copy: editing keywords afterwards must not quietly rewrite the
  // saved preset, which is the whole point of (Modified).
  S.categories = JSON.parse(JSON.stringify(
    name === DEFAULT_PRESET ? DEFAULT_CATS : (S.presets[name] || DEFAULT_CATS)));
  S.selCat = 0;
  renderDetail(); autoSave();
}

function startSavePreset()   { S.presetMenu = false; S.presetEdit = 'save';   renderDetail(); _focusPresetName(); }
function startRenamePreset() { S.presetMenu = false; S.presetEdit = 'rename'; renderDetail(); _focusPresetName(); }
function _focusPresetName() {
  setTimeout(() => { const el = document.getElementById('preset-name'); el?.focus(); el?.select(); }, 0);
}

function presetNameKey(e) {
  if (e.key === 'Escape') { S.presetEdit = null; renderDetail(); return; }
  if (e.key !== 'Enter') return;
  const name = e.target.value.trim();
  const mode = S.presetEdit;
  S.presetEdit = null;
  if (!name || name === DEFAULT_PRESET) { renderDetail(); return; }

  if (mode === 'rename' && S.activePreset !== DEFAULT_PRESET) {
    delete S.presets[S.activePreset];
  }
  S.presets[name] = JSON.parse(JSON.stringify(S.categories));
  S.activePreset = name;
  renderDetail(); autoSave();
}

function deletePreset() {
  S.presetMenu = false;
  if (S.activePreset === DEFAULT_PRESET) { renderDetail(); return; }
  delete S.presets[S.activePreset];
  // The categories on screen are left exactly as they are - deleting the
  // name you saved under should not also throw away what you were editing.
  S.activePreset = DEFAULT_PRESET;
  renderDetail(); autoSave();
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
    ${presetRowHTML()}
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

// ── Category reordering (drag a row) ─────────────────────────────────────────
// Order matters to the converter twice over: it sets the order the groups
// appear in the AAF, and it decides the winner when a filename matches
// keywords from more than one category.
//
// Dragging is the only way to reorder now. There were also up/down buttons
// in the footer, added when there was no way at all; once dragging worked
// they were a second route to the same result, taking two of the five
// footer slots to do what the list already does directly.

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
let _kwGhost = null;  // the chip copy that travels with the cursor

function kwDragStart(event, catIdx, kwIdx) {
  if (event.target.closest('.chip-x')) return;
  const chip = event.currentTarget;
  const box  = chip.getBoundingClientRect();
  _dragKw = {
    catIdx, kwIdx, chip, moved: false,
    startX: event.clientX, startY: event.clientY,
    // Where inside the chip it was grabbed, so the ghost stays under that
    // same point rather than snapping its corner to the cursor.
    grabX: event.clientX - box.left,
    grabY: event.clientY - box.top,
  };
  event.preventDefault();
  document.addEventListener('mousemove', _kwDragMove);
  document.addEventListener('mouseup',   _kwDragUp);
}
function _kwDragMove(event) {
  if (!_dragKw) return;

  // Lift only past a few pixels, so a stray press on a chip doesn't flash
  // a ghost for one frame.
  if (!_dragKw.moved) {
    const dx = event.clientX - _dragKw.startX, dy = event.clientY - _dragKw.startY;
    if (dx * dx + dy * dy < 16) return;          // 4px
    _dragKw.moved = true;
    _dragKw.chip.classList.add('dragging');
    _kwGhost = _dragKw.chip.cloneNode(true);
    _kwGhost.className = 'kw-chip kw-ghost';     // drop 'dragging' from the copy
    _kwGhost.removeAttribute('onmousedown');
    _kwGhost.style.width = _dragKw.chip.getBoundingClientRect().width + 'px';
    document.body.appendChild(_kwGhost);
  }

  _kwGhost.style.left = (event.clientX - _dragKw.grabX) + 'px';
  _kwGhost.style.top  = (event.clientY - _dragKw.grabY) + 'px';

  document.querySelectorAll('.cl-row').forEach(r => r.classList.remove('drag-over'));
  const target = document.elementFromPoint(event.clientX, event.clientY);
  const row = target?.closest?.('[data-idx]');
  if (row && +row.dataset.idx !== _dragKw.catIdx) row.classList.add('drag-over');
}
function _kwDragUp(event) {
  document.removeEventListener('mousemove', _kwDragMove);
  document.removeEventListener('mouseup',   _kwDragUp);
  _kwGhost?.remove();
  _kwGhost = null;
  document.querySelectorAll('.kw-chip.dragging').forEach(c => c.classList.remove('dragging'));
  document.querySelectorAll('.cl-row.drag-over').forEach(r => r.classList.remove('drag-over'));
  // Never moved: a press, not a drag. Nothing to drop.
  if (!_dragKw || !_dragKw.moved) { _dragKw = null; return; }
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
      // presetMenu / presetEdit are transient UI and deliberately absent.
      presets:       S.presets,
      active_preset: S.activePreset,
    }
  });
}

// ── Boot ──────────────────────────────────────────────────────────────────────
renderSidebar();
renderDetail();
