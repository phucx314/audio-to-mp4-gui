"""
core/pipeline.py — Core processing pipeline.

Handles filename standardization, FFmpeg MP4 export, and full-file
orchestration. PNG generation is delegated to core.png_generator.

No GUI / tkinter imports anywhere in this file.
"""

import os
import subprocess
import platform
from pathlib import Path


# ── Conflict resolution ───────────────────────────────────────────────────────

class FileSkippedError(Exception):
    """Raised when the user chose to skip a conflicting output file."""


def _auto_rename(path: str) -> str:
    """Append _(2), _(3), … before the extension until the path is free."""
    stem, ext = os.path.splitext(path)
    n = 2
    while True:
        candidate = f"{stem}_({n}){ext}"
        if not os.path.exists(candidate):
            return candidate
        n += 1


# ── Public constants ──────────────────────────────────────────────────────────

AUDIO_EXTENSIONS = frozenset({
    ".mp3", ".m4a", ".aac", ".wav", ".amr", ".mid",
    ".3ga", ".3gp", ".wma", ".awb", ".ogg", ".flac",
})


# ── Utilities ─────────────────────────────────────────────────────────────────

def get_default_output_dir() -> str:
    system = platform.system()
    base   = Path(os.environ.get("USERPROFILE", Path.home())) if system == "Windows" else Path.home()
    path   = base / "Documents" / "Audio" / "output"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


SPECIAL_CHAR_MAP = {
    # FFmpeg / shell special characters
    "[":    "$open_sqr_bracket",
    "]":    "$close_sqr_bracket",
    "'":    "$single_quote",
    "\u2019": "$curly_single_quote",
    "^":    "$caret",
    "=":    "$equal",
    # NTFS-illegal characters → underscore
    ":":    "_",
    "\\":   "_",
    "*":    "_",
    "?":    "_",
    '"':    "_",
    "<":    "_",
    ">":    "_",
    "|":    "_",
}


def standardize_filename(file_path: str) -> str:
    """
    Rename *file_path* if it contains shell/NTFS-illegal characters.
    Returns the (possibly unchanged) absolute path.
    """
    directory = os.path.dirname(file_path)
    old_name  = os.path.basename(file_path)
    new_name  = old_name
    for ch, rep in SPECIAL_CHAR_MAP.items():
        new_name = new_name.replace(ch, rep)
    if new_name != old_name:
        new_path = os.path.join(directory, new_name)
        os.rename(file_path, new_path)
        return new_path
    return file_path


def get_audio_duration(file_path: str) -> str | None:
    """Return HH:MM:SS duration string, or None on failure."""
    try:
        import wave, mido
        from mutagen import File as MutagenFile
        from mutagen.mp4 import MP4
        from pydub import AudioSegment

        ext = os.path.splitext(file_path)[1].lower()
        if   ext == ".amr":                  duration = len(AudioSegment.from_file(file_path, format="amr")) / 1000
        elif ext in {".m4a", ".3gp", ".3ga"}: duration = MP4(file_path).info.length
        elif ext == ".wav":
            with wave.open(file_path, "rb") as wf:
                duration = wf.getnframes() / float(wf.getframerate())
        elif ext == ".mid":                   duration = mido.MidiFile(file_path).length
        else:                                 duration = MutagenFile(file_path).info.length

        h, rem = divmod(int(duration), 3600)
        m, s   = divmod(rem, 60)
        return f"{h:02}:{m:02}:{s:02}"
    except Exception:
        return None


# ── Step 3: FFmpeg MP4 export ─────────────────────────────────────────────────

