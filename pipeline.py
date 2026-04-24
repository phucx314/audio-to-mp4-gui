"""
pipeline.py — Core processing pipeline (no GUI).
Handles: filename standardization, PNG generation, FFmpeg MP4 export.
"""

import os
import sys
import re
import time
import subprocess
import platform
from pathlib import Path

# ── Resolve path to sibling filename_to_png module ──────────────────────────
GUI_APP_DIR = Path(__file__).parent.resolve()
REPO_ROOT = GUI_APP_DIR.parent
PNG_MODULE_DIR = REPO_ROOT / "filename_to_png"

if str(PNG_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(PNG_MODULE_DIR))

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin
from mutagen import File as MutagenFile
from mutagen.mp4 import MP4
from pydub import AudioSegment
import wave
import mido


# ── Conflict resolution ──────────────────────────────────────────────────────
class FileSkippedError(Exception):
    """Raised when the user chose to skip a conflicting output file."""
    pass


def _auto_rename(path: str) -> str:
    """Return next available path by appending _(2), _(3), ... before the ext."""
    stem, ext = os.path.splitext(path)
    counter = 2
    while True:
        candidate = f"{stem}_({counter}){ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1


# ── Supported audio extensions ───────────────────────────────────────────────
AUDIO_EXTENSIONS = {
    '.mp3', '.m4a', '.aac', '.wav', '.amr', '.mid',
    '.3ga', '.3gp', '.wma', '.awb', '.ogg', '.flac',
}

# ── Default output path ──────────────────────────────────────────────────────
def get_default_output_dir() -> str:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("USERPROFILE", Path.home()))
    else:
        base = Path.home()
    path = base / "Documents" / "Audio" / "output"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


# ── Step 1: Standardize filename ─────────────────────────────────────────────
SPECIAL_CHAR_MAP = {
    # Verbose replacements (FFmpeg / shell compat)
    '[':    '$open_sqr_bracket',
    ']':    '$close_sqr_bracket',
    "'":    '$single_quote',
    '\u2019': '$curly_single_quote',
    '^':    '$caret',
    '=':    '$equal',
    # NTFS-illegal characters → underscore
    ':':    '_',
    '\\':   '_',
    '*':    '_',
    '?':    '_',
    '"':    '_',
    '<':    '_',
    '>':    '_',
    '|':    '_',
}

def standardize_filename(file_path: str) -> str:
    """
    Rename file if it contains special characters that break FFmpeg/shell.
    Returns the new (possibly unchanged) absolute file path.
    """
    directory = os.path.dirname(file_path)
    old_name = os.path.basename(file_path)
    new_name = old_name
    for char, replacement in SPECIAL_CHAR_MAP.items():
        new_name = new_name.replace(char, replacement)

    if new_name != old_name:
        new_path = os.path.join(directory, new_name)
        os.rename(file_path, new_path)
        return new_path
    return file_path


# ── Audio duration helper ────────────────────────────────────────────────────
def get_audio_duration(file_path: str):
    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.amr':
            audio = AudioSegment.from_file(file_path, format="amr")
            duration = len(audio) / 1000
        elif ext in ['.m4a', '.3gp', '.3ga']:
            audio = MP4(file_path)
            duration = audio.info.length
        elif ext == '.wav':
            with wave.open(file_path, 'rb') as wf:
                duration = wf.getnframes() / float(wf.getframerate())
        elif ext == '.mid':
            mid = mido.MidiFile(file_path)
            duration = mid.length
        else:
            audio = MutagenFile(file_path)
            duration = audio.info.length
        h, rem = divmod(int(duration), 3600)
        m, s = divmod(rem, 60)
        return f"{h:02}:{m:02}:{s:02}"
    except Exception:
        return None


# ── Step 2: Generate PNG ─────────────────────────────────────────────────────
def resource_path(relative_path: str) -> str:
    """Resolve a path relative to filename_to_png module directory."""
    return str(PNG_MODULE_DIR / relative_path)


def is_emoji(character: str) -> bool:
    cp = ord(character)
    return (
        (0x1F600 <= cp <= 0x1F64F) or
        (0x1F300 <= cp <= 0x1F5FF) or
        (0x1F680 <= cp <= 0x1F6FF) or
        (0x1F1E6 <= cp <= 0x1F1FF) or
        (0x2600 <= cp <= 0x26FF) or
        (0x2700 <= cp <= 0x27BF)
    )


