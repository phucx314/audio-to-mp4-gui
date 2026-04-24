"""
main_gui.py — Entry point for the Audio → MP4 Converter GUI.

Boot sequence:
  1. Force X11/XCB backend on Wayland (must happen before any Tk import).
  2. Import customtkinter and apply global theme.
  3. Import dnd_support (runs tkinterdnd2 probe).
  4. Build the correct App subclass and start the mainloop.
"""

import os
import sys
from pathlib import Path

# ── 1. Wayland → X11 shim ─────────────────────────────────────────────────────
# These MUST be set before any GUI toolkit initialises its display connection.
if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("GDK_BACKEND"):
    os.environ["GDK_BACKEND"] = "x11"
if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
    os.environ["QT_QPA_PLATFORM"] = "xcb"

# ── 2. GUI toolkit ────────────────────────────────────────────────────────────
import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── 3. Ensure gui_app/ is importable as a package ─────────────────────────────
_GUI_APP_DIR = str(Path(__file__).parent.resolve())
if _GUI_APP_DIR not in sys.path:
    sys.path.insert(0, _GUI_APP_DIR)

# ── 4. tkinterdnd2 probe (must run before App window is created) ───────────────
import dnd_support  # noqa: E402 — order matters

# ── 5. App class — base class chosen at runtime ───────────────────────────────
from app import _BaseApp  # noqa: E402

if dnd_support.DND_AVAILABLE:
    class App(dnd_support.TkinterDnD.Tk, _BaseApp):
        def __init__(self):
            dnd_support.TkinterDnD.Tk.__init__(self)
            self._init_app()
else:
    class App(ctk.CTk, _BaseApp):
        def __init__(self):
            ctk.CTk.__init__(self)
            self._init_app()


# ── 6. Run ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    App().mainloop()
