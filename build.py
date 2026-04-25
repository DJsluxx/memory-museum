#!/usr/bin/env python3
"""
build.py — compile `index-source.html` → `index.html`.

Produces a single self-contained file that opens from `file://` on a phone:
  • Three.js and PointerLockControls bundled as inline importmap data URIs
    (no CDN round-trip at runtime — hard constraint from the project brief).
  • Every referenced photo inlined as a base64 data URI.
  • If `photo-manifest.json` exists, the exhibits array is regenerated from it
    (keeping any plaque overrides from `plaques.json`). Otherwise the file's
    existing `exhibits: [...]` block is left alone.

Usage
-----
    python3 build.py                       # default paths
    python3 build.py -o site/index.html    # write somewhere else
    python3 build.py --no-manifest         # ignore photo-manifest.json
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent

THREE_MODULE = ROOT / "node_modules/three/build/three.module.min.js"
PLC_MODULE = ROOT / "node_modules/three/examples/jsm/controls/PointerLockControls.js"


def data_uri(js: str) -> str:
    b64 = base64.b64encode(js.encode("utf-8")).decode("ascii")
    return f"data:text/javascript;base64,{b64}"


def read_or_die(p: Path) -> str:
    if not p.exists():
        sys.exit(f"✗ {p} not found — did you run `npm install three@0.161.0`?")
    return p.read_text()


def bundle_importmap() -> str:
    """Inline three + PointerLockControls as importmap data URIs."""
    three_js = read_or_die(THREE_MODULE)
    plc_js = read_or_die(PLC_MODULE)
    # PointerLockControls imports `from 'three'` — that identifier is resolved
    # by the same importmap at load time, so the chain is self-contained.
    return json.dumps({
        "imports": {
            "three": data_uri(three_js),
            "three/addons/controls/PointerLockControls.js": data_uri(plc_js),
        }
    })


def _placeholder_plaque(entry: dict) -> tuple[str, str, str]:
    """Return (title, date, plaque) for a manifest entry without a user override.

    The title and plaque here are intentionally restrained and honest: we don't
    know what's in the photo, so we don't invent. A line about time-of-day +
    country keeps the card from looking empty but avoids fake-specificity."""
    country = entry.get("country") or "unknown"
    iso = entry.get("timestamp") or ""
    date_display = iso[:10] if len(iso) >= 10 else "—"

    # Friendly country name for the title
    country_name = {
        "japan": "Japan", "china": "China", "south-korea": "Korea",
        "korea": "Korea", "taiwan": "Taiwan", "thailand": "Thailand",
        "singapore": "Singapore", "vietnam": "Vietnam", "israel": "Israel",
        "uae": "UAE", "hong-kong": "Hong Kong", "india": "India",
        "usa": "USA", "uk": "UK", "france": "France", "italy": "Italy",
        "greece": "Greece", "spain": "Spain", "unknown": "Somewhere",
        "cambodia": "Cambodia", "laos": "Laos", "malaysia": "Malaysia",
        "indonesia": "Indonesia", "philippines": "Philippines",
    }.get(country, country.title().replace("-", " "))

    # Time-of-day hint if we can parse the hour
    hour = None
    if len(iso) >= 13:
        try:
            hour = int(iso[11:13])
        except ValueError:
            pass
    if hour is None:
        tod = ""
    elif 5 <= hour < 11:
        tod = "Morning. "
    elif 11 <= hour < 14:
        tod = "Midday. "
    elif 14 <= hour < 17:
        tod = "Afternoon. "
    elif 17 <= hour < 20:
        tod = "Early evening. "
    elif 20 <= hour < 24:
        tod = "After dark. "
    else:
        tod = "Late, or very early. "

    title = f"{country_name} — a moment"
    plaque = (
        f"{tod}We were here. The specifics of this one haven't been written yet; "
        f"the photograph has more to say than the caption does. Look at it."
    )
    return title, date_display, plaque


def _curate(manifest: list[dict], wall_cap: int = 10, center_cap: int = 6, burst_seconds: int = 6) -> list[dict]:
    """Down-select the manifest before turning it into exhibits.

    Three passes:
      1. Burst dedupe — collapse runs of photos taken within `burst_seconds`
         into a single representative (largest filesize → likely sharpest).
      2. Wall sampling — pick `wall_cap` photos per country, spread evenly
         across the country's date range. Tagged display="wall".
      3. Centerpiece sampling — for countries with more than `wall_cap`
         remaining photos, pick up to `center_cap` additional ones (also
         spread evenly across what's left) and tag display="center".
         These render as free-standing canvases in the room's middle.
    """
    from collections import defaultdict

    # 1. Burst dedupe (sorted by timestamp inside each country bucket)
    by_country = defaultdict(list)
    for m in manifest:
        by_country[m.get("country") or "unknown"].append(m)
    for country, items in by_country.items():
        items.sort(key=lambda p: p.get("timestamp") or "")

    deduped: list[dict] = []
    for country, items in by_country.items():
        last_ts = None
        kept_in_burst: dict | None = None
        for m in items:
            ts = m.get("timestamp") or ""
            close = False
            if last_ts and ts:
                try:
                    from datetime import datetime
                    dt_prev = datetime.fromisoformat(last_ts)
                    dt_cur  = datetime.fromisoformat(ts)
                    close = abs((dt_cur - dt_prev).total_seconds()) <= burst_seconds
                except ValueError:
                    close = False
            if close and kept_in_burst is not None:
                cur_path  = ROOT / "photos" / m["filename"]
                prev_path = ROOT / "photos" / kept_in_burst["filename"]
                try:
                    if cur_path.stat().st_size > prev_path.stat().st_size:
                        deduped[-1] = m
                        kept_in_burst = m
                except FileNotFoundError:
                    pass
            else:
                deduped.append(m)
                kept_in_burst = m
            last_ts = ts

    # 2 + 3. Wall + centre sampling per country.
    chosen: list[dict] = []
    by_country2 = defaultdict(list)
    for m in deduped:
        by_country2[m.get("country") or "unknown"].append(m)

    def _spread(items: list[dict], n: int) -> list[dict]:
        """Return n items evenly spread across `items` (chronological)."""
        if n <= 0 or not items:
            return []
        if len(items) <= n:
            return list(items)
        step = (len(items) - 1) / (n - 1)
        idx = sorted({round(i * step) for i in range(n)})
        return [items[i] for i in idx[:n]]

    wall_total = 0
    centre_total = 0
    for country, items in by_country2.items():
        items.sort(key=lambda p: p.get("timestamp") or "")
        wall = _spread(items, wall_cap)
        wall_set = {id(m) for m in wall}
        for m in wall:
            m["display"] = "wall"
        chosen.extend(wall)
        wall_total += len(wall)
        leftover = [m for m in items if id(m) not in wall_set]
        centre = _spread(leftover, center_cap)
        for m in centre:
            m["display"] = "center"
        chosen.extend(centre)
        centre_total += len(centre)

    chosen.sort(key=lambda p: p.get("timestamp") or "")
    print(f"  ✓ curated {len(manifest)} → {len(deduped)} after burst-dedupe → {len(chosen)} chosen ({wall_total} wall + {centre_total} centre, ≤{wall_cap}+{center_cap}/country)")
    return chosen


def regenerate_exhibits(html: str, manifest_path: Path, plaques_path: Path) -> str:
    """Replace the `exhibits: [...]` literal with one built from the manifest.

    The manifest decides WHICH photos exist and in WHICH country each lives.
    `plaques.json` (optional) decides the title/date/plaque copy per photo.
    Anything without a plaque override falls back to a voice-rule placeholder
    produced by _placeholder_plaque (country + time-of-day-aware)."""
    if not manifest_path.exists():
        print(f"  · no {manifest_path.name} — leaving exhibits block intact")
        return html

    manifest = json.loads(manifest_path.read_text())
    plaques = json.loads(plaques_path.read_text()) if plaques_path.exists() else {}

    # Curate: burst-dedupe + 10 wall photos + up to 6 centre standing canvases per country.
    manifest = _curate(manifest, wall_cap=10, center_cap=6, burst_seconds=6)

    # Build an exhibits array where each entry matches the structure the
    # engine consumes: { room, src, title, date, plaque }.
    lines = ["    // GENERATED FROM photo-manifest.json — edit plaques.json to rewrite copy"]
    for m in manifest:
        filename = m["filename"]
        country = m.get("country") or "unknown"
        overrides = plaques.get(filename, {})
        ph_title, ph_date, ph_plaque = _placeholder_plaque(m)
        title = overrides.get("title") or ph_title
        date = overrides.get("date") or ph_date
        plaque = overrides.get("plaque") or ph_plaque
        entry = {
            "room": country,
            "src": f"photos/{filename}",
            "title": title,
            "date": date,
            "plaque": plaque,
            "display": m.get("display") or "wall",
        }
        lines.append("    " + json.dumps(entry, ensure_ascii=False) + ",")

    new_block = "exhibits: [\n" + "\n".join(lines) + "\n  ]"
    # Replace the existing exhibits array — the match is anchored on the key
    # so we never accidentally overwrite unrelated arrays.
    pattern = re.compile(r"exhibits:\s*\[[\s\S]*?\n\s*\]", re.MULTILINE)
    if not pattern.search(html):
        print("  ⚠ could not find exhibits: [ ... ] block — skipping regeneration")
        return html
    html = pattern.sub(new_block, html, count=1)
    print(f"  ✓ regenerated exhibits from {manifest_path.name} ({len(manifest)} curated photos)")
    return html


def inject_importmap(html: str) -> str:
    """Replace any CDN-based importmap with an inline data-URI importmap."""
    inline = f'<script type="importmap">\n{bundle_importmap()}\n</script>'
    # Match the existing importmap (whatever its contents) and replace it.
    pattern = re.compile(r'<script\s+type="importmap">[\s\S]*?</script>', re.IGNORECASE)
    if pattern.search(html):
        html = pattern.sub(inline, html, count=1)
        print("  ✓ inlined importmap (three + PointerLockControls) — no CDN at runtime")
    else:
        # No existing importmap — inject one right before the module script.
        html = html.replace('<script type="module">', inline + "\n<script type=\"module\">", 1)
        print("  ✓ injected importmap before module script")
    return html


def _shrink_jpeg_for_embed(fpath: Path, longest: int = 1600, quality: int = 78) -> bytes:
    """Re-encode a photo to fit a longest-edge / quality budget for embedding.

    Used to keep the inlined data-URI payload under the mobile budget. Falls
    back to the raw bytes if Pillow is missing or the image is already small.
    """
    raw = fpath.read_bytes()
    if len(raw) < 220 * 1024:
        # Already small enough; don't recompress.
        return raw
    try:
        from PIL import Image, ImageOps
        from io import BytesIO
        with Image.open(BytesIO(raw)) as img:
            img = ImageOps.exif_transpose(img)
            w, h = img.size
            if max(w, h) > longest:
                if w >= h:
                    img = img.resize((longest, round(h * longest / w)), Image.LANCZOS)
                else:
                    img = img.resize((round(w * longest / h), longest), Image.LANCZOS)
            img = img.convert("RGB")
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
            shrunk = buf.getvalue()
            return shrunk if len(shrunk) < len(raw) else raw
    except Exception:
        return raw


def embed_photos(html: str) -> str:
    """Inline every photos/*.jpg reference as a base64 data URI.

    Each photo is shrunk to a 1600px longest-edge / q=78 JPEG before encoding
    so the shipped HTML stays under the mobile-budget ceiling even with
    70+ photos. The on-disk photos/ directory is untouched.
    """
    refs = sorted(set(re.findall(r'photos/[\w\-]+\.(?:jpg|jpeg|png)', html)))
    if not refs:
        print("  · no photo references found — nothing to embed")
        return html

    photos_dir = ROOT / "photos"
    entries = []
    total = 0
    missing = []
    for ref in refs:
        fpath = ROOT / ref
        if not fpath.exists():
            missing.append(ref)
            continue
        mime = "image/jpeg" if fpath.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        if fpath.suffix.lower() in {".jpg", ".jpeg"}:
            data = _shrink_jpeg_for_embed(fpath)
        else:
            data = fpath.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        uri = f"data:{mime};base64,{b64}"
        entries.append(f'  {json.dumps(ref)}: {json.dumps(uri)},')
        total += len(uri)
    if missing:
        print(f"  ⚠ {len(missing)} missing photos — rendering placeholder frames for them:")
        for m in missing[:5]:
            print(f"      {m}")

    block = "window.PHOTO_DATA = {\n" + "\n".join(entries) + "\n};\n"
    html = re.sub(r"window\.PHOTO_DATA\s*=\s*\{[\s\S]*?\n\};\n", "", html, count=1)
    html = html.replace('<script type="module">', '<script type="module">\n' + block, 1)

    html = re.sub(
        r'loader\.load\(\s*ex\.src\s*,',
        'loader.load((window.PHOTO_DATA && window.PHOTO_DATA[ex.src]) || ex.src,',
        html, count=1,
    )
    print(f"  ✓ embedded {len(entries)} photos  ({total / (1024*1024):.1f} MB base64)")
    return html


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="index-source.html", type=Path)
    ap.add_argument("-o", "--output", default="index.html", type=Path)
    ap.add_argument("--manifest", default="photo-manifest.json", type=Path)
    ap.add_argument("--plaques", default="plaques.json", type=Path)
    ap.add_argument("--no-manifest", action="store_true",
                    help="ignore photo-manifest.json (keep source's exhibits block verbatim)")
    args = ap.parse_args()

    if not args.input.exists():
        sys.exit(f"✗ {args.input} not found")

    print(f"→ building {args.output} from {args.input}")
    html = args.input.read_text()

    if not args.no_manifest:
        html = regenerate_exhibits(html, args.manifest, args.plaques)
    html = inject_importmap(html)
    html = embed_photos(html)

    args.output.write_text(html)
    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(f"\n✓ {args.output} ({size_mb:.1f} MB) — opens from file:// with no server")
    if size_mb > 35:
        print("  ⚠ over 35 MB budget — consider --longest 1600 in process_photos.py")


if __name__ == "__main__":
    main()
