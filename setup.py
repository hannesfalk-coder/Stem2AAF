"""
Build script for the standalone macOS app.

Run this ON A MAC (py2app cannot cross-compile from Linux/Windows):

    cd stem2aaf
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    python3 setup.py py2app

Note: build.sh generates app_icon.icns (from
src/assets/app_icon_source.png, via macOS's own sips/iconutil)
immediately before running this - if you're running this file directly
rather than through build.sh, generate that .icns yourself first, or
this app will fall back to a plain default icon in Finder/Spotlight/Dock
(the menu-bar tray icon it shows at runtime is unaffected either way,
since that comes from icon.png below, not this).

The finished app appears at dist/Stem2AAF.app - drag it to /Applications.

There is only one py2app target now. The Uninstaller used to be a second
.app built from its own setup_uninstaller.py; it is a shell script in
Contents/Resources these days (src/assets/uninstall.sh).
"""

import os
import sys

from setuptools import setup

sys.path.insert(0, "src")
from version import VERSION, BUILD  # noqa: E402  - src/ added to path just above

APP = ["src/app.py"]
# Places icon.png and its animation frames directly in Contents/Resources
# - matches the lookup in app.py's _find_asset_path(), which reads
# NSBundle's resourcePath(). The frames are the "Convert to AAF" progress
# animation: bars fill left to right as real work completes, then flash
# white/orange a few times on completion.
DATA_FILES = [(
    "",
    [
        # Menu-bar icon and its progress animation. icon.png (all five
        # bars orange) and icon_flash_white.png (all white) are the two
        # ends of the sequence; icon_prog_1..4 are the steps between,
        # a white logo with the N leftmost bars filled orange.
        "src/assets/icon.png",
        "src/assets/icon_prog_1.png",
        "src/assets/icon_prog_2.png",
        "src/assets/icon_prog_3.png",
        "src/assets/icon_prog_4.png",
        "src/assets/icon_flash_white.png",
        # Run by "Uninstall Stem2AAF..." in the menu. This replaced a
        # second full .app, built by its own py2app run, that existed only
        # to show one dialog and delete two folders at a cost of ~20 MB.
        "src/assets/uninstall.sh",
    ],
)]
OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "LSUIElement": True,  # menu-bar only app, no Dock icon
        "CFBundleName": "Stem2AAF",
        "CFBundleDisplayName": "Stem to AAF",
        "CFBundleIdentifier": "com.local.stem2aaf",
        "CFBundleShortVersionString": VERSION,
        # Previously unset, so every build shipped as CFBundleVersion
        # 0.0.0 while the About panel claimed something else entirely.
        "CFBundleVersion": BUILD,
    },
    # "_soundfile_data" (note the leading underscore - it's a separate,
    # independent package from "soundfile" itself, not a submodule of it)
    # is what actually matters here. soundfile.py loads its native audio
    # engine by running `import _soundfile_data` as its own statement and
    # reading THAT package's __file__ - not soundfile.py's own location -
    # to find the bundled libsndfile binary living alongside it. Without
    # this listed explicitly, py2app compresses it into the shared
    # python zip archive like any other discovered dependency, and a
    # native library can't be dlopen'd directly out of a zip - which is
    # exactly the runtime failure this was causing ("cannot load library
    # ... tried: .../python39.zip/_soundfile_data/..."). Listing it here
    # forces py2app to place it as a real, unzipped directory instead,
    # which is all soundfile actually needs - soundfile.py itself can
    # stay zipped with no effect on this.
    "packages": ["aaf2", "watchdog", "rumps", "soundfile", "_soundfile_data"],
    # Strip unused stdlib modules that py2app bundles by default.
    # Saves significant disk space without affecting any functionality.
    "excludes": [
        "tkinter", "test", "unittest", "doctest", "pydoc", "idlelib",
        "turtle", "curses", "lib2to3", "ensurepip", "antigravity",
        "cgi", "cgitb", "ftplib", "imaplib", "nntplib", "poplib",
        "smtplib", "smtpd", "telnetlib", "xmlrpc",
        # Asian-language codec modules - never needed for audio/AAF work
        "_codecs_cn", "_codecs_hk", "_codecs_iso2022",
        "_codecs_jp", "_codecs_kr", "_codecs_tw",
        # numpy is deliberately NOT bundled. soundfile only imports it
        # inside the functions that hand back arrays, and converter.py
        # uses buffer_read/buffer_write instead, which never touch it.
        #
        # Leaving it in was expensive: numpy's x86_64 wheel bundles its own
        # OpenBLAS and libgfortran, about 93 MB that the arm64 wheel does
        # not carry at all because it uses Accelerate. A universal build
        # with numpy came to 156 MB; without it the app is around 30 MB.
        #
        # If a future change calls sf.read(), sf.write() or SoundFile.blocks(),
        # that will raise ImportError in the packaged app while working fine
        # from source. tests/test_converter.py's numpy-free check guards this.
        "numpy",
        "pytest", "setuptools", "pip", "wheel",
    ],
}

if os.path.exists("app_icon.icns"):
    OPTIONS["iconfile"] = "app_icon.icns"

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
