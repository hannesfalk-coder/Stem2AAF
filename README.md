# Bitwig → AAF

A menu-bar app for macOS that watches a folder for Bitwig stem exports
(`File → Export Audio…`) and compiles them into an `.aaf` file for use in
DaVinci Resolve, Pro Tools, Avid Media Composer, or other post-production
software.

## Important: one honest limitation up front

This can't hook directly into Bitwig's Export button — Bitwig has no
plugin API for that. Instead, you export into a watched folder, and this
app compiles the result into an AAF automatically within a few seconds.

## Why stems only

An earlier version of this tool also supported Bitwig's
`File → Export DAWproject…` path, which preserves clip-level structure.
That's been removed. DAWproject references the project's original,
unprocessed source samples - not what actually plays back through a
track's plugin chain. A compressed drum bus imported via DAWproject comes
through dry, with no compression applied, since nothing ever ran the
audio through the plugin. Bitwig's own engine has to actually render
through the chain to get the real processed sound, and that's exactly
what Export Audio does. So for any track where plugins are doing real
work - which is most real mixes - DAWproject silently gives you the
wrong audio. Stems doesn't have that problem, so it's the only workflow
this tool supports now.

**One thing this genuinely can't do, in either workflow**: carry the
plugins themselves into Resolve as live, editable effects. AAF has no way
to represent a VST/AU plugin's state at all. Stems gives you the *sound*
those plugins produced, baked into the audio - not the ability to change
that processing later.

## Installing (do this once, on your Mac)

py2app (the tool that packages this into a `.app`) only works on macOS, so
this step has to happen on your machine.

**Option A — no Terminal needed (recommended):**

1. Double-click `Build Stem2AAF.applescript` — it opens in Script Editor,
   which comes built into every Mac (nothing to install).
2. Click the **Run** button (▶) in Script Editor's toolbar.
3. Click OK on the confirmation dialog. Wait a minute or two - no visible
   Terminal window appears, everything happens in the background.
4. You'll get a dialog confirming it's done, or one explaining what went
   wrong if the build failed.

**Option B — Terminal, one script:**

```bash
cd stem2aaf
chmod +x build.sh
./build.sh
```

Add `--no-install` to build into `dist/` without replacing whatever is
currently in `/Applications`:

```bash
./build.sh --no-install
```

**Option C — Terminal, step by step:**

```bash
cd stem2aaf
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 setup.py py2app
mv "dist/Stem2AAF.app" /Applications/
```

Option C skips the universal-binary step that `build.sh` performs, so the
app it produces only runs on the kind of Mac you built it on. See
"Intel and Apple Silicon" below. There's one app to build - the
uninstaller is a script inside it, not a second bundle.

If you don't have Python 3 installed, get it from python.org first, or via
`brew install python3` if you use Homebrew.

## Intel and Apple Silicon

`build.sh` produces a universal app that runs on both Intel and Apple
Silicon Macs, and prints a warning if any bundled binary turns out to be
single-architecture.

This takes real work, because pip installs wheels for the machine doing
the building. A plain build on an Apple Silicon Mac used to produce an app
whose launcher was universal but whose cffi, libsndfile and watchdog
binaries were arm64 only - so on an Intel Mac, macOS would start it as
x86_64 and the first import would fail. Any `.dmg` shared from such a
build was dead on arrival for Intel users. `build.sh` now downloads both
architectures' wheels for those packages and fuses them into universal2
ones before packaging.

Two pins in `requirements.txt` exist for this:

- `cffi` is the newest version that still publishes an x86_64 wheel for
  Python 3.9.
- The `pyobjc` packages are pinned to 11.1, the last release with Python
  3.9 wheels at all. Left unpinned, pip resolves to a version that has to
  compile from source, and that compile fails against current clang.

**numpy is deliberately not bundled.** soundfile only imports it inside
the calls that hand back arrays, and the converter uses the buffer API
instead, so nothing in the app ever needs it. This matters because numpy's
Intel wheel ships its own copy of OpenBLAS: including it made the
universal app 156 MB instead of about 30 MB, for a library used only to
move samples between two libsndfile handles. `tests/test_converter.py` has
a test that fails if the conversion path starts importing numpy again.

## First launch

macOS will likely warn "Stem2AAF can't be opened because it is from an
unidentified developer" the first time, since it isn't signed with an Apple
Developer certificate. To open it anyway: **right-click the app → Open →
Open** (only needed once).

A small icon will appear in your menu bar. Clicking it gives you
**Convert to AAF**, **Settings**, and **Quit**.

## Settings

Everything except conversion itself lives in the Settings window, which
applies each change immediately - there's no Save button.

**Folders**

- **Watch Folder** — where Bitwig exports stems. The **name of this
  folder becomes the project name**: each conversion creates a folder
  named after it, e.g. "The Sun" produces `The Sun Converted v1/`
  containing `The Sun_v1.aaf` - the folder and file share the same
  version number, so they're easy to associate at a glance. Each further
  conversion increments the version automatically, so use one watched
  folder per project rather than reusing one across unrelated projects.
- **Output Folder** — where those `<project> Converted vN` folders are
  written. Leave it the same as the watch folder to keep everything
  together, which is the default.

**Conversion**

