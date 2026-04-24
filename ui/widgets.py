"""
ui/widgets.py — Reusable CTk widgets: FileRow and ConflictDialog.
"""

import os
import time
import threading

import customtkinter as ctk

from ui.theme import (
    ACCENT, ACCENT2, BG_CARD, BG_MAIN, TEXT_DIM,
    STATUS_COLORS, STATUS_ICONS,
)


# ══════════════════════════════════════════════════════════════════════════════
class FileRow(ctk.CTkFrame):
    """Single file entry shown in the queue list."""

    def __init__(self, master, file_path: str, on_remove, **kw):
        super().__init__(master, fg_color=BG_CARD, corner_radius=8, **kw)
        self.file_path = file_path
        self._status   = "pending"
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
            self, text="\u2715", width=28, height=28,
            fg_color="transparent", text_color="#f87171",
            hover_color="#2a1e2e", font=("Inter", 13, "bold"),
            command=lambda: on_remove(self))
        self.rm_btn.grid(row=0, column=4, padx=(0, 8))

    def set_status(self, status: str):
        self._status = status
        color = STATUS_COLORS.get(status, TEXT_DIM)
        self.icon_lbl.configure(text=STATUS_ICONS.get(status, "?"), text_color=color)
        self.status_lbl.configure(text=status.capitalize(), text_color=color)
        if status == "done":
            self.rm_btn.configure(state="disabled")

    def update_name(self, new_path: str):
        self.file_path = new_path
        self.name_lbl.configure(text=os.path.basename(new_path))


# ══════════════════════════════════════════════════════════════════════════════
class ConflictDialog(ctk.CTkToplevel):
    """
    Modal dialog shown when the output MP4 already exists.
    Blocks the caller via threading.Event until the user picks an action.
    """

    def __init__(self, master, existing_path: str, source_path: str,
                 result_holder: list, event: threading.Event, **kw):
        super().__init__(master, **kw)
        self.title("File Conflict")
        self.resizable(False, False)
        self.configure(fg_color=BG_CARD)
        self.withdraw()  # hide until fully built

        self._result_holder = result_holder
        self._event         = event

        # ── Metadata ──────────────────────────────────────────────────────────
        fname       = os.path.basename(existing_path)
        exist_mtime = os.path.getmtime(existing_path)
        exist_size  = os.path.getsize(existing_path)
        src_mtime   = os.path.getmtime(source_path)
        src_size    = os.path.getsize(source_path)
        exist_newer = exist_mtime >= src_mtime

        def fmt_date(ts):
            return time.strftime("%b %d, %Y  %H:%M", time.localtime(ts))

        def fmt_size(b):
            if b < 1024:     return f"{b} B"
            if b < 1024**2:  return f"{b/1024:.1f} KB"
            if b < 1024**3:  return f"{b/1024**2:.1f} MB"
            return f"{b/1024**3:.1f} GB"

        # ── Title ──────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        ctk.CTkLabel(hdr, text="\u26a0", font=("Segoe UI Emoji", 22),
                     text_color="#f7c948").pack(side="left")
        ctk.CTkLabel(hdr, text="  File Already Exists",
                     font=("Inter", 16, "bold"), text_color="white").pack(side="left")

        ctk.CTkLabel(self, text=fname, font=("Inter", 12),
                     text_color=ACCENT, wraplength=500).pack(padx=20, anchor="w")
        ctk.CTkFrame(self, height=1, fg_color="#2e2e50").pack(fill="x", padx=20, pady=10)

        # ── Two-column comparison ──────────────────────────────────────────────
        cols = ctk.CTkFrame(self, fg_color="transparent")
        cols.pack(fill="x", padx=20, pady=(0, 8))
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, weight=1)

        def _card(col, label, icon, date_str, size_str, newer):
            border = "#4ade80" if newer else "#2e2e50"
            lc     = "#4ade80" if newer else TEXT_DIM
            card = ctk.CTkFrame(cols, fg_color=BG_MAIN, corner_radius=10,
                                border_width=1, border_color=border)
            card.grid(row=0, column=col, sticky="ew",
                      padx=(0, 6) if col == 0 else (6, 0))
            ctk.CTkLabel(card, text=f"{icon}  {label}",
                         font=("Inter", 11, "bold"), text_color=lc
                         ).pack(anchor="w", padx=12, pady=(10, 4))
            ctk.CTkLabel(card, text=f"\U0001f4c5  {date_str}",
                         font=("Inter", 10), text_color="white",
                         wraplength=210, justify="left").pack(anchor="w", padx=12)
            ctk.CTkLabel(card, text=f"\U0001f4be  {size_str}",
                         font=("Inter", 10), text_color=TEXT_DIM
                         ).pack(anchor="w", padx=12, pady=(2, 4))
            badge = "\u25cf  Newer" if newer else ""
            ctk.CTkLabel(card, text=badge,
                         font=("Inter", 10, "bold") if newer else ("Inter", 10),
                         text_color="#4ade80" if newer else TEXT_DIM
                         ).pack(anchor="w", padx=12, pady=(0, 8))

        _card(0, "Existing MP4", "\U0001f4c1",
              fmt_date(exist_mtime), fmt_size(exist_size), exist_newer)
        _card(1, "Source Audio", "\U0001f3a7",
              fmt_date(src_mtime),  fmt_size(src_size),   not exist_newer)

        ctk.CTkLabel(
            self,
            text="\u24d8  Sizes differ: source is audio-only; MP4 output includes a video track",
            font=("Inter", 9), text_color="#555577", wraplength=500,
        ).pack(padx=20, anchor="w", pady=(0, 2))

        # ── Hint ───────────────────────────────────────────────────────────────
        hint, hc = (
            ("Existing file is up-to-date \u2014 consider skipping.", "#4ade80")
            if exist_newer else
            ("Source is newer \u2014 consider overwriting.", "#f7c948")
        )
        ctk.CTkLabel(self, text=hint, font=("Inter", 11),
                     text_color=hc).pack(padx=20, pady=(0, 8))

        # ── Buttons ────────────────────────────────────────────────────────────
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(0, 18))

        for text, color, hover, action in [
            ("\u23ed  Skip",      "#2e2e50", "#3a3a60", "skip"),
            ("\u270f  Rename",    ACCENT2,   "#6d28d9", "rename"),
            ("\u26a1  Overwrite", "#dc2626", "#b91c1c", "overwrite"),
        ]:
            ctk.CTkButton(
                row, text=text, width=140, height=40,
                fg_color=color, hover_color=hover,
                text_color=TEXT_DIM if action == "skip" else "white",
                font=("Inter", 12, "bold") if action != "skip" else ("Inter", 12),
                command=lambda a=action: self._choose(a),
            ).pack(side="left", padx=(0, 8) if action != "overwrite" else 0)

        self.protocol("WM_DELETE_WINDOW", lambda: self._choose("skip"))
        self.update_idletasks()
        self.deiconify()
        self.after(200, self._post_show)

    def _post_show(self):
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
