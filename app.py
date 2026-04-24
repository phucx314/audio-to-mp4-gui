"""
app.py — _BaseApp mixin: all UI-building and event-handling logic.

The concrete App class (with the correct Tk base) is assembled in main_gui.py
after the tkinterdnd2 probe has run. This file has zero circular dependencies.
"""

import os
import platform
import queue
import subprocess
import threading
from tkinter import filedialog, colorchooser

import customtkinter as ctk

from constants import (
    APP_TITLE, WIN_W, WIN_H,
    ACCENT, BG_CARD, BG_MAIN, BG_DROP, TEXT_DIM,
)
from widgets import FileRow, ConflictDialog
from pipeline import AUDIO_EXTENSIONS, get_default_output_dir, process_file
import dnd_support


# ══════════════════════════════════════════════════════════════════════════════
class _BaseApp:
    """Mixin with all UI-building and application logic."""

    def _init_app(self):
        self.title(APP_TITLE)
        self.geometry(f"{WIN_W}x{WIN_H}")
        self.minsize(820, 560)
        try:
            self.configure(bg=BG_MAIN)
        except Exception:
            pass

        self._rows:             list[FileRow]  = []
        self._log_q:            queue.Queue    = queue.Queue()
        self._running:          bool           = False
        self._cancel_requested: bool           = False
        self._bg_color:         str            = "#171717"
        self._style             = ctk.StringVar(value="Style 1")
        self._output_dir        = ctk.StringVar(value=get_default_output_dir())

        self._build_ui()
        self._poll_log()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=58)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="  \U0001f3b5 Audio \u2192 MP4 Converter",
                     font=("Inter", 20, "bold"), text_color="white"
                     ).pack(side="left", padx=12)
        ctk.CTkLabel(hdr, text="Gen PNG  \u2192  Standardize Name  \u2192  Export MP4",
                     font=("Inter", 12), text_color=TEXT_DIM
                     ).pack(side="left", padx=4)

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

        icon_lbl = ctk.CTkLabel(self._drop_zone, text="\U0001f3b5",
                                 font=("Segoe UI Emoji", 40), cursor="hand2")
        icon_lbl.pack(pady=(20, 4))
        icon_lbl.bind("<Button-1>", lambda e: self._pick_files())

        dnd_prefix = "Drag & Drop  or  " if dnd_support.DND_AVAILABLE else ""
        main_lbl = ctk.CTkLabel(
            self._drop_zone,
            text=f"{dnd_prefix}Click to browse files",
            font=("Inter", 13), text_color=TEXT_DIM, cursor="hand2")
        main_lbl.pack()
        main_lbl.bind("<Button-1>", lambda e: self._pick_files())

        ctk.CTkLabel(
            self._drop_zone,
            text="mp3  \u00b7  m4a  \u00b7  aac  \u00b7  wav  \u00b7  amr  \u00b7  mid  \u00b7  "
                 "3ga  \u00b7  ogg  \u00b7  flac  \u00b7  wma",
            font=("Inter", 10), text_color="#444466"
        ).pack(pady=(2, 0))

        if dnd_support.DND_AVAILABLE:
            self._drop_zone.after_idle(self._register_dnd_recursive, self._drop_zone)

    def _build_queue(self, parent):
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.grid(row=1, column=0, sticky="nsew")
        top.columnconfigure(0, weight=1)
        top.rowconfigure(1, weight=1)

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
        self._queue_frame.after_idle(self._bind_scroll_recursive, self._queue_frame)

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
                     text_color=TEXT_DIM).grid(row=2, column=0, sticky="w", padx=12)

        self._log_box = ctk.CTkTextbox(
            pf, height=120, font=("Courier", 10),
            fg_color="#0d0d1a", text_color="#aaaacc",
            corner_radius=6, state="disabled")
        self._log_box.grid(row=3, column=0, sticky="ew", padx=12, pady=(2, 12))

    def _build_settings(self, parent):
        parent.columnconfigure(0, weight=1)
        r = 0

        ctk.CTkLabel(parent, text="Settings",
                     font=("Inter", 16, "bold"), text_color="white"
                     ).grid(row=r, column=0, sticky="w", padx=18, pady=(18, 10)); r += 1

        self._sec(parent, "PNG Style", r); r += 1
        ctk.CTkSegmentedButton(
            parent, values=["Style 1", "Style 2"],
            variable=self._style, font=("Inter", 12)
        ).grid(row=r, column=0, sticky="ew", padx=18, pady=(4, 14)); r += 1

        self._sec(parent, "Background Color", r); r += 1
        self._color_btn = ctk.CTkButton(
            parent, text="  #171717",
            fg_color="#171717", border_width=1, border_color="#333355",
            font=("Inter", 12), command=self._pick_color)
        self._color_btn.grid(row=r, column=0, sticky="ew", padx=18, pady=(4, 14)); r += 1

        self._sec(parent, "Output Folder", r); r += 1
        out_row = ctk.CTkFrame(parent, fg_color="transparent")
        out_row.grid(row=r, column=0, sticky="ew", padx=18, pady=(4, 2)); r += 1
        out_row.columnconfigure(0, weight=1)

        ctk.CTkEntry(out_row, textvariable=self._output_dir, font=("Inter", 11)
                     ).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(out_row, text="\U0001f4c1", width=36,
                      fg_color=BG_MAIN, hover_color="#2a2a3e",
                      command=self._pick_output_dir
                      ).grid(row=0, column=1, padx=(6, 0))

        ctk.CTkLabel(parent, text="Default: ~/Documents/Audio/output",
                     font=("Inter", 10), text_color="#555577"
                     ).grid(row=r, column=0, sticky="w", padx=18, pady=(0, 14)); r += 1

        ctk.CTkFrame(parent, height=1, fg_color="#2e2e50"
                     ).grid(row=r, column=0, sticky="ew", padx=18, pady=8); r += 1

        self._start_btn = ctk.CTkButton(
            parent, text="\u25b6  Start Processing",
            height=46, corner_radius=10, fg_color=ACCENT,
            font=("Inter", 14, "bold"), command=self._start_processing)
        self._start_btn.grid(row=r, column=0, sticky="ew", padx=18, pady=(8, 6)); r += 1

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
                     text_color=TEXT_DIM).grid(row=row, column=0, sticky="w", padx=18)

    # ── DnD helpers ───────────────────────────────────────────────────────────

    def _register_dnd_recursive(self, widget):
        """Register widget and all descendants as DnD drop targets."""
        try:
            widget.drop_target_register(dnd_support.DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._register_dnd_recursive(child)

    def _bind_scroll_recursive(self, widget):
        """Bind mouse-wheel on widget tree to scroll the queue frame."""
        canvas = getattr(self._queue_frame, '_parent_canvas', None)
        if canvas is None:
            return

        def _linux(event):
            canvas.yview_scroll(-1 if event.num == 4 else 1, 'units')

        def _win(event):
            canvas.yview_scroll(int(-event.delta / 120), 'units')

        def _bind_one(w):
            w.bind('<Button-4>',   _linux, add='+')
            w.bind('<Button-5>',   _linux, add='+')
            w.bind('<MouseWheel>', _win,   add='+')
            for child in w.winfo_children():
                _bind_one(child)

        _bind_one(widget)

    # ── Conflict resolver ─────────────────────────────────────────────────────

    def _conflict_resolver(self, existing_path: str, source_path: str) -> str:
        """Block worker thread; show ConflictDialog on main thread."""
        event         = threading.Event()
        result_holder = ["overwrite"]

        def _show():
            ConflictDialog(self, existing_path, source_path, result_holder, event)

        self.after(0, _show)
        event.wait()
        return result_holder[0]

    # ── File management ───────────────────────────────────────────────────────

    def _parse_dnd_paths(self, data: str) -> list:
        paths, data, i = [], data.strip(), 0
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
                ("All files", "*.*"),
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
                text=f"{total} file(s)  \u00b7  {done} done  \u00b7  {errs} error(s)")

    # ── Settings callbacks ────────────────────────────────────────────────────

    def _pick_color(self):
        c = colorchooser.askcolor(color=self._bg_color, title="PNG Background Color")[1]
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
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    # ── Processing ────────────────────────────────────────────────────────────

    def _start_processing(self):
        pending = [r for r in self._rows if r._status in ("pending", "error", "skipped")]
        if not pending:
            self._log("No pending files to process.")
            return
        if self._running:
            return
        self._running          = True
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
                    conflict_resolver=self._conflict_resolver,
                )
                status = result["status"]
                self.after(0, row.set_status, status)
                self.after(0, self._set_progress, idx + 1, total)
            else:
                self._log("\n\u2705 All done!")
            self.after(0, self._finish)

        threading.Thread(target=worker, daemon=True).start()

    def _cancel_processing(self):
        self._cancel_requested = True
        self._start_btn.configure(state="disabled", text="Cancelling\u2026")

    def _set_progress(self, done: int, total: int):
        self._progress.set(done / total if total else 0)
        self._prog_lbl.configure(text=f"{done} / {total}")
        self._update_stats()

    def _finish(self):
        self._running          = False
        self._cancel_requested = False
        self._start_btn.configure(
            state="normal", text="\u25b6  Start Processing",
            fg_color=ACCENT, hover_color="#3d7ae0",
            command=self._start_processing)

    # ── Log ───────────────────────────────────────────────────────────────────

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
            pass
        finally:
            self.after(100, self._poll_log)
