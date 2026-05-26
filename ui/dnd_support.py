"""
ui/dnd_support.py — tkinterdnd2 availability probe.

Run this AFTER Wayland env-vars are set but BEFORE the main App window
is created. Exports DND_AVAILABLE, DND_FILES, and TkinterDnD so other
ui modules can query them without triggering circular imports.
"""

DND_AVAILABLE: bool = False
DND_FILES            = None   # tkinterdnd2.DND_FILES constant
TkinterDnD           = None   # tkinterdnd2.TkinterDnD class

try:
    import tkinterdnd2 as _tkdnd
    import tkinter as _tk_probe

    _cls        = _tkdnd.TkinterDnD
    _files_const = _tkdnd.DND_FILES

    _probe = _cls.Tk()
    _probe.withdraw()  # hide immediately — prevents blank flash on startup
    try:
        _probe.tk.call("package", "require", "tkdnd")
        DND_AVAILABLE = True
        TkinterDnD    = _cls
        DND_FILES     = _files_const
    except Exception:
        pass
    finally:
        _probe.destroy()
        # Python 3.14: probe.destroy() clears _default_root.
        # We explicitly set to None so _init_app knows to re-set it.
        _tk_probe._default_root = None
        del _probe, _tk_probe

except Exception:
    pass
