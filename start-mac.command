#!/bin/bash
# bufferradio launcher for macOS (also works on Linux): double-click this file.
# Finds a Python 3.12+ interpreter, sets up a private environment with all
# dependencies on the first run, then starts the player.
cd "$(dirname "$0")" || exit 1
echo "=== bufferradio ==="

fail() {
    echo
    echo "$1"
    read -rp "Press Enter to close..."
    exit 1
}

# --- 1. find a Python 3.12+ interpreter ------------------------------------
PY=""
for candidate in python3.14 python3.13 python3.12 python3 \
        /opt/homebrew/bin/python3 /usr/local/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.*/bin/python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    if command -v brew >/dev/null 2>&1; then
        echo "Python 3.12+ is not installed. Installing it with Homebrew (one time)..."
        brew install python@3.13 && PY="$(brew --prefix python@3.13)/bin/python3.13"
    fi
fi
if [ -z "$PY" ] || ! "$PY" -c 'import sys' 2>/dev/null; then
    fail "Python 3.12 or newer is needed. Install it from https://www.python.org/downloads/macos/ then double-click this file again."
fi

# --- 2. private environment + dependencies (fast if already done) -----------
if [ ! -x ".venv/bin/python" ]; then
    echo "Setting up a private Python environment - one time only..."
    "$PY" -m venv .venv || fail "Could not create the Python environment."
fi
echo "Checking dependencies..."
.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt \
    || fail "Could not install dependencies - see the messages above."

# --- 3. play ------------------------------------------------------------------
echo
.venv/bin/python run.py "$@" || fail "Something went wrong - see the messages above."
