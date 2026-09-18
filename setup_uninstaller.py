"""
Build script for the standalone Uninstaller app.

This is a SEPARATE setup.py from the main app's, deliberately - py2app
merges plist settings across all targets when multiple apps are built in
one invocation, which would make this app and the main app end up sharing
the same CFBundleName/identifier. Building them as two independent
`python3 setupX.py py2app` calls keeps them cleanly distinct. build.sh
runs both automatically - you shouldn't normally need to run this by hand.

Run this ON A MAC (py2app cannot cross-compile from Linux/Windows):

    python3 setup_uninstaller.py py2app

Note: build.sh generates uninstaller_icon.icns (from
src/assets/uninstaller_icon_source.png, via macOS's own sips/iconutil)
immediately before running this - if you're running this file directly
rather than through build.sh, generate that .icns yourself first, or
this app will fall back to a plain default icon.

The finished app appears at dist/Stem2AAF Uninstaller.app (py2app
names the output folder after CFBundleName, set below).
"""

import os

from setuptools import setup

APP = ["src/uninstaller.py"]
DATA_FILES = []
OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "LSUIElement": False,  # briefly visible in the Dock while it runs
        "CFBundleName": "Stem2AAF Uninstaller",
        "CFBundleDisplayName": "Stem2AAF Uninstaller",
        "CFBundleIdentifier": "com.local.stem2aaf-uninstaller",
        "CFBundleShortVersionString": "1.0.0",
    },
    "packages": ["rumps"],
    # Strip unused stdlib to keep the Uninstaller as lean as possible -
    # it only shows a confirmation dialog and deletes two app folders.
    "excludes": [
        "tkinter", "test", "unittest", "doctest", "pydoc", "idlelib",
        "turtle", "curses", "lib2to3", "ensurepip", "antigravity",
        "cgi", "cgitb", "ftplib", "imaplib", "nntplib", "poplib",
        "smtplib", "smtpd", "telnetlib", "xmlrpc",
        "_codecs_cn", "_codecs_hk", "_codecs_iso2022",
        "_codecs_jp", "_codecs_kr", "_codecs_tw",
    ],
}

if os.path.exists("uninstaller_icon.icns"):
    OPTIONS["iconfile"] = "uninstaller_icon.icns"

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
