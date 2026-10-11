"""Where things are, for the tests: the app (put on sys.path), its test
pictures, and a work folder in the system temp directory for everything a
test writes (screenshots, scratch settings, exported files)."""

import sys
import tempfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent
APP = TESTS.parent                      # the Pixel Forge folder
IMAGES = APP / "Test"                   # the pictures the tests convert
SCR = Path(tempfile.gettempdir()) / "pixel-forge-tests"   # scratch: safe to delete
SCR.mkdir(parents=True, exist_ok=True)

if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