- **Group stems by category** — off by default, in which case tracks land
  in the AAF in the order Bitwig wrote them and keep their own names
  (`01 Kick.wav` becomes `Kick (01)`). Turn it on to group tracks into
  Drums / Bass / Guitar / Keys / Orchestral / Synth / Strings / Vocal /
  Sends / Other based on keywords in each file's name, and to prefix each
  track name with its category (`Drums_Kick (01)`). This is a
  naming-convention heuristic, not audio analysis - a file with no
  recognizable name (e.g. "Track 7") lands in "Other" and is named
  `Unmatched_Track 7`. A name matching two categories goes to whichever
  comes first in the Categories list, which you can reorder and edit.
- **Delete stems after conversion** — off by default, which archives the
  source `.wav` stems into that same per-conversion folder, alongside the
  AAF, as a backup. Turn this on to delete them outright instead - safe
  to do, since the AAF fully embeds the audio rather than just
  referencing the original files.
- **Auto-convert when stems arrive** — off by default. When on, a
  conversion starts once the number of waiting stems has held completely
  steady for 12 seconds. This is a convenience, not a guarantee: only you
  can really know the export has finished. It is safe to leave on,
  though, because of the all-or-nothing rule below.

**Application**

- **Launch at login** — keeps the app running automatically.
- **Uninstall Stem2AAF** — removes the app. This is the only place it
  lives; it's deliberately not in the menu bar dropdown, which you open
  constantly to reach Convert to AAF.

## Everyday use

1. In Bitwig: select the tracks you want, then **File → Export Audio…**,
   and export them all together in one operation into your watched folder.
   Bitwig writes one WAV file per track, all starting from the same point
   on the timeline.
2. Once you can see in Finder that every file you expect has landed, click
   **Convert to AAF** in the menu (its label shows a live count, e.g.
   "Convert to AAF (4 waiting)"). You'll get a macOS notification when
   it's done, or one explaining what went wrong if it fails.
3. Grab the `.aaf` from your chosen folder.

While it's working, the menu bar icon animates to show real progress: the
bars fill in left to right as work actually completes (settling files,
then writing the AAF), so a bigger batch visibly takes longer than a small
one. Once finished, it flashes white/orange a few times and settles back
to plain orange - regardless of whether it succeeded, so "the icon stopped
moving" always means "check the notification, or the log file inside the
resulting `<project> Converted vN` folder," never "nothing is happening."

## Nothing is ever converted halfway

If any file in the batch is still being written when a conversion starts,
**nothing is converted at all**. You get an error naming exactly which
files weren't ready, and no AAF and no conversion folder are created.

This matters more than it sounds. An AAF that is quietly missing two
tracks looks completely normal until you're deep into a mix session. So
the tool would rather refuse and tell you than hand you something that
looks finished and isn't. Wait for the export to complete, then convert
again.

Export all the tracks together in a single Export Audio operation, not one
at a time. A sample-rate mismatch between files is treated as a sign they
came from separate export operations and might not actually line up, so
the app refuses to combine them rather than guessing. A format issue alone
(e.g. 32-bit float audio, which Bitwig's engine can produce) is still
transcoded automatically; it's specifically a *rate* difference that's
treated as a hard stop.

## Uninstalling

Open **Settings → Application** and click **Uninstall…**. After a
confirmation dialog, it quits the app and removes the app bundle, its
settings, and its login-item entry.
Your project folder and everything in it is never touched - only the app's
own code and config get removed.

Under the hood this is a small script inside the app bundle
(`Contents/Resources/uninstall.sh`) which the app launches detached just
before quitting, so it outlives the app and can delete it. Earlier
versions shipped a whole second `.app` for this, which cost about 20 MB
inside every copy of Stem2AAF.

## Creating a distributable .dmg

The steps above install straight into your own `/Applications` folder -
that's all you need for using it yourself. If you want to share the app
with someone else, package it into a .dmg afterward:

```bash
chmod +x make_dmg.sh && ./make_dmg.sh
```

Run this in Terminal, from inside this project folder, **after**
Stem2AAF.app is already sitting in `/Applications`. It opens a brief
Finder window on its own while it works (it's arranging the icon layout) -
that's expected, not an error. The result, `Stem2AAF.dmg`, is the one file
to share. The recipient still needs to right-click → Open the first time,
same as you do, since it's not signed with an Apple Developer certificate.

## Running the tests

```bash
venv/bin/python3 tests/run_tests.py
```

No extra dependencies: it uses the standard library's `unittest` and the
packages the app already needs. `venv/bin/python3 -m pytest tests -q`
works too if you prefer pytest.

The suite covers track naming, the audio transcoding path, sample-rate
rejection, output-folder handling, atomic config writes, and above all the
rule that a batch containing a still-being-written stem must fail rather
than produce a partial AAF.

## Project files

- `src/converter.py` — the actual stems → AAF conversion logic
- `src/watcher.py` — watches the folder, batches arriving stems, runs conversions
- `src/app.py` — the menu bar app (menu, timers, notifications, uninstall)
- `src/settings_window.py` — the Settings window (WKWebView-based)
- `src/config.py` — remembers your settings between launches
- `src/version.py` — the one place the version number is defined
- `src/assets/uninstall.sh` — the uninstaller, bundled into the app
- `setup.py` — py2app packaging config
- `build.sh` — builds universal dependencies, packages, installs
- `tests/` — the test suite

## If something doesn't convert

Every conversion writes a log next to its AAF. Check that first.

To get a clearer error, run the converter directly:

```bash
source venv/bin/activate
python3 src/converter.py "/path/to/out.aaf" "/path/to/stem1.wav" "/path/to/stem2.wav"
```
