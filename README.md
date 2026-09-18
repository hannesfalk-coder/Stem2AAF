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
this step has to happen on your machine — I can't produce a compiled Mac
app from this sandbox; what's in this zip is source code, not an app yet.

**Option A — no Terminal needed (recommended):**

1. Double-click `Build Stem2AAF.applescript` — it opens in Script Editor,
   which comes built into every Mac (nothing to install).
2. Click the **Run** button (▶) in Script Editor's toolbar.
3. Click OK on the confirmation dialog. Wait a minute or two - no visible
   Terminal window appears, everything happens in the background.
4. You'll get a dialog confirming it's done, or one explaining what went
   wrong if the build failed.

I haven't been able to test-run this script myself, since Script Editor
only exists on macOS and I'm working from a Linux sandbox - if it doesn't
behave as described, tell me exactly what happened and I'll fix it.

**Option B — Terminal, one script:**

```bash
cd stem2aaf
chmod +x build.sh
./build.sh
```

**Option C — Terminal, step by step:**

```bash
cd stem2aaf
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 setup.py py2app
rm -rf build
python3 setup_uninstaller.py py2app
cp -R "dist/Stem2AAF Uninstaller.app" "dist/Stem2AAF.app/Contents/Resources/"
mv "dist/Stem2AAF.app" /Applications/
```

(These are run as two separate py2app invocations rather than one combined
build - see the comment at the top of `build.sh` for why. The Uninstaller
ends up bundled inside Stem2AAF.app's own Contents/Resources folder
rather than installed separately - see "Uninstalling" below.)

If you don't have Python 3 installed, get it from python.org first, or via
`brew install python3` if you use Homebrew.

## First launch

macOS will likely warn "Stem2AAF can't be opened because it is from an
unidentified developer" the first time, since it isn't signed with an Apple
Developer certificate. To open it anyway: **right-click the app → Open →
Open** (only needed once).

A small icon will appear in your menu bar. Click it to:

- **Choose folder...** — the single folder Bitwig exports stems into and
  where finished conversions also land (defaults to `~/Documents/Stem2AAF`).
  The **name of this folder becomes the project name**: each conversion
  creates a folder named after it, e.g. "The Sun" produces `The Sun
  Converted v1/` containing `The Sun_v1.aaf` - the folder and file share
  the same version number, so they're easy to associate at a glance.
  Each further conversion in that same watched folder increments the
  version automatically (`The Sun Converted v2/` with `The Sun_v2.aaf`,
  and so on) — so use one watched folder per project (e.g. rename or
  create a new folder for each song) rather than reusing one folder
  across unrelated projects.
- **Launch at login** — keeps it running automatically
- **Delete stems after conversion** — off by default, which archives the
  source `.wav` stems into that same per-conversion folder, alongside the
  AAF, as a backup. Turn this on to delete them outright instead, leaving
  only the `.aaf` in the folder - safe to do, since the AAF fully embeds
  the audio rather than just referencing the original files.
- **Group stems by category** — off by default (tracks land in the AAF in
  the order Bitwig wrote them). Turn this on to group tracks into
  Drums / Bass / Guitar / Keys / Synth / Strings / Vocal / Other instead,
  based on keywords in each file's name (e.g. "Kick", "Perc", "Conga" →
  Drums; "808", "Reese", "Wobble" → Bass; "Rhodes", "Organ" → Keys;
  "Violin", "Arco", "Pizzicato" → Strings; "Lead Vocal" → Vocal). This is
  a naming-convention heuristic, not audio analysis - a file with no
  recognizable name (e.g. "Track 7") just lands in "Other". A name
  matching keywords from two categories goes to whichever is listed
  first above (e.g. "Moog Bass" → Bass, not Synth). Order within each
  category still follows arrival order.
- **Convert to AAF** — shows how many stem files are currently waiting
  (e.g. "Convert to AAF (4 waiting)"), and compiles them into an AAF when
  clicked. **This is the only way conversion ever happens - there's no
  automatic timer.** Bitwig renders each track at a speed that depends on
  that track's own plugin load and how much actual audio is in it - a
  CPU-heavy plugin chain (convolution reverb, oversampled synths) renders
  slower, and a mostly-silent track renders faster. A fixed timeout can't
  reliably tell "still rendering a slow track" from "export finished", so
  rather than risk silently compiling an incomplete AAF, this app doesn't
  guess at all: export your stems, watch Finder until every file you
  expect has landed, then click this yourself. While it's working, the
  menu bar icon animates to show real progress: the first bar flashes
  immediately on click, then hands off to the bars filling in left to
  right as work actually completes (settling files, then writing the
  AAF) - not a fixed timer guessing at duration, so a bigger batch
  visibly takes longer than a small one. Once finished, it flashes white/
  orange a few times and settles back to plain orange - regardless of
  whether it succeeded, so "the icon stopped moving" always means "check
  the notification (or the log file inside the resulting `<project>
  Converted vN` folder) for what actually happened," never "nothing is
  happening."

## Uninstalling

Choose **"Uninstall Stem2AAF..."** from the menu bar icon - there's no
separate app to find or run. It quits Stem2AAF if it's running, then
removes the app, its settings, and its login-item entry, after a
confirmation dialog. Your project folder and everything in it
(`.wav`/`.aaf` files) is never touched - only the app's own code and
config get removed. Under the hood this launches a small Uninstaller app
bundled inside Stem2AAF.app itself (so it travels along automatically
whenever you install or copy the app - nothing extra to drag or download)
and it's removed along with everything else once the uninstall finishes.

## Creating a distributable .dmg

The steps above install straight into your own `/Applications` folder -
that's all you need for using it yourself. If you want to share the app
with someone else instead (e.g. as a download), package it into a .dmg
afterward:

```
chmod +x make_dmg.sh && ./make_dmg.sh
```

Run this in Terminal, from inside this project folder, **after**
Stem2AAF.app is already sitting in `/Applications` (i.e. after a
successful build). It opens a brief Finder window on its own while it
works (it's arranging the icon layout) - that's expected, not an error.
It copies the app into a disk image laid out with the app and a shortcut
to `/Applications` side by side, so whoever opens it gets the familiar
drag-the-app-onto-Applications install gesture (its Uninstaller comes
along automatically, bundled inside). The result, `Stem2AAF.dmg`, is
the one file to share - the recipient still needs to right-click → Open
the first time, same as you do, since it's not signed with an Apple
Developer certificate.

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

Important: export all the tracks together in a single Export Audio
operation, not one at a time. A sample-rate mismatch between files is
treated as a sign they came from separate export operations and might not
actually line up, so the app refuses to combine them rather than
guessing. (A format issue alone - e.g. 32-bit float audio, which Bitwig's
engine can produce - is still transcoded automatically; it's specifically
a *rate* difference that's treated as a hard stop.)

## Project files

- `src/converter.py` — the actual stems → AAF conversion logic
- `src/watcher.py` — watches the folder, batches arriving stems, triggers conversion
- `src/app.py` — the menu bar app (folder picker, toggles, notifications)
- `src/config.py` — remembers your settings between launches
- `src/uninstaller.py` — the Uninstaller app's logic (bundled inside Stem2AAF.app, not installed separately)
- `setup.py` / `setup_uninstaller.py` — py2app packaging config for each app

## If something doesn't convert

Run the converter directly for a clearer error message:

```bash
source venv/bin/activate
python3 src/converter.py "/path/to/out.aaf" "/path/to/stem1.wav" "/path/to/stem2.wav"
```
