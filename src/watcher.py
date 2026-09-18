import os
import re
import shutil
import threading
import time
import traceback

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import config
from converter import stems_to_aaf, ConversionError, _sanitize_name

# Bitwig writes each stem file in one go, but we still wait for the file
# size to stop changing before touching it, in case of a slow disk /
# network volume.
SETTLE_SECONDS = 1.5
STEMS_POLL_INTERVAL_SECONDS = 1.0

_WAV_EXTENSIONS = (".wav", ".wave")


def _next_conversion_dir(watch_folder: str, output_folder: str) -> tuple[str, int, str]:
    """
    Creates a fresh per-conversion folder inside output_folder, named
    "<project> Converted v<N>" after the watched folder itself (e.g. a
    folder named "The Sun" produces "The Sun Converted v1"), and returns
    it alongside the version number N and the sanitized project name - so
    the AAF written inside it (as "<project>_v<N>.aaf") shares the exact
    same version number as the folder that contains it, making the two
    easy to associate at a glance. The version auto-increments each time
    a conversion happens for this project, based on existing "<project>
    Converted v*" folders, so repeated exports don't collide or overwrite
    each other.
    """
    project_name = _sanitize_name(os.path.basename(os.path.normpath(watch_folder)), fallback="Project")
    pattern = re.compile(re.escape(project_name) + r" Converted v(\d+)$")

    highest = 0
    try:
        for entry in os.listdir(output_folder):
            full = os.path.join(output_folder, entry)
            if not os.path.isdir(full):
                continue
            m = pattern.match(entry)
            if m:
                highest = max(highest, int(m.group(1)))
    except OSError:
        pass

    version = highest + 1
    conversion_dir = os.path.join(output_folder, f"{project_name} Converted v{version}")
    os.makedirs(conversion_dir, exist_ok=True)
    return conversion_dir, version, project_name


