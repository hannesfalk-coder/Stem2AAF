import json
import os

CONFIG_DIR = os.path.expanduser("~/Library/Application Support/Stem2AAF")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    # Single folder used both ways: DAW exports stem .wav files here,
    # and the converted .aaf files are written into this same folder.
    "folder": os.path.expanduser("~/Documents/Stem2AAF"),
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
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)
