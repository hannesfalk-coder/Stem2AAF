"""
Tests for the stems -> AAF conversion itself.

Run them with:

    venv/bin/python3 -m pytest tests -q

or, without installing pytest:

    venv/bin/python3 tests/run_tests.py
"""

import os
import sys
import tempfile
import unittest

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import aaf2  # noqa: E402
from converter import (  # noqa: E402
    _CATEGORY_KEYWORDS,
    ConversionError,
    _normalize_wav,
    _rename_stem_track,
    _sanitize_name,
    stems_to_aaf,
)

SR = 48000


def write_stem(path, seconds=0.25, rate=SR, subtype="PCM_24", channels=2):
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
    sig = (0.2 * np.sin(2 * np.pi * 220 * t)).astype("float32")
    data = np.column_stack([sig] * channels) if channels > 1 else sig
    sf.write(path, data, rate, subtype=subtype)
    return path


def slot_names(aaf_path):
    with aaf2.open(aaf_path, "r") as f:
        comp = list(f.content.compositionmobs())[0]
        return [s.name for s in comp.slots]


class TrackNaming(unittest.TestCase):
    def test_bitwig_number_is_kept_in_parentheses(self):
        """The sanitizer used to strip the parentheses the renamer had just
        added, turning every "Kick (01)" into "Kick _01_"."""
        name = _sanitize_name(_rename_stem_track("01 Kick.wav", group_by_category=True))
        self.assertEqual(name, "Drums_Kick (01)")

    def test_no_category_prefix_when_grouping_is_off(self):
        """Turning grouping off used to still stamp "Unmatched_" on names."""
        self.assertEqual(
            _sanitize_name(_rename_stem_track("Boards of X.wav", group_by_category=False)),
            "Boards of X",
        )
        self.assertEqual(
            _sanitize_name(_rename_stem_track("01 Kick.wav", group_by_category=False)),
            "Kick (01)",
        )

    def test_category_prefix_when_grouping_is_on(self):
        self.assertEqual(
            _sanitize_name(_rename_stem_track("Boards of X.wav", group_by_category=True)),
            "Unmatched_Boards of X",
        )

    def test_master_is_left_alone(self):
        for grouping in (True, False):
            self.assertEqual(
                _sanitize_name(_rename_stem_track("Master.wav", group_by_category=grouping)),
                "Master",
            )

    def test_non_ascii_is_still_stripped(self):
        """Accented characters are a documented AAF relink hazard and must
        keep being replaced, even though parentheses are now allowed."""
        self.assertEqual(_sanitize_name("Café Señor"), "Caf_ Se_or")


class Normalizing(unittest.TestCase):
    def test_float_source_becomes_24_bit_pcm(self):
        with tempfile.TemporaryDirectory() as d:
            src = write_stem(os.path.join(d, "float.wav"), subtype="FLOAT")
            out = _normalize_wav(src, SR, d)
            info = sf.info(out)
            self.assertEqual(info.subtype, "PCM_24")
            self.assertEqual(info.samplerate, SR)
            self.assertEqual(info.frames, sf.info(src).frames)
            self.assertEqual(info.channels, 2)

    def test_audio_survives_the_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            src = write_stem(os.path.join(d, "float.wav"), seconds=1.0, subtype="FLOAT")
            out = _normalize_wav(src, SR, d)
            a, _ = sf.read(src)
            b, _ = sf.read(out)
            # 24-bit quantisation error only.
            self.assertLess(np.abs(a - b).max(), 1e-6)

    def test_mono_stays_mono(self):
        with tempfile.TemporaryDirectory() as d:
            src = write_stem(os.path.join(d, "mono.wav"), subtype="FLOAT", channels=1)
            out = _normalize_wav(src, SR, d)
            self.assertEqual(sf.info(out).channels, 1)

    def test_rate_mismatch_is_an_internal_error(self):
        with tempfile.TemporaryDirectory() as d:
            src = write_stem(os.path.join(d, "a.wav"), rate=44100, subtype="FLOAT")
            with self.assertRaises(ConversionError):
                _normalize_wav(src, 48000, d)


