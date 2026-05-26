"""
core/icon_store.py — Two-tier icon map system.

Tier 1 (built-in): assets/icon_map.py   — bundled defaults, read-only
Tier 2 (user):     <user_data_dir>/      — writable, persists across rebuilds

Merged = built-in + user; user wins on key conflict.
"""

import json
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Optional

from PIL import Image

# ── Paths ─────────────────────────────────────────────────────────────────────

ASSETS_DIR = Path(__file__).parent.parent.resolve() / "assets"

try:
    from platformdirs import user_data_dir as _udd
    USER_DATA_DIR = Path(_udd("mp3-to-mp4", appauthor=False))
except ImportError:
    if sys.platform == "win32":
        USER_DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "mp3-to-mp4"
    else:
        USER_DATA_DIR = Path.home() / ".local" / "share" / "mp3-to-mp4"

USER_ICONS_DIR = USER_DATA_DIR / "icons"
USER_MAP_FILE  = USER_DATA_DIR / "icon_map.json"

# User icons are stored at this size; png_generator always resizes to 64×64 at render time
USER_ICON_SAVE_SIZE = 256


# ── Built-in map (loaded once at module init) ─────────────────────────────────

_BUILTIN_ICON_RAW: dict = {}
_BUILTIN_DESC_RAW: dict = {}


def _init_builtin() -> None:
    global _BUILTIN_ICON_RAW, _BUILTIN_DESC_RAW
    assets_str = str(ASSETS_DIR)
    inserted = assets_str not in sys.path
    if inserted:
        sys.path.insert(0, assets_str)
    try:
        from icon_map import icon_map as _im, description_map as _dm  # type: ignore
        _BUILTIN_ICON_RAW = dict(_im)
        _BUILTIN_DESC_RAW = dict(_dm)
    except ImportError:
        pass
    finally:
        if inserted and assets_str in sys.path:
            sys.path.remove(assets_str)


_init_builtin()


def _builtin_icon_abs() -> dict:
    """Built-in map with values converted to absolute path strings."""
    return {ext: str(ASSETS_DIR / rel) for ext, rel in _BUILTIN_ICON_RAW.items()}


# ── User map persistence ───────────────────────────────────────────────────────

