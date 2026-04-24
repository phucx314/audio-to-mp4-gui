"""
core/png_generator.py — Generate 480×480 PNG thumbnails for audio files.

Pure business logic: no GUI imports, no tkinter, no customtkinter.
Assets are read from gui_app/assets/ (parent of this file's parent dir).
"""

import os
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── Locate assets dir: gui_app/assets/ ───────────────────────────────────────
ASSETS_DIR = Path(__file__).parent.parent.resolve() / "assets"

# Make icon_map importable from assets/
if str(ASSETS_DIR) not in sys.path:
    sys.path.insert(0, str(ASSETS_DIR))


def asset_path(relative: str) -> str:
    """Resolve a path relative to gui_app/assets/."""
    return str(ASSETS_DIR / relative)


# ── Emoji helpers ─────────────────────────────────────────────────────────────

def is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return (
        (0x1F600 <= cp <= 0x1F64F) or
        (0x1F300 <= cp <= 0x1F5FF) or
        (0x1F680 <= cp <= 0x1F6FF) or
        (0x1F1E6 <= cp <= 0x1F1FF) or
        (0x2600  <= cp <= 0x26FF)  or
        (0x2700  <= cp <= 0x27BF)
    )


def measure_text(text, font, draw) -> int:
    width = 0
    for ch in text:
        if is_emoji(ch):
            width += font.size
        else:
            bb = draw.textbbox((0, 0), ch, font=font)
            width += bb[2] - bb[0]
    return width


def wrap_text(text, font, max_width, draw) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip() if current else word
        if measure_text(candidate, font, draw) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            if measure_text(word, font, draw) > max_width:
                buf = ""
                for ch in word:
                    if measure_text(buf + ch, font, draw) <= max_width:
                        buf += ch
                    else:
                        lines.append(buf)
                        buf = ch
                current = buf
            else:
                current = word
    if current:
        lines.append(current)
    return lines


def draw_text(img, draw, pos, text, font, fill):
    x, y = pos
    for ch in text:
        if is_emoji(ch):
            code = f"{ord(ch):x}"
            path = asset_path(f"emoji_images/{code}.png")
            if os.path.exists(path):
                ei = Image.open(path).convert("RGBA").resize(
                    (font.size, font.size), Image.LANCZOS)
                img.paste(ei, (int(x), int(y)), ei)
                x += font.size
            else:
                bb = draw.textbbox((x, y), ch, font=font)
                draw.text((x, y), ch, font=font, fill=fill)
                x += bb[2] - bb[0]
        else:
            bb = draw.textbbox((x, y), ch, font=font)
            draw.text((x, y), ch, font=font, fill=fill)
            x += bb[2] - bb[0]


# ── Script detection ──────────────────────────────────────────────────────────

def has_japanese(text: str) -> bool:
    return any(
        (0x3040 <= ord(c) <= 0x309F) or (0x30A0 <= ord(c) <= 0x30FF) or
        (0x4E00 <= ord(c) <= 0x9FFF) or (0xFF66 <= ord(c) <= 0xFF9F)
        for c in text
    )


def has_korean(text: str) -> bool:
    return any(
        (0x1100 <= ord(c) <= 0x11FF) or (0x3130 <= ord(c) <= 0x318F) or
        (0xAC00 <= ord(c) <= 0xD7AF) or (0xA960 <= ord(c) <= 0xA97F) or
        (0xD7B0 <= ord(c) <= 0xD7FF)
        for c in text
    )


# ── PNG generation ────────────────────────────────────────────────────────────

