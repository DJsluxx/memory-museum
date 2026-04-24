#!/usr/bin/env python3
"""
process_photos.py  —  EXIF → country + chronology, then write photo-manifest.json.

Input:   photos/raw/GPID_*.jp*g  (produced by fetch_all_photos.py)
Output:  photos/NNNN.jpg         (chronologically ordered, 2048px long edge)
         photo-manifest.json     (authoritative source for index-source.html)
         process-errors.log      (anything we couldn't parse)

Behavior
--------
1. Read EXIF with piexif (richer than PIL _getexif and resilient to quirks).
2. Apply EXIF `Orientation` so sideways phones display upright.
3. Assign a country from GPS if present; otherwise inherit from the nearest
   GPS-tagged photo within a 48h rolling window; otherwise mark "unknown".
4. Sort by DateTimeOriginal ascending, ties broken by filename.
5. Resize so the longest edge is 2048px, progressive JPEG q=85.
6. Emit photo-manifest.json — this is the ONLY source of truth the web
   museum consumes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

try:
    import piexif
    from PIL import Image, ExifTags, ImageOps
except ImportError as e:
    sys.exit(f"missing dependency: {e.name} — run `pip install pillow piexif`")


# ─── Country bounding boxes ────────────────────────────────────────────────
# Order matters: specific (Taiwan, Hong Kong, Singapore) must come before
# containing boxes (China mainland, rest of Asia). First hit wins.
COUNTRY_BOXES: list[tuple[str, float, float, float, float]] = [
    # key,       lat_min, lat_max, lng_min, lng_max
    ("hong-kong", 22.15, 22.6,  113.8, 114.5),
    ("singapore",  1.1,   1.5,  103.6, 104.1),
    ("taiwan",    21.9,  25.3,  120.0, 122.0),
    ("japan",     24.0,  45.6,  122.9, 146.0),
    ("south-korea", 33.1, 38.6, 124.6, 131.9),
    ("china",     18.2,  53.6,   73.5, 134.8),
    ("thailand",   5.6,  20.5,   97.3, 105.6),
    ("vietnam",    8.2,  23.4,  102.1, 109.5),
    ("cambodia",  10.4,  14.7,  102.3, 107.6),
    ("laos",      13.9,  22.5,  100.1, 107.7),
    ("malaysia",   0.8,   7.4,   99.6, 119.3),
    ("indonesia", -11.0,  6.1,   95.0, 141.0),
    ("philippines", 4.5, 21.2,  116.9, 126.6),
    ("india",      6.5,  35.7,   68.1,  97.4),
    ("israel",    29.5,  33.3,   34.2,  35.9),
    ("uae",       22.6,  26.1,   51.5,  56.4),
    ("usa",       24.4,  49.4, -125.0, -66.9),
    ("usa-alaska", 51.0, 71.5, -180.0, -130.0),
    ("usa-hawaii", 18.9, 22.2, -160.5, -154.7),
    ("uk",        49.9,  59.4,   -8.2,   1.8),
    ("france",    41.3,  51.1,   -5.1,   9.6),
    ("italy",     35.5,  47.1,    6.6,  18.6),
    ("greece",    34.8,  41.8,   19.4,  28.3),
    ("spain",     35.2,  43.8,   -9.4,   4.3),
]

# Human-facing country display data, keyed by the detection slug above.
# The web museum reads this verbatim — native script, colors, flag drawer.
COUNTRY_META: dict[str, dict] = {
    "japan":       {"name": "Japan",       "native": "日本",      "primary": 0xBC002D, "secondary": 0xFFFFFF, "accent": 0xBC002D, "flagFn": "japan"},
    "china":       {"name": "China",       "native": "中国",      "primary": 0xEE1C25, "secondary": 0xFFDE00, "accent": 0xFFDE00, "flagFn": "china"},
    "south-korea": {"name": "Korea",       "native": "한국",      "primary": 0x003478, "secondary": 0xC60C30, "accent": 0xC60C30, "flagFn": "korea"},
    "taiwan":      {"name": "Taiwan",      "native": "台灣",      "primary": 0xFE0000, "secondary": 0xFFFFFF, "accent": 0x000095, "flagFn": "taiwan"},
    "thailand":    {"name": "Thailand",    "native": "ประเทศไทย", "primary": 0xA51931, "secondary": 0xFFFFFF, "accent": 0x2D2A4A, "flagFn": "thailand"},
    "singapore":   {"name": "Singapore",   "native": "新加坡",    "primary": 0xEF3340, "secondary": 0xFFFFFF, "accent": 0xEF3340, "flagFn": "singapore"},
    "vietnam":     {"name": "Vietnam",     "native": "Việt Nam",  "primary": 0xDA251D, "secondary": 0xFFFF00, "accent": 0xFFFF00, "flagFn": "vietnam"},
    "cambodia":    {"name": "Cambodia",    "native": "កម្ពុជា",     "primary": 0x032EA1, "secondary": 0xE00025, "accent": 0xE00025, "flagFn": "banner"},
    "laos":        {"name": "Laos",        "native": "ລາວ",       "primary": 0xCE1126, "secondary": 0x002868, "accent": 0xFFFFFF, "flagFn": "banner"},
    "hong-kong":   {"name": "Hong Kong",   "native": "香港",      "primary": 0xDE2408, "secondary": 0xFFFFFF, "accent": 0xFFFFFF, "flagFn": "banner"},
    "malaysia":    {"name": "Malaysia",    "native": "Malaysia",  "primary": 0xCC0001, "secondary": 0xFFCC00, "accent": 0x010066, "flagFn": "banner"},
    "indonesia":   {"name": "Indonesia",   "native": "Indonesia", "primary": 0xFF0000, "secondary": 0xFFFFFF, "accent": 0xFF0000, "flagFn": "banner"},
    "philippines": {"name": "Philippines", "native": "Pilipinas", "primary": 0x0038A8, "secondary": 0xCE1126, "accent": 0xFCD116, "flagFn": "banner"},
    "india":       {"name": "India",       "native": "भारत",       "primary": 0xFF9933, "secondary": 0xFFFFFF, "accent": 0x138808, "flagFn": "banner"},
    "israel":      {"name": "Israel",      "native": "ישראל",     "primary": 0x0038B8, "secondary": 0xFFFFFF, "accent": 0x0038B8, "flagFn": "israel"},
    "uae":         {"name": "UAE",         "native": "الإمارات",  "primary": 0x00732F, "secondary": 0xFFFFFF, "accent": 0xFF0000, "flagFn": "banner"},
    "usa":         {"name": "United States","native": "USA",      "primary": 0x3C3B6E, "secondary": 0xFFFFFF, "accent": 0xB22234, "flagFn": "banner"},
    "usa-alaska":  {"name": "Alaska",      "native": "Alaska",    "primary": 0x0032A0, "secondary": 0xFFD700, "accent": 0xFFD700, "flagFn": "banner"},
    "usa-hawaii":  {"name": "Hawaii",      "native": "Hawaiʻi",   "primary": 0xCC0000, "secondary": 0xFFFFFF, "accent": 0x0033A0, "flagFn": "banner"},
    "uk":          {"name": "United Kingdom", "native": "UK",     "primary": 0x012169, "secondary": 0xFFFFFF, "accent": 0xC8102E, "flagFn": "banner"},
    "france":      {"name": "France",      "native": "France",    "primary": 0x0055A4, "secondary": 0xFFFFFF, "accent": 0xEF4135, "flagFn": "banner"},
    "italy":       {"name": "Italy",       "native": "Italia",    "primary": 0x009246, "secondary": 0xFFFFFF, "accent": 0xCE2B37, "flagFn": "banner"},
    "greece":      {"name": "Greece",      "native": "Ελλάς",     "primary": 0x0D5EAF, "secondary": 0xFFFFFF, "accent": 0x0D5EAF, "flagFn": "banner"},
    "spain":       {"name": "Spain",       "native": "España",    "primary": 0xAA151B, "secondary": 0xF1BF00, "accent": 0xAA151B, "flagFn": "banner"},
    "unknown":     {"name": "Travels",     "native": "✦",         "primary": 0xC4A05A, "secondary": 0xF4EAD5, "accent": 0xC4A05A, "flagFn": "banner"},
}


# ─── EXIF helpers ──────────────────────────────────────────────────────────
def _rational(v) -> float:
    try:
        num, den = v
        return float(num) / float(den) if den else 0.0
    except Exception:
        return float(v)


def gps_to_decimal(ex: dict) -> tuple[float, float] | None:
    """piexif GPS block → (lat, lng) in decimal degrees, or None."""
    gps = ex.get("GPS") or {}
    if not gps:
        return None
    try:
        lat_ref = gps.get(piexif.GPSIFD.GPSLatitudeRef, b"N")
        lng_ref = gps.get(piexif.GPSIFD.GPSLongitudeRef, b"E")
        lat = gps.get(piexif.GPSIFD.GPSLatitude)
        lng = gps.get(piexif.GPSIFD.GPSLongitude)
        if not lat or not lng:
            return None
        lat_d = _rational(lat[0]) + _rational(lat[1]) / 60 + _rational(lat[2]) / 3600
        lng_d = _rational(lng[0]) + _rational(lng[1]) / 60 + _rational(lng[2]) / 3600
        if lat_ref in (b"S", "S"):
            lat_d = -lat_d
        if lng_ref in (b"W", "W"):
            lng_d = -lng_d
        return lat_d, lng_d
    except Exception:
        return None


def gps_to_country(gps: tuple[float, float]) -> str:
    lat, lng = gps
    for key, la_min, la_max, lo_min, lo_max in COUNTRY_BOXES:
        if la_min <= lat <= la_max and lo_min <= lng <= lo_max:
            # Fold regional USA back into generic USA for display.
            return "usa" if key.startswith("usa") else key
    return "unknown"


def timestamp_of(ex: dict, fallback: Path) -> datetime:
    zero = ex.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
    if not zero:
        zero = ex.get("0th", {}).get(piexif.ImageIFD.DateTime)
    if zero:
        s = zero.decode() if isinstance(zero, bytes) else zero
        try:
            return datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
        except ValueError:
            pass
    # File mtime is a weak fallback but better than "now".
    return datetime.fromtimestamp(fallback.stat().st_mtime)


# ─── Core pipeline ─────────────────────────────────────────────────────────
@dataclass
class PhotoRecord:
    src_path: Path
    timestamp: datetime
    gps: tuple[float, float] | None
    country: str
    sha1: str
    make: str = ""
    model: str = ""


def iter_source(raw_dir: Path) -> Iterable[Path]:
    for p in sorted(raw_dir.iterdir()):
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".heic"}:
            yield p


def read_one(path: Path, log: logging.Logger) -> PhotoRecord | None:
    try:
        with Image.open(path) as img:
            try:
                ex = piexif.load(img.info.get("exif", b""))
            except Exception:
                ex = {"0th": {}, "Exif": {}, "GPS": {}}
            gps = gps_to_decimal(ex)
            ts = timestamp_of(ex, path)
            country = gps_to_country(gps) if gps else "unknown"
            digest = hashlib.sha1(path.read_bytes()).hexdigest()
            return PhotoRecord(
                src_path=path,
                timestamp=ts,
                gps=gps,
                country=country,
                sha1=digest,
                make=(ex.get("0th", {}).get(piexif.ImageIFD.Make, b"").decode("utf-8", "ignore")).strip("\x00 "),
                model=(ex.get("0th", {}).get(piexif.ImageIFD.Model, b"").decode("utf-8", "ignore")).strip("\x00 "),
            )
    except Exception as e:
        log.warning(f"{path.name}: {type(e).__name__}: {e}")
        return None


def backfill_countries(records: list[PhotoRecord], window_hours: int = 48) -> None:
    """For photos with country='unknown', adopt the country of the nearest
    GPS-tagged photo within ±window_hours. Otherwise leave as 'unknown'."""
    tagged = [r for r in records if r.country != "unknown"]
    if not tagged:
        return
    window = timedelta(hours=window_hours)
    for r in records:
        if r.country != "unknown":
            continue
        near = min(tagged, key=lambda t: abs(t.timestamp - r.timestamp))
        if abs(near.timestamp - r.timestamp) <= window:
            r.country = near.country


def deduplicate(records: list[PhotoRecord]) -> list[PhotoRecord]:
    seen: dict[str, PhotoRecord] = {}
    for r in records:
        prev = seen.get(r.sha1)
        if not prev or r.src_path.stat().st_size > prev.src_path.stat().st_size:
            seen[r.sha1] = r
    return list(seen.values())


def resave(record: PhotoRecord, dest: Path, longest: int = 2048, quality: int = 85) -> None:
    with Image.open(record.src_path) as img:
        img = ImageOps.exif_transpose(img)  # apply Orientation
        w, h = img.size
        if max(w, h) > longest:
            if w >= h:
                img = img.resize((longest, round(h * longest / w)), Image.LANCZOS)
            else:
                img = img.resize((round(w * longest / h), longest), Image.LANCZOS)
        img = img.convert("RGB")
        img.save(dest, format="JPEG", quality=quality, optimize=True, progressive=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="photos/raw", type=Path)
    ap.add_argument("--out", default="photos", type=Path)
    ap.add_argument("--manifest", default="photo-manifest.json", type=Path)
    ap.add_argument("--longest", default=2048, type=int)
    ap.add_argument("--quality", default=85, type=int)
    ap.add_argument("--log", default="process-errors.log", type=Path)
    args = ap.parse_args()

    logging.basicConfig(filename=args.log, filemode="w", level=logging.WARNING, format="%(message)s")
    log = logging.getLogger("process_photos")

    if not args.raw.exists():
        sys.exit(f"✗ {args.raw} not found — run fetch_all_photos.py first")
    args.out.mkdir(parents=True, exist_ok=True)

    print(f"→ scanning {args.raw}")
    records: list[PhotoRecord] = []
    for p in iter_source(args.raw):
        r = read_one(p, log)
        if r:
            records.append(r)
    print(f"  read {len(records)} photos")

    records = deduplicate(records)
    print(f"  after dedup: {len(records)} photos")

    backfill_countries(records)
    records.sort(key=lambda r: (r.timestamp, r.src_path.name))

    # Emit processed JPEGs + manifest.
    manifest = []
    for i, r in enumerate(records, start=1):
        fname = f"{i:04d}.jpg"
        dest = args.out / fname
        try:
            resave(r, dest, longest=args.longest, quality=args.quality)
        except Exception as e:
            log.warning(f"{r.src_path.name}: resave failed: {e}")
            continue
        manifest.append({
            "filename": fname,
            "original_id": r.src_path.stem,
            "country": r.country,
            "timestamp": r.timestamp.isoformat(timespec="seconds"),
            "gps": list(r.gps) if r.gps else None,
            "sha1": r.sha1,
            "make": r.make,
            "model": r.model,
        })

    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"  wrote {args.manifest} ({len(manifest)} entries)")

    # Print a country-distribution summary so Daniel sees the shape at a glance.
    by_country: dict[str, list[dict]] = {}
    for m in manifest:
        by_country.setdefault(m["country"], []).append(m)
    print("\n── country distribution ──")
    for c, entries in sorted(by_country.items(), key=lambda kv: -len(kv[1])):
        first = entries[0]["timestamp"][:10]
        last = entries[-1]["timestamp"][:10]
        label = COUNTRY_META.get(c, {"name": c}).get("name", c)
        print(f"  {label:22s}  {len(entries):>4d}    {first} → {last}")


if __name__ == "__main__":
    main()
