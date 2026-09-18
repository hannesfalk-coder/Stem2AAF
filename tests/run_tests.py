#!/usr/bin/env python3
"""
Runs the whole suite with the standard library only, so no extra install is
needed beyond what the app already depends on:

    venv/bin/python3 tests/run_tests.py

pytest works too if you have it: venv/bin/python3 -m pytest tests -q
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(HERE, pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
