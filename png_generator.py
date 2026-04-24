"""
png_generator.py — Generate 480x480 PNG thumbnails for audio files.

Extracted from pipeline.py so that pipeline.py stays focused on
file I/O orchestration (standardize, convert, process).
"""

import os
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── Resolve assets directory (inside gui_app/) ───────────────────────────────
ASSETS_DIR = Path(__file__).parent.resolve() / "assets"

# Make icon_map importable from assets/
if str(ASSETS_DIR) not in sys.path:
    sys.path.insert(0, str(ASSETS_DIR))


def asset_path(relative_path: str) -> str:
    """Resolve a path relative to gui_app/assets/."""
    return str(ASSETS_DIR / relative_path)


# ── Emoji helpers ─────────────────────────────────────────────────────────────

def is_emoji(character: str) -> bool:
    cp = ord(character)
    return (
        (0x1F600 <= cp <= 0x1F64F) or
        (0x1F300 <= cp <= 0x1F5FF) or
        (0x1F680 <= cp <= 0x1F6FF) or
        (0x1F1E6 <= cp <= 0x1F1FF) or
        (0x2600  <= cp <= 0x26FF)  or
        (0x2700  <= cp <= 0x27BF)
    )


def measure_text_with_emoji(text, font, draw) -> int:
    width = 0
    for char in text:
        if is_emoji(char):
            width += font.size
        else:
            bbox = draw.textbbox((0, 0), char, font=font)
            width += bbox[2] - bbox[0]
    return width


def wrap_text_with_emoji(text, font, max_width, draw) -> list:
    lines = []
    words = text.split()
    current_line = ""
    for word in words:
        test_line = f"{current_line} {word}".strip() if current_line else word
        if measure_text_with_emoji(test_line, font, draw) <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            if measure_text_with_emoji(word, font, draw) > max_width:
                char_line = ""
                for char in word:
                    if measure_text_with_emoji(char_line + char, font, draw) <= max_width:
                        char_line += char
                    else:
                        lines.append(char_line)
                        char_line = char
                current_line = char_line
            else:
                current_line = word
    if current_line:
        lines.append(current_line)
    return lines


def draw_text_with_emoji(img, draw, pos, text, font, fill):
    x, y = pos
    for char in text:
        if is_emoji(char):
            emoji_code = f"{ord(char):x}"
            emoji_path = asset_path(f"emoji_images/{emoji_code}.png")
            if os.path.exists(emoji_path):
                emoji_img = Image.open(emoji_path).convert("RGBA")
                emoji_size = font.size
                emoji_img = emoji_img.resize((emoji_size, emoji_size), Image.LANCZOS)
                img.paste(emoji_img, (int(x), int(y)), emoji_img)
                x += emoji_size
            else:
                bbox = draw.textbbox((x, y), char, font=font)
                draw.text((x, y), char, font=font, fill=fill)
                x += bbox[2] - bbox[0]
        else:
            bbox = draw.textbbox((x, y), char, font=font)
            draw.text((x, y), char, font=font, fill=fill)
            x += bbox[2] - bbox[0]


# ── Script / language detection ───────────────────────────────────────────────

