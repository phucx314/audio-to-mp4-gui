"""
main_gui.py — Audio → MP4 Converter GUI
Uses customtkinter for modern dark UI.
Drag-and-drop via tkinterdnd2 (requires Tcl 8.x / python3.11).
On Wayland: GDK_BACKEND=x11 is forced automatically so XWayland
accepts the XDND protocol from file managers.
"""

import os
import sys
import time
import platform
import threading
import queue
from pathlib import Path
from tkinter import filedialog, colorchooser
import tkinter as tk

# ── Force X11 backend on Wayland so XDND drag-and-drop works ─────────────────
# Must be set BEFORE any GUI toolkit is imported.
if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("GDK_BACKEND"):
    os.environ["GDK_BACKEND"] = "x11"
if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
    os.environ["QT_QPA_PLATFORM"] = "xcb"

import customtkinter as ctk

# ── Try tkinterdnd2 ────────────────────────────────────────────────────────
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    import tkinterdnd2.TkinterDnD as _dnd_mod
    # Probe using TkinterDnD.Tk so the bundled .so path is registered first
    _r = TkinterDnD.Tk()
    try:
        _r.tk.call('package', 'require', 'tkdnd')
        _DND_AVAILABLE = True
    except Exception:
        _DND_AVAILABLE = False
    finally:
        _r.destroy()
except Exception:
    _DND_AVAILABLE = False

# ── local imports ──────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from pipeline import AUDIO_EXTENSIONS, get_default_output_dir, process_file

# ── App config ─────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_TITLE    = "Audio → MP4 Converter"
WIN_W, WIN_H = 980, 700
ACCENT       = "#4f8ef7"
ACCENT2      = "#7c3aed"
BG_CARD      = "#1e1e2e"
BG_MAIN      = "#13131f"
BG_DROP      = "#1a1a2e"
TEXT_DIM     = "#8888aa"

STATUS_COLORS = {
    "pending":    "#8888aa",
    "processing": "#f7c948",
    "done":       "#4ade80",
    "skipped":    "#64748b",
    "error":      "#f87171",
}
STATUS_ICONS = {
    "pending":    "⏳",
    "processing": "⚙",
    "done":       "✓",
    "skipped":    "⏭",
    "error":      "✕",
}


# ══════════════════════════════════════════════════════════════════════════════
class FileRow(ctk.CTkFrame):
    """Single file entry in the queue list."""

    def __init__(self, master, file_path: str, on_remove, **kw):
        super().__init__(master, fg_color=BG_CARD, corner_radius=8, **kw)
        self.file_path = file_path
        self._status = "pending"
        self.columnconfigure(1, weight=1)

        self.icon_lbl = ctk.CTkLabel(
            self, text=STATUS_ICONS["pending"], width=28,
            font=("Inter", 15, "bold"), text_color=STATUS_COLORS["pending"])
        self.icon_lbl.grid(row=0, column=0, padx=(10, 6), pady=9)

        self.name_lbl = ctk.CTkLabel(
            self, text=os.path.basename(file_path),
            anchor="w", font=("Inter", 13), text_color="white")
        self.name_lbl.grid(row=0, column=1, sticky="ew", pady=9)

        ext = os.path.splitext(file_path)[1].upper().lstrip(".")
        ctk.CTkLabel(self, text=ext, width=50,
                     font=("Inter", 11, "bold"), text_color=ACCENT
                     ).grid(row=0, column=2, padx=6)

        self.status_lbl = ctk.CTkLabel(
            self, text="Pending", width=90,
            font=("Inter", 11), text_color=STATUS_COLORS["pending"])
        self.status_lbl.grid(row=0, column=3, padx=6)

        self.rm_btn = ctk.CTkButton(
            self, text="✕", width=28, height=28,
            fg_color="transparent", text_color="#f87171",
            hover_color="#2a1e2e", font=("Inter", 13, "bold"),
            command=lambda: on_remove(self))
        self.rm_btn.grid(row=0, column=4, padx=(0, 8))

    def set_status(self, status: str):
        self._status = status
        color = STATUS_COLORS.get(status, TEXT_DIM)
        self.icon_lbl.configure(text=STATUS_ICONS.get(status, "?"),
                                text_color=color)
        self.status_lbl.configure(text=status.capitalize(), text_color=color)
        if status == "done":
            self.rm_btn.configure(state="disabled")

    def update_name(self, new_path: str):
        self.file_path = new_path
        self.name_lbl.configure(text=os.path.basename(new_path))


