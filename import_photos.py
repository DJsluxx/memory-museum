#!/usr/bin/env python3
"""
Memory Museum — Photo Import Helper
====================================

Takes a folder of images (e.g. your Google Photos "My Love" album export),
resizes them sensibly for web, saves them as photos/NN.jpg, and generates
the JavaScript `exhibits` config block you paste into index.html.

Usage:
    python import_photos.py /path/to/google-photos-export

Optional flags:
    --max-size 1400     Max pixel dimension on longest side (default: 1400)
    --quality 85        JPEG quality (default: 85)
    --dry-run           Print plan without writing files
    --shuffle           Shuffle photos before assigning (default: chronological by filename)

Requirements:
    pip install Pillow

Author: Claude, for Daniel, for Alena.
"""

from __future__ import annotations
import argparse
import json
import random
import shutil
import sys
from pathlib import Path
from typing import List, Tuple

try:
    from PIL import Image, ImageOps, ExifTags
except ImportError:
    print("Pillow is required. Install with:  pip install Pillow", file=sys.stderr)
    sys.exit(1)

SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}

# Room distribution — photos get split across these rooms in order, roughly evenly.
ROOMS = [
    ("beginnings", "Where We Began"),
    ("journeys",   "Journeys"),
    ("home",       "Our Small World"),
]

# Lyrical placeholder plaques, cycled per room so you have decent defaults
# until you write your own.
PLAQUES = {
    "beginnings": [
        ("A Morning",          "the early days",       "The coffee went cold twice. Neither of us noticed."),
        ("Laughter, Unposed",  "somewhere early",      "She was mid-sentence. I lowered my phone on purpose."),
        ("The First Trip",     "our first weekend",    "The hotel was worse than the pictures. The weekend was better than we imagined."),
        ("Before We Knew",     "early weeks",          "I didn't know yet. I think she did."),
        ("A Small Moment",     "an ordinary day",      "Nothing photographable happened. I photographed it anyway."),
        ("The Look",           "captured quietly",     "I didn't ask her to pose. She wasn't posing."),
        ("Light Through Glass","late afternoon",       "The light did what light does in new love — conspired."),
        ("Quiet Beginning",    "the first of many",    "A photograph is proof that something was. This one was."),
        ("Something New",      "a week in",            "She laughed at something I said. I didn't know yet that she'd keep laughing."),
        ("Evening, Learning",  "getting to know you",  "Every new person is a country. I was just beginning to learn the language."),
        ("First Snow of Us",   "when it was still new","I remember what I wore. I don't remember why. She does."),
        ("A Word She Said",    "I wrote it down later","I can't put it here. It wouldn't mean the same thing to anyone else."),
    ],
    "journeys": [
        ("Somewhere Far",      "a place we chose",     "We'd been planning it for weeks. It turned out nothing like the plan. It turned out perfect."),
        ("A View",             "an afternoon",         "She said: look. And I looked. And then I looked at her instead."),
        ("Unfamiliar Streets", "lost on purpose",      "We had a map. We used it once, for folding into a paper boat."),
        ("A Meal Somewhere",   "one good evening",     "Neither of us remembers what we ordered. Both of us remember the conversation."),
        ("Water",              "the edge of something","The sea was impossible. She was more impossible. I kept turning left."),
        ("A Long Flight",      "miles apart, then not","Distance is a strange architect. It teaches you which feelings have foundations."),
        ("High Ground",        "a view earned",        "We climbed for this. She pretended she wasn't tired. I pretended I wasn't either."),
        ("The Window Seat",    "somewhere above",      "She fell asleep on my shoulder. The cabin went quiet. The engines kept their promise."),
        ("Golden Hour",        "just before dusk",     "The light does not forgive shaky hands. Neither does memory. Both held this one anyway."),
        ("A Harbor",           "somewhere we stopped", "The boats went on. We stayed where we were."),
        ("A Border Crossed",   "a stamp in both books","Some places you only get to with another person. This was one of them."),
        ("The Far Table",      "a restaurant, abroad", "The waiter asked how we knew each other. Neither of us had an answer short enough."),
    ],
    "home": [
        ("Sunday",             "any Sunday",           "Nothing happened. Everything happened. Both are true."),
        ("Luci",               "her favorite subject", "Our cat, photographed in the pose she holds professionally: indifferent, radiant, ours."),
        ("The Kitchen",        "an ordinary Tuesday",  "She was reading something out loud. I was pretending to cook. Neither of us was doing a good job of it."),
        ("A Window",           "late afternoon light", "The light does this thing in our apartment. She's noticed too. I see her noticing."),
        ("Asleep",             "before I left for work","I took this one quietly. It felt like stealing. It felt like keeping."),
        ("Small Hands",        "a hand on a cup",      "Nothing in the frame but her hand. Still, obviously, her."),
        ("The Couch",          "a Saturday in",        "We'd agreed to do something. We did this instead. Better."),
        ("Our Doorway",        "coming home",          "She's walking in. I'm already home."),
        ("A Shared Blanket",   "winter at home",       "Half each. It's the one unfair distribution I've never argued about."),
        ("A Quiet Hour",       "late, lights low",     "Neither of us said anything. Nothing needed saying."),
        ("Breakfast, Again",   "the two hundredth time","The ritual has not gotten old. I don't think it will."),
        ("Luci, Again",        "she insists on it",    "She walked into the frame. I wasn't going to argue with her."),
    ],
}