def has_japanese(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if (0x3040 <= cp <= 0x309F) or (0x30A0 <= cp <= 0x30FF) or \
           (0x4E00 <= cp <= 0x9FFF) or (0xFF66 <= cp <= 0xFF9F):
            return True
    return False


def has_korean(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if (0x1100 <= cp <= 0x11FF) or (0x3130 <= cp <= 0x318F) or \
           (0xAC00 <= cp <= 0xD7AF) or (0xA960 <= cp <= 0xA97F) or \
           (0xD7B0 <= cp <= 0xD7FF):
            return True
    return False


# ── PNG generation ────────────────────────────────────────────────────────────

def generate_png(file_path: str, output_dir: str,
                 style: str = "Style 1", bg_color: str = "#171717",
                 get_audio_duration_fn=None) -> str:
    """
    Generate a 480x480 PNG thumbnail for the given audio file.
    Returns path to the generated PNG file.

    get_audio_duration_fn: optional callable(file_path) -> str | None
    """
    try:
        from icon_map import icon_map, description_map
    except ImportError:
        icon_map = {}
        description_map = {}

    file_name    = os.path.basename(file_path)
    file_ext     = os.path.splitext(file_name)[1].lower()
    os.makedirs(output_dir, exist_ok=True)

    modified_time = os.path.getmtime(file_path)
    modified_date = time.strftime('%B %d, %Y - %I:%M %p', time.localtime(modified_time))
    file_size     = os.path.getsize(file_path)

    # ── Fonts ──────────────────────────────────────────────────────────────────
    title_font_path = asset_path('fonts/WixMadeforDisplay-Bold.ttf')
    date_font_path  = asset_path('fonts/WixMadeforDisplay-Medium.ttf')
    title_font_size, date_font_size, size_font_size = 24, 18, 14

    def _load(path, size):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            return ImageFont.load_default()

    title_font = _load(title_font_path, title_font_size)
    date_font  = _load(date_font_path,  date_font_size)
    size_font  = _load(date_font_path,  size_font_size)

    # CJK font selection
    if has_japanese(file_name):
        current_title_font = _load(asset_path('fonts/Murecho-SemiBold.ttf'), title_font_size)
    elif has_korean(file_name):
        current_title_font = _load(asset_path('fonts/GmarketSansTTFBold.ttf'), title_font_size)
    else:
        current_title_font = title_font

    # ── Draw ───────────────────────────────────────────────────────────────────
    img          = Image.new("RGB", (480, 480), bg_color)
    draw         = ImageDraw.Draw(img)
    wrapped_title = wrap_text_with_emoji(file_name, current_title_font, 480 - 50, draw)

    if style == "Style 1":
        start_y = 20
        for line in wrapped_title:
            draw_text_with_emoji(img, draw, (25, start_y), line, current_title_font, "white")
            start_y += current_title_font.size + 5

        if   file_size < 1024:      size_str = f"{file_size} bytes"
        elif file_size < 1024**2:   size_str = f"{file_size/1024:.2f} kB"
        elif file_size < 1024**3:   size_str = f"{file_size/1024**2:.2f} MB"
        else:                        size_str = f"{file_size/1024**3:.2f} GB"

        if file_ext in {'.mp3', '.m4a', '.aac', '.wav', '.amr', '.mid', '.3gp', '.3ga'}:
            if get_audio_duration_fn:
                dur = get_audio_duration_fn(file_path)
                size_str += f" ({dur})" if dur else " (Duration: N/A)"

        draw.text((25, start_y + 15), modified_date, font=date_font, fill="lightgrey")
        draw.text((25, start_y + 42), f"File size: {size_str}", font=size_font, fill="darkgrey")

    else:  # Style 2
        start_y = 20
        for line in wrapped_title:
            draw_text_with_emoji(img, draw, (25, start_y), line, current_title_font, "white")
            start_y += current_title_font.size + 5
        draw.text((25, start_y + 5), modified_date, font=date_font, fill="lightgrey")
        dot_pos = (30, start_y + 46)
        r = 5
        draw.ellipse([dot_pos[0]-r, dot_pos[1]-r, dot_pos[0]+r, dot_pos[1]+r], fill="red")
        draw.text((dot_pos[0]+15, dot_pos[1]-12), "REC", font=date_font, fill="grey")

    # ── Paste format icon ──────────────────────────────────────────────────────
    icon_filename = icon_map.get(file_ext)
    if icon_filename:
        icon_path = asset_path(icon_filename)
        if os.path.exists(icon_path):
            icon   = Image.open(icon_path).resize((64, 64))
            icon_y = 480 - 25 - 64
            img.paste(icon, (25, icon_y), icon)
            desc_text  = description_map.get(file_ext, "Audio File")
            text_font  = _load(title_font_path, 16)
            max_w      = 480 - (25 + 64 + 15) - 25
            wrapped_desc = wrap_text_with_emoji(desc_text, text_font, max_w, draw)
            line_h = text_font.size
            sy     = icon_y + 32 - (line_h * len(wrapped_desc)) // 2 - 8
            tx     = 25 + 64 + 15
            for dline in wrapped_desc:
                draw_text_with_emoji(img, draw, (tx, sy), dline, text_font, "white")
                sy += line_h + 5

    out_stem        = os.path.splitext(file_name)[0]
    output_png_path = os.path.join(output_dir, f"{out_stem}.png")
    img.save(output_png_path)
    os.utime(output_png_path, (modified_time, modified_time))
    return output_png_path
