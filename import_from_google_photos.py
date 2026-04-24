#!/usr/bin/env python3
"""
Memory Museum — One-Command Google Photos Importer
===================================================

Takes a Google Photos shared album URL, does everything:
  1. Fetches the album HTML
  2. Extracts photo URLs in album order (chronological)
  3. Downloads each at 2048px
  4. Resizes / re-encodes for web
  5. Generates curator plaques
  6. Patches index.html with the new exhibits

Usage:
    python import_from_google_photos.py "https://photos.app.goo.gl/..."

Requirements:
    pip install Pillow

Notes:
    - Only works on public shared-album links (photos.app.goo.gl or
      photos.google.com/share/...). Private albums require sign-in.
    - The initial HTML typically contains the first 30–100 photos of an album.
      Larger albums lazy-load more on scroll, which this script can't trigger.
      If you have more than ~100 photos, split into multiple shared albums or
      download via Google Takeout and use import_photos.py instead.
"""

from __future__ import annotations
import argparse
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import List

# Reuse the plaque pool and room distribution from import_photos
from import_photos import (
    PLAQUES, ROOMS, load_and_orient, resize_within,
    distribute_to_rooms, js_escape,
)

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")


def fetch(url: str, to: Path | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    if to:
        to.write_bytes(data)
    return data


def extract_photo_urls(html: str) -> List[str]:
    """Pull all distinct lh3.googleusercontent.com photo URLs from the album HTML,
    preserving document order (which Google emits in chronological order)."""
    seen = set()
    ordered = []
    pattern = re.compile(r'https://lh3\.googleusercontent\.com/pw/[A-Za-z0-9_\-]+(?==w\d+-h\d+-no)')
    for m in pattern.finditer(html):
        u = m.group(0)
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    return ordered


def build_exhibits_block(count: int) -> str:
    """Generate the exhibits: [...] config block for `count` photos."""
    room_assignments = distribute_to_rooms(count)
    lines = ["  exhibits: ["]
    current_room = None
    for i in range(1, count + 1):
        room = room_assignments[i - 1]
        if room != current_room:
            current_room = room
            room_name = dict(ROOMS)[room]
            lines.append(f"    // --- Room: {room_name} ---")
        title, date, body = PLAQUES[room][(i - 1) % len(PLAQUES[room])]
        lines.append(
            f'    {{ room: "{room}", src: "photos/{i:02d}.jpg", '
            f'title: "{js_escape(title)}", date: "{js_escape(date)}",\n'
            f'      plaque: "{js_escape(body)}" }},'
        )
    lines.append("  ]")
    return "\n".join(lines)


def patch_index_html(block: str, index_path: Path = Path("index.html")):
    html = index_path.read_text()
    pattern = re.compile(r'  exhibits: \[.*?\n  \]', re.DOTALL)
    matches = pattern.findall(html)
    if len(matches) != 1:
        raise RuntimeError(f"Expected 1 exhibits block in index.html, found {len(matches)}")
    index_path.write_text(pattern.sub(lambda m: block, html, count=1))


def main():
    ap = argparse.ArgumentParser(description="Import a Google Photos shared album into the museum.")
    ap.add_argument("url", help="Public shared album URL (photos.app.goo.gl/... or photos.google.com/share/...)")
    ap.add_argument("--max-size", type=int, default=1400, help="Max pixel dimension for web output (default 1400)")
    ap.add_argument("--quality", type=int, default=85, help="JPEG quality (default 85)")
    ap.add_argument("--keep-raw", action="store_true", help="Keep the raw 2048px downloads in ./raw/")
    args = ap.parse_args()

    # Try Pillow import here so error is nice if not installed
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("Pillow is required. Install with:  pip install Pillow", file=sys.stderr)
        sys.exit(1)

    print(f"\n  Fetching album HTML from {args.url}")
    html = fetch(args.url).decode("utf-8", errors="replace")

    urls = extract_photo_urls(html)
    if not urls:
        print("  No photo URLs found. Is this a public shared album?", file=sys.stderr)
        sys.exit(1)
    print(f"  Found {len(urls)} photos\n")

    raw_dir = Path("raw" if args.keep_raw else "/tmp/museum-raw")
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir = Path("photos")
    out_dir.mkdir(exist_ok=True)
    # Clean output for a fresh run
    for f in out_dir.glob("*.jpg"):
        f.unlink()

    # Download at =s2048 (max dimension 2048)
    print("  Downloading at 2048px:")
    for i, base in enumerate(urls, start=1):
        dest = raw_dir / f"{i:02d}.jpg"
        try:
            fetch(base + "=s2048", to=dest)
            print(f"    [{i:02d}] {dest.stat().st_size // 1024:>4} KB")
        except Exception as e:
            print(f"    [{i:02d}] FAILED: {e}", file=sys.stderr)
        time.sleep(0.25)

    # Resize for web
    print(f"\n  Resizing to {args.max_size}px / JPEG q{args.quality}:")
    for src in sorted(raw_dir.glob("*.jpg")):
        img = load_and_orient(src)
        img = resize_within(img, args.max_size)
        dest = out_dir / src.name
        img.save(dest, "JPEG", quality=args.quality, optimize=True, progressive=True)
        print(f"    {dest.name}  {img.size[0]}×{img.size[1]}")

    # Generate and patch
    count = len(list(out_dir.glob("*.jpg")))
    print(f"\n  Generating exhibit config for {count} photos")
    block = build_exhibits_block(count)
    patch_index_html(block)
    print("  ✓ index.html patched")

    if not args.keep_raw:
        for f in raw_dir.glob("*.jpg"):
            f.unlink()
        try:
            raw_dir.rmdir()
        except OSError:
            pass

    print(f"\n  Done. Open index.html (or host the folder) to walk through.")
    print(f"  Next: edit the plaque text in index.html to be real memories.\n")


if __name__ == "__main__":
    main()
