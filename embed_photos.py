#!/usr/bin/env python3
"""
Embed all referenced photos into index.html as base64 data URIs.

Produces `index.html` with photos inlined — a single self-contained file
that works from file:// with no HTTP server needed.

Usage:
    python3 embed_photos.py              # edits index.html in place
    python3 embed_photos.py -o out.html  # writes to a new file
"""
import argparse
import base64
import re
import sys
from pathlib import Path

def encode_jpeg(path: Path) -> str:
    b64 = base64.b64encode(path.read_bytes()).decode('ascii')
    return f"data:image/jpeg;base64,{b64}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="index.html", help="source HTML (default: index.html)")
    ap.add_argument("-o", "--output", default=None, help="output HTML (default: overwrite input)")
    args = ap.parse_args()

    src = Path(args.input)
    dst = Path(args.output) if args.output else src
    if not src.exists():
        sys.exit(f"✗ {src} not found")

    html = src.read_text()

    # Find every photos/*.jpg reference in the HTML (should appear inside src: "photos/...")
    refs = sorted(set(re.findall(r'photos/[\w\-]+\.jpg', html)))
    if not refs:
        sys.exit("✗ no photos/*.jpg references found in HTML")

    print(f"Embedding {len(refs)} photos into {dst.name}...\n")

    # Build a JS map of path → data URI, injected near top of the module script
    map_entries = []
    total_bytes = 0
    photos_dir = Path("photos")
    for ref in refs:
        fname = Path(ref).name
        fpath = photos_dir / fname
        if not fpath.exists():
            print(f"  ✗ missing: {ref}")
            continue
        data_uri = encode_jpeg(fpath)
        # Escape for safe embedding in a JS string literal
        map_entries.append(f'  "{ref}": "{data_uri}",')
        sz = len(data_uri)
        total_bytes += sz
        print(f"  ✓ {ref:42s} {sz // 1024:>5} KB (base64)")

    photo_map = "window.PHOTO_DATA = {\n" + "\n".join(map_entries) + "\n};\n"
    print(f"\n  Total embedded: {total_bytes // 1024} KB ({total_bytes // (1024*1024)} MB)")

    # Inject the map at the start of the module script (after the <script type="module"> opening).
    # If a previous PHOTO_DATA block already exists, replace it to avoid double-embedding.
    module_tag = '<script type="module">'
    if module_tag not in html:
        sys.exit("✗ could not find <script type=\"module\"> opener in HTML")

    # Remove any existing PHOTO_DATA block
    html = re.sub(
        r'window\.PHOTO_DATA = \{[\s\S]*?\n\};\n',
        '',
        html,
        count=1,
    )
    # Inject new one right after the module tag
    html = html.replace(module_tag, module_tag + "\n" + photo_map, 1)

    # Patch the TextureLoader call so it resolves paths through PHOTO_DATA first.
    # Look for the distinct signature of the loader call and make it use the map if present.
    loader_pattern = re.compile(r'loader\.load\(\s*ex\.src\s*,')
    if loader_pattern.search(html):
        html = loader_pattern.sub(
            'loader.load((window.PHOTO_DATA && window.PHOTO_DATA[ex.src]) || ex.src,',
            html,
            count=1,
        )
        print("  ✓ patched TextureLoader to resolve through PHOTO_DATA")
    else:
        print("  ⚠ TextureLoader pattern not found — map injected but not wired")

    dst.write_text(html)
    out_size = dst.stat().st_size
    print(f"\n✓ wrote {dst} ({out_size // 1024} KB, {out_size / (1024*1024):.1f} MB)")
    print(f"  This file is fully self-contained — opens from file:// with no server needed.")

if __name__ == "__main__":
    main()
