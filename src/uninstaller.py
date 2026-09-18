"""
Standalone uninstaller for Stem2AAF (macOS only).

Built as its own .app, but bundled INSIDE Stem2AAF.app's own
Contents/Resources folder rather than installed separately - so
installing or dragging the one app carries this along with it
automatically. Launched via Stem2AAF's own "Uninstall Stem2AAF..."
menu item (see app.py's launch_uninstaller). It quits the main app if
it's currently running, then deletes the app itself, its settings, its
login-item entry, and finally itself too (implicitly, since it lives
inside the very app bundle it just deleted).

Your project folder and any .wav/.aaf files in it are never
touched - only the main app's own code and settings are removed.
"""

import os
import shlex
import shutil
import subprocess
import time

import rumps
from AppKit import NSBundle

import config

MAIN_APP_PATH = "/Applications/Stem2AAF.app"
LAUNCH_AGENT_PATH = os.path.expanduser("~/Library/LaunchAgents/com.local.stem2aaf.plist")


def _quit_main_app_if_running():
    # Targeting by CFBundleName via AppleScript/System Events - works
    # whether or not the app is currently running; harmless no-op if not.
    subprocess.run(
        ["osascript", "-e", 'tell application "Stem2AAF" to quit'],
        capture_output=True,
    )
    time.sleep(1)  # give it a moment to actually exit before we delete its files


def _remove_login_item():
    if os.path.exists(LAUNCH_AGENT_PATH):
        subprocess.run(["launchctl", "unload", LAUNCH_AGENT_PATH], check=False)
        os.remove(LAUNCH_AGENT_PATH)


def _self_delete():
    """
    Removes this Uninstaller app itself, a couple of seconds after this
    process exits. macOS (unlike Windows) allows deleting a running app
    bundle's files while it's still executing - the pages already loaded
    into memory stay valid until the process actually exits, and the
    directory entry disappears from Finder immediately. The short delay
    in the detached shell command just gives this process time to
    actually finish quitting first, so nothing gets pulled out from under
    it mid-write. Found via NSBundle rather than a hardcoded path so this
    keeps working even if the app is ever renamed or moved.
    """
    bundle_path = NSBundle.mainBundle().bundlePath()
    if not bundle_path or not os.path.isdir(bundle_path):
        return
    subprocess.Popen(
        ["/bin/sh", "-c", f"sleep 2 && rm -rf {shlex.quote(bundle_path)}"],
        start_new_session=True,
    )


def main():
    confirmed = rumps.alert(
        title="Uninstall Stem2AAF?",
        message="This removes the app, its settings, its login-item entry, and finally "
                "this Uninstaller itself.\n\nYour project folder and any .wav/.aaf files "
                "in it are NOT touched - only the app's own code and settings are removed.",
        ok="Uninstall",
        cancel="Cancel",
    )
    if confirmed != 1:
        return

    _quit_main_app_if_running()
    _remove_login_item()
    shutil.rmtree(config.CONFIG_DIR, ignore_errors=True)

    removed_app = False
    if os.path.isdir(MAIN_APP_PATH):
        shutil.rmtree(MAIN_APP_PATH, ignore_errors=True)
        removed_app = not os.path.isdir(MAIN_APP_PATH)

    if removed_app:
        # This Uninstaller lives inside Stem2AAF.app's own Resources
        # folder, so removing that app above already took this along
        # with it - there's nothing left to separately clean up.
        message = "Stem2AAF has been removed, along with this Uninstaller."
    else:
        message = (
            f"Its settings were removed, but the app itself wasn't found at "
            f"{MAIN_APP_PATH} - if you installed it somewhere else, delete "
            "it manually from there.\n\nThis Uninstaller will remove itself in a few seconds."
        )

    rumps.alert(title="Uninstall complete", message=message, ok="OK")

    _self_delete()


if __name__ == "__main__":
    main()
