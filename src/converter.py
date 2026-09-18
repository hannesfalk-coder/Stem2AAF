"""
converter.py

Reads a batch of full-length stem WAV files (from Bitwig's
File -> Export Audio...) and writes an .aaf file for import into
DaVinci Resolve (Fairlight page) or other post-production tools that
accept Pro Tools-style AAF - one track per file, each starting at
timeline position zero.

This is stems-only by design. An earlier version of this tool also
supported Bitwig's File -> Export DAWproject... path, which preserves
clip-level structure - but DAWproject references the project's original,
unprocessed source samples rather than what actually plays back through
each track's plugin chain (EQ, compression, etc.). For a real
post-production handoff, that's usually the wrong audio: a compressed
drum bus imported via DAWproject comes through dry, with no compression
applied. Bitwig's own audio engine has to actually render through the
plugin chain to get the real, processed sound - which is exactly what
Export Audio does and DAWproject does not. So this tool only supports
that path now.

Resolve-specific hardening (per Blackmagic's own AAF interchange guidance):
- All clips must share one sample rate - a mismatch is treated as a sign
  the files came from separate export operations and rejected outright,
  rather than guessed at.
- Only uncompressed PCM (.wav/.aiff) essence is embedded. Bitwig can
  write 32-bit float WAV (its internal engine precision) which pyaaf2's
  own WAV reader can't embed directly - anything not already 16/24-bit
  integer PCM is transcoded first.
- Track names are sanitized to plain ASCII - accented/special characters
  are a documented cause of relinking failures on both macOS and Windows.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile

import aaf2


class ConversionError(Exception):
    """Raised when a batch of stems can't be converted."""


_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9 _\-]")


def _sanitize_name(name: str, fallback: str = "Track") -> str:
    """Strips anything that isn't plain ASCII alphanumerics/space/-/_ , since
    accented or special characters in track names are a documented cause
    of relinking failures when the AAF is later imported."""
    cleaned = _UNSAFE_NAME_CHARS.sub("_", name or "")
    cleaned = cleaned.strip() or fallback
    return cleaned


_UNCOMPRESSED_EXTENSIONS = {".wav", ".wave", ".aif", ".aiff"}

# Best-effort keyword categorization for stem filenames, used only when the
# user turns on "Group stems by category". This is a heuristic, not audio
# analysis - a file with no recognizable naming convention (e.g. "Track 7")
# simply won't match anything and falls into "Other". Checked in this order
# so a name matching multiple categories (e.g. "Bass Synth") resolves to
# whichever is listed first below - there's no way to do this perfectly
# from a filename alone.
_CATEGORY_KEYWORDS = [
    ("Drums",      ["drum", "kick", "snare", "hat", "hihat", "hi-hat", "tom", "cymbal",
                    "crash", "ride", "overhead", "percussion", "perc", "conga", "clap",
                    "rim", "shaker", "tambourine", "bongo", "timbale", "cabasa", "cowbell",
                    "brush", "break", "china", "splash", "hh", "bd", "sd"]),
    ("Bass",       ["bass", "sub", "808", "reese", "wobble", "growl",
                    "pbass", "p-bass", "jbass", "j-bass", "slap", "upright",
                    "subbass", "sub-bass", "bassline", "bass line", "lowend",
                    "low-end", "rumble", "fretless"]),
    ("Guitar",     ["guitar", "gtr", "acoustic", "riff", "strum", "slide", "nylon",
                    "picked", "fingerpicked", "strat", "tele", "lick", "crunch",
                    "rhythm", "12string", "dobro", "lap steel"]),
    ("Keys",       ["keys", "keyboard", "piano", "organ", "rhodes", "wurli", "wurlitzer",
                    "clav", "clavinet", "epiano", "e-piano", "harpsichord", "hammond",
                    "mellotron", "grand", "nord"]),
    ("Orchestral", ["orchestra", "brass", "horn", "trumpet", "trombone", "tuba",
                    "french horn", "sax", "saxophone", "flute", "oboe", "clarinet",
                    "bassoon", "piccolo", "harp", "woodwind", "ensemble", "section",
                    "chamber", "quartet", "quintet", "philharmonic"]),
    ("Synth",      ["synth", "syn", "pad", "arp", "arpeggio", "pluck", "seq", "sweep",
                    "stab", "drone", "moog", "noise", "oscillator", "juno",
                    "jupiter", "prophet", "oberheim", "minimoog", "korg", "virus",
                    "massive", "serum", "omnisphere", "diva", "repro", "zebra",
                    "pigments", "phase plant", "riser", "saw", "sawtooth", "square",
                    "sine", "pulse", "wavetable", "waveform", "lfo", "granular",
                    "modular", "dx7", "ms20", "ms-20", "sh101", "sh-101",
                    "waldorf", "sylenth", "sylenth1"]),
    ("Strings",    ["violin", "viola", "cello", "strings", "string", "pizzicato",
                    "arco", "legato"]),
    ("Vocal",      ["vocal", "vox", "voice", "vo", "voiceover", "voice over", "narration",
                    "spoken", "rap", "hook", "ad lib", "adlib", "choir", "bgv",
                    "harmony", "harmonies"]),
    ("Sends",      ["reverb", "verb", "delay", "echo", "hall", "plate", "send",
                    "return", "aux", "bus", "pre-delay", "predelay", "fx", "fx track", "room"]),
]
_CATEGORY_ORDER = [name for name, _ in _CATEGORY_KEYWORDS] + ["Other"]