# ════════════════════════════════════════════════════════════════════════════════
class ConflictDialog(ctk.CTkToplevel):
    """Modal dialog shown when the output MP4 already exists.
    Blocks the caller via threading.Event until the user chooses an action."""

    def __init__(self, master, existing_path: str, source_path: str,
                 result_holder: list, event: threading.Event, **kw):
        super().__init__(master, **kw)
        self.title("File Conflict")
        self.resizable(False, False)
        self.configure(fg_color=BG_CARD)
        # Withdraw first so we can build content before showing
        self.withdraw()

        self._result_holder = result_holder
        self._event         = event

        # ── Gather file info ────────────────────────────────────────────────────
        fname       = os.path.basename(existing_path)
        exist_mtime = os.path.getmtime(existing_path)
        exist_size  = os.path.getsize(existing_path)
        src_mtime   = os.path.getmtime(source_path)
        src_size    = os.path.getsize(source_path)
        exist_newer = exist_mtime >= src_mtime

        def fmt_date(ts):
            return time.strftime("%b %d, %Y  %H:%M", time.localtime(ts))

        def fmt_size(b):
            if b < 1024:      return f"{b} B"
            if b < 1024**2:   return f"{b/1024:.1f} KB"
            if b < 1024**3:   return f"{b/1024**2:.1f} MB"
            return f"{b/1024**3:.1f} GB"

        # ── Title bar ─────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        ctk.CTkLabel(hdr, text="⚠", font=("Segoe UI Emoji", 22),
                     text_color="#f7c948").pack(side="left")
        ctk.CTkLabel(hdr, text="  File Already Exists",
                     font=("Inter", 16, "bold"),
                     text_color="white").pack(side="left")

        ctk.CTkLabel(self, text=fname, font=("Inter", 12),
                     text_color=ACCENT, wraplength=500
                     ).pack(padx=20, anchor="w")

        # Divider
        ctk.CTkFrame(self, height=1, fg_color="#2e2e50"
                     ).pack(fill="x", padx=20, pady=10)

        # ── Two-column comparison ─────────────────────────────────────────────
        cols = ctk.CTkFrame(self, fg_color="transparent")
        cols.pack(fill="x", padx=20, pady=(0, 8))
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, weight=1)

        def _info_card(col, label, icon, date_str, size_str, is_newer):
            border = "#4ade80" if is_newer else "#2e2e50"
            label_color = "#4ade80" if is_newer else TEXT_DIM
            card = ctk.CTkFrame(cols, fg_color=BG_MAIN, corner_radius=10,
                                border_width=1, border_color=border)
            card.grid(row=0, column=col, sticky="ew",
                      padx=(0, 6) if col == 0 else (6, 0))
            ctk.CTkLabel(card, text=f"{icon}  {label}",
                         font=("Inter", 11, "bold"),
                         text_color=label_color
                         ).pack(anchor="w", padx=12, pady=(10, 4))
            ctk.CTkLabel(card, text=f"\U0001f4c5  {date_str}",
                         font=("Inter", 10), text_color="white",
                         wraplength=210, justify="left"
                         ).pack(anchor="w", padx=12)
            ctk.CTkLabel(card, text=f"\U0001f4be  {size_str}",
                         font=("Inter", 10), text_color=TEXT_DIM
                         ).pack(anchor="w", padx=12, pady=(2, 4))
            if is_newer:
                ctk.CTkLabel(card, text="●  Newer",
                             font=("Inter", 10, "bold"),
                             text_color="#4ade80"
                             ).pack(anchor="w", padx=12, pady=(0, 8))
            else:
                ctk.CTkLabel(card, text="",
                             font=("Inter", 10)).pack(pady=(0, 8))

        _info_card(0, "Existing MP4",  "\U0001f4c1",
                   fmt_date(exist_mtime), fmt_size(exist_size), exist_newer)
        _info_card(1, "Source Audio",  "\U0001f3a7",
                   fmt_date(src_mtime),  fmt_size(src_size),   not exist_newer)

        # Size note — MP4 will always be larger than its source audio
        ctk.CTkLabel(
            self,
            text="\u24d8  Sizes differ: source is audio-only; MP4 output includes a video track",
            font=("Inter", 9), text_color="#555577", wraplength=500
        ).pack(padx=20, anchor="w", pady=(0, 2))

        # ── Hint text ─────────────────────────────────────────────────────
        if exist_newer:
            hint       = "Existing file is up-to-date \u2014 consider skipping."
            hint_color = "#4ade80"
        else:
            hint       = "Source is newer \u2014 consider overwriting."
            hint_color = "#f7c948"
        ctk.CTkLabel(self, text=hint, font=("Inter", 11),
                     text_color=hint_color).pack(padx=20, pady=(0, 8))

        # ── Action buttons ─────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 18))

        ctk.CTkButton(
            btn_row, text="\u23ed  Skip", width=140, height=40,
            fg_color="#2e2e50", hover_color="#3a3a60",
            text_color=TEXT_DIM, font=("Inter", 12),
            command=lambda: self._choose("skip")
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row, text="\u270f  Rename", width=140, height=40,
            fg_color=ACCENT2, hover_color="#6d28d9",
            font=("Inter", 12, "bold"),
            command=lambda: self._choose("rename")
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row, text="\u26a1  Overwrite", width=140, height=40,
            fg_color="#dc2626", hover_color="#b91c1c",
            font=("Inter", 12, "bold"),
            command=lambda: self._choose("overwrite")
        ).pack(side="left")

        # Closing the window counts as Skip
        self.protocol("WM_DELETE_WINDOW", lambda: self._choose("skip"))

        # Force layout calculation, then show + grab after a short delay
        self.update_idletasks()
        self.deiconify()
        self.after(200, self._post_show)

    def _post_show(self):
        """Deferred: raise window and grab input after rendering is done."""
        self.lift()
        self.focus_force()
        try:
            self.grab_set()
        except Exception:
            pass

    def _choose(self, action: str):
        self._result_holder[0] = action
        self._event.set()
        self.destroy()


