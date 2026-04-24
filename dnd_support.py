"""
dnd_support.py — tkinterdnd2 availability probe.

Import this AFTER Wayland env-vars are set but BEFORE the main App window
is created. Exports DND_AVAILABLE, DND_FILES, and TkinterDnD so other
modules can query them without triggering circular imports.
"""

DND_AVAILABLE: bool = False
DND_FILES            = None   # tkinterdnd2.DND_FILES constant
TkinterDnD           = None   # tkinterdnd2.TkinterDnD class

try:
    import tkinterdnd2 as _tkdnd

    _TkinterDnD = _tkdnd.TkinterDnD
    _DND_FILES  = _tkdnd.DND_FILES

    # Probe: create a throw-away Tk root so the bundled .so path is
    # registered, then check that the 'tkdnd' Tcl package loads correctly.
    _probe = _TkinterDnD.Tk()
    try:
        _probe.tk.call("package", "require", "tkdnd")
        DND_AVAILABLE = True
        TkinterDnD    = _TkinterDnD
        DND_FILES     = _DND_FILES
    except Exception:
        pass
    finally:
        _probe.destroy()
        del _probe

except Exception:
    pass