def generate_png(
    file_path: str,
    output_dir: str,
    style: str = "Style 1",
    bg_color: str = "#171717",
    get_duration_fn=None,
) -> str:
    """
    Render a 480×480 PNG thumbnail for *file_path* and save it to *output_dir*.
    Returns the absolute path of the generated PNG.

    get_duration_fn: optional callable(path) -> str | None
    """
    try:
        from icon_map import icon_map, description_map
    except ImportError:
        icon_map = {}
        description_map = {}

    name   = os.path.basename(file_path)
    ext    = os.path.splitext(name)[1].lower()
    mtime  = os.path.getmtime(file_path)
    date   = time.strftime("%B %d, %Y - %I:%M %p", time.localtime(mtime))
    size   = os.path.getsize(file_path)
    os.makedirs(output_dir, exist_ok=True)

    # ── Load fonts ────────────────────────────────────────────────────────────
    def _font(path, sz):
        try:
            return ImageFont.truetype(path, sz)
        except Exception:
            return ImageFont.load_default()

    title_path = asset_path("fonts/WixMadeforDisplay-Bold.ttf")
    date_path  = asset_path("fonts/WixMadeforDisplay-Medium.ttf")
    title_font = _font(title_path, 24)
    date_font  = _font(date_path,  18)
    size_font  = _font(date_path,  14)

    if has_japanese(name):
        cur_font = _font(asset_path("fonts/Murecho-SemiBold.ttf"),    24)
    elif has_korean(name):
        cur_font = _font(asset_path("fonts/GmarketSansTTFBold.ttf"),   24)
    else:
        cur_font = title_font

    # ── Draw canvas ───────────────────────────────────────────────────────────
    img   = Image.new("RGB", (480, 480), bg_color)
    draw  = ImageDraw.Draw(img)
    lines = wrap_text(name, cur_font, 430, draw)

    if style == "Style 1":
        y = 20
        for line in lines:
            draw_text(img, draw, (25, y), line, cur_font, "white")
            y += cur_font.size + 5

        if   size < 1024:      sz_str = f"{size} bytes"
        elif size < 1024**2:   sz_str = f"{size/1024:.2f} kB"
        elif size < 1024**3:   sz_str = f"{size/1024**2:.2f} MB"
        else:                   sz_str = f"{size/1024**3:.2f} GB"

        if ext in {".mp3", ".m4a", ".aac", ".wav", ".amr", ".mid", ".3gp", ".3ga"}:
            if get_duration_fn:
                dur = get_duration_fn(file_path)
                sz_str += f" ({dur})" if dur else " (Duration: N/A)"

        draw.text((25, y + 15), date, font=date_font, fill="lightgrey")
        draw.text((25, y + 42), f"File size: {sz_str}", font=size_font, fill="darkgrey")

    else:  # Style 2
        y = 20
        for line in lines:
            draw_text(img, draw, (25, y), line, cur_font, "white")
            y += cur_font.size + 5
        draw.text((25, y + 5), date, font=date_font, fill="lightgrey")
        dot = (30, y + 46)
        draw.ellipse([dot[0]-5, dot[1]-5, dot[0]+5, dot[1]+5], fill="red")
        draw.text((dot[0]+15, dot[1]-12), "REC", font=date_font, fill="grey")

    # ── Paste file-type icon ──────────────────────────────────────────────────
    icon_file = icon_map.get(ext)
    if icon_file:
        ipath = asset_path(icon_file)
        if os.path.exists(ipath):
            icon   = Image.open(ipath).resize((64, 64))
            icon_y = 480 - 25 - 64
            img.paste(icon, (25, icon_y), icon)

            desc      = description_map.get(ext, "Audio File")
            tf        = _font(title_path, 16)
            max_w     = 480 - (25 + 64 + 15) - 25
            desc_lines = wrap_text(desc, tf, max_w, draw)
            sy = icon_y + 32 - (tf.size * len(desc_lines)) // 2 - 8
            tx = 25 + 64 + 15
            for dl in desc_lines:
                draw_text(img, draw, (tx, sy), dl, tf, "white")
                sy += tf.size + 5

    out = os.path.join(output_dir, os.path.splitext(name)[0] + ".png")
    img.save(out)
    os.utime(out, (mtime, mtime))
    return out
