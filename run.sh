#!/usr/bin/env bash
# run.sh — Launch the Audio → MP4 Converter GUI
# NOTE: Uses python3.11 (Tcl 8.6) — required for drag-and-drop (tkdnd).
#       python3.14 uses Tcl 9 which is NOT compatible with tkinterdnd2.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Wayland: force X11 backend so XDND drag-and-drop works ──
if [ -n "$WAYLAND_DISPLAY" ]; then
    export GDK_BACKEND=x11
    export QT_QPA_PLATFORM=xcb
    echo "Wayland detected → forcing X11 backend for DnD support"
fi

# Prefer python3.11 for Tcl 8.6 / tkdnd compatibility
if command -v python3.11 &>/dev/null; then
    PY=python3.11
else
    echo "Warning: python3.11 not found, falling back to python3 (drag-and-drop may not work)"
    PY=python3
fi

echo "Using $($PY --version)"
echo "Checking dependencies..."
$PY -m pip install --user -q -r requirements.txt

echo "Starting Audio → MP4 Converter..."
$PY main_gui.py
