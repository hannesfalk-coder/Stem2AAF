#!/bin/bash
# Run this once, in Terminal, on your Mac, from inside the project folder:
#   chmod +x build.sh && ./build.sh
#
# (Or double-click "Build Stem2AAF.applescript" instead - no Terminal needed.)
#
# Builds Stem2AAF.app and installs it to /Applications.
#
# One py2app target. The Uninstaller used to be a second .app built from
# its own setup_uninstaller.py - a whole extra copy of Python and PyObjC,
# about 20 MB, to show one dialog and delete two folders. It is a shell
# script in Contents/Resources now (src/assets/uninstall.sh), reachable
# from the app's own "Uninstall Stem2AAF..." menu item.

set -e

# --no-install builds into dist/ and stops there, without replacing what is
# in /Applications. Useful for checking a build before committing to it.
INSTALL=1
for arg in "$@"; do
    case "$arg" in
        --no-install) INSTALL=0 ;;
        *) echo "Unknown option: $arg"; echo "Usage: ./build.sh [--no-install]"; exit 1 ;;
    esac
done

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

# --- Universal (Intel + Apple Silicon) dependencies --------------------------
#
# pip installs wheels for the machine doing the build, so a build on an
# Apple Silicon Mac produced an app whose launcher and Python framework
# were universal but whose cffi, libsndfile and watchdog binaries were
# arm64 only. macOS runs that app as x86_64 on an Intel Mac and the
# very first import fails, which made every shared .dmg dead on arrival
# there.
#
# cffi, soundfile and watchdog publish per-architecture wheels rather
# than universal2 ones, so fetch both architectures and fuse them with
# delocate. soundfile's merged wheel carries libsndfile_arm64.dylib and
# libsndfile_x86_64.dylib side by side and picks the right one at import,
# which is how that package expects to be universal.
echo "Building universal2 dependencies..."
# numpy is not in this list because it is not bundled at all - see the
# excludes in setup.py. Fusing it would mean downloading ~93 MB of OpenBLAS
# for nothing.
UNIV_PKGS=(cffi soundfile watchdog)
WHEEL_DIR="build_wheels"
rm -rf "$WHEEL_DIR"
mkdir -p "$WHEEL_DIR/arm64" "$WHEEL_DIR/x86_64" "$WHEEL_DIR/universal2"

for pkg in "${UNIV_PKGS[@]}"; do
    # Resolve to whatever version the venv already settled on, so the
    # universal build matches the versions everything else was tested with.
    ver=$(venv/bin/python3 -c "
import importlib.metadata as m
try: print(m.version('$pkg'))
except Exception: print('')
")
    [ -n "$ver" ] || { echo "  skipping $pkg (not installed)"; continue; }
    venv/bin/python3 -m pip download --quiet --no-deps --only-binary=:all: \
        --platform macosx_11_0_arm64  --python-version 3.9 \
        -d "$WHEEL_DIR/arm64"  "$pkg==$ver"
    venv/bin/python3 -m pip download --quiet --no-deps --only-binary=:all: \
        --platform macosx_10_9_x86_64 --python-version 3.9 \
        -d "$WHEEL_DIR/x86_64" "$pkg==$ver"
done

for arm_whl in "$WHEEL_DIR"/arm64/*.whl; do
    [ -e "$arm_whl" ] || continue
    stem="$(basename "$arm_whl")"; stem="${stem%%-macosx*}"
    x86_whl=$(ls "$WHEEL_DIR/x86_64/${stem}"-macosx*.whl 2>/dev/null | head -1 || true)
    if [ -n "$x86_whl" ]; then
        venv/bin/delocate-merge "$arm_whl" "$x86_whl" -w "$WHEEL_DIR/universal2" >/dev/null
    else
        echo "  WARNING: no x86_64 wheel for $stem - the app will be Apple Silicon only"
    fi
done

if ls "$WHEEL_DIR"/universal2/*.whl >/dev/null 2>&1; then
    venv/bin/python3 -m pip install --quiet --force-reinstall --no-deps \
        "$WHEEL_DIR"/universal2/*.whl
fi
rm -rf "$WHEEL_DIR"

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
make_icns "src/assets/app_icon_source.png" "app_icon.icns"

echo "Building Stem2AAF.app..."
rm -rf build dist/Stem2AAF.app
venv/bin/python3 setup.py py2app

echo "Checking the build is universal..."
# A non-universal binary here means the app will not start on an Intel
# Mac. Report it rather than discovering it from someone else's crash.
# A plain while-read loop, not xargs: passing 79 long paths through
# `xargs -I{}` overflows its command-line limit, and it reported success
# while actually having checked nothing.
#
# libsndfile is the deliberate exception. soundfile ships
# libsndfile_arm64.dylib and libsndfile_x86_64.dylib side by side and
# picks one at import, so each of those two files is single-architecture
# by design; what matters is that both are present.
non_universal=""
checked=0
while IFS= read -r binary; do
    case "$(basename "$binary")" in libsndfile_*) continue ;; esac
    checked=$((checked + 1))
    archs=$(lipo -archs "$binary" 2>/dev/null)
    case "$archs" in
        *arm64*x86_64*|*x86_64*arm64*) ;;
        *) non_universal="${non_universal}    $(basename "$binary") [$archs]"$'\n' ;;
    esac
done < <(find "dist/Stem2AAF.app" \( -name "*.so" -o -name "*.dylib" \))

for arch in arm64 x86_64; do
    if ! find "dist/Stem2AAF.app" -name "libsndfile_${arch}.dylib" | grep -q .; then
        non_universal="${non_universal}    libsndfile_${arch}.dylib is missing"$'\n'
    fi
done

if [ -n "$non_universal" ]; then
    echo "  WARNING: this build will not run on every Mac:"
    printf '%s' "$non_universal"
else
    echo "  All $checked bundled binaries are universal, and both libsndfile"
    echo "  slices are present (Intel + Apple Silicon)."
fi

if [ "$INSTALL" -eq 1 ]; then
    echo "Installing to /Applications..."
    rm -rf "/Applications/Stem2AAF.app"
    mv     "dist/Stem2AAF.app" /Applications/

    # Older installs put a separate Uninstaller app here. It has no app left
    # to uninstall now, so take it away rather than leaving a dead icon.
    rm -rf "/Applications/Stem2AAF Uninstaller.app"
fi

# Clean up leftover build artifacts
rm -f app_icon.icns

echo ""
echo "BUILD_COMPLETE_OK"
if [ "$INSTALL" -eq 1 ]; then
    echo "Done. Stem2AAF.app is in /Applications."
    echo "Use \"Uninstall Stem2AAF...\" from its menu bar icon to remove it."
    echo "First launch: right-click -> Open -> Open (to bypass the unsigned-developer warning)."
else
    echo "Done. Stem2AAF.app is in dist/ (not installed - --no-install was given)."
fi