def measure_text_with_emoji(text, font, draw):
    width = 0
    for char in text:
        if is_emoji(char):
            width += font.size
        else:
            bbox = draw.textbbox((0, 0), char, font=font)
            width += bbox[2] - bbox[0]
    return width


def wrap_text_with_emoji(text, font, max_width, draw):
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
            emoji_path = resource_path(f"emoji_images/{emoji_code}.png")
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


def has_japanese(text):
    for ch in text:
        cp = ord(ch)
        if (0x3040 <= cp <= 0x309F) or (0x30A0 <= cp <= 0x30FF) or \
           (0x4E00 <= cp <= 0x9FFF) or (0xFF66 <= cp <= 0xFF9F):
            return True
    return False


def has_korean(text):
    for ch in text:
        cp = ord(ch)
        if (0x1100 <= cp <= 0x11FF) or (0x3130 <= cp <= 0x318F) or \
           (0xAC00 <= cp <= 0xD7AF) or (0xA960 <= cp <= 0xA97F) or \
           (0xD7B0 <= cp <= 0xD7FF):
            return True
    return False


def has_symbols(text):
    symbol_ranges = [
        (0x2600, 0x26FF), (0x2700, 0x27BF),
        (0x1F300, 0x1F5FF), (0x1F600, 0x1F64F),
        (0x1F680, 0x1F6FF), (0x1F700, 0x1F7FF),
        (0x1F780, 0x1F7FF), (0x1F800, 0x1F8FF),
        (0x1F900, 0x1F9FF), (0x1FA00, 0x1FA6F),
        (0x1FA70, 0x1FAFF),
    ]
    for ch in text:
        cp = ord(ch)
        for start, end in symbol_ranges:
            if start <= cp <= end:
                return True
    return False


