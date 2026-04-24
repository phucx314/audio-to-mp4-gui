"""
main_gui.py — Entry point for the Audio → MP4 Converter.

Boot sequence
─────────────
1. Force X11/XCB on Wayland (must happen before any Tk import).
2. Apply customtkinter global theme.
3. Ensure gui_app/ is on sys.path so package imports work.
4. Import ui.dnd_support  →  runs the tkinterdnd2 probe once.
5. Build the correct App subclass (DnD-capable or plain CTk).
6. Start the mainloop.
"""

import os
import sys
from pathlib import Path

# ── 1. Wayland shim ───────────────────────────────────────────────────────────
if os.environ.get("WAYLAND_DISPLAY"):
    os.environ.setdefault("GDK_BACKEND", "x11")
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

# ── 2. Global theme ───────────────────────────────────────────────────────────
import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── 3. Package path ───────────────────────────────────────────────────────────
_ROOT = str(Path(__file__).parent.resolve())
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ── 4. DnD probe ──────────────────────────────────────────────────────────────
import ui.dnd_support as _dnd  # probe runs at import time

# ── 5. App class ──────────────────────────────────────────────────────────────
from ui.app import _BaseApp

if _dnd.DND_AVAILABLE:
    class App(_dnd.TkinterDnD.Tk, _BaseApp):
        def __init__(self):
            _dnd.TkinterDnD.Tk.__init__(self)
            self._init_app()
else:
    class App(ctk.CTk, _BaseApp):
        def __init__(self):
            ctk.CTk.__init__(self)
            self._init_app()

# ── 6. Run ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    App().mainloop()
