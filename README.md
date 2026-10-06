# Stem2AAF

A macOS menu-bar app that watches a folder for stem exports from your DAW
and compiles them into a single `.aaf` file — the interchange format
Pro Tools, Media Composer, DaVinci Resolve, Premiere Pro, Audition,
Logic Pro, Nuendo, Cubase Pro and Studio One all import.

Built around Bitwig Studio's `File → Export Audio…`, but it works with any
DAW that writes one WAV per track.

**[Download the latest release →](https://github.com/hannesfalk-coder/stem2aaf/releases/latest)**

---

## What it does

You export stems. Stem2AAF notices them land, reads every filename, sorts
the tracks into categories, and hands you one AAF with every track named,
grouped and in sync. One file instead of many, ready for whatever software
comes next.

It can't hook directly into your DAW's Export button — Bitwig has no plugin
API for that, and neither do most DAWs. So it watches a folder instead, and
compiles whatever lands there.

**One thing it genuinely can't do**: carry plugins into Resolve as live,
editable effects. AAF has no way to represent a VST/AU plugin's state at
all. Stems give you the *sound* those plugins produced, baked into the
audio — not the ability to change that processing later.

---

## Install

1. Download `Stem2AAF.dmg` from the
   [latest release](https://github.com/hannesfalk-coder/stem2aaf/releases/latest).
2. Open the DMG and drag **Stem2AAF** onto the **Applications** shortcut.
3. Open it once — see the next section, the first launch needs one extra step.

Runs on both Intel and Apple Silicon Macs.

### First launch: "Apple could not verify…"

Stem2AAF is not signed with an Apple Developer certificate — that costs $99
a year, and this is a free tool. So the first time you open it, macOS blocks
it and says it can't check the app for malicious software. Nothing is wrong;
this is what macOS says about every unsigned app.

To open it anyway:

1. Double-click **Stem2AAF** in your Applications folder. Let the warning
   appear and click **Done**.
2. Open **System Settings → Privacy & Security**.
3. Scroll down to the **Security** section. There'll be a line reading
   *"Stem2AAF" was blocked to protect your Mac.*
4. Click **Open Anyway**, then confirm with Touch ID or your password.

You only have to do this once. On macOS Sequoia (15) and later this is the
only route — Apple removed the old right-click → Open shortcut.

If you'd rather not run an unsigned app at all, build it yourself from
source: see [Building from source](#building-from-source) below.

---

## Everyday use

1. In your DAW, select the tracks you want and export them **all together in
   one operation** into your watched folder. One WAV per track, all starting
   from the same point on the timeline.
2. Once Finder shows every file you expect, click **Convert to AAF** in the
   menu bar. The menu item carries a live count, e.g. *Convert to AAF
   (4 waiting)*. You'll get a macOS notification when it's done, or one
   explaining what went wrong if it fails.
3. Grab the `.aaf` from your output folder.

While it works, the menu-bar icon fills left to right as real work completes
— settling the files, then writing the AAF — so a bigger batch visibly takes
longer than a small one. When it finishes it flashes white and orange a few
times and settles back to plain orange. It does that whether it succeeded or
failed, so "the icon stopped moving" always means *check the notification, or
the log inside the conversion folder* — never "nothing is happening."

Each conversion creates its own folder, `<project> Converted vN`, holding the
AAF, a log, and your stems. The version number increments automatically, so
repeated exports never overwrite each other.

---

## Categories, keywords and presets

With **Group stems by category** switched on, Stem2AAF reads each filename
and sorts the track into a category — Drums, Bass, Guitar, Keys, Orchestral,
Synth, Strings, Vocal, Sends, Other — then prefixes the track name with it, so
`01 Kick.wav` arrives as `Drums_Kick (01)`. The tracks come into your editor
already grouped instead of in raw export order.

This is a naming heuristic, not audio analysis. A file with no recognisable
name (`Track 7.wav`) lands in Other as `Unmatched_Track 7`. A name matching
two categories goes to whichever sits higher in the list.

All of it is editable, in **Settings → Categories**:

- **Categories** can be renamed, reordered, switched off, deleted, or created
  from scratch. Order matters — it decides which category wins a tie, and the
  order tracks appear in the AAF.
- **Keywords** are what each category matches on. Add your own, delete the
  ones you don't use, or drag a keyword from one category to another. If you
  name your overheads `OH`, add `OH` to Drums and it will be recognised from
  then on.
- **Presets** save the whole arrangement — every category, its order, its
  on/off state and all its keywords — under a name. Keep one for band
  sessions and one for orchestral work, and switch between them in a click.
  The built-in arrangement is always there as *Default Keywords*, so you can
  get back to it at any point.

Switched off, tracks land in export order and keep their own names
(`01 Kick.wav` becomes `Kick (01)`).

---

## Settings

Every change applies immediately — there's no Save button.

**Folders**

- **Watch Folder** — where your DAW exports stems. This one stays put; that's
  the whole point of watching a folder.
- **Output Folder** — where the `<project> Converted vN` folders are written.
  **The name of this folder becomes the project name**: an output folder
  called "The Sun" produces `The Sun Converted v1/` containing `The Sun_v1.aaf`,
  folder and file sharing a version number so they're easy to pair at a
  glance. Point it at a new folder per project. Leave it empty to write
  alongside the stems in the watch folder.

**Conversion**

- **Group stems by category** — off by default. See the section above.
- **Keep stems after conversion** — on by default, archiving the source WAVs
  into the conversion folder next to the AAF as a backup. Switch it off to
  delete them instead, which is safe: the AAF fully embeds the audio rather
  than referencing the original files.
- **Auto-convert when stems arrive** — off by default. When on, a conversion
  starts once the number of waiting stems has held completely steady for
  6 seconds. It's a convenience, not a guarantee — only you really know when
  the export has finished — but it's safe to leave on, because of the
  all-or-nothing rule below.

**Application**

- **Launch at login** — keeps the app running automatically.
- **Uninstall Stem2AAF** — removes the app. It lives here deliberately, not in
  the menu-bar dropdown you open constantly to reach Convert to AAF.

---

## Nothing is ever converted halfway

If any file in the batch is still being written when a conversion starts,
**nothing is converted at all**. You get an error naming exactly which files
weren't ready, and no AAF and no conversion folder are created.

This matters more than it sounds. An AAF quietly missing two tracks looks
completely normal until you're deep into a mix session. The tool would rather
refuse and tell you than hand you something that looks finished and isn't.
Wait for the export to complete, then convert again.

For the same reason, export all your tracks in a single operation. A sample
rate that differs between files is treated as a sign they came from separate
exports and might not line up, so the app refuses to combine them rather than
guessing. A format difference alone — 32-bit float, say, which plenty of DAW
engines produce — is transcoded automatically; it's specifically a *rate*
mismatch that stops the conversion.

---

## Uninstalling

Open **Settings → Application** and click **Uninstall…**. After a confirmation
dialog it quits the app and removes the app bundle, its settings, and its
login-item entry. Your project folders are never touched — only the app's own
code and config.

Under the hood this is a small script inside the app bundle
(`Contents/Resources/uninstall.sh`) which the app launches detached just
before quitting, so it outlives the app and can delete it.

---

## Building from source

py2app only works on macOS, so this has to happen on your own Mac.

**Option A — no Terminal needed:**

1. Double-click `Build Stem2AAF.applescript`. It opens in Script Editor,
   which is built into every Mac.
2. Click **Run** (▶).
3. Click OK on the confirmation. Wait a minute or two — no Terminal window
   appears, everything happens in the background.
4. A dialog confirms it's done, or explains what went wrong.

**Option B — Terminal, one script:**

```bash
cd stem2aaf
chmod +x build.sh
./build.sh
```

Add `--no-install` to build into `dist/` without replacing whatever is
currently in `/Applications`.

**Option C — Terminal, step by step:**

```bash
cd stem2aaf
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 setup.py py2app
mv "dist/Stem2AAF.app" /Applications/
```

Option C skips the universal-binary step `build.sh` performs, so the app it
produces only runs on the kind of Mac you built it on. There's one app to
build — the uninstaller is a script inside it, not a second bundle.

No Python 3? Get it from python.org, or `brew install python3`.

### Packaging a .dmg

After `Stem2AAF.app` is sitting in `/Applications`:

```bash
chmod +x make_dmg.sh && ./make_dmg.sh
```

It opens a brief Finder window while it arranges the icon layout — expected,
not an error. The result is `Stem2AAF.dmg`, the one file to share.

---

## Intel and Apple Silicon

`build.sh` produces a universal app that runs on both, and warns if any
bundled binary turns out to be single-architecture.

This takes real work, because pip installs wheels for the machine doing the
building. A plain build on an Apple Silicon Mac used to produce an app whose
launcher was universal but whose cffi, libsndfile and watchdog binaries were
arm64 only — so on an Intel Mac, macOS would start it as x86_64 and the first
import would fail. Any `.dmg` shared from such a build was dead on arrival for
Intel users. `build.sh` now downloads both architectures' wheels for those
packages and fuses them into universal2 ones before packaging.

Two pins in `requirements.txt` exist for this:

- `cffi` is the newest version that still publishes an x86_64 wheel for
  Python 3.9.
- The `pyobjc` packages are pinned to 11.1, the last release with Python 3.9
  wheels at all. Left unpinned, pip resolves to a version that compiles from
  source, and that compile fails against current clang.

**numpy is deliberately not bundled.** soundfile only imports it inside the
calls that hand back arrays, and the converter uses the buffer API instead, so
nothing in the app ever needs it. numpy's Intel wheel ships its own copy of
OpenBLAS: including it made the universal app 156 MB instead of about 30 MB,
for a library used only to move samples between two libsndfile handles.
`tests/test_converter.py` fails if the conversion path starts importing numpy
again.

---

## Running the tests

```bash
venv/bin/python3 tests/run_tests.py
```

No extra dependencies — the standard library's `unittest` plus the packages
the app already needs. `venv/bin/python3 -m pytest tests -q` works too.

The suite covers track naming, the audio transcoding path, sample-rate
rejection, output-folder handling, atomic config writes, and above all the
rule that a batch containing a still-being-written stem must fail rather than
produce a partial AAF.

---

## Project files

- `src/converter.py` — the stems → AAF conversion itself
- `src/watcher.py` — watches the folder, batches arriving stems, runs conversions
- `src/app.py` — the menu-bar app (menu, timers, notifications, uninstall)
- `src/settings_window.py` — the Settings window (WKWebView-based)
- `src/web/` — the Settings page: `settings.html`, `settings.css`, `settings.js`
- `src/config.py` — remembers your settings between launches
- `src/version.py` — the one place the version number is defined
- `src/assets/uninstall.sh` — the uninstaller, bundled into the app
- `setup.py` — py2app packaging config
- `build.sh` — builds universal dependencies, packages, installs
- `make_dmg.sh` — packages the installed app into a shareable .dmg
- `tests/` — the test suite

---

## If something doesn't convert

Every conversion writes a log next to its AAF. Check that first.

For a clearer error, run the converter directly:

```bash
source venv/bin/activate
python3 src/converter.py "/path/to/out.aaf" "/path/to/stem1.wav" "/path/to/stem2.wav"
```

### Stereo stems showing up as mono in Resolve

A known Resolve-side quirk. In Resolve, select all the clips → Clip Attributes
→ Audio → Channel Format → Stereo. Or in Fairlight, right-click the track
headers → Change Track Type To → Stereo.

---

## Licence

MIT. See [LICENSE](LICENSE).
