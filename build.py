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


def regenerate_exhibits(html: str, manifest_path: Path, plaques_path: Path) -> str:
    """Replace the `exhibits: [...]` literal with one built from the manifest.

    The manifest decides WHICH photos exist and in WHICH country each lives.
    `plaques.json` (optional) decides the title/date/plaque copy per photo.
    Anything without a plaque override falls back to a voice-rule placeholder.
    """
    if not manifest_path.exists():
        print(f"  · no {manifest_path.name} — leaving exhibits block intact")
        return html

    manifest = json.loads(manifest_path.read_text())
    plaques = json.loads(plaques_path.read_text()) if plaques_path.exists() else {}

    # Build an exhibits array where each entry matches the structure the
    # engine consumes: { room, src, title, date, plaque }.
    lines = ["    // GENERATED FROM photo-manifest.json — edit plaques.json to rewrite copy"]
    for m in manifest:
        filename = m["filename"]
        country = m.get("country") or "unknown"
        overrides = plaques.get(filename, {})
        title = overrides.get("title") or ""
        date = overrides.get("date") or m.get("timestamp", "")[:10]
        plaque = overrides.get("plaque") or ""
        entry = {
            "room": country,
            "src": f"photos/{filename}",
            "title": title,
            "date": date,
            "plaque": plaque,
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
    print(f"  ✓ regenerated exhibits from {manifest_path.name} ({len(manifest)} photos)")
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


def embed_photos(html: str) -> str:
    """Inline every photos/*.jpg reference as a base64 data URI."""
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
        b64 = base64.b64encode(fpath.read_bytes()).decode("ascii")
        uri = f"data:{mime};base64,{b64}"
        entries.append(f'  {json.dumps(ref)}: {json.dumps(uri)},')
        total += len(uri)
    if missing:
        print(f"  ⚠ {len(missing)} missing photos — rendering placeholder frames for them:")
        for m in missing[:5]:
            print(f"      {m}")

    block = "window.PHOTO_DATA = {\n" + "\n".join(entries) + "\n};\n"
    # Remove any existing PHOTO_DATA block and prepend a fresh one.
    html = re.sub(r"window\.PHOTO_DATA\s*=\s*\{[\s\S]*?\n\};\n", "", html, count=1)
    html = html.replace('<script type="module">', '<script type="module">\n' + block, 1)

    # Patch the TextureLoader call so it resolves photos through PHOTO_DATA.
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