class NumpyIsNotRequired(unittest.TestCase):
    """
    numpy is excluded from the packaged app because its Intel wheel drags
    in ~93 MB of OpenBLAS. soundfile only imports numpy inside its
    array-returning calls, so the conversion path has to stay clear of
    sf.read, sf.write and SoundFile.blocks. If it doesn't, the app works
    from source and raises ImportError once packaged, which is the worst
    possible place to find out.
    """

    def test_normalizing_never_imports_numpy(self):
        import subprocess

        src_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"
        )
        probe = (
            "import sys, os, tempfile, array, math, math as _m\n"
            f"sys.path.insert(0, {src_dir!r})\n"
            # Make any numpy import a hard failure, exactly as the packaged
            # app would, instead of quietly succeeding from site-packages.
            "import builtins\n"
            "_real = builtins.__import__\n"
            "def _guard(name, *a, **k):\n"
            "    if name == 'numpy' or name.startswith('numpy.'):\n"
            "        raise AssertionError('numpy was imported')\n"
            "    return _real(name, *a, **k)\n"
            "builtins.__import__ = _guard\n"
            "import soundfile as sf\n"
            "from converter import _normalize_wav\n"
            "d = tempfile.mkdtemp(); p = os.path.join(d, 'f.wav'); sr = 48000\n"
            "buf = array.array('f', [0.2 * math.sin(2*math.pi*440*i/sr)\n"
            "                        for i in range(sr) for _ in range(2)])\n"
            "with sf.SoundFile(p, 'w', sr, 2, subtype='FLOAT') as f:\n"
            "    f.buffer_write(buf, dtype='float32')\n"
            "out = _normalize_wav(p, sr, d)\n"
            "assert sf.info(out).subtype == 'PCM_24'\n"
            "assert sf.info(out).frames == sr\n"
            "print('OK')\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True
        )
        self.assertEqual(
            proc.returncode, 0,
            f"conversion path touched numpy:\n{proc.stdout}\n{proc.stderr}",
        )
        self.assertIn("OK", proc.stdout)