# ══════════════════════════════════════════════════════════════════════════════
class _BaseApp:
    """Mixin with all the UI + logic. Separated so we can choose Tk base class."""

    def _init_app(self):
        self.title(APP_TITLE)
        self.geometry(f"{WIN_W}x{WIN_H}")
        self.minsize(820, 560)
        try:
            self.configure(bg=BG_MAIN)
        except Exception:
            pass

        self._rows: list[FileRow] = []
        self._log_q: queue.Queue = queue.Queue()
        self._running = False
        self._cancel_requested = False
        self._bg_color = "#171717"
        self._style = ctk.StringVar(value="Style 1")
        self._output_dir = ctk.StringVar(value=get_default_output_dir())

        self._build_ui()
        self._poll_log()

    # ── UI ─────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=58)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="  🎵 Audio → MP4 Converter",
                     font=("Inter", 20, "bold"), text_color="white"
                     ).pack(side="left", padx=12)
        ctk.CTkLabel(hdr,
                     text="Gen PNG  →  Standardize Name  →  Export MP4",
                     font=("Inter", 12), text_color=TEXT_DIM
                     ).pack(side="left", padx=4)

        # Body 2-column
        body = ctk.CTkFrame(self, fg_color=BG_MAIN, corner_radius=0)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, minsize=290)
        body.rowconfigure(0, weight=1)

        left = ctk.CTkFrame(body, fg_color=BG_MAIN, corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew", padx=(14, 6), pady=14)
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        self._build_drop_zone(left)
        self._build_queue(left)
        self._build_progress(left)

        right = ctk.CTkFrame(body, fg_color=BG_CARD, corner_radius=14)
        right.grid(row=0, column=1, sticky="nsew", padx=(0, 14), pady=14)
        self._build_settings(right)

    def _register_dnd_recursive(self, widget):
        """Register widget AND all descendants as DnD drop targets."""
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._register_dnd_recursive(child)

    def _conflict_resolver(self, existing_path: str, source_path: str) -> str:
        """Called from the worker thread.
        Shows ConflictDialog on the main thread, blocks until user chooses.
        Returns 'skip' | 'rename' | 'overwrite'."""
        event         = threading.Event()
        result_holder = ["overwrite"]  # safe default

        def _show():
            ConflictDialog(self, existing_path, source_path,
                           result_holder, event)

        self.after(0, _show)
        event.wait()
        return result_holder[0]

    def _bind_scroll_recursive(self, widget):
        """Bind mouse-wheel events on widget and all children so they scroll
        the queue CTkScrollableFrame regardless of which child the cursor is on.
        Linux uses Button-4/Button-5; Windows/Mac use MouseWheel."""
        # Resolve the internal canvas of CTkScrollableFrame
        canvas = getattr(self._queue_frame, '_parent_canvas', None)
        if canvas is None:
            return

        def _on_wheel_linux(event):
            canvas.yview_scroll(-1 if event.num == 4 else 1, 'units')

        def _on_wheel_win(event):
            canvas.yview_scroll(int(-event.delta / 120), 'units')

        def _bind_one(w):
            w.bind('<Button-4>', _on_wheel_linux, add='+')
            w.bind('<Button-5>', _on_wheel_linux, add='+')
            w.bind('<MouseWheel>', _on_wheel_win, add='+')
            for child in w.winfo_children():
                _bind_one(child)

        _bind_one(widget)

    def _build_drop_zone(self, parent):
        self._drop_zone = ctk.CTkFrame(
            parent, fg_color=BG_DROP, corner_radius=14,
            border_width=2, border_color="#2e2e50", height=148)
        self._drop_zone.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self._drop_zone.pack_propagate(False)
        self._drop_zone.bind("<Button-1>", lambda e: self._pick_files())
        self._drop_zone.bind("<Enter>",
            lambda e: self._drop_zone.configure(border_color=ACCENT))
        self._drop_zone.bind("<Leave>",
            lambda e: self._drop_zone.configure(border_color="#2e2e50"))

        icon = ctk.CTkLabel(self._drop_zone, text="🎵",
                            font=("Segoe UI Emoji", 40), cursor="hand2")
        icon.pack(pady=(20, 4))
        icon.bind("<Button-1>", lambda e: self._pick_files())

        dnd_status = "Drag & Drop  or  " if _DND_AVAILABLE else ""
        main_lbl = ctk.CTkLabel(
            self._drop_zone,
            text=f"{dnd_status}Click to browse files",
            font=("Inter", 13), text_color=TEXT_DIM, cursor="hand2")
        main_lbl.pack()
        main_lbl.bind("<Button-1>", lambda e: self._pick_files())

        ctk.CTkLabel(
            self._drop_zone,
            text="mp3  ·  m4a  ·  aac  ·  wav  ·  amr  ·  mid  ·  "
                 "3ga  ·  ogg  ·  flac  ·  wma",
            font=("Inter", 10), text_color="#444466"
        ).pack(pady=(2, 0))

        # Register DnD on drop zone + all its children (prevents block cursor)
        # Use after_idle so all child widgets are fully created first
        if _DND_AVAILABLE:
            self._drop_zone.after_idle(self._register_dnd_recursive,
                                       self._drop_zone)

    def _build_queue(self, parent):
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.grid(row=1, column=0, sticky="nsew")
        top.columnconfigure(0, weight=1)
        top.rowconfigure(1, weight=1)

        # Label row
        lrow = ctk.CTkFrame(top, fg_color="transparent")
        lrow.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        lrow.columnconfigure(0, weight=1)

        ctk.CTkLabel(lrow, text="File Queue",
                     font=("Inter", 13, "bold"), text_color="white"
                     ).grid(row=0, column=0, sticky="w")
        self._clear_btn = ctk.CTkButton(
            lrow, text="Clear All", width=80, height=26,
            fg_color="transparent", border_width=1,
            border_color="#444466", text_color=TEXT_DIM,
            hover_color="#2a2a3e", font=("Inter", 11),
            command=self._clear_all)
        self._clear_btn.grid(row=0, column=1, sticky="e")

        self._queue_frame = ctk.CTkScrollableFrame(
            top, fg_color=BG_MAIN, corner_radius=8)
        self._queue_frame.grid(row=1, column=0, sticky="nsew")
        self._queue_frame.columnconfigure(0, weight=1)
        # Bind scroll wheel on the frame itself so it works out of the box
        self._queue_frame.after_idle(self._bind_scroll_recursive,
                                     self._queue_frame)

    def _build_progress(self, parent):
        pf = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=10)
        pf.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        pf.columnconfigure(0, weight=1)

        top_row = ctk.CTkFrame(pf, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        top_row.columnconfigure(0, weight=1)

        ctk.CTkLabel(top_row, text="Progress",
                     font=("Inter", 12, "bold"), text_color="white"
                     ).grid(row=0, column=0, sticky="w")
        self._prog_lbl = ctk.CTkLabel(
            top_row, text="0 / 0", font=("Inter", 11), text_color=TEXT_DIM)
        self._prog_lbl.grid(row=0, column=1, sticky="e")

        self._progress = ctk.CTkProgressBar(
            pf, height=8, corner_radius=4, progress_color=ACCENT)
        self._progress.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        self._progress.set(0)

        ctk.CTkLabel(pf, text="Log", font=("Inter", 11, "bold"),
                     text_color=TEXT_DIM
                     ).grid(row=2, column=0, sticky="w", padx=12)

        self._log_box = ctk.CTkTextbox(
            pf, height=120, font=("Courier", 10),
            fg_color="#0d0d1a", text_color="#aaaacc",
            corner_radius=6, state="disabled")
        self._log_box.grid(row=3, column=0, sticky="ew",
                           padx=12, pady=(2, 12))

    def _build_settings(self, parent):
        parent.columnconfigure(0, weight=1)
        r = 0

        ctk.CTkLabel(parent, text="Settings",
                     font=("Inter", 16, "bold"), text_color="white"
                     ).grid(row=r, column=0, sticky="w", padx=18, pady=(18, 10))
        r += 1

        # PNG style
        self._sec(parent, "PNG Style", r); r += 1
        seg = ctk.CTkSegmentedButton(
            parent, values=["Style 1", "Style 2"],
            variable=self._style, font=("Inter", 12))
        seg.grid(row=r, column=0, sticky="ew", padx=18, pady=(4, 14)); r += 1

        # Background color
        self._sec(parent, "Background Color", r); r += 1
        self._color_btn = ctk.CTkButton(
            parent, text="  #171717",
            fg_color="#171717", border_width=1, border_color="#333355",
            font=("Inter", 12), command=self._pick_color)
        self._color_btn.grid(row=r, column=0, sticky="ew",
                             padx=18, pady=(4, 14)); r += 1

        # Output folder
        self._sec(parent, "Output Folder", r); r += 1
        out_row = ctk.CTkFrame(parent, fg_color="transparent")
        out_row.grid(row=r, column=0, sticky="ew", padx=18, pady=(4, 2)); r += 1
        out_row.columnconfigure(0, weight=1)

        self._out_entry = ctk.CTkEntry(
            out_row, textvariable=self._output_dir, font=("Inter", 11))
        self._out_entry.grid(row=0, column=0, sticky="ew")

        ctk.CTkButton(out_row, text="📁", width=36,
                      fg_color=BG_MAIN, hover_color="#2a2a3e",
                      command=self._pick_output_dir
                      ).grid(row=0, column=1, padx=(6, 0))

        ctk.CTkLabel(parent, text="Default: ~/Documents/Audio/output",
                     font=("Inter", 10), text_color="#555577"
                     ).grid(row=r, column=0, sticky="w", padx=18, pady=(0, 14))
        r += 1

        # Separator
        ctk.CTkFrame(parent, height=1, fg_color="#2e2e50"
                     ).grid(row=r, column=0, sticky="ew", padx=18, pady=8)
        r += 1

        # Buttons
        self._start_btn = ctk.CTkButton(
            parent, text="\u25b6  Start Processing",
            height=46, corner_radius=10, fg_color=ACCENT,
            font=("Inter", 14, "bold"), command=self._start_processing)
        self._start_btn.grid(row=r, column=0, sticky="ew",
                             padx=18, pady=(8, 6)); r += 1

        ctk.CTkButton(
            parent, text="Open Output Folder",
            height=36, corner_radius=10,
            fg_color="transparent", border_width=1,
            border_color="#444466", text_color=TEXT_DIM,
            hover_color="#2a2a3e", font=("Inter", 12),
            command=self._open_output_folder
        ).grid(row=r, column=0, sticky="ew", padx=18, pady=(0, 6)); r += 1

        self._stats_lbl = ctk.CTkLabel(
            parent, text="No files added yet",
            font=("Inter", 11), text_color=TEXT_DIM)
        self._stats_lbl.grid(row=r, column=0, padx=18, pady=(8, 0))

    def _sec(self, parent, text, row):
        ctk.CTkLabel(parent, text=text, font=("Inter", 12, "bold"),
                     text_color=TEXT_DIM
                     ).grid(row=row, column=0, sticky="w", padx=18)

    # ── File management ────────────────────────────────────────────────────
    def _parse_dnd_paths(self, data: str) -> list:
        paths = []
        data = data.strip()
        i = 0
        while i < len(data):
            if data[i] == '{':
                end = data.index('}', i)
                paths.append(data[i+1:end])
                i = end + 2
            else:
                end = data.find(' ', i)
                if end == -1:
                    paths.append(data[i:])
                    break
                paths.append(data[i:end])
                i = end + 1
        return paths

    def _on_drop(self, event):
        for p in self._parse_dnd_paths(event.data):
            self._add_file(p)

    def _pick_files(self):
        files = filedialog.askopenfilenames(
            title="Select audio files",
            filetypes=[
                ("Audio files",
                 "*.mp3 *.m4a *.aac *.wav *.amr *.mid *.3ga *.3gp "
                 "*.wma *.awb *.ogg *.flac"),
                ("All files", "*.*")
            ])
        for f in files:
            self._add_file(f)

    def _add_file(self, path: str):
        if not os.path.isfile(path):
            return
        if os.path.splitext(path)[1].lower() not in AUDIO_EXTENSIONS:
            self._log(f"Skipped (unsupported): {os.path.basename(path)}")
            return
        if path in [r.file_path for r in self._rows]:
            return
        row = FileRow(self._queue_frame, path, on_remove=self._remove_row)
        row.pack(fill="x", pady=3, padx=4)
        self._rows.append(row)
        # Bind scroll on new row and its children so wheel works over them too
        row.after_idle(self._bind_scroll_recursive, row)
        self._update_stats()

    def _remove_row(self, row: FileRow):
        if self._running:
            return
        row.pack_forget()
        row.destroy()
        self._rows.remove(row)
        self._update_stats()

    def _clear_all(self):
        if self._running:
            return
        for row in list(self._rows):
            row.pack_forget()
            row.destroy()
        self._rows.clear()
        self._progress.set(0)
        self._prog_lbl.configure(text="0 / 0")
        self._update_stats()

    def _update_stats(self):
        total = len(self._rows)
        done  = sum(1 for r in self._rows if r._status == "done")
        errs  = sum(1 for r in self._rows if r._status == "error")
        if total == 0:
            self._stats_lbl.configure(text="No files added yet")
        else:
            self._stats_lbl.configure(
                text=f"{total} file(s)  ·  {done} done  ·  {errs} error(s)")

    # ── Settings ──────────────────────────────────────────────────────────
    def _pick_color(self):
        c = colorchooser.askcolor(color=self._bg_color,
                                  title="PNG Background Color")[1]
        if c:
            self._bg_color = c
            self._color_btn.configure(text=f"  {c}", fg_color=c)

    def _pick_output_dir(self):
        d = filedialog.askdirectory(title="Select Output Folder")
        if d:
            self._output_dir.set(d)

    def _open_output_folder(self):
        path = self._output_dir.get()
        os.makedirs(path, exist_ok=True)
        system = platform.system()
        if system == "Windows":
            os.startfile(path)
        elif system == "Darwin":
            import subprocess; subprocess.Popen(["open", path])
        else:
            import subprocess; subprocess.Popen(["xdg-open", path])

    # ── Processing ────────────────────────────────────────────────────────
    def _start_processing(self):
        pending = [r for r in self._rows if r._status in ("pending", "error", "skipped")]
        if not pending:
            self._log("No pending files to process.")
            return
        if self._running:
            return
        self._running = True
        self._cancel_requested = False
        self._start_btn.configure(
            text="\u23f9  Stop", fg_color="#991b1b",
            hover_color="#7f1d1d", command=self._cancel_processing)

        out_dir  = self._output_dir.get()
        png_tmp  = os.path.join(out_dir, "_png_tmp")
        style    = self._style.get()
        bg_color = self._bg_color

        def worker():
            total = len(pending)
            for idx, row in enumerate(pending):
                if self._cancel_requested:
                    self._log("\n\u23f9 Processing cancelled by user.")
                    break
                self.after(0, row.set_status, "processing")
                self._log(f"\n\u2500\u2500 [{idx+1}/{total}] {os.path.basename(row.file_path)}")
                result = process_file(
                    row.file_path, out_dir, png_tmp,
                    style, bg_color, self._log,
                    conflict_resolver=self._conflict_resolver
                )
                if result["status"] == "done":
                    self.after(0, row.set_status, "done")
                elif result["status"] == "skipped":
                    self.after(0, row.set_status, "skipped")
                else:
                    self.after(0, row.set_status, "error")
                self.after(0, self._set_progress, idx + 1, total)
            else:
                self._log("\n\u2705 All done!")
            self.after(0, self._finish)

        threading.Thread(target=worker, daemon=True).start()

    def _cancel_processing(self):
        """Request cancellation — worker will stop before the next file."""
        self._cancel_requested = True
        self._start_btn.configure(state="disabled", text="Cancelling\u2026")

    def _set_progress(self, done: int, total: int):
        self._progress.set(done / total if total else 0)
        self._prog_lbl.configure(text=f"{done} / {total}")
        self._update_stats()

    def _finish(self):
        self._running = False
        self._cancel_requested = False
        self._start_btn.configure(
            state="normal", text="\u25b6  Start Processing",
            fg_color=ACCENT, hover_color="#3d7ae0",
            command=self._start_processing)

    # ── Log ───────────────────────────────────────────────────────────────
    def _log(self, msg: str):
        self._log_q.put(msg)

    def _poll_log(self):
        try:
            while True:
                msg = self._log_q.get_nowait()
                self._log_box.configure(state="normal")
                self._log_box.insert("end", msg + "\n")
                self._log_box.see("end")
                self._log_box.configure(state="disabled")
        except queue.Empty:
            pass
        except Exception:
            pass  # Don't crash the polling loop (e.g. widget destroyed)
        finally:
            self.after(100, self._poll_log)


# ══════════════════════════════════════════════════════════════════════════════
# Choose base class at runtime depending on DnD availability

if _DND_AVAILABLE:
    class App(TkinterDnD.Tk, _BaseApp):
        def __init__(self):
            TkinterDnD.Tk.__init__(self)
            self._init_app()
else:
    # DnD not available (e.g. Python 3.14 / Tcl 9) — use plain CTk
    class App(ctk.CTk, _BaseApp):
        def __init__(self):
            ctk.CTk.__init__(self)
            self._init_app()


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = App()
    app.mainloop()
