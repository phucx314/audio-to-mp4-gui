"""
ui/icon_manager.py — Icon Manager dialog (grid view).

Displays all mapped file-type icons (built-in + user) in a card grid.
Supports search/filter, add new mapping, delete user entries,
and install .m34p icon packs.
"""

import os
import threading
import tkinter as tk
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


def _fix_default_root(widget):
    """Python 3.14 compat: ensure tkinter._default_root is set."""
    if tk._default_root is None:
        tk._default_root = widget.winfo_toplevel()


# ── Thumbnail cache ───────────────────────────────────────────────────────────

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


# Grid layout constants
CARD_W      = 130   # card width
CARD_H      = 130   # card height
CARD_PAD    = 8     # gap between cards
ICON_SIZE   = 48    # icon thumbnail size


# ══════════════════════════════════════════════════════════════════════════════
class IconManagerDialog(ctk.CTkToplevel):
    """Modal-like dialog for browsing and managing icon mappings."""

    _instance = None

    @classmethod
    def open(cls, master):
        """Open the dialog, or focus the existing one."""
        if cls._instance is not None:
            try:
                if cls._instance.winfo_exists():
                    cls._instance.lift()
                    cls._instance.focus_force()
                    return cls._instance
            except Exception:
                pass
        dlg = cls(master)
        cls._instance = dlg
        return dlg

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.title("Icon Manager")
        self.geometry("800x600")
        self.minsize(600, 440)
        self.configure(fg_color=BG_MAIN)
        self._all_entries: list[dict] = []
        self._pending_icons: list = []
        self._entries_to_render: list = []
        self._rendered_count: int = 0
        self._render_job = None
        self._n_cols = 5
        self.withdraw()
        self.after(10, self._deferred_init)

    def _deferred_init(self):
        _fix_default_root(self)
        self._build_ui()
        self._load_entries()
        self.deiconify()
        self.after(200, self._post_show)

    def _post_show(self):
        self.lift()
        self.focus_force()
        # Bind scroll immediately so touchpad works without needing to hover-enter first
        self._bind_scroll()
        try:
            self.grab_set()
        except Exception:
            pass

    def destroy(self):
        if self._render_job:
            self.after_cancel(self._render_job)
            self._render_job = None
        self._unbind_scroll()
        IconManagerDialog._instance = None
        super().destroy()

    # ── Scroll helpers ────────────────────────────────────────────────────────

    def _bind_scroll(self, _e=None):
        self.bind_all("<Button-4>", self._on_scroll_up)
        self.bind_all("<Button-5>", self._on_scroll_down)
        self.bind_all("<MouseWheel>", self._on_scroll_wheel)

    def _unbind_scroll(self, _e=None):
        try:
            self.unbind_all("<Button-4>")
            self.unbind_all("<Button-5>")
            self.unbind_all("<MouseWheel>")
        except Exception:
            pass

    def _on_scroll_up(self, _e):
        if self._canvas.winfo_exists():
            self._canvas.yview_scroll(-3, "units")

    def _on_scroll_down(self, _e):
        if self._canvas.winfo_exists():
            self._canvas.yview_scroll(3, "units")

    def _on_scroll_wheel(self, e):
        if self._canvas.winfo_exists():
            self._canvas.yview_scroll(int(-1 * e.delta / 120), "units")

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header bar ────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(hdr, text="Icon Manager",
                     font=("Inter", 16, "bold"), text_color="white",
                     ).pack(side="left", padx=16)

        btn_frame = ctk.CTkFrame(hdr, fg_color="transparent")
        btn_frame.pack(side="right", padx=12)

        ctk.CTkButton(btn_frame, text="Install Pack", width=120, height=32,
                      fg_color=ACCENT2, hover_color="#6d28d9",
                      font=("Inter", 12, "bold"),
                      command=self._install_pack
                      ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(btn_frame, text="Add New", width=100, height=32,
                      fg_color=ACCENT, hover_color="#3d7ae0",
                      font=("Inter", 12, "bold"),
                      command=self._add_new
                      ).pack(side="right")

        # ── Search bar ────────────────────────────────────────────────────────
        search_frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=44)
        search_frame.pack(fill="x")
        search_frame.pack_propagate(False)
        self._search_var = ctk.StringVar(master=self)
        self._search_var.trace_add("write", lambda *_: self._filter())
        ctk.CTkEntry(search_frame, textvariable=self._search_var,
                     placeholder_text="Search by extension or description...",
                     font=("Inter", 12), fg_color=BG_DROP,
                     border_color="#2e2e50", border_width=1,
                     ).pack(fill="x", padx=12, pady=8)

        # ── Status bar ────────────────────────────────────────────────────────
        self._status = ctk.CTkLabel(self, text="", font=("Inter", 11),
                                    text_color=TEXT_DIM, height=28, anchor="w")
        self._status.pack(fill="x", padx=12, side="bottom")

        # ── Scrollable grid area ──────────────────────────────────────────────
        self._canvas = tk.Canvas(self, bg=BG_MAIN, highlightthickness=0, bd=0)
        _sb = ctk.CTkScrollbar(self, orientation="vertical", command=self._canvas.yview)
        self._grid_frame = tk.Frame(self._canvas, bg=BG_MAIN)
        self._grid_win = self._canvas.create_window(
            (0, 0), window=self._grid_frame, anchor="nw"
        )
        self._canvas.configure(yscrollcommand=_sb.set)
        _sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._grid_frame.bind("<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        # Scroll bindings (enter/leave)
        self._canvas.bind("<Enter>", self._bind_scroll)
        self._canvas.bind("<Leave>", self._unbind_scroll)


    def _on_canvas_resize(self, e):
        """Recalculate grid columns when canvas width changes."""
        if hasattr(self, '_resize_job') and self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(100, lambda: self._do_resize(e.width))

    def _do_resize(self, width):
        self._canvas.itemconfig(self._grid_win, width=width)
        new_cols = max(2, width // (CARD_W + CARD_PAD))
        if new_cols != self._n_cols:
            self._n_cols = new_cols
            self._repack_grid()

    def _repack_grid(self):
        """Update grid positions of existing cards without destroying them."""
        # Ensure all available columns expand to fill any remaining horizontal space
        for i in range(self._n_cols):
            self._grid_frame.columnconfigure(i, weight=1)

        for idx, w in enumerate(self._grid_frame.winfo_children()):
            row = idx // self._n_cols
            col = idx % self._n_cols
            w.grid(row=row, column=col)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load_entries(self):
        self._all_entries = get_all_entries_for_ui()
        self._filter()

    def _filter(self):
        q = self._search_var.get().lower().strip()
        visible = [
            e for e in self._all_entries
            if q in e["ext"].lower() or q in e["description"].lower()
        ] if q else self._all_entries
        self._render_grid(visible)

    # ── Grid rendering ────────────────────────────────────────────────────────

    def _render_grid(self, entries: list[dict]):
        if self._render_job:
            self.after_cancel(self._render_job)
            self._render_job = None

        for w in self._grid_frame.winfo_children():
            w.destroy()
        
        self._pending_icons = []
        self._entries_to_render = entries.copy()
        self._rendered_count = 0

        total = len(self._all_entries)
        shown = len(entries)
        self._status.configure(
            text=f"{total} mapping(s) total  ·  {shown} shown"
                 + (f"  ·  {total - shown} filtered" if shown < total else "")
        )

        self._render_batch()

    def _render_batch(self):
        """Build cards in small batches to prevent UI freezing."""
        batch = self._entries_to_render[:12]
        self._entries_to_render = self._entries_to_render[12:]

        for entry in batch:
            row = self._rendered_count // self._n_cols
            col = self._rendered_count % self._n_cols
            self._build_card(row, col, entry)
            self._rendered_count += 1

        if self._entries_to_render:
            self._render_job = self.after(5, self._render_batch)
        elif self._pending_icons:
            self._load_icons_batch()

    def _build_card(self, row: int, col: int, entry: dict):
        """Build one icon card in the grid."""
        is_user = entry["source"] == "user"
        border = ACCENT2 if is_user else "#2e2e50"

        card = ctk.CTkFrame(
            self._grid_frame, width=CARD_W, height=CARD_H,
            fg_color=BG_CARD, corner_radius=10,
            border_width=1, border_color=border,
        )
        card.grid(row=row, column=col, padx=CARD_PAD // 2, pady=CARD_PAD // 2,
                  sticky="nsew")
        card.grid_propagate(False)
        card.pack_propagate(False)

        # Configure grid column weights on the parent frame (also handled in _repack_grid)
        self._grid_frame.columnconfigure(col, weight=1)

        # Icon placeholder — loaded lazily
        icon_lbl = ctk.CTkLabel(card, text="·", width=ICON_SIZE, height=ICON_SIZE,
                                 fg_color="transparent", text_color=TEXT_DIM)
        icon_lbl.pack(pady=(12, 4))
        self._pending_icons.append((icon_lbl, entry["icon_path"]))

        # Extension label
        ctk.CTkLabel(card, text=entry["ext"],
                     font=("Courier", 13, "bold"), text_color=ACCENT,
                     height=18,
                     ).pack()

        # Description (truncated)
        desc = entry["description"]
        if len(desc) > 16:
            desc = desc[:14] + "…"
        ctk.CTkLabel(card, text=desc,
                     font=("Inter", 9), text_color=TEXT_DIM,
                     height=14,
                     ).pack()

        # Source badge
        badge_bg = ACCENT2 if is_user else "#2e4060"
        badge_text = "User" if is_user else "Built-in"
        ctk.CTkLabel(card, text=badge_text,
                     font=("Inter", 8, "bold"),
                     text_color="white" if is_user else TEXT_DIM,
                     fg_color=badge_bg, corner_radius=4,
                     width=50, height=16,
                     ).pack(pady=(2, 0))

        # Delete button (user only) — overlay in top-right corner
        if is_user:
            del_btn = ctk.CTkButton(
                card, text="×", width=20, height=20,
                fg_color="#3a1e1e", text_color="#f87171",
                hover_color="#5a2e2e", corner_radius=4,
                font=("Inter", 12, "bold"),
                command=lambda e=entry["ext"]: self._delete_entry(e),
            )
            del_btn.place(relx=1.0, rely=0.0, x=-4, y=4, anchor="ne")

    def _load_icons_batch(self):
        """Load thumbnails in small batches so UI stays responsive."""
        batch = self._pending_icons[:10]
        self._pending_icons = self._pending_icons[10:]
        for lbl, icon_path in batch:
            try:
                img = _ctk_icon(icon_path, ICON_SIZE)
                if img and lbl.winfo_exists():
                    lbl.configure(image=img, text="")
            except Exception:
                pass
        if self._pending_icons:
            self.after(5, self._load_icons_batch)

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
        self.title("Add Icon Mapping")
        self.geometry("420x440")
        self.minsize(380, 440)
        self.resizable(False, False)
        self.configure(fg_color=BG_CARD)
        self._on_save     = on_save
        self._img_path    = ""
        self._preview_img = None
        self._prefill_ext = prefill_ext
        self.withdraw()
        self.after(10, self._deferred_init)

    def _deferred_init(self):
        _fix_default_root(self)
        self._build(self._prefill_ext)
        self.deiconify()
        self.after(150, lambda: (self.lift(), self.focus_force()))

    def _build(self, prefill_ext: str):
        # Title
        ctk.CTkLabel(self, text="Add Icon Mapping",
                     font=("Inter", 15, "bold"), text_color="white",
                     ).pack(fill="x", padx=24, pady=(20, 16))

        # Extension field
        ctk.CTkLabel(self, text="Extension (e.g. .xyz)",
                     font=("Inter", 11), text_color=TEXT_DIM,
                     anchor="w"
                     ).pack(fill="x", padx=24)
        self._ext_var = ctk.StringVar(master=self, value=prefill_ext)
        ctk.CTkEntry(self, textvariable=self._ext_var, font=("Inter", 12),
                     fg_color=BG_DROP, border_color="#2e2e50", border_width=1,
                     placeholder_text=".xyz", height=36
                     ).pack(fill="x", padx=24, pady=(4, 12))

        # Description field
        ctk.CTkLabel(self, text="Description",
                     font=("Inter", 11), text_color=TEXT_DIM,
                     anchor="w"
                     ).pack(fill="x", padx=24)
        self._desc_var = ctk.StringVar(master=self)
        ctk.CTkEntry(self, textvariable=self._desc_var, font=("Inter", 12),
                     fg_color=BG_DROP, border_color="#2e2e50", border_width=1,
                     placeholder_text="My Custom Format", height=36
                     ).pack(fill="x", padx=24, pady=(4, 12))

        # Icon picker
        ctk.CTkLabel(self, text="Icon Image",
                     font=("Inter", 11), text_color=TEXT_DIM,
                     anchor="w"
                     ).pack(fill="x", padx=24)

        icon_row = ctk.CTkFrame(self, fg_color="transparent")
        icon_row.pack(fill="x", padx=24, pady=(4, 4))
        icon_row.columnconfigure(0, weight=1)

        self._icon_lbl = ctk.CTkLabel(icon_row, text="No image selected",
                                       font=("Inter", 11), text_color=TEXT_DIM,
                                       anchor="w")
        self._icon_lbl.grid(row=0, column=0, sticky="w")

        ctk.CTkButton(icon_row, text="Browse…", width=90, height=32,
                      fg_color=BG_MAIN, hover_color="#2a2a3e",
                      border_width=1, border_color="#2e2e50",
                      font=("Inter", 11),
                      command=self._pick_image
                      ).grid(row=0, column=1, padx=(8, 0))

        # Preview
        self._preview_lbl = ctk.CTkLabel(self, text="", image=None,
                                          fg_color=BG_MAIN, corner_radius=8,
                                          width=64, height=64)
        self._preview_lbl.pack(pady=(8, 16))

        # Buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=24, pady=(0, 20))

        ctk.CTkButton(btn_row, text="Cancel", width=120, height=38,
                      fg_color="transparent", border_width=1,
                      border_color="#444466", text_color=TEXT_DIM,
                      font=("Inter", 12),
                      command=self.destroy
                      ).pack(side="left")

        ctk.CTkButton(btn_row, text="Save", width=120, height=38,
                      fg_color=ACCENT, hover_color="#3d7ae0",
                      font=("Inter", 12, "bold"),
                      command=self._save
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
        self.title("Install Icon Pack")
        self.geometry("460x380")
        self.resizable(False, False)
        self.configure(fg_color=BG_CARD)
        self._pack_path  = pack_path
        self._on_install = on_install
        self._preview    = preview
        self.withdraw()
        self.after(10, self._deferred_init)

    def _deferred_init(self):
        _fix_default_root(self)
        self._build(self._preview)
        self.deiconify()
        self.after(150, lambda: (self.lift(), self.focus_force()))

    def _build(self, preview: dict):
        manifest = preview.get("manifest", {})
        new      = preview.get("new", [])
        override = preview.get("override", [])

        ctk.CTkLabel(self, text="Install Icon Pack",
                     font=("Inter", 15, "bold"), text_color="white",
                     ).pack(fill="x", padx=20, pady=(18, 4))

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
        summary = ctk.CTkFrame(self, fg_color="transparent")
        summary.pack(anchor="w", padx=20, pady=6)

        for text, color in [(f"{len(new)} new", "#166534"), (f"{len(override)} override", "#92400e")]:
            ctk.CTkLabel(summary, text=text, font=("Inter", 11),
                         fg_color=color, corner_radius=6,
                         text_color="white",
                         width=80, height=24,
                         ).pack(side="left", padx=(0, 8))

        # Preview list
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
                      font=("Inter", 12),
                      command=self.destroy
                      ).pack(side="left")

        ctk.CTkButton(btn_row, text="Install", width=100, height=36,
                      fg_color=ACCENT2, hover_color="#6d28d9",
                      font=("Inter", 12, "bold"),
                      command=self._do_install
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