def generate_png(file_path: str, output_dir: str, style: str = "Style 1",
                 bg_color: str = "#171717") -> str:
    """
    Generate a 480×480 PNG thumbnail for the given audio file.
    Returns path to the generated PNG file.
    """
    try:
        from icon_map import icon_map, description_map
    except ImportError:
        icon_map = {}
        description_map = {}

    file_name = os.path.basename(file_path)
    file_ext = os.path.splitext(file_name)[1].lower()

    os.makedirs(output_dir, exist_ok=True)

    modified_time = os.path.getmtime(file_path)
    modified_date = time.strftime('%B %d, %Y - %I:%M %p', time.localtime(modified_time))
    file_size = os.path.getsize(file_path)

    # ── Fonts ──
    title_font_path = resource_path('fonts/WixMadeforDisplay-Bold.ttf')
    date_font_path = resource_path('fonts/WixMadeforDisplay-Medium.ttf')
    title_font_size = 24
    date_font_size = 18
    size_font_size = 14

    try:
        title_font = ImageFont.truetype(title_font_path, title_font_size)
    except Exception:
        title_font = ImageFont.load_default()

    try:
        date_font = ImageFont.truetype(date_font_path, date_font_size)
    except Exception:
        date_font = ImageFont.load_default()

    try:
        size_font = ImageFont.truetype(date_font_path, size_font_size)
    except Exception:
        size_font = ImageFont.load_default()

    # ── Choose appropriate font for CJK / symbols ──
    if has_japanese(file_name):
        try:
            current_title_font = ImageFont.truetype(
                resource_path('fonts/Murecho-SemiBold.ttf'), title_font_size)
        except Exception:
            current_title_font = title_font
    elif has_korean(file_name):
        try:
            current_title_font = ImageFont.truetype(
                resource_path('fonts/GmarketSansTTFBold.ttf'), title_font_size)
        except Exception:
            current_title_font = title_font
    else:
        current_title_font = title_font

    # ── Create image ──
    img = Image.new("RGB", (480, 480), bg_color)
    draw = ImageDraw.Draw(img)
    wrapped_title = wrap_text_with_emoji(file_name, current_title_font, 480 - 50, draw)

    # ── Apply style ──
    if style == "Style 1":
        start_y = 20
        for line in wrapped_title:
            draw_text_with_emoji(img, draw, (25, start_y), line, current_title_font, "white")
            start_y += current_title_font.size + 5

        if file_size < 1024:
            size_str = f"{file_size} bytes"
        elif file_size < 1024 ** 2:
            size_str = f"{file_size / 1024:.2f} kB"
        elif file_size < 1024 ** 3:
            size_str = f"{file_size / 1024 ** 2:.2f} MB"
        else:
            size_str = f"{file_size / 1024 ** 3:.2f} GB"

        if file_ext in {'.mp3', '.m4a', '.aac', '.wav', '.amr', '.mid', '.3gp', '.3ga'}:
            dur = get_audio_duration(file_path)
            size_str += f" ({dur})" if dur else " (Duration: N/A)"

        draw.text((25, start_y + 15), modified_date, font=date_font, fill="lightgrey")
        draw.text((25, start_y + 42), f"File size: {size_str}", font=size_font, fill="darkgrey")
    else:
        # Style 2
        start_y = 20
        for line in wrapped_title:
            draw_text_with_emoji(img, draw, (25, start_y), line, current_title_font, "white")
            start_y += current_title_font.size + 5
        draw.text((25, start_y + 5), modified_date, font=date_font, fill="lightgrey")
        dot_pos = (30, start_y + 46)
        r = 5
        draw.ellipse([dot_pos[0]-r, dot_pos[1]-r, dot_pos[0]+r, dot_pos[1]+r], fill="red")
        draw.text((dot_pos[0]+15, dot_pos[1]-12), "REC", font=date_font, fill="grey")

    # ── Paste icon ──
    icon_filename = icon_map.get(file_ext)
    if icon_filename:
        icon_path = resource_path(icon_filename)
        if os.path.exists(icon_path):
            icon = Image.open(icon_path).resize((64, 64))
            icon_y = 480 - 25 - 64
            img.paste(icon, (25, icon_y), icon)
            desc_text = description_map.get(file_ext, "Audio File")
            try:
                text_font = ImageFont.truetype(title_font_path, 16)
            except Exception:
                text_font = date_font
            max_w = 480 - (25 + 64 + 15) - 25
            wrapped_desc = wrap_text_with_emoji(desc_text, text_font, max_w, draw)
            line_h = text_font.size
            sy = icon_y + 32 - (line_h * len(wrapped_desc)) // 2 - 8
            tx = 25 + 64 + 15
            for dline in wrapped_desc:
                draw_text_with_emoji(img, draw, (tx, sy), dline, text_font, "white")
                sy += line_h + 5

    out_stem = os.path.splitext(file_name)[0]
    output_png_path = os.path.join(output_dir, f"{out_stem}.png")
    img.save(output_png_path)
    os.utime(output_png_path, (modified_time, modified_time))
    return output_png_path


