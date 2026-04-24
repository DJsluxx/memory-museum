#!/usr/bin/env python3
"""
fetch_all_photos.py  —  full Google Photos shared-album scraper.

Why this exists
---------------
`import_from_google_photos.py` can only see the initial HTML of a shared album,
which caps out around the first 30–100 photos. Everything else lazy-loads on
scroll. This script drives a real headless Chromium through Playwright,
scrolls until the grid stops growing, extracts every photo URL, strips the
thumbnail suffix, requests a near-original-quality variant, and downloads
concurrently with polite retries.

EXIF is preserved — the resulting JPEGs keep DateTimeOriginal and GPSInfo,
which `process_photos.py` uses to assign a country and a chronological index
to each photo.

Usage
-----
    pip install playwright pillow aiohttp
    playwright install chromium
    python3 fetch_all_photos.py "https://photos.app.goo.gl/XXXXXXXXXX"

Options
-------
    --out photos/raw          target directory
    --concurrency 6           parallel downloads (6–8 is a safe ceiling)
    --max-minutes 15          hard timeout on the scroll loop
    --size 2560               requested dimension for each photo
    --headed                  show the browser (useful when selectors drift)

Outputs
-------
    photos/raw/GPID_<id>.jpg   downloaded originals, EXIF intact
    fetched-photo-urls.txt     audit trail, one URL per line
    fetch-debug-<ts>.png       saved only when the page structure changes

Exit codes
----------
    0 — fetched at least one new photo, or everything already on disk
    2 — album private / blocked / selectors broke (see fetch-debug-*.png)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import re
import sys
import time
from pathlib import Path
from typing import Iterable

try:
    import aiohttp
    from playwright.async_api import Browser, Page, async_playwright
except ImportError as e:
    sys.exit(
        f"missing dependency: {e.name}\n"
        "run: pip install playwright aiohttp pillow && playwright install chromium"
    )

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.6 Safari/605.1.15"
)

# Anything matching these hosts is a Google-served photo.
PHOTO_HOST_RE = re.compile(r"https://(?:lh3|lh4|lh5|lh6)\.googleusercontent\.com/[^\"\s<>]+")
# Thumbnail size suffixes: =w200-h200-no-k, =s400, =w1024-h768-rw etc.
SIZE_SUFFIX_RE = re.compile(r"=(?:[swhr]\d+|-[^\"\s]+)(?:-[^\"\s]+)*$")


def log(msg: str) -> None:
    print(msg, flush=True)


def upscale_url(raw: str, size: int) -> str:
    """Drop any size suffix and ask for a larger variant."""
    # Google Photos URLs look like `...=w200-h200-no-k`. Everything after the
    # final `=` is the size request; replacing it with `=w{size}-h{size}` asks
    # for a ~original-quality image while keeping EXIF intact.
    base = raw.split("=", 1)[0]
    return f"{base}=w{size}-h{size}"


def extract_gpid(raw: str) -> str:
    """The long opaque ID that follows the host — stable per photo."""
    tail = raw.split("googleusercontent.com/", 1)[-1]
    # Keep everything up to the first `=` (the size suffix) or `?`.
    tail = tail.split("=", 1)[0].split("?", 1)[0]
    # Collapse path separators for a safe filename.
    return re.sub(r"[^A-Za-z0-9_-]+", "_", tail)[-80:] or "unknown"


async def scroll_until_stable(page: Page, max_minutes: int) -> int:
    """Scroll the album until the photo count stops growing.

    Google Photos sometimes uses an inner scroll container. We scroll BOTH the
    window and the widest scrollable child until no new `googleusercontent`
    URLs appear for three consecutive 1.2s idle cycles.
    """
    deadline = time.time() + max_minutes * 60
    prev_count = 0
    unchanged = 0
    step = 0

    while time.time() < deadline:
        step += 1
        # Scroll both window and the largest scrollable element.
        await page.evaluate(
            """
            () => {
                const scroller =
                    [...document.querySelectorAll('*')].find(el => {
                        const s = getComputedStyle(el);
                        return (s.overflowY === 'auto' || s.overflowY === 'scroll')
                            && el.scrollHeight > el.clientHeight + 200;
                    }) || document.scrollingElement;
                const dy = Math.floor((scroller.clientHeight || window.innerHeight) * 0.8);
                scroller.scrollBy(0, dy);
                window.scrollBy(0, dy);
            }
            """
        )
        try:
            await page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            pass  # networkidle may never fire on some infinite scrollers
        await page.wait_for_timeout(900)

        count = await page.evaluate(
            """
            () => new Set(
                [...document.images].map(i => i.src)
                    .filter(s => /googleusercontent\\.com/.test(s))
            ).size
            """
        )
        if count == prev_count:
            unchanged += 1
        else:
            unchanged = 0
            log(f"  scroll {step}: {count} photos visible")
        prev_count = count
        if unchanged >= 3:
            break

    return prev_count


async def harvest_urls(page: Page) -> list[str]:
    """Pull every unique photo URL the page has loaded so far."""
    raw_html = await page.content()
    # Catch both <img src> and URLs embedded in inline JSON blobs.
    urls = set(PHOTO_HOST_RE.findall(raw_html))
    # Deduplicate by GPID (different size suffixes of the same photo collapse).
    by_gpid: dict[str, str] = {}
    for u in urls:
        gpid = extract_gpid(u)
        # Prefer the longest variant we saw (more likely near-original).
        if gpid not in by_gpid or len(u) > len(by_gpid[gpid]):
            by_gpid[gpid] = u
    return list(by_gpid.values())


async def download_one(
    session: aiohttp.ClientSession,
    url: str,
    out: Path,
    retries: int = 4,
) -> tuple[str, str]:
    """Return (gpid, 'ok' | 'skip' | 'video' | 'fail:<reason>')."""
    gpid = extract_gpid(url)
    target = out / f"GPID_{gpid}.jpg"
    if target.exists() and target.stat().st_size > 8192:
        return gpid, "skip"

    backoff = 1.5
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=40)) as resp:
                if resp.status == 429 or resp.status >= 500:
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                if resp.status != 200:
                    return gpid, f"fail:http{resp.status}"
                ctype = resp.headers.get("Content-Type", "")
                if "video" in ctype or ctype.endswith("/mp4"):
                    return gpid, "video"
                # Extension by content type, fall back to .jpg
                ext = mimetypes.guess_extension(ctype.split(";")[0]) or ".jpg"
                if ext == ".jpe":
                    ext = ".jpg"
                final = target.with_suffix(ext)
                data = await resp.read()
                if len(data) < 4096:
                    return gpid, "fail:tiny"
                final.write_bytes(data)
                return gpid, "ok"
        except asyncio.TimeoutError:
            await asyncio.sleep(backoff)
            backoff *= 2
        except aiohttp.ClientError as e:
            return gpid, f"fail:{type(e).__name__}"
    return gpid, "fail:retries"


async def run(album_url: str, out: Path, concurrency: int, max_minutes: int, size: int, headed: bool) -> int:
    out.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(headless=not headed)
        ctx = await browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 960})
        page = await ctx.new_page()

        log(f"→ opening {album_url}")
        await page.goto(album_url, wait_until="domcontentloaded", timeout=45_000)

        # Catch the "this album is private" case early.
        body_text = (await page.locator("body").inner_text())[:1500].lower()
        if any(m in body_text for m in ("sign in", "album isn't available", "no longer shared")):
            stamp = time.strftime("%Y%m%d-%H%M%S")
            await page.screenshot(path=f"fetch-debug-{stamp}.png", full_page=True)
            log("✗ album appears private or unavailable — share link must be public")
            await browser.close()
            return 2

        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        total = await scroll_until_stable(page, max_minutes)
        if total == 0:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            await page.screenshot(path=f"fetch-debug-{stamp}.png", full_page=True)
            log(f"✗ no photos found — selectors may have drifted. see fetch-debug-{stamp}.png")
            await browser.close()
            return 2

        urls = await harvest_urls(page)
        log(f"\n✓ collected {len(urls)} unique photo URLs")
        Path("fetched-photo-urls.txt").write_text("\n".join(urls) + "\n")

        await browser.close()

    # Now download. Upscale every URL to the requested size.
    targets = [upscale_url(u, size) for u in urls]

    sem = asyncio.Semaphore(concurrency)
    stats = {"ok": 0, "skip": 0, "video": 0, "fail": 0}
    failures: list[tuple[str, str]] = []

    async with aiohttp.ClientSession(headers={"User-Agent": UA, "Referer": album_url}) as session:
        async def worker(u: str) -> None:
            async with sem:
                gpid, status = await download_one(session, u, out)
                if status == "ok":
                    stats["ok"] += 1
                    print(f"  ✓ {gpid[:16]}… → {out}/GPID_{gpid}.jpg")
                elif status == "skip":
                    stats["skip"] += 1
                elif status == "video":
                    stats["video"] += 1
                    print(f"  · skipped video: {gpid[:16]}…")
                else:
                    stats["fail"] += 1
                    failures.append((gpid, status))

        await asyncio.gather(*(worker(u) for u in targets))

    log(
        f"\n── summary ──"
        f"\n  new:      {stats['ok']}"
        f"\n  skipped:  {stats['skip']} (already on disk)"
        f"\n  videos:   {stats['video']} (ignored by design)"
        f"\n  failed:   {stats['fail']}"
    )
    if failures:
        log("  first 5 failures:")
        for g, s in failures[:5]:
            log(f"    {g[:24]}…  {s}")

    # Success if we have meaningful output on disk.
    jpegs = list(out.glob("GPID_*.jp*g"))
    log(f"\n  total on disk: {len(jpegs)} photos in {out}/")
    return 0 if jpegs else 2


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n", 1)[0])
    ap.add_argument("url", help="shared Google Photos album URL")
    ap.add_argument("--out", default="photos/raw", type=Path)
    ap.add_argument("--concurrency", default=6, type=int)
    ap.add_argument("--max-minutes", default=15, type=int)
    ap.add_argument("--size", default=2560, type=int)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()

    code = asyncio.run(
        run(
            album_url=args.url,
            out=args.out,
            concurrency=args.concurrency,
            max_minutes=args.max_minutes,
            size=args.size,
            headed=args.headed,
        )
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
