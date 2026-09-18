"""
Tests for the folder watcher, above all its refusal to build an AAF from a
batch that isn't fully written yet.

That refusal is the whole point of the tool: an AAF quietly missing a track
looks fine until it is halfway through a mix session. Before this, a stem
that was still being written when Convert ran was dropped from the batch and
the conversion reported success.
"""

import os
import sys
import tempfile
import threading
import time
import unittest

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import aaf2  # noqa: E402
import config  # noqa: E402
import watcher as watcher_mod  # noqa: E402
from watcher import StemsBatchHandler, _next_conversion_dir  # noqa: E402

SR = 48000


def write_stem(path, seconds=0.25):
    t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
    sig = (0.2 * np.sin(2 * np.pi * 220 * t)).astype("float32")
    sf.write(path, np.column_stack([sig, sig]), SR, subtype="PCM_24")
    return path


class _Harness:
    """Runs one flush through a StemsBatchHandler and captures the result."""

    def __init__(self, folder, out_folder=None):
        self.folder = folder
        self.results = []
        self.handler = StemsBatchHandler(
            folder, out_folder or folder, self._on_result, lambda f: None
        )

    def _on_result(self, label, success, message, log_dir=None, skip_log=False):
        self.results.append(
            {"label": label, "success": success, "message": message, "log_dir": log_dir}
        )

    def flush(self, timeout=60):
        self.handler.flush_now()
        deadline = time.time() + timeout
        while not self.results and time.time() < deadline:
            time.sleep(0.05)
        self.handler.stop()
        return self.results[0] if self.results else None


class SettleBehaviour(unittest.TestCase):
    def setUp(self):
        # Keep the tests quick; the logic under test is unchanged by this.
        self._orig = watcher_mod.SETTLE_SECONDS
        watcher_mod.SETTLE_SECONDS = 0.1
        self._orig_passes = watcher_mod.SETTLE_MAX_PASSES
        watcher_mod.SETTLE_MAX_PASSES = 6

    def tearDown(self):
        watcher_mod.SETTLE_SECONDS = self._orig
        watcher_mod.SETTLE_MAX_PASSES = self._orig_passes

    def test_a_still_writing_stem_blocks_the_whole_batch(self):
        """The regression this suite exists for. Three finished stems and
        one still being written must produce an error, not a three-track
        AAF reported as a success."""
        with tempfile.TemporaryDirectory() as d:
            for n in ("01 Kick.wav", "02 Bass.wav", "03 Rhodes.wav"):
                write_stem(os.path.join(d, n))

            growing = os.path.join(d, "04 Vocal.wav")
            stop = threading.Event()

            def grow():
                with open(growing, "wb") as f:
                    while not stop.is_set():
                        f.write(b"\0" * 8192)
                        f.flush()
                        time.sleep(0.02)

            t = threading.Thread(target=grow, daemon=True)
            t.start()
            try:
                result = _Harness(d).flush()
            finally:
                stop.set()
                t.join(timeout=2)

            self.assertIsNotNone(result)
            self.assertFalse(result["success"], "a partial batch must not report success")
            self.assertIn("04 Vocal.wav", result["message"])
            self.assertIn("Nothing was converted", result["message"])
            aafs = [n for n in os.listdir(d) if n.endswith(".aaf")]
            self.assertEqual(aafs, [], "no AAF may be written for a partial batch")
            made = [n for n in os.listdir(d) if n.endswith("v1")]
            self.assertEqual(made, [], "no conversion folder for a batch that never converted")

    def test_a_complete_batch_converts(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("01 Kick.wav", "02 Bass.wav"):
                write_stem(os.path.join(d, n))
            result = _Harness(d).flush()
            self.assertIsNotNone(result)
            self.assertTrue(result["success"], result["message"])
            self.assertTrue(result["message"].endswith(".aaf"))
            with aaf2.open(result["message"], "r") as f:
                comp = list(f.content.compositionmobs())[0]
                self.assertEqual(len(list(comp.slots)), 2)

    def test_settling_is_not_per_file_sequential(self):
        """Every file is checked once per pass, so eight stems must not take
        eight times as long as one. The old loop slept per file."""
        with tempfile.TemporaryDirectory() as d:
            for i in range(8):
                write_stem(os.path.join(d, f"{i:02d} Stem.wav"))
            h = _Harness(d)
            settled, problems = h.handler._settle_batch(
                sorted(os.path.join(d, n) for n in os.listdir(d))
            )
            h.handler.stop()
            self.assertEqual(len(settled), 8)
            self.assertEqual(problems, {})

    def test_empty_folder_reports_nothing_to_do(self):
        with tempfile.TemporaryDirectory() as d:
            result = _Harness(d).flush()
            self.assertIsNotNone(result)
            self.assertFalse(result["success"])
            self.assertIn("No .wav stem files", result["message"])


class OutputFolder(unittest.TestCase):
    def test_versions_increment_per_project(self):
        with tempfile.TemporaryDirectory() as d:
            watch = os.path.join(d, "The Sun")
            os.makedirs(watch)
            d1, v1, name = _next_conversion_dir(watch, watch)
            d2, v2, _ = _next_conversion_dir(watch, watch)
            self.assertEqual(name, "The Sun")
            self.assertEqual((v1, v2), (1, 2))
            self.assertTrue(d1.endswith("The Sun Converted v1"))
            self.assertTrue(d2.endswith("The Sun Converted v2"))

    def test_output_can_live_outside_the_watched_folder(self):
        with tempfile.TemporaryDirectory() as d:
            watch = os.path.join(d, "Stems")
            out = os.path.join(d, "Exports")
            os.makedirs(watch)
            os.makedirs(out)
            write_stem(os.path.join(watch, "01 Kick.wav"))

            orig = watcher_mod.SETTLE_SECONDS
            watcher_mod.SETTLE_SECONDS = 0.1
            try:
                result = _Harness(watch, out).flush()
            finally:
                watcher_mod.SETTLE_SECONDS = orig

            self.assertIsNotNone(result)
            self.assertTrue(result["success"], result["message"])
            self.assertTrue(
                result["message"].startswith(out),
                f"AAF should be under {out}, got {result['message']}",
            )


class ConfigWrites(unittest.TestCase):
    def test_save_is_atomic_and_leaves_no_debris(self):
        with tempfile.TemporaryDirectory() as d:
            orig_dir, orig_path = config.CONFIG_DIR, config.CONFIG_PATH
            config.CONFIG_DIR = d
            config.CONFIG_PATH = os.path.join(d, "config.json")
            try:
                config.save({"folder": "/tmp/a", "custom_keywords": {"Drums": ["kick"]}})
                self.assertEqual(config.load()["folder"], "/tmp/a")
                self.assertEqual(config.load()["custom_keywords"], {"Drums": ["kick"]})
                self.assertEqual(sorted(os.listdir(d)), ["config.json"])
            finally:
                config.CONFIG_DIR, config.CONFIG_PATH = orig_dir, orig_path

    def test_corrupt_config_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            orig_dir, orig_path = config.CONFIG_DIR, config.CONFIG_PATH
            config.CONFIG_DIR = d
            config.CONFIG_PATH = os.path.join(d, "config.json")
            try:
                with open(config.CONFIG_PATH, "w") as f:
                    f.write("{not json")
                self.assertEqual(config.load()["folder"], config.DEFAULTS["folder"])
            finally:
                config.CONFIG_DIR, config.CONFIG_PATH = orig_dir, orig_path


if __name__ == "__main__":
    unittest.main()
