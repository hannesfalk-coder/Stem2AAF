#!/bin/bash
# Packages the already-built, already-installed app into a distributable
# .dmg with the familiar "drag the app onto Applications" layout - run
# this AFTER a successful build (via the AppleScript or build.sh), once
# Stem2AAF.app is sitting in /Applications. This is only needed if you
# want to share the app with someone else (e.g. as a download); it's not
# part of the normal local install flow.
#
# Only Stem2AAF.app goes in the image. Uninstalling is a menu item in the
# app itself now ("Uninstall Stem2AAF..."), backed by a script inside
# Contents/Resources, so there is no second app to ship alongside it.
#
# Usage (in Terminal, from inside this project folder):
#   chmod +x make_dmg.sh && ./make_dmg.sh

set -e
cd "$(dirname "$0")"

APP_NAME="Stem2AAF"
VOL_NAME="Stem2AAF"
DMG_NAME="Stem2AAF.dmg"
STAGING_DIR="dmg_staging"
TMP_DMG="dmg_temp.dmg"
MOUNT_DIR="/Volumes/$VOL_NAME"

if [ ! -d "/Applications/$APP_NAME.app" ]; then
    echo "Stem2AAF.app isn't in /Applications yet - build and install it first (see build.sh or the AppleScript installer)."
    exit 1
fi

echo "Staging files..."
# In case an earlier run left a mounted volume or leftover files behind.
if [ -d "$MOUNT_DIR" ]; then
    hdiutil detach "$MOUNT_DIR" -force >/dev/null 2>&1 || true
fi
rm -rf "$STAGING_DIR" "$DMG_NAME" "$TMP_DMG"
mkdir "$STAGING_DIR"
cp -R "/Applications/$APP_NAME.app" "$STAGING_DIR/"
# A symlink to /Applications inside the DMG gives the standard macOS
# "drag the app onto Applications" install gesture people expect.
ln -s /Applications "$STAGING_DIR/Applications"
# A hidden folder for the window's background image - Finder looks for
# it there when the AppleScript below points "background picture" at it.
mkdir "$STAGING_DIR/.background"
cp src/assets/dmg_background.png "$STAGING_DIR/.background/background.png"

echo "Creating a writable disk image..."
# A writable UDRW image first, so Finder can be scripted against it
# interactively below - it gets converted to the final compressed,
# read-only version at the very end.
SIZE_MB=$(( $(du -sm "$STAGING_DIR" | cut -f1) + 20 ))
hdiutil create -volname "$VOL_NAME" -srcfolder "$STAGING_DIR" -ov -fs HFS+ -format UDRW -size "${SIZE_MB}m" "$TMP_DMG"

echo "Mounting it to arrange the window..."
hdiutil attach "$TMP_DMG" -mountpoint "$MOUNT_DIR" -nobrowse

# Lays out the Finder window that appears when someone opens the DMG:
# just the app on the left and Applications on the right, with a small
# arrow (baked into background.png, since Finder has no native arrow
# element) between them - the classic, minimal "drag this onto that"
# installer look. Finder can be briefly slow to respond right after a
# volume mounts, hence the delays.
osascript <<APPLESCRIPT
tell application "Finder"
    tell disk "$VOL_NAME"
        open
        delay 1
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set the bounds of container window to {400, 100, 880, 380}
        set viewOptions to the icon view options of container window
        set arrangement of viewOptions to not arranged
        set icon size of viewOptions to 96
        set background picture of viewOptions to file ".background:background.png"
        set position of item "$APP_NAME.app" to {130, 115}
        set position of item "Applications" to {350, 115}
        close
        open
        update without registering applications
        delay 1
    end tell
end tell
APPLESCRIPT

echo "Finalizing..."
hdiutil detach "$MOUNT_DIR"
rm -f "$DMG_NAME"
hdiutil convert "$TMP_DMG" -format UDZO -o "$DMG_NAME"

rm -f "$TMP_DMG"
rm -rf "$STAGING_DIR"

echo ""
echo "DMG_COMPLETE_OK"
echo "Done. $DMG_NAME is ready in this folder - share that one file."
