"""Launcher: `python run.py` from a source checkout, and the PyInstaller entry point.

When running as a frozen exe that was double-clicked, the console window
would vanish on error before anyone could read it, so wait for Enter first.
"""

import sys
import traceback

from bufferradio.__main__ import cli

if getattr(sys, "frozen", False) and len(sys.argv) == 1:
    sys.argv.append("--web")  # the exe was double-clicked: open the web page

try:
    cli()
    code = 0
except SystemExit as exc:
    code = exc.code or 0
except Exception:
    traceback.print_exc()
    code = 1

if code and getattr(sys, "frozen", False):
    input("\nPress Enter to close...")
sys.exit(code)