def _categorize_stem_name(
    filename: str,
    kw_list: list | None = None,
    disabled_keywords: dict | None = None,
) -> str:
    """Returns a best-guess category label for a stem based on keywords in
    its filename, or 'Other' if nothing matches.

    kw_list is a pre-built [(category_name, [keywords]), ...] list in
    priority order, derived from the user's custom keyword map. When None,
    falls back to the built-in _CATEGORY_KEYWORDS with optional
    disabled_keywords as a filtering overlay (legacy path).
    """
    base = os.path.splitext(os.path.basename(filename))[0].lower()
    if kw_list is not None:
        for category, keywords in kw_list:
            if any(kw in base for kw in keywords):
                return category
    else:
        disabled = disabled_keywords or {}
        for category, keywords in _CATEGORY_KEYWORDS:
            active_kws = [kw for kw in keywords if kw not in disabled.get(category, [])]
            if any(kw in base for kw in active_kws):
                return category
    return "Other"


_BITWIG_NUMBER_RE = re.compile(r'^(\d+)\s+(.+)$')


def _rename_stem_track(filename: str, kw_list: list | None = None, disabled_keywords: dict | None = None) -> str:
    """
    Converts a Bitwig stem filename to a readable AAF track name.

    Bitwig prepends a number to individual track exports ("01 Kick.wav").
    This moves that number to the end and prefixes with the detected
    category so DaVinci Resolve shows clean, sorted track names:

      "01 Kick.wav"          -> "Drums_Kick (01)"
      "Drum grp Master.wav"  -> "Drums_Drum grp Master"
      "Boards of X.wav"      -> "Unmatched_Boards of X"
      "Master.wav"           -> "Master"  (kept intact, sorted last)
    """
    base = os.path.splitext(os.path.basename(filename))[0]

    # Bitwig's project-folder Master stem keeps its name as-is.
    if base.strip().lower() == "master":
        return "Master"

    m = _BITWIG_NUMBER_RE.match(base)
    if m:
        number = m.group(1)
        name   = m.group(2)
    else:
        number = None
        name   = base

    category = _categorize_stem_name(filename, kw_list, disabled_keywords)
    prefix   = category if category != "Other" else "Unmatched"

    if number is not None:
        return f"{prefix}_{name} ({number})"
    return f"{prefix}_{name}"


def _validate_aaf(path: str, expected_track_count: int) -> None:
    """
    Re-opens the AAF we just wrote and checks it actually has the structure
    we intended, before telling the user it succeeded. A file that opens
    without a Python exception but is structurally wrong (e.g. an empty
    composition) would otherwise only surface as a mysterious failure once
    it's already inside Resolve.
    """
    try:
        with aaf2.open(path, "r") as f:
            comps = list(f.content.compositionmobs())
            if not comps:
                raise ConversionError("Validation failed: no composition mob was written to the AAF.")
            slot_count = len(list(comps[0].slots))
            if slot_count != expected_track_count:
                raise ConversionError(
                    f"Validation failed: expected {expected_track_count} track(s) but the "
                    f"written AAF has {slot_count}."
                )
    except ConversionError:
        raise
    except Exception as e:  # noqa: BLE001 - any failure to re-open means the file is suspect
        raise ConversionError(f"Validation failed: the written AAF could not be re-opened ({e}).")


