"""
Single source of truth for the app's version.

Three different versions used to ship in one build: the About panel said
1.0.2 build 42, Info.plist's CFBundleShortVersionString said 1.0.0, and
CFBundleVersion was never set at all so it defaulted to 0.0.0. setup.py
and settings_window.py both read these constants now, so there is one
place to bump and nothing to keep in sync by hand.

VERSION is the human-facing release number (CFBundleShortVersionString).
BUILD is a monotonically increasing build counter (CFBundleVersion); it
continues from 42, the last number the About panel displayed.
"""

VERSION = "1.1.0"
BUILD = "43"
