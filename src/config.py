import json
import os
import tempfile

# How long the number of waiting stems must hold completely steady before
# auto-convert fires, in seconds. Lives here because app.py acts on it and
# settings_window.py quotes it to the user in two places; a second
# hardcoded copy would drift the moment this changed.
#
# A single 2-second tick, which is what this used to be, is shorter than
# the gap Bitwig leaves between finishing one track and creating the next
# when a track carries a heavy plugin chain, so auto-convert could fire in
# the middle of an export.
#
# 6 rather than 12: this window is dead time from the user's side. The
# stems are already sitting in the folder and the menu-bar icon is showing
# the "detected" blink, but nothing advances until it elapses, so every
# second of it reads as the app being slow. 6 still clears the worst
# inter-track gap above by roughly 3x, and a mistimed fire is not silent
# corruption: the watcher refuses to build an AAF from a batch where any
# file is still being written, so the failure mode is a visible error
# rather than an AAF quietly missing tracks.
AUTO_CONVERT_QUIET_SECONDS = 6

CONFIG_DIR = os.path.expanduser("~/Library/Application Support/Stem2AAF")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    # The watched folder: the DAW exports stem .wav files here.
    # Kept under the historical key name "folder" so existing configs
    # keep working without a migration step.
    "folder": os.path.expanduser("~/Documents/Stem2AAF"),
    # Where the "<project> Converted vN" folders are written. Empty means
    # "alongside the stems, in the watched folder", which is the long-
    # standing behaviour and stays the default. The Settings panel has
    # always shown a separate output folder; until now the app discarded
    # whatever was chosen there and wrote next to the stems regardless.
    "output_folder": "",
    "launch_at_login": False,
    # After a successful stems conversion, the source .wav files are
    # archived alongside the resulting AAF, inside a per-conversion
    # "<project> Converted vN" folder (kept as a backup). If this is
    # True, they're deleted instead, since the AAF fully embeds the audio
    # and doesn't need them.
    "delete_stems_after_conversion": False,
    # When True, stems tracks are ordered into Drums/Bass/Guitar/Keys/
    # Synth/Strings/Vocal/Other groups by filename keywords instead of
    # plain arrival order. A best-effort heuristic based on common
    # naming conventions - not audio analysis - so a file with no
    # recognizable name (e.g. "Track 7") just lands in "Other".
    "group_stems_by_category": False,
    # Convert automatically once the number of waiting stems has stopped
    # changing for AUTO_CONVERT_QUIET_SECONDS (see app.py). Off by default:
    # clicking "Convert to AAF" once the export has visibly finished is
    # always the reliable option.
    "auto_convert": False,
    # Written by the Settings panel. category_order is
    # [{"name": str, "enabled": bool}, ...] and custom_keywords is
    # {category_name: [keyword, ...]}. Absent until the user edits them,
    # in which case the converter's built-in table is used.
    "category_order": [],
    "custom_keywords": {},
}


def load() -> dict:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        save(DEFAULTS)
        return dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r") as f:
            data = json.load(f)
        merged = dict(DEFAULTS)
        merged.update(data)
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULTS)


def save(data: dict) -> None:
    """
    Writes the config atomically: a complete temp file first, then an
    os.replace() onto the real path, which is atomic on macOS.

    Writing straight into config.json meant a crash or a full disk midway
    left a truncated file behind, and load() silently falls back to
    DEFAULTS when the JSON won't parse - so a half-written save didn't
    just lose that one change, it quietly discarded every custom category
    and keyword the user had built up. The settings panel saves on every
    toggle and every keyword edit, so there are a lot of chances to be
    interrupted.
    """
    os.makedirs(CONFIG_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".config-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CONFIG_PATH)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
