#!/bin/bash
# Run this once, in Terminal, on your Mac, from inside the project folder:
#   chmod +x build.sh && ./build.sh
#
# (Or double-click "Build Stem2AAF.applescript" instead - no Terminal needed.)
#
# Builds Stem2AAF.app with the Uninstaller bundled inside it at
# Contents/Resources/Stem2AAF Uninstaller.app, then installs both to
# /Applications. Built as two separate py2app invocations so each app gets
# its own distinct bundle identity (py2app merges plist settings when
# multiple targets share one invocation).

set -e

# Widen PATH so this still finds python3 when triggered from a minimal
# environment (e.g. AppleScript's `do shell script`), which doesn't load
# the usual shell profile and may not see a Homebrew-installed python3.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

cd "$(dirname "$0")"

if ! command -v python3 &> /dev/null; then
    echo "python3 not found. Install it from python.org or run: brew install python3"
    exit 1
fi

echo "Creating virtual environment..."
python3 -m venv venv

echo "Installing dependencies..."
venv/bin/python3 -m pip install --quiet -r requirements.txt

# Converts a source PNG into a full multi-resolution .icns file using
# macOS's built-in sips and iconutil - no extra tools needed.
# All sips resizes run in parallel (& ... wait) to save time.
make_icns() {
    local src_png="$1"
    local out_icns="$2"
    local iconset_dir="${out_icns%.icns}.iconset"
    rm -rf "$iconset_dir" "$out_icns"
    mkdir "$iconset_dir"
    sips -z 16   16   "$src_png" --out "$iconset_dir/icon_16x16.png"      >/dev/null &
    sips -z 32   32   "$src_png" --out "$iconset_dir/icon_16x16@2x.png"   >/dev/null &
    sips -z 32   32   "$src_png" --out "$iconset_dir/icon_32x32.png"      >/dev/null &
    sips -z 64   64   "$src_png" --out "$iconset_dir/icon_32x32@2x.png"   >/dev/null &
    sips -z 128  128  "$src_png" --out "$iconset_dir/icon_128x128.png"    >/dev/null &
    sips -z 256  256  "$src_png" --out "$iconset_dir/icon_128x128@2x.png" >/dev/null &
    sips -z 256  256  "$src_png" --out "$iconset_dir/icon_256x256.png"    >/dev/null &
    sips -z 512  512  "$src_png" --out "$iconset_dir/icon_256x256@2x.png" >/dev/null &
    sips -z 512  512  "$src_png" --out "$iconset_dir/icon_512x512.png"    >/dev/null &
    sips -z 1024 1024 "$src_png" --out "$iconset_dir/icon_512x512@2x.png" >/dev/null &
    wait
    iconutil -c icns "$iconset_dir" -o "$out_icns"
    rm -rf "$iconset_dir"
}

echo "Generating icons..."
make_icns "src/assets/app_icon_source.png"         "app_icon.icns"
make_icns "src/assets/uninstaller_icon_source.png" "uninstaller_icon.icns"

echo "Building Stem2AAF.app..."
venv/bin/python3 setup.py py2app

echo "Building Stem2AAF Uninstaller.app..."
rm -rf build   # py2app reuses ./build between invocations; start clean per target
venv/bin/python3 setup_uninstaller.py py2app

echo "Bundling Uninstaller inside Stem2AAF.app..."
rm -rf "dist/Stem2AAF.app/Contents/Resources/Stem2AAF Uninstaller.app"
cp -R  "dist/Stem2AAF Uninstaller.app" "dist/Stem2AAF.app/Contents/Resources/"

echo "Installing to /Applications..."
rm -rf "/Applications/Stem2AAF.app"
mv     "dist/Stem2AAF.app" /Applications/

# Also extract the Uninstaller directly to /Applications for local builds
# so it appears immediately without needing a first launch.
# DMG installs skip this - the main app extracts it automatically on first run.
rm -rf "/Applications/Stem2AAF Uninstaller.app"
cp -R  "/Applications/Stem2AAF.app/Contents/Resources/Stem2AAF Uninstaller.app" /Applications/

# Clean up leftover build artifacts
rm -f app_icon.icns uninstaller_icon.icns

echo ""
echo "BUILD_COMPLETE_OK"
echo "Done. Stem2AAF.app and Stem2AAF Uninstaller.app are in /Applications."
echo "Use \"Uninstall Stem2AAF...\" from the menu bar to remove them."
echo "First launch: right-click -> Open -> Open (to bypass the unsigned-developer warning)."