def load_and_orient(path: Path) -> Image.Image:
    """Open image and auto-rotate based on EXIF orientation."""
    img = Image.open(path)
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return img


def resize_within(img: Image.Image, max_size: int) -> Image.Image:
    w, h = img.size
    longest = max(w, h)
    if longest <= max_size:
        return img
    scale = max_size / longest
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


def distribute_to_rooms(n: int) -> List[str]:
    """Evenly distribute n photos across the configured rooms."""
    room_keys = [k for k, _ in ROOMS]
    if n == 0:
        return []
    # Round-robin for predictable interleaving across rooms
    result = []
    per_room = n // len(room_keys)
    remainder = n % len(room_keys)
    for i, key in enumerate(room_keys):
        count = per_room + (1 if i < remainder else 0)
        result.extend([key] * count)
    return result


def js_escape(s: str) -> str:
    """Escape a string for embedding in a JavaScript string literal."""
    return (s.replace("\\", "\\\\")
             .replace('"', '\\"')
             .replace("\n", "\\n")
             .replace("\r", ""))


def main():
    ap = argparse.ArgumentParser(description="Import photos for Memory Museum")
    ap.add_argument("source", type=Path, help="Folder containing photos (e.g. Google Photos export)")
    ap.add_argument("--max-size", type=int, default=1400, help="Max pixel dimension (default 1400)")
    ap.add_argument("--quality", type=int, default=85, help="JPEG quality (default 85)")
    ap.add_argument("--dry-run", action="store_true", help="Print plan without writing files")
    ap.add_argument("--shuffle", action="store_true", help="Shuffle photos (default: sort by filename)")
    ap.add_argument("--output-dir", type=Path, default=Path("photos"), help="Output directory for processed images")
    args = ap.parse_args()

    if not args.source.is_dir():
        print(f"Error: source folder not found: {args.source}", file=sys.stderr)
        sys.exit(1)

    # Collect image files
    files = sorted(
        [p for p in args.source.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXT],
        key=lambda p: p.name.lower(),
    )
    if args.shuffle:
        random.shuffle(files)

    if not files:
        print(f"No images found in {args.source}", file=sys.stderr)
        sys.exit(1)

    print(f"\n  Memory Museum — Photo Importer")
    print(f"  ──────────────────────────────")
    print(f"  Source:    {args.source}")
    print(f"  Output:    {args.output_dir}/")
    print(f"  Photos:    {len(files)}")
    print(f"  Max size:  {args.max_size}px")
    print(f"  Quality:   {args.quality}\n")

    if not args.dry_run:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    # Distribute to rooms
    room_assignments = distribute_to_rooms(len(files))

    # Process each file
    exhibits = []
    for i, src in enumerate(files, start=1):
        dest_name = f"{i:02d}.jpg"
        dest_path = args.output_dir / dest_name
        room = room_assignments[i - 1]
        # Pull a default plaque from that room's rotation
        room_plaques = PLAQUES[room]
        title, date, body = room_plaques[(i - 1) % len(room_plaques)]

        if args.dry_run:
            print(f"  [{i:02d}] {src.name:<40} → {dest_name}  ({room})")
        else:
            try:
                img = load_and_orient(src)
                img = resize_within(img, args.max_size)
                img.save(dest_path, "JPEG", quality=args.quality, optimize=True, progressive=True)
                w, h = img.size
                print(f"  [{i:02d}] {src.name:<40} → {dest_name}  {w}×{h}  ({room})")
            except Exception as e:
                print(f"  [{i:02d}] FAILED {src.name}: {e}", file=sys.stderr)
                continue

        exhibits.append({
            "room": room,
            "src": f"photos/{dest_name}",
            "title": title,
            "date": date,
            "plaque": body,
        })

    # Generate JS config snippet
    lines = ["    exhibits: ["]
    current_room = None
    for ex in exhibits:
        if ex["room"] != current_room:
            current_room = ex["room"]
            room_name = dict(ROOMS)[current_room]
            lines.append(f"      // --- Room: {room_name} ---")
        lines.append(
            f'      {{ room: "{ex["room"]}", src: "{ex["src"]}", '
            f'title: "{js_escape(ex["title"])}", '
            f'date: "{js_escape(ex["date"])}",\n'
            f'        plaque: "{js_escape(ex["plaque"])}" }},'
        )
    lines.append("    ]")
    config_snippet = "\n".join(lines)

    # Write to file and print
    snippet_path = Path("exhibits_snippet.js")
    if not args.dry_run:
        snippet_path.write_text(config_snippet, encoding="utf-8")

    print(f"\n  ──────────────────────────────")
    print(f"  ✓ Processed {len(exhibits)} photos")
    if not args.dry_run:
        print(f"  ✓ Saved to {args.output_dir}/")
        print(f"  ✓ Config snippet written to {snippet_path}")
    print(f"\n  Next: open index.html, find the `exhibits: [...]` array inside")
    print(f"  MUSEUM_CONFIG, and replace it with the contents of {snippet_path}.")
    print(f"  Then rewrite the plaque text to be yours.\n")


if __name__ == "__main__":
    main()