class StemsBatchHandler(FileSystemEventHandler):
    """
    Tracks .wav stem files in the watch folder - both ones that arrive
    while the app is running (via watchdog events) and ones already
    sitting there when the folder is chosen or the app starts (via a
    directory scan, since watchdog only reports changes that happen after
    it starts observing). Conversion only ever happens when the user
    explicitly clicks "Convert to AAF" - there's no automatic timer
    guessing whether Bitwig's export has finished, since render time per
    track depends on that track's own plugin load and how much audio it
    contains, which makes any fixed timeout an unreliable signal.
    """

    def __init__(self, watch_folder: str, output_folder: str, on_result, on_progress=None):
        self.watch_folder = watch_folder
        self.output_folder = output_folder
        self.on_result = on_result
        self.on_progress = on_progress or (lambda fraction: None)
        self._pending: dict[str, float] = {}
        # Tracks (path, mtime) pairs, not bare paths - so a NEW file that
        # later reuses the same path (e.g. a re-exported "Kick.wav" after
        # the earlier one was deleted or archived) is correctly seen as
        # new rather than permanently skipped just because something
        # with that same name was processed once before.
        self._processed: set[tuple[str, float]] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._flush_now = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def on_created(self, event):
        self._maybe_track(event.src_path)

    def on_moved(self, event):
        self._maybe_track(event.dest_path)

    def _is_processed(self, path: str) -> bool:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return False
        return (path, mtime) in self._processed

    def _maybe_track(self, path: str):
        path = os.path.normpath(path)
        if os.path.isdir(path):
            return
        if not path.lower().endswith(_WAV_EXTENSIONS):
            return
        if self._is_processed(path):
            return
        with self._lock:
            self._pending[path] = time.time()

    def _scan_existing(self) -> list[str]:
        """
        Lists .wav files currently sitting in the watch folder, regardless
        of whether they arrived before or after the watcher started.
        watchdog's on_created/on_moved events only fire for filesystem
        changes that happen *after* the observer is running - a file
        already in the folder when the app starts watching (or when the
        folder is first chosen) never generates an event and would
        otherwise be permanently invisible to _pending. This scan is the
        source of truth for "what's actually here right now"; the
        event-based _pending tracking above just wakes things up sooner
        for files that arrive while the app is already running.
        """
        try:
            entries = os.listdir(self.watch_folder)
        except OSError:
            return []
        found = []
        for name in entries:
            full = os.path.normpath(os.path.join(self.watch_folder, name))
            if os.path.isdir(full):
                continue
            if not name.lower().endswith(_WAV_EXTENSIONS):
                continue
            if self._is_processed(full):
                continue
            found.append(full)
        return found

    def _current_batch_candidates(self) -> set[str]:
        with self._lock:
            tracked = set(self._pending.keys())
        return tracked | set(self._scan_existing())

    def pending_count(self) -> int:
        return len(self._current_batch_candidates())

    def flush_now(self):
        """Converts whatever stems have arrived so far, right away - the
        only way a batch ever gets converted. See convert_now in the
        app's menu ("Convert to AAF")."""
        self._flush_now.set()

    def _loop(self):
        while not self._stop.is_set():
            time.sleep(STEMS_POLL_INTERVAL_SECONDS)
            if not self._flush_now.is_set():
                continue
            with self._lock:
                self._flush_now.clear()
                self._pending.clear()
            batch = sorted(self._current_batch_candidates())
            if not batch:
                self.on_result(
                    "0 stem file(s)", False, "No .wav stem files were found in the folder to convert.",
                    skip_log=True,  # nothing was actually attempted, so there's nothing worth logging to
                    # disk - the on-screen notification alone is enough feedback for this case
                )
                continue
            try:
                self._convert_batch(batch)
            except Exception as e:  # noqa: BLE001 - never let this background thread die silently;
                # a silent death here would make every future click on
                # "Convert to AAF" do nothing, with no way to tell why.
                self.on_result(
                    f"{len(batch)} stem file(s)",
                    False,
                    f"Internal error: {type(e).__name__}: {e}\n{traceback.format_exc()}",
                    log_dir=self.watch_folder,  # this can happen before a conversion folder exists
                )

    def _convert_batch(self, batch: list[str]):
        # Wait for every file's size to stop changing before touching them.
        # This settle-check phase and the actual AAF-writing phase below
        # are weighted 50/50 into one combined 0.0-1.0 progress signal -
        # see stems_to_aaf's own on_progress for the second half.
        settled = []
        unsettled = []
        for i, path in enumerate(batch):
            last_size = -1
            ok = False
            try:
                for _ in range(15):
                    if not os.path.exists(path):
                        break
                    size = os.path.getsize(path)
                    if size == last_size and size > 0:
                        ok = True
                        break
                    last_size = size
                    time.sleep(SETTLE_SECONDS)
            except OSError:
                ok = False
            if ok:
                settled.append(path)
            else:
                unsettled.append(path)
            self.on_progress(0.5 * (i + 1) / len(batch))

        if not settled:
            names = ", ".join(os.path.basename(p) for p in unsettled) or "no files"
            self.on_result(
                f"{len(batch)} stem file(s)",
                False,
                f"None of the stem files finished settling (still changing size, missing, or unreadable after "
                f"{15 * SETTLE_SECONDS:.0f}s): {names}",
                log_dir=self.watch_folder,  # no conversion folder exists yet - nothing was attempted
            )
            return

        # Captured now, right as each file is confirmed stable - not
        # re-read later in the finally block below, since by then the
        # file may already have been archived (moved) or deleted, making
        # its original path unreadable.
        settled_mtimes = {}
        for path in settled:
            try:
                settled_mtimes[path] = os.path.getmtime(path)
            except OSError:
                settled_mtimes[path] = None

        os.makedirs(self.output_folder, exist_ok=True)
        conversion_dir, version, project_name = _next_conversion_dir(self.watch_folder, self.output_folder)
        out_path = os.path.join(conversion_dir, f"{project_name}_v{version}.aaf")
        label = f"{len(settled)} stem file(s)"

        try:
            cfg = config.load()
            group_by_category = cfg.get("group_stems_by_category", False)
            category_order = cfg.get("category_order") or None
            custom_keywords = cfg.get("custom_keywords") or None
            disabled_keywords = cfg.get("disabled_keywords") or {}  # legacy fallback
            stems_to_aaf(
                settled, out_path,
                group_by_category=group_by_category,
                category_order=category_order,
                on_progress=lambda fraction: self.on_progress(0.5 + 0.5 * fraction),
                custom_keywords=custom_keywords,
                disabled_keywords=disabled_keywords,
            )
            self._archive(settled, conversion_dir)
            self.on_result(label, True, out_path, log_dir=conversion_dir)
        except ConversionError as e:
            self.on_result(label, False, str(e), log_dir=conversion_dir)
        except Exception as e:  # noqa: BLE001
            self.on_result(
                label, False, f"Unexpected error: {type(e).__name__}: {e}\n{traceback.format_exc()}",
                log_dir=conversion_dir,
            )
        finally:
            for path in settled:
                mtime = settled_mtimes.get(path)
                if mtime is not None:
                    self._processed.add((path, mtime))

    def _archive(self, paths: list[str], destination_dir: str):
        """
        Cleans up the source stem files after a successful conversion, by
        moving them into the same per-conversion folder as the AAF that
        was just built from them - so each conversion's output and its
        source stems live together, clearly grouped. If the user has
        turned on delete_stems_after_conversion, they're deleted outright
        instead, since the AAF fully embeds the audio and doesn't need
        them.
        """
        delete_instead = config.load().get("delete_stems_after_conversion", False)

        if delete_instead:
            for path in paths:
                try:
                    os.remove(path)
                except OSError:
                    pass  # leave it in place rather than fail the whole batch over this
            return

        for path in paths:
            try:
                shutil.move(path, os.path.join(destination_dir, os.path.basename(path)))
            except OSError:
                pass  # leave it in place rather than fail the whole batch over this

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=STEMS_POLL_INTERVAL_SECONDS + 1)


class Watcher:
    def __init__(self, watch_folder: str, output_folder: str, on_result, on_progress=None):
        self.watch_folder = watch_folder
        self.output_folder = output_folder
        self.on_result = on_result
        self.on_progress = on_progress
        self._observer = None
        self._stems_handler = None

    def start(self):
        os.makedirs(self.watch_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)
        self._stems_handler = StemsBatchHandler(
            self.watch_folder, self.output_folder, self.on_result, self.on_progress
        )

        self._observer = Observer()
        self._observer.schedule(self._stems_handler, self.watch_folder, recursive=False)
        self._observer.start()

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        if self._stems_handler:
            self._stems_handler.stop()
            self._stems_handler = None

    def restart(self, watch_folder: str, output_folder: str):
        self.stop()
        self.watch_folder = watch_folder
        self.output_folder = output_folder
        self.start()

    def pending_stems_count(self) -> int:
        """How many .wav stems are currently waiting to be batched into an
        AAF. Lets the menu show something concrete instead of the user
        having to guess whether every file has landed yet."""
        if self._stems_handler:
            return self._stems_handler.pending_count()
        return 0

    def convert_pending_stems_now(self):
        """Converts whatever stems have arrived so far - the only way a
        batch ever gets converted, since there's no automatic timer."""
        if self._stems_handler:
            self._stems_handler.flush_now()