class Conversion(unittest.TestCase):
    def test_one_slot_per_stem(self):
        with tempfile.TemporaryDirectory() as d:
            paths = [write_stem(os.path.join(d, f"{i:02d} Kick.wav")) for i in range(1, 4)]
            out = os.path.join(d, "out.aaf")
            stems_to_aaf(paths, out)
            self.assertTrue(os.path.exists(out))
            self.assertEqual(len(slot_names(out)), 3)

    def test_mixed_subtypes_convert(self):
        """Bitwig can write 32-bit float; those need transcoding first."""
        with tempfile.TemporaryDirectory() as d:
            paths = [
                write_stem(os.path.join(d, "01 Kick.wav"), subtype="PCM_24"),
                write_stem(os.path.join(d, "02 Bass.wav"), subtype="FLOAT"),
                write_stem(os.path.join(d, "03 Rhodes.wav"), subtype="PCM_16"),
            ]
            out = os.path.join(d, "out.aaf")
            stems_to_aaf(paths, out)
            self.assertEqual(len(slot_names(out)), 3)

    def test_sample_rate_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            paths = [
                write_stem(os.path.join(d, "a.wav"), rate=48000),
                write_stem(os.path.join(d, "b.wav"), rate=48000),
                write_stem(os.path.join(d, "c.wav"), rate=44100),
            ]
            out = os.path.join(d, "out.aaf")
            with self.assertRaises(ConversionError) as cm:
                stems_to_aaf(paths, out)
            self.assertIn("same sample rate", str(cm.exception))
            self.assertFalse(os.path.exists(out))

    def test_empty_batch_is_rejected(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ConversionError):
            stems_to_aaf([], os.path.join(d, "out.aaf"))

    def test_non_audio_extension_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "stem.mp3")
            open(bad, "wb").close()
            with self.assertRaises(ConversionError) as cm:
                stems_to_aaf([bad], os.path.join(d, "out.aaf"))
            self.assertIn("uncompressed", str(cm.exception))

    def test_grouping_orders_by_category_and_names_accordingly(self):
        with tempfile.TemporaryDirectory() as d:
            # Written deliberately out of category order.
            for n in ("03 Lead Vocal.wav", "01 Reese Bass.wav", "02 Kick.wav"):
                write_stem(os.path.join(d, n))
            paths = [os.path.join(d, n) for n in os.listdir(d) if n.endswith(".wav")]
            out = os.path.join(d, "out.aaf")
            stems_to_aaf(paths, out, group_by_category=True)
            names = slot_names(out)
            self.assertEqual(
                names,
                ["Drums_Kick (02)", "Bass_Reese Bass (01)", "Vocal_Lead Vocal (03)"],
            )

    def test_master_sorts_last(self):
        with tempfile.TemporaryDirectory() as d:
            write_stem(os.path.join(d, "Master.wav"))
            write_stem(os.path.join(d, "01 Kick.wav"))
            paths = [os.path.join(d, n) for n in os.listdir(d) if n.endswith(".wav")]
            out = os.path.join(d, "out.aaf")
            stems_to_aaf(paths, out)
            self.assertEqual(slot_names(out)[-1], "Master")

    def test_category_order_decides_track_order(self):
        """The Categories list is reorderable, and that order has to reach
        the AAF. Nothing covered this while there was no way to change it."""
        with tempfile.TemporaryDirectory() as d:
            for n in ("01 Kick.wav", "02 Reese Bass.wav", "03 Lead Vocal.wav"):
                write_stem(os.path.join(d, n))
            paths = sorted(os.path.join(d, n) for n in os.listdir(d) if n.endswith(".wav"))
            custom = dict(_CATEGORY_KEYWORDS)
            default = [{"name": n, "enabled": True} for n, _ in _CATEGORY_KEYWORDS]

            out = os.path.join(d, "a.aaf")
            stems_to_aaf(paths, out, group_by_category=True,
                         category_order=default, custom_keywords=custom)
            self.assertEqual(
                slot_names(out),
                ["Drums_Kick (01)", "Bass_Reese Bass (02)", "Vocal_Lead Vocal (03)"],
            )

            moved = [{"name": "Vocal", "enabled": True}] + [
                c for c in default if c["name"] != "Vocal"
            ]
            out2 = os.path.join(d, "b.aaf")
            stems_to_aaf(paths, out2, group_by_category=True,
                         category_order=moved, custom_keywords=custom)
            self.assertEqual(
                slot_names(out2),
                ["Vocal_Lead Vocal (03)", "Drums_Kick (01)", "Bass_Reese Bass (02)"],
            )

    def test_disabled_category_sorts_last_and_is_unmatched(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("01 Kick.wav", "02 Reese Bass.wav"):
                write_stem(os.path.join(d, n))
            paths = sorted(os.path.join(d, n) for n in os.listdir(d) if n.endswith(".wav"))
            custom = dict(_CATEGORY_KEYWORDS)
            order = [{"name": n, "enabled": n != "Bass"} for n, _ in _CATEGORY_KEYWORDS]
            out = os.path.join(d, "c.aaf")
            stems_to_aaf(paths, out, group_by_category=True,
                         category_order=order, custom_keywords=custom)
            names = slot_names(out)
            self.assertEqual(names[0], "Drums_Kick (01)")
            self.assertEqual(names[-1], "Unmatched_Reese Bass (02)")

    def test_progress_runs_from_zero_to_one(self):
        with tempfile.TemporaryDirectory() as d:
            paths = [write_stem(os.path.join(d, f"{i:02d} Kick.wav")) for i in range(1, 3)]
            seen = []
            stems_to_aaf(paths, os.path.join(d, "out.aaf"), on_progress=seen.append)
            self.assertTrue(seen)
            self.assertAlmostEqual(seen[-1], 1.0, places=6)
            self.assertEqual(seen, sorted(seen))

    def test_failed_conversion_leaves_no_temp_directories(self):
        before = set(os.listdir(tempfile.gettempdir()))
        with tempfile.TemporaryDirectory() as d:
            paths = [
                write_stem(os.path.join(d, "a.wav"), rate=48000),
                write_stem(os.path.join(d, "b.wav"), rate=44100),
            ]
            with self.assertRaises(ConversionError):
                stems_to_aaf(paths, os.path.join(d, "out.aaf"))
        leaked = [
            n for n in set(os.listdir(tempfile.gettempdir())) - before
            if n.startswith("stems_normalize_")
        ]
        self.assertEqual(leaked, [])


if __name__ == "__main__":
    unittest.main()
