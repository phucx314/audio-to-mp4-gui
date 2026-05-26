"""
ui/dnd_support.py — tkinterdnd2 availability probe.

Run this AFTER Wayland env-vars are set but BEFORE the main App window
is created. Exports DND_AVAILABLE, DND_FILES, and TkinterDnD so other
ui modules can query them without triggering circular imports.
"""

import importlib.util as _ilu

DND_AVAILABLE: bool = False
DND_FILES            = None   # tkinterdnd2.DND_FILES constant
TkinterDnD           = None   # tkinterdnd2.TkinterDnD class

# Only attempt DnD if tkinterdnd2 package exists on disk.
# We do NOT import it unless the Tcl/Tk 'tkdnd' package is also present,
# because importing tkinterdnd2 can create phantom Tk windows on some
# Python 3.14 setups.
if _ilu.find_spec("tkinterdnd2") is not None:
    import tkinter as _tk

    _probe = _tk.Tk()
    _probe.withdraw()
    try:
        _probe.tk.call("package", "require", "tkdnd")
        # tkdnd Tcl package is available → safe to import tkinterdnd2
        import tkinterdnd2 as _tkdnd
        DND_AVAILABLE = True
        TkinterDnD    = _tkdnd.TkinterDnD
        DND_FILES     = _tkdnd.DND_FILES
    except Exception:
        pass
    finally:
        _probe.destroy()
        _tk._default_root = None
        del _probe