def _read_user_raw() -> tuple[dict, dict]:
    """Return (icon_rel_map, description_map) from USER_MAP_FILE (relative paths)."""
    if not USER_MAP_FILE.exists():
        return {}, {}
    try:
        with open(USER_MAP_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("icon_map", {}), data.get("description_map", {})
    except Exception:
        return {}, {}


def _user_icon_abs() -> dict:
    """User icon map with values as absolute paths into USER_ICONS_DIR."""
    raw_icon, _ = _read_user_raw()
    return {ext: str(USER_ICONS_DIR / rel) for ext, rel in raw_icon.items()}


def _write_user_raw(icon_rel: dict, desc: dict) -> None:
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(USER_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump({"icon_map": icon_rel, "description_map": desc},
                  f, indent=2, ensure_ascii=False)


# ── Cache ─────────────────────────────────────────────────────────────────────

_cache: Optional[tuple[dict, dict]] = None


def invalidate_cache() -> None:
    global _cache
    _cache = None


def get_merged_maps(reload: bool = False) -> tuple[dict, dict]:
    """
    Return (icon_map_abs, description_map) — cached.
    icon_map_abs values are absolute path strings ready for PIL.Image.open().
    """
    global _cache
    if _cache is None or reload:
        bi_icon = _builtin_icon_abs()
        us_icon = _user_icon_abs()
        _, bi_desc = {}, _BUILTIN_DESC_RAW
        _, us_desc = _read_user_raw()
        _cache = ({**bi_icon, **us_icon}, {**bi_desc, **us_desc})
    return _cache


# ── CRUD ──────────────────────────────────────────────────────────────────────

def save_user_entry(ext: str, src_img_path: str, description: str) -> str:
    """
    Copy *src_img_path* into USER_ICONS_DIR resized to USER_ICON_SAVE_SIZE.
    Update USER_MAP_FILE. Invalidate cache.
    Returns absolute path of the saved icon.
    """
    ext = ext.lower()
    if not ext.startswith("."):
        ext = f".{ext}"

    USER_ICONS_DIR.mkdir(parents=True, exist_ok=True)
    icon_name = f"{ext[1:]}.png"
    dest = USER_ICONS_DIR / icon_name

    img = Image.open(src_img_path).convert("RGBA")
    img = img.resize((USER_ICON_SAVE_SIZE, USER_ICON_SAVE_SIZE), Image.LANCZOS)
    img.save(dest, format="PNG")

    raw_icon, raw_desc = _read_user_raw()
    raw_icon[ext] = icon_name
    raw_desc[ext] = description
    _write_user_raw(raw_icon, raw_desc)
    invalidate_cache()
    return str(dest)


def delete_user_entry(ext: str) -> None:
    """Remove a user-defined entry. Invalidates cache."""
    ext = ext.lower()
    if not ext.startswith("."):
        ext = f".{ext}"

    raw_icon, raw_desc = _read_user_raw()
    icon_name = raw_icon.pop(ext, None)
    raw_desc.pop(ext, None)
    _write_user_raw(raw_icon, raw_desc)

    if icon_name:
        f = USER_ICONS_DIR / icon_name
        if f.exists():
            f.unlink()
    invalidate_cache()


def is_supported(ext: str) -> bool:
    icon_map, _ = get_merged_maps()
    return ext.lower() in icon_map


# ── UI data helper ─────────────────────────────────────────────────────────────

def get_all_entries_for_ui() -> list[dict]:
    """
    Return sorted list of dicts for Icon Manager table:
    [{"ext", "description", "icon_path" (abs), "source": "builtin"|"user"}]
    User entries shadow built-in entries in display.
    """
    bi_icon = _builtin_icon_abs()
    us_icon = _user_icon_abs()
    _, us_desc = _read_user_raw()

    entries: dict[str, dict] = {}
    for ext, path in bi_icon.items():
        entries[ext] = {
            "ext": ext,
            "description": _BUILTIN_DESC_RAW.get(ext, ""),
            "icon_path": path,
            "source": "builtin",
        }
    for ext, path in us_icon.items():
        entries[ext] = {
            "ext": ext,
            "description": us_desc.get(ext, ""),
            "icon_path": path,
            "source": "user",
        }
    return sorted(entries.values(), key=lambda e: e["ext"])


# ── Icon Pack (.m34p) ─────────────────────────────────────────────────────────

def read_pack_preview(m34p_path: str) -> dict:
    """
    Parse a .m34p pack and return a preview dict (no writes).
    Returns: {manifest, new: [ext], override: [ext]}
    """
    bi_icon = _builtin_icon_abs()
    us_icon = _user_icon_abs()
    current = {**bi_icon, **us_icon}
    result = {"manifest": {}, "new": [], "override": []}

    with zipfile.ZipFile(m34p_path, "r") as zf:
        names = zf.namelist()
        if "manifest.json" in names:
            result["manifest"] = json.loads(zf.read("manifest.json"))
        if "icon_map.json" in names:
            for ext in json.loads(zf.read("icon_map.json")):
                (result["override"] if ext in current else result["new"]).append(ext)

    return result


def install_pack(m34p_path: str) -> int:
    """
    Install a .m34p pack into USER_DATA_DIR. Invalidates cache.
    Returns number of entries installed.
    """
    USER_ICONS_DIR.mkdir(parents=True, exist_ok=True)
    raw_icon, raw_desc = _read_user_raw()
    installed = 0

    with zipfile.ZipFile(m34p_path, "r") as zf:
        names = zf.namelist()
        pack_icon = json.loads(zf.read("icon_map.json")) if "icon_map.json" in names else {}
        pack_desc = json.loads(zf.read("description_map.json")) if "description_map.json" in names else {}

        for ext, icon_rel in pack_icon.items():
            if icon_rel in names:
                icon_name = Path(icon_rel).name
                dest = USER_ICONS_DIR / icon_name
                with zf.open(icon_rel) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                raw_icon[ext] = icon_name
                if ext in pack_desc:
                    raw_desc[ext] = pack_desc[ext]
                installed += 1

    _write_user_raw(raw_icon, raw_desc)
    invalidate_cache()
    return installed
