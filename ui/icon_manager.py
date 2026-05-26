"""
ui/icon_manager.py — Icon Manager dialog.

Displays all mapped file-type icons (built-in + user), supports:
  - Search / filter by extension or description
  - Add new mapping (pick image, type ext + description)
  - Delete user-defined entries
  - Install .m34p icon pack
"""

import os
import threading
from tkinter import filedialog, messagebox
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageTk

from core.icon_store import (
    get_all_entries_for_ui,
    save_user_entry,
    delete_user_entry,
    invalidate_cache,
    read_pack_preview,
    install_pack,
)
from ui.theme import ACCENT, ACCENT2, BG_CARD, BG_MAIN, BG_DROP, TEXT_DIM, STATUS_COLORS


# ── Thumbnail cache (CTkImage) ────────────────────────────────────────────────

_img_cache: dict[str, ctk.CTkImage] = {}

def _ctk_icon(path: str, size: int = 32) -> ctk.CTkImage | None:
    key = f"{path}:{size}"
    if key not in _img_cache:
        try:
            pil = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
            _img_cache[key] = ctk.CTkImage(light_image=pil, dark_image=pil, size=(size, size))
        except Exception:
            return None
    return _img_cache[key]


# ══════════════════════════════════════════════════════════════════════════════
class IconManagerDialog(ctk.CTkToplevel):
    """Modal-like dialog for browsing and managing icon mappings."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.title("🗂  Icon Manager")
        self.geometry("780x560")
        self.minsize(680, 440)
        self.configure(fg_color=BG_MAIN)
        self._all_entries: list[dict] = []
        self._row_widgets:  list[dict] = []
        self._build_ui()
        self._load_entries()
        self.after(200, self._post_show)

    def _post_show(self):
        self.lift(); self.focus_force()
        try: self.grab_set()
        except Exception: pass

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(hdr, text="🗂  Icon Manager",
                     font=("Inter", 16, "bold"), text_color="white"
                     ).pack(side="left", padx=16)

        btn_frame = ctk.CTkFrame(hdr, fg_color="transparent")
        btn_frame.pack(side="right", padx=12)

        ctk.CTkButton(btn_frame, text="📦 Install Pack", width=130, height=32,
                      fg_color=ACCENT2, hover_color="#6d28d9",
                      font=("Inter", 12), command=self._install_pack
                      ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(btn_frame, text="➕ Add New", width=110, height=32,
                      fg_color=ACCENT, hover_color="#3d7ae0",
                      font=("Inter", 12), command=self._add_new
                      ).pack(side="right")

        # Search bar
        search_frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=44)
        search_frame.pack(fill="x")
        search_frame.pack_propagate(False)
        self._search_var = ctk.StringVar(master=self)
        self._search_var.trace_add("write", lambda *_: self._filter())
        ctk.CTkEntry(search_frame, textvariable=self._search_var,
                     placeholder_text="🔍  Search by extension or description...",
                     font=("Inter", 12), fg_color=BG_DROP,
                     border_color="#2e2e50", border_width=1,
                     ).pack(fill="x", padx=12, pady=8)

        # Column headers
        col_hdr = ctk.CTkFrame(self, fg_color="#1a1a2e", corner_radius=0, height=30)
        col_hdr.pack(fill="x")
        col_hdr.pack_propagate(False)
        for text, anchor, padx in [
            ("Icon", "center", (12, 0)),
            ("Extension", "w", (6, 0)),
            ("Description", "w", (6, 0)),
            ("Source", "center", (6, 12)),
        ]:
            ctk.CTkLabel(col_hdr, text=text, font=("Inter", 11, "bold"),
                         text_color="#555577", anchor=anchor,
                         ).pack(side="left", padx=padx)

        # Scrollable list
        self._list = ctk.CTkScrollableFrame(self, fg_color=BG_MAIN, corner_radius=0)
        self._list.pack(fill="both", expand=True)
        self._list.columnconfigure(0, minsize=48)   # icon
        self._list.columnconfigure(1, minsize=80)   # ext
        self._list.columnconfigure(2, weight=1)     # description
        self._list.columnconfigure(3, minsize=110)  # source
        self._list.columnconfigure(4, minsize=40)   # delete btn

        # Status bar
        self._status = ctk.CTkLabel(self, text="", font=("Inter", 11),
                                    text_color=TEXT_DIM, height=28)
        self._status.pack(fill="x", padx=12)

    # ── Data loading / filtering ───────────────────────────────────────────────

    def _load_entries(self):
        self._all_entries = get_all_entries_for_ui()
        self._filter()

    def _filter(self):
        q = self._search_var.get().lower().strip()
        visible = [
            e for e in self._all_entries
            if q in e["ext"].lower() or q in e["description"].lower()
        ] if q else self._all_entries
        self._render_rows(visible)

    def _render_rows(self, entries: list[dict]):
        # Destroy old rows
        for w in self._list.winfo_children():
            w.destroy()
        self._row_widgets.clear()

        for row_idx, entry in enumerate(entries):
            bg = BG_CARD if row_idx % 2 == 0 else BG_MAIN
            self._build_row(row_idx, entry, bg)

        total = len(self._all_entries)
        shown = len(entries)
        self._status.configure(
            text=f"{total} mapping(s) total  ·  {shown} shown"
                 + (f"  ·  {total - shown} filtered" if shown < total else "")
        )

    def _build_row(self, row_idx: int, entry: dict, bg: str):
        frame = ctk.CTkFrame(self._list, fg_color=bg, corner_radius=0, height=40)
        frame.grid(row=row_idx, column=0, columnspan=5, sticky="ew", pady=1)
        frame.grid_propagate(False)
        frame.columnconfigure(2, weight=1)

        # Icon thumbnail
        img = _ctk_icon(entry["icon_path"], 28)
        icon_lbl = ctk.CTkLabel(frame, text="" if img else "?",
                                 image=img, width=48, fg_color="transparent")
        icon_lbl.grid(row=0, column=0, padx=(8, 0))

        # Extension
        ctk.CTkLabel(frame, text=entry["ext"],
                     font=("Courier", 12, "bold"), text_color=ACCENT,
                     anchor="w", width=80
                     ).grid(row=0, column=1, sticky="w", padx=(6, 0))

        # Description
        ctk.CTkLabel(frame, text=entry["description"],
                     font=("Inter", 11), text_color="white",
                     anchor="w"
                     ).grid(row=0, column=2, sticky="ew", padx=(6, 0))

        # Source badge
        is_user = entry["source"] == "user"
        badge_color = ACCENT2 if is_user else "#2e4060"
        badge_text  = "User" if is_user else "Built-in"
        ctk.CTkLabel(frame, text=badge_text,
                     font=("Inter", 10, "bold"),
                     text_color="white" if is_user else TEXT_DIM,
                     fg_color=badge_color, corner_radius=6,
                     width=72, height=22,
                     ).grid(row=0, column=3, padx=8)

        # Delete button (user only)
        if is_user:
            ctk.CTkButton(
                frame, text="🗑", width=28, height=28,
                fg_color="transparent", text_color="#f87171",
                hover_color="#2a1e1e", font=("Inter", 14),
                command=lambda e=entry["ext"]: self._delete_entry(e),
            ).grid(row=0, column=4, padx=(0, 8))

    # ── Actions ───────────────────────────────────────────────────────────────

    def _delete_entry(self, ext: str):
        if not messagebox.askyesno(
            "Delete Entry",
            f"Delete user mapping for '{ext}'?\nThe icon file will also be removed.",
            parent=self,
        ):
            return
        delete_user_entry(ext)
        self._load_entries()

    def _add_new(self):
        _AddEntryDialog(self, on_save=self._load_entries)

    def _install_pack(self):
        path = filedialog.askopenfilename(
            title="Select Icon Pack",
            filetypes=[("MP3-to-MP4 Icon Pack", "*.m34p"), ("ZIP Archive", "*.zip")],
            parent=self,
        )
        if not path:
            return
        try:
            preview = read_pack_preview(path)
            _InstallPackDialog(self, path, preview, on_install=self._load_entries)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read pack:\n{e}", parent=self)


# ══════════════════════════════════════════════════════════════════════════════
class _AddEntryDialog(ctk.CTkToplevel):
    """Sub-dialog for adding a new icon mapping."""

    def __init__(self, master, on_save=None, prefill_ext: str = "", **kw):
        super().__init__(master, **kw)
        self.title("➕ Add Icon Mapping")
        self.geometry("400x360")
        self.resizable(False, False)
        self.configure(fg_color=BG_CARD)
        self._on_save     = on_save
        self._img_path    = ""
        self._preview_img = None

        self._build(prefill_ext)
        self.after(150, lambda: (self.lift(), self.focus_force()))

    def _build(self, prefill_ext: str):
        pad = {"padx": 20, "pady": (0, 10)}

        ctk.CTkLabel(self, text="➕ Add Icon Mapping",
                     font=("Inter", 15, "bold"), text_color="white"
                     ).pack(anchor="w", padx=20, pady=(18, 12))

        ctk.CTkLabel(self, text="Extension (e.g. .xyz)",
                     font=("Inter", 12), text_color=TEXT_DIM
                     ).pack(anchor="w", padx=20)
        self._ext_var = ctk.StringVar(master=self, value=prefill_ext)
        ctk.CTkEntry(self, textvariable=self._ext_var, font=("Inter", 12),
                     placeholder_text=".xyz"
                     ).pack(fill="x", **pad)

        ctk.CTkLabel(self, text="Description",
                     font=("Inter", 12), text_color=TEXT_DIM
                     ).pack(anchor="w", padx=20)
        self._desc_var = ctk.StringVar(master=self)
        ctk.CTkEntry(self, textvariable=self._desc_var, font=("Inter", 12),
                     placeholder_text="My Custom Format"
                     ).pack(fill="x", **pad)

        ctk.CTkLabel(self, text="Icon Image",
                     font=("Inter", 12), text_color=TEXT_DIM
                     ).pack(anchor="w", padx=20)

        icon_row = ctk.CTkFrame(self, fg_color="transparent")
        icon_row.pack(fill="x", padx=20, pady=(0, 4))
        icon_row.columnconfigure(0, weight=1)

        self._icon_lbl = ctk.CTkLabel(icon_row, text="No image selected",
                                       font=("Inter", 11), text_color=TEXT_DIM,
                                       anchor="w")
        self._icon_lbl.grid(row=0, column=0, sticky="w")

        ctk.CTkButton(icon_row, text="Browse…", width=80, height=30,
                      fg_color=BG_MAIN, hover_color="#2a2a3e",
                      font=("Inter", 11), command=self._pick_image
                      ).grid(row=0, column=1, padx=(6, 0))

        # Preview
        self._preview_lbl = ctk.CTkLabel(self, text="", image=None,
                                          fg_color=BG_MAIN, corner_radius=8,
                                          width=64, height=64)
        self._preview_lbl.pack(pady=(0, 12))

        # Buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 18))
        ctk.CTkButton(btn_row, text="Cancel", width=100, height=36,
                      fg_color="transparent", border_width=1,
                      border_color="#444466", text_color=TEXT_DIM,
                      command=self.destroy
                      ).pack(side="left")
        ctk.CTkButton(btn_row, text="Save", width=100, height=36,
                      fg_color=ACCENT, hover_color="#3d7ae0",
                      font=("Inter", 12, "bold"), command=self._save
                      ).pack(side="right")

    def _pick_image(self):
        path = filedialog.askopenfilename(
            title="Select Icon Image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.ico"),
                       ("All files", "*.*")],
            parent=self,
        )
        if not path:
            return
        self._img_path = path
        self._icon_lbl.configure(text=os.path.basename(path))
        try:
            pil = Image.open(path).convert("RGBA").resize((64, 64), Image.LANCZOS)
            self._preview_img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(64, 64))
            self._preview_lbl.configure(image=self._preview_img)
        except Exception:
            pass

    def _save(self):
        ext  = self._ext_var.get().strip()
        desc = self._desc_var.get().strip()
        if not ext:
            messagebox.showwarning("Missing", "Please enter an extension.", parent=self)
            return
        if not self._img_path:
            messagebox.showwarning("Missing", "Please select an icon image.", parent=self)
            return
        if not ext.startswith("."):
            ext = f".{ext}"
        try:
            save_user_entry(ext, self._img_path, desc or "Unknown File Type")
            if self._on_save:
                self._on_save()
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save:\n{e}", parent=self)


# ══════════════════════════════════════════════════════════════════════════════
class _InstallPackDialog(ctk.CTkToplevel):
    """Preview and confirm installing a .m34p icon pack."""

    def __init__(self, master, pack_path: str, preview: dict, on_install=None, **kw):
        super().__init__(master, **kw)
        self.title("📦 Install Icon Pack")
        self.geometry("460x380")
        self.resizable(False, False)
        self.configure(fg_color=BG_CARD)
        self._pack_path = pack_path
        self._on_install = on_install
        self._build(preview)
        self.after(150, lambda: (self.lift(), self.focus_force()))

    def _build(self, preview: dict):
        manifest = preview.get("manifest", {})
        new      = preview.get("new", [])
        override = preview.get("override", [])

        ctk.CTkLabel(self, text="📦 Install Icon Pack",
                     font=("Inter", 15, "bold"), text_color="white"
                     ).pack(anchor="w", padx=20, pady=(18, 4))

        # Manifest info
        info = ctk.CTkFrame(self, fg_color=BG_MAIN, corner_radius=10)
        info.pack(fill="x", padx=20, pady=(0, 12))

        name    = manifest.get("name", os.path.basename(self._pack_path))
        author  = manifest.get("author", "Unknown")
        version = manifest.get("version", "—")

        for label, value in [("Name", name), ("Author", author), ("Version", version)]:
            row = ctk.CTkFrame(info, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=2)
            ctk.CTkLabel(row, text=f"{label}:", font=("Inter", 11),
                         text_color=TEXT_DIM, width=60, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=value, font=("Inter", 11),
                         text_color="white", anchor="w").pack(side="left")

        ctk.CTkFrame(self, height=1, fg_color="#2e2e50").pack(fill="x", padx=20, pady=4)

        # New / override counts
        def _badge(parent, text, color):
            ctk.CTkLabel(parent, text=text, font=("Inter", 11),
                         fg_color=color, corner_radius=6,
                         text_color="white", padx=8, pady=2
                         ).pack(side="left", padx=(0, 8))

        summary = ctk.CTkFrame(self, fg_color="transparent")
        summary.pack(anchor="w", padx=20, pady=6)
        _badge(summary, f"➕ {len(new)} new", "#166534")
        _badge(summary, f"⚡ {len(override)} override", "#92400e")

        # Preview list (first 8)
        preview_items = [f"{e} (new)" for e in new[:4]] + \
                        [f"{e} (override)" for e in override[:4]]
        if preview_items:
            box = ctk.CTkTextbox(self, height=80, font=("Courier", 10),
                                  fg_color=BG_MAIN, text_color="#aaaacc",
                                  state="normal")
            box.pack(fill="x", padx=20, pady=(0, 12))
            box.insert("end", "\n".join(preview_items))
            if len(new) + len(override) > 8:
                box.insert("end", f"\n... and {len(new)+len(override)-8} more")
            box.configure(state="disabled")

        # Buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 18), side="bottom")
        ctk.CTkButton(btn_row, text="Cancel", width=100, height=36,
                      fg_color="transparent", border_width=1,
                      border_color="#444466", text_color=TEXT_DIM,
                      command=self.destroy
                      ).pack(side="left")
        ctk.CTkButton(btn_row, text="Install", width=100, height=36,
                      fg_color=ACCENT2, hover_color="#6d28d9",
                      font=("Inter", 12, "bold"), command=self._do_install
                      ).pack(side="right")

    def _do_install(self):
        try:
            n = install_pack(self._pack_path)
            messagebox.showinfo("Done", f"Installed {n} icon(s) successfully!", parent=self)
            if self._on_install:
                self._on_install()
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Install failed:\n{e}", parent=self)