def _normalize_wav(src_path: str, target_rate: int, work_dir: str) -> str:
    """
    Transcodes a WAV file to 24-bit PCM - the format pyaaf2 can reliably
    embed - and returns the path to the normalized copy, written into
    work_dir. Does not resample: target_rate is expected to already match
    the file's actual rate (stems_to_aaf() enforces this upstream).
    """
    import soundfile as sf

    data, orig_rate = sf.read(src_path, always_2d=True)
    if orig_rate != target_rate:
        # Should be unreachable: stems_to_aaf() already rejects any batch
        # with a sample-rate mismatch before normalization ever runs, so
        # every call here should already be at target_rate. Fail loudly
        # instead of silently writing a mismatched file if that invariant
        # is ever broken by a future change.
        raise ConversionError(
            f"Internal error: '{os.path.basename(src_path)}' is {orig_rate}Hz "
            f"but {target_rate}Hz was expected after rate validation."
        )

    out_name = f"normalized_{target_rate}_{os.path.basename(src_path)}"
    out_path = os.path.join(work_dir, out_name)
    sf.write(out_path, data, target_rate, subtype="PCM_24")
    return out_path


def stems_to_aaf(
    wav_paths: list[str], out_path: str, group_by_category: bool = False,
    category_order: list | None = None, on_progress=None,
    custom_keywords: dict | None = None,
    disabled_keywords: dict | None = None,
) -> str:
    """
    Builds an AAF from a batch of full-length stem WAV files, one track per
    file, each starting at time zero.

    Track order defaults to file modification time (closest available
    proxy for the order Bitwig wrote them during export). If
    group_by_category is True, tracks are grouped by filename keywords -
    a best-effort heuristic, not audio analysis - with arrival order
    preserved within each category.

    category_order is an optional list of {"name": str, "enabled": bool}
    dicts (from the Category Order panel) that controls both the group
    sequence and which categories are active. Disabled categories\'
    stems are treated as "Other" and placed at the end. When None the
    built-in _CATEGORY_ORDER is used as before.

    If given, on_progress(fraction) is called repeatedly with a 0.0-1.0
    value as work actually completes (once per file normalized, once per
    file embedded) - real progress through this function's own work, not
    a fixed timer, so it stays accurate regardless of how large the batch
    is or how long embedding actually takes.
    """
    import soundfile as sf

    if on_progress is None:
        on_progress = lambda fraction: None  # noqa: E731

    # Build keyword lookup from custom_keywords when provided, ordered by
    # category_order priority. Falls back to None (-> _CATEGORY_KEYWORDS path).
    kw_list: list | None = None
    if custom_keywords:
        if category_order:
            ordered_names = [c["name"] for c in category_order if c.get("enabled", True)]
        else:
            ordered_names = list(custom_keywords.keys())
        kw_list = [(name, custom_keywords.get(name, [])) for name in ordered_names]

    if not wav_paths:
        raise ConversionError("No stem files given to convert.")

    for p in wav_paths:
        ext = os.path.splitext(p)[1].lower()
        if ext not in _UNCOMPRESSED_EXTENSIONS:
            raise ConversionError(
                f"'{os.path.basename(p)}' is not an uncompressed WAV/AIFF file. "
                "Export stems from Bitwig as WAV, not a compressed format."
            )

    infos = {}
    for p in wav_paths:
        try:
            infos[p] = sf.info(p)
        except Exception as e:  # noqa: BLE001
            raise ConversionError(f"Couldn't read '{os.path.basename(p)}' as audio: {e}")

    rate_counts: dict[int, int] = {}
    for info in infos.values():
        rate_counts[info.samplerate] = rate_counts.get(info.samplerate, 0) + 1
    max_count = max(rate_counts.values())
    target_rate = max(r for r, c in rate_counts.items() if c == max_count)

    mismatched = [p for p, i in infos.items() if i.samplerate != target_rate]
    if mismatched:
        raise ConversionError(
            f"'{os.path.basename(mismatched[0])}' doesn't share the same sample rate as the "
            "rest of this batch. These don't look like they came from the same Export Audio "
            "operation - re-export them together in one pass so they stay aligned."
        )

    # pyaaf2's WAV reader only accepts 16/24-bit integer PCM - transcode
    # anything else (e.g. 32-bit float, which Bitwig can produce) to
    # 24-bit PCM first, into a temp folder next to the source files.
    #
    # Normalizing and embedding are weighted evenly (each file counts as
    # one step in each phase) into the overall 0.0-1.0 progress reported
    # here, regardless of whether a given file actually needed
    # transcoding - the point is steady, real forward progress per file
    # touched, not a precise time estimate.
    total_steps = 2 * len(wav_paths)
    completed_steps = 0

    _SAFE_SUBTYPES = {"PCM_16", "PCM_24"}
    work_dir = tempfile.mkdtemp(prefix="stems_normalize_")
    normalized_paths: dict[str, str] = {}
    for p, info in infos.items():
        if info.subtype in _SAFE_SUBTYPES:
            normalized_paths[p] = p
        else:
            normalized_paths[p] = _normalize_wav(p, target_rate, work_dir)
        completed_steps += 1
        on_progress(completed_steps / total_steps)

    if os.path.exists(out_path):
        os.remove(out_path)

    tmp_out = os.path.join(work_dir, "output.aaf")
    try:
        with aaf2.open(tmp_out, "w") as f:
            # Name the composition after the AAF file itself so Resolve
            # shows the actual project name instead of a generic label.
            composition_name = os.path.splitext(os.path.basename(out_path))[0]
            composition = f.create.CompositionMob(composition_name)
            f.content.mobs.append(composition)

            if group_by_category:
                # Group into categories by filename keywords, preserving
                # arrival order within each category. Uses the user-defined
                # category_order when provided (respecting enabled/disabled
                # state), otherwise falls back to the built-in _CATEGORY_ORDER.
                if category_order:
                    enabled_names = [c["name"] for c in category_order if c.get("enabled", True)]
                    def sort_key(p):
                        _b = os.path.splitext(os.path.basename(p))[0].strip().lower()
                        if _b == "master":
                            return (len(enabled_names) + 1, os.path.getmtime(p))
                        cat = _categorize_stem_name(p, kw_list, disabled_keywords)
                        try:
                            idx = enabled_names.index(cat)
                        except ValueError:
                            idx = len(enabled_names)  # disabled or "Other" — goes to end
                        return (idx, os.path.getmtime(p))
                else:
                    def sort_key(p):
                        _b = os.path.splitext(os.path.basename(p))[0].strip().lower()
                        if _b == "master":
                            return (len(_CATEGORY_ORDER) + 1, os.path.getmtime(p))
                        cat = _categorize_stem_name(p, kw_list, disabled_keywords)
                        try:
                            return (_CATEGORY_ORDER.index(cat), os.path.getmtime(p))
                        except ValueError:
                            return (len(_CATEGORY_ORDER), os.path.getmtime(p))
            else:
                # Order tracks by file modification time (closest available
                # proxy for the order Bitwig wrote them during export) rather
                # than filename - alphabetical sort would scramble the
                # original top-to-bottom track order, which has nothing to do
                # with names.
                def sort_key(p):
                    _b = os.path.splitext(os.path.basename(p))[0].strip().lower()
                    if _b == "master":
                        return (1, os.path.getmtime(p))
                    return (0, os.path.getmtime(p))

            for wav_path in sorted(wav_paths, key=sort_key):
                track_name = _sanitize_name(_rename_stem_track(wav_path, kw_list, disabled_keywords))
                embed_path = normalized_paths[wav_path]

                embed_info = sf.info(embed_path)
                sample_rate = embed_info.samplerate
                length_samples = embed_info.frames

                master_mob = f.create.MasterMob(track_name)
                f.content.mobs.append(master_mob)
                master_slot = master_mob.import_audio_essence(embed_path, sample_rate)

                source_clip = master_mob.create_source_clip(
                    master_slot.slot_id, start=0, length=length_samples, media_kind="sound"
                )

                slot = composition.create_timeline_slot(edit_rate=sample_rate)
                slot.name = track_name
                slot.segment = source_clip

                completed_steps += 1
                on_progress(completed_steps / total_steps)

            f.save()

        # Only validated here, then moved into place - if writing failed
        # partway through (as pyaaf2 can, on unsupported audio formats), the
        # real output location never ends up with a broken file in it.
        _validate_aaf(tmp_out, expected_track_count=len(wav_paths))
        shutil.move(tmp_out, out_path)
    finally:
        # Guaranteed regardless of success or failure - without this, a
        # failed conversion (e.g. validation error) would leave the
        # normalized-audio temp folder behind indefinitely, since nothing
        # else ever cleans up a directory made with tempfile.mkdtemp.
        shutil.rmtree(work_dir, ignore_errors=True)

    return out_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python converter.py output.aaf stem1.wav [stem2.wav ...]")
        sys.exit(1)
    result = stems_to_aaf(sys.argv[2:], sys.argv[1])
    print(f"Wrote {result}")
