#!/usr/bin/env python3
"""
build_icon_pack.py — Build a .m34p icon pack from a folder of icons.

Usage:
    python3 build_icon_pack.py <icons_folder> [options]

Options:
    --name     Pack name           (default: folder name)
    --author   Author name         (default: unknown)
    --version  Pack version        (default: 1.0.0)
    --out      Output .m34p path   (default: <folder_name>.m34p)

The icons_folder should contain:
    - PNG files named after their extension (e.g., xyz.png, custom_type.png)
    - Optionally a descriptions.json file:
      { ".xyz": "My Custom Format", ".custom_type": "Custom Type File" }

Example:
    python3 build_icon_pack.py ./my_icons --name "My Pack" --author "John"

The script will:
    1. Read all .png files in the folder
    2. Resize each to 64x64 (high quality)
    3. Package them into a .m34p (ZIP) with the proper manifests
"""

import argparse
import json
import os
import zipfile
from pathlib import Path
from PIL import Image
import io

ICON_SIZE = (64, 64)


def build_pack(
    icons_folder: str,
    name: str,
    author: str,
    version: str,
    out_path: str,
):
    folder = Path(icons_folder).resolve()
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")

    # Load optional descriptions.json
    desc_file = folder / "descriptions.json"
    descriptions: dict = {}
    if desc_file.exists():
        with open(desc_file, encoding="utf-8") as f:
            descriptions = json.load(f)
        print(f"  Loaded descriptions.json ({len(descriptions)} entries)")

    # Collect all .png files
    icon_files = sorted(folder.glob("*.png"))
    if not icon_files:
        raise ValueError(f"No .png files found in: {folder}")

    icon_map: dict[str, str] = {}  # {".ext": "ext.png"}
    desc_map: dict[str, str]  = {}  # {".ext": "description"}

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:

        # Process each icon
        for icon_file in icon_files:
            stem = icon_file.stem  # e.g. "xyz"
            ext  = f".{stem}"     # e.g. ".xyz"

            # Resize to ICON_SIZE using Lanczos
            try:
                img = Image.open(icon_file).convert("RGBA")
                if img.size != ICON_SIZE:
                    img = img.resize(ICON_SIZE, Image.Resampling.LANCZOS)
                    print(f"  Resized {icon_file.name}: {img.size[0]}x{img.size[1]} -> 64x64")
                else:
                    print(f"  Added   {icon_file.name}")
            except Exception as e:
                print(f"  SKIP    {icon_file.name}: {e}")
                continue

            # Save resized image into ZIP in-memory
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            buf.seek(0)
            zf.writestr(icon_file.name, buf.read())

            icon_map[ext] = icon_file.name
            desc_map[ext] = descriptions.get(ext, f"{stem.upper()} File")

        if not icon_map:
            raise ValueError("No icons could be processed.")

        # Write manifests
        zf.writestr("manifest.json", json.dumps({
            "name":    name,
            "author":  author,
            "version": version,
            "count":   len(icon_map),
        }, indent=2))

        zf.writestr("icon_map.json",       json.dumps(icon_map, indent=2, ensure_ascii=False))
        zf.writestr("description_map.json", json.dumps(desc_map, indent=2, ensure_ascii=False))

    print(f"\n✅ Built '{out}' with {len(icon_map)} icon(s)")


def main():
    p = argparse.ArgumentParser(
        description="Build a .m34p icon pack from a folder of PNG icons."
    )
    p.add_argument("folder",            help="Folder containing .png icon files")
    p.add_argument("--name",    default=None,    help="Pack name (default: folder name)")
    p.add_argument("--author",  default="unknown", help="Author name")
    p.add_argument("--version", default="1.0.0",  help="Pack version")
    p.add_argument("--out",     default=None,    help="Output .m34p path")
    args = p.parse_args()

    folder = Path(args.folder).resolve()
    name   = args.name   or folder.name
    out    = args.out    or str(folder.parent / f"{folder.name}.m34p")

    print(f"Building pack '{name}' from: {folder}")
    print(f"Output: {out}\n")

    build_pack(
        icons_folder=str(folder),
        name=name,
        author=args.author,
        version=args.version,
        out_path=out,
    )


if __name__ == "__main__":
    main()