def convert_to_mp4(
    audio_path: str,
    png_path: str,
    output_dir: str,
    log_callback=None,
    conflict_resolver=None,
) -> str:
    """
    Combine *png_path* + *audio_path* into an MP4 via FFmpeg.

    conflict_resolver(existing, source) -> 'skip' | 'rename' | 'overwrite'
    Raises FileSkippedError on skip, RuntimeError on FFmpeg failure.
    """
    os.makedirs(output_dir, exist_ok=True)
    stem       = os.path.splitext(os.path.basename(audio_path))[0]
    output_mp4 = os.path.join(output_dir, f"{stem}.mp4")
    ext        = os.path.splitext(audio_path)[1].lower()

    # ── Conflict check ────────────────────────────────────────────────────────
    if os.path.exists(output_mp4):
        action = conflict_resolver(output_mp4, audio_path) if conflict_resolver else "overwrite"
        if action == "skip":
            if log_callback:
                log_callback(f"      \u23ed Skipped (file exists): {os.path.basename(output_mp4)}")
            raise FileSkippedError(output_mp4)
        elif action == "rename":
            output_mp4 = _auto_rename(output_mp4)
            if log_callback:
                log_callback(f"      \u270f Renamed \u2192 {os.path.basename(output_mp4)}")
        else:
            os.remove(output_mp4)
            if log_callback:
                log_callback("      \u267b Overwriting existing file...")

    # ── MIDI pre-conversion ───────────────────────────────────────────────────
    actual_audio  = audio_path
    temp_midi_mp3 = None
    if ext == ".mid":
        temp_midi_mp3 = os.path.join(output_dir, f"_tmp_{stem}.mp3")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-i", audio_path, "-acodec", "libmp3lame", temp_midi_mp3],
            check=True, capture_output=True,
        )
        actual_audio = temp_midi_mp3

    # ── Build FFmpeg command ──────────────────────────────────────────────────
    audio_flags = ["-c:a", "aac", "-b:a", "192k"] if ext == ".wav" else ["-acodec", "copy"]
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-v", "error", "-stats",
        "-loop", "1", "-i", png_path,
        "-i", actual_audio,
        "-c:v", "libx264", "-preset", "ultrafast",
        *audio_flags,
        "-pix_fmt", "yuv420p", "-shortest",
        "-vf", "scale=360:360", "-threads", "4",
        output_mp4,
    ]

    if log_callback:
        log_callback("      Running FFmpeg...")

    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
    stderr_lines: list[str] = []
    for raw in proc.stderr:
        for line in raw.replace("\r", "\n").splitlines():
            line = line.strip()
            if not line:
                continue
            stderr_lines.append(line)
            if log_callback:
                log_callback(f"      {line}")
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg failed:\n" + "\n".join(stderr_lines))

    audio_mtime = os.path.getmtime(audio_path)
    os.utime(output_mp4, (audio_mtime, audio_mtime))

    if temp_midi_mp3 and os.path.exists(temp_midi_mp3):
        os.remove(temp_midi_mp3)

    return output_mp4


# ── Full pipeline ─────────────────────────────────────────────────────────────

def process_file(
    file_path: str,
    output_dir: str,
    png_tmp_dir: str,
    style: str = "Style 1",
    bg_color: str = "#171717",
    log_callback=None,
    conflict_resolver=None,
) -> dict:
    """
    Run the full 3-step pipeline for one audio file.
    Returns: {status: 'done'|'skipped'|'error', output_mp4, error}
    """
    from core.png_generator import generate_png

    def log(msg):
        if log_callback:
            log_callback(msg)

    result: dict = {"status": "error", "output_mp4": None, "error": None}

    try:
        log(f"[1/3] Standardizing filename: {os.path.basename(file_path)}")
        file_path = standardize_filename(file_path)
        log(f"      \u2192 {os.path.basename(file_path)}")

        log("[2/3] Generating PNG thumbnail...")
        png_path = generate_png(file_path, png_tmp_dir, style, bg_color,
                                get_duration_fn=get_audio_duration)
        log(f"      \u2192 {os.path.basename(png_path)}")

        log("[3/3] Converting to MP4 with FFmpeg...")
        mp4_path = convert_to_mp4(file_path, png_path, output_dir,
                                   log_callback=log,
                                   conflict_resolver=conflict_resolver)
        log(f"      \u2192 {os.path.basename(mp4_path)} \u2705")

        result["status"]     = "done"
        result["output_mp4"] = mp4_path

    except FileSkippedError as e:
        result["status"]     = "skipped"
        result["output_mp4"] = str(e)

    except Exception as e:
        result["error"] = str(e)
        log(f"      \u274c Error: {e}")

    return result