# ── Step 3: FFmpeg MP4 export ────────────────────────────────────────────────
def convert_to_mp4(audio_path: str, png_path: str, output_dir: str,
                   log_callback=None, conflict_resolver=None) -> str:
    """
    Use FFmpeg to combine png_path + audio_path into an MP4.
    Returns path to the output MP4.
    Raises FileSkippedError if the user chose to skip a conflict.
    Raises RuntimeError on FFmpeg failure.

    conflict_resolver(existing_path, source_path) -> 'skip' | 'rename' | 'overwrite'
    If None, defaults to 'overwrite'.
    """
    os.makedirs(output_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(audio_path))[0]
    output_mp4 = os.path.join(output_dir, f"{stem}.mp4")
    ext = os.path.splitext(audio_path)[1].lower()

    # ── Conflict check ────────────────────────────────────────────────────────
    if os.path.exists(output_mp4):
        action = conflict_resolver(output_mp4, audio_path) if conflict_resolver else "overwrite"
        if action == "skip":
            if log_callback:
                log_callback(f"      ⏭ Skipped (file exists): {os.path.basename(output_mp4)}")
            raise FileSkippedError(output_mp4)
        elif action == "rename":
            output_mp4 = _auto_rename(output_mp4)
            if log_callback:
                log_callback(f"      ✏ Renamed → {os.path.basename(output_mp4)}")
        else:  # overwrite
            os.remove(output_mp4)
            if log_callback:
                log_callback(f"      ♻ Overwriting existing file...")

    # Handle MIDI: convert to mp3 first
    actual_audio = audio_path
    temp_midi_mp3 = None
    if ext == '.mid':
        temp_midi_mp3 = os.path.join(output_dir, f"_tmp_{stem}.mp3")
        subprocess.run(
            ['ffmpeg', '-hide_banner', '-loglevel', 'error',
             '-i', audio_path, '-acodec', 'libmp3lame', temp_midi_mp3],
            check=True, capture_output=True
        )
        actual_audio = temp_midi_mp3

    # WAV: re-encode audio as AAC; others: copy audio stream
    # Note: no -y flag — conflict is already resolved above.
    if ext == '.wav':
        cmd = [
            'ffmpeg', '-hide_banner', '-loglevel', 'error',
            '-v', 'error', '-stats',
            '-loop', '1', '-i', png_path,
            '-i', actual_audio,
            '-c:v', 'libx264', '-preset', 'ultrafast',
            '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p', '-shortest',
            '-vf', 'scale=360:360', '-threads', '4',
            output_mp4
        ]
    else:
        cmd = [
            'ffmpeg', '-hide_banner', '-loglevel', 'error',
            '-v', 'error', '-stats',
            '-loop', '1', '-i', png_path,
            '-i', actual_audio,
            '-c:v', 'libx264', '-preset', 'ultrafast',
            '-acodec', 'copy',
            '-pix_fmt', 'yuv420p', '-shortest',
            '-vf', 'scale=360:360', '-threads', '4',
            output_mp4
        ]

    if log_callback:
        log_callback(f"      Running FFmpeg...")

    import io
    proc = subprocess.Popen(
        cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True
    )
    stderr_lines = []
    for raw in proc.stderr:
        # FFmpeg -stats uses \r to overwrite; normalise to lines
        for line in raw.replace('\r', '\n').splitlines():
            line = line.strip()
            if not line:
                continue
            stderr_lines.append(line)
            if log_callback:
                log_callback(f"      {line}")
    proc.wait()
    if proc.returncode != 0:
        err = '\n'.join(stderr_lines)
        raise RuntimeError(f"FFmpeg failed:\n{err}")

    # Preserve original audio timestamp
    audio_mtime = os.path.getmtime(audio_path)
    os.utime(output_mp4, (audio_mtime, audio_mtime))

    # Cleanup temp MIDI mp3
    if temp_midi_mp3 and os.path.exists(temp_midi_mp3):
        os.remove(temp_midi_mp3)

    return output_mp4


# ── Full pipeline for a single file ─────────────────────────────────────────
def process_file(file_path: str, output_dir: str, png_tmp_dir: str,
                 style: str = "Style 1", bg_color: str = "#171717",
                 log_callback=None, conflict_resolver=None) -> dict:
    """
    Run the full pipeline for one audio file.
    Returns dict with keys: status ('done'|'skipped'|'error'), output_mp4, error

    conflict_resolver is forwarded to convert_to_mp4 for filename conflict handling.
    """
    def log(msg):
        if log_callback:
            log_callback(msg)

    result = {"status": "error", "output_mp4": None, "error": None}

    try:
        # Step 1 — Standardize filename
        log(f"[1/3] Standardizing filename: {os.path.basename(file_path)}")
        file_path = standardize_filename(file_path)
        log(f"      → {os.path.basename(file_path)}")

        # Step 2 — Generate PNG
        log(f"[2/3] Generating PNG thumbnail...")
        png_path = generate_png(file_path, png_tmp_dir, style, bg_color)
        log(f"      → {os.path.basename(png_path)}")

        # Step 3 — Convert to MP4
        log(f"[3/3] Converting to MP4 with FFmpeg...")
        mp4_path = convert_to_mp4(
            file_path, png_path, output_dir,
            log_callback=log, conflict_resolver=conflict_resolver
        )
        log(f"      → {os.path.basename(mp4_path)} ✅")

        result["status"] = "done"
        result["output_mp4"] = mp4_path

    except FileSkippedError as e:
        result["status"] = "skipped"
        result["output_mp4"] = str(e)

    except Exception as e:
        result["error"] = str(e)
        log(f"      ❌ Error: {e}")

    return result
