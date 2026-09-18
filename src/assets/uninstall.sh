#!/bin/bash
# Stem2AAF uninstaller.
#
# Launched detached by the app's own "Uninstall Stem2AAF..." menu item,
# which shows the confirmation dialog first and then quits. Running
# detached is what lets this delete the very app bundle it lives inside:
# by the time the deletion happens, the app has exited and this script is
# the only thing still running.
#
# This replaces a second full .app that used to be built by its own
# py2app run purely to show one dialog and delete two folders, at a cost
# of about 20 MB inside every copy of Stem2AAF.app.
#
# Usage (the app passes these):
#   uninstall.sh <app-bundle-path> <config-dir> <launch-agent-plist>
#
# The user's project folder and their .wav/.aaf files are never touched.

APP_PATH="${1:-}"
CONFIG_DIR="${2:-}"
LAUNCH_AGENT="${3:-}"

BUNDLE_ID="com.local.stem2aaf"

notify() {
    /usr/bin/osascript -e "display dialog \"$1\" buttons {\"OK\"} default button \"OK\" with title \"Stem2AAF\"" \
        >/dev/null 2>&1
}

# Wait for the app to actually exit before deleting its files. It was told
# to quit just before this script started, but "told to quit" and "gone"
# aren't the same instant, and pulling the bundle out from under a still
# running process is how you get a half-removed install.
for _ in $(seq 1 50); do
    /usr/bin/pgrep -f "$BUNDLE_ID" >/dev/null 2>&1 || break
    sleep 0.2
done
sleep 0.5

# Login item first, so launchd can't relaunch the app we're removing.
if [ -n "$LAUNCH_AGENT" ] && [ -f "$LAUNCH_AGENT" ]; then
    /bin/launchctl unload "$LAUNCH_AGENT" >/dev/null 2>&1
    rm -f "$LAUNCH_AGENT"
fi

if [ -n "$CONFIG_DIR" ] && [ -d "$CONFIG_DIR" ]; then
    rm -rf "$CONFIG_DIR"
fi

# Older installs put a separate Uninstaller app next to the main one.
# Clean it up too, so upgrading from one of those doesn't leave a dead
# icon in Launchpad pointing at an app that no longer exists.
rm -rf "/Applications/Stem2AAF Uninstaller.app" 2>/dev/null

removed="no"
if [ -n "$APP_PATH" ] && [ -d "$APP_PATH" ]; then
    rm -rf "$APP_PATH"
    [ -d "$APP_PATH" ] || removed="yes"
fi

if [ "$removed" = "yes" ]; then
    notify "Stem2AAF has been removed.\n\nYour project folder and its .wav/.aaf files were left untouched."
else
    notify "Stem2AAF's settings and login item were removed, but the app itself could not be deleted from:\n\n$APP_PATH\n\nDrag it to the Trash to finish removing it."
fi
