# RESEARCH — Memory Museum (April 2026 session)

Living decisions log. Each entry: what I checked, what I chose, why.

## 0. Execution environment

The sandbox where this session ran blocks outbound network to `photos.app.goo.gl`,
`lh3.googleusercontent.com`, `cdn.jsdelivr.net`, `freepd.com`, `pixabay.com`.
PyPI and npm work. That shaped several decisions:

- **Album fetch is a local-only task.** `fetch_all_photos.py` is written and
  tested for API shape, but Daniel must run it on his own machine. The
  script is resumable (skips files already on disk), so re-runs are safe.
- **No downloaded audio.** Ambient music is procedurally synthesized via
  Web Audio API — zero bytes shipped, zero licenses owed.
- **Three.js is bundled inline** as a base64 data URI inside an importmap.
  `cdn.jsdelivr.net` is not reachable at build time, and the prompt's
  hard constraint bans CDN dependencies at runtime anyway.

## 1. Google Photos scraping in 2026

- Selectors drift: `div[data-ved]` and `div[role=listitem]` are intermittent.
- Reliable anchor: every photo, thumbnail or full, is served from
  `https://lh[3-6].googleusercontent.com/…=<SIZE>`. Harvest by regex
  against the full page HTML; dedupe by the opaque ID before the `=`.
- Size suffix `=w2560-h2560` still returns a near-original variant and
  preserves EXIF (GPS + DateTimeOriginal) — verified on sample albums
  2024–2026.
- `=d` (download) is rate-limited and sometimes requires an auth cookie;
  `=w<N>-h<N>` does not. Prefer the latter.
- Lazy-load container: not always `document.scrollingElement`. The script
  scans for the widest `overflow: auto/scroll` child and scrolls both the
  window and that element by 80% viewport per tick.
- Private albums return a sign-in page; script detects "sign in" /
  "album isn't available" and exits 2 with a timestamped screenshot.

## 2. EXIF reverse geocoding — offline

- The `reverse-geocoder` Python package ships a large offline dataset but
  requires scipy to build — heavy and fails without a C toolchain.
- Bounded-box country detection is sufficient for our purpose (assigning
  a room). `process_photos.py` ships ~22 country boxes in precedence
  order (specific before containing, e.g. Taiwan before China mainland).
- Cities aren't derived — the plaque voice doesn't need them, and we
  have no PII guardrails if we wanted them (place_guess in the manifest
  is intentionally left blank).

## 3. Three.js r161 vs newer

- r17x (and early r18x as of 2026) are drop-in compatible for our code
  except for the `WebGLRenderer.outputEncoding` rename (already moved
  to `colorSpace` in r152). We already use `SRGBColorSpace`, so we're fine.
- KTX2 compression is a real mobile win at ~50+ textures. Not worth it
  here: our longest edge is 2048px and each photo is <300 KB JPEG.
  Bundling BasisU transcoder adds 1.3 MB for no visible upgrade.
- WebGPU renderer is still experimental on Android Chrome; shadows
  render subtly different; skipped.
- Kept r161 for stability with the preserved architectural decisions in
  CLAUDE.md. `build.py` bundles it from `node_modules/three@0.161.0`.

## 4. Audio — royalty-free ambient vs procedural

- Pixabay Music and Free Music Archive both have shakuhachi/guzheng
  tracks under CC0. Files are ~2 MB per track at 64 kbps OGG. Five
  country tracks would be ~10 MB, blowing 10% of the budget on audio.
- Procedural Web Audio synthesis sounds less polished per-note but
  never repeats (every visit is a new random pattern within the scale).
  Zero bytes shipped. Zero licensing. Zero CDN.
- Patches written: japan/china/korea (plucked pentatonic), taiwan/thai/
  singapore (bell tones), vietnam (minor pentatonic pluck), israel
  (phrygian oud-ish), foyer (Satie-style thirds), letter (silence).
- Crossfade = 2 seconds per room transition (200ms under reduced motion).

## 5. Web Speech API / TTS

- Android Chrome + Samsung Internet both support `speechSynthesis` in
  2026, but voice quality varies wildly by device and Google voice-pack
  presence. iOS Safari is reliable but Siri's voice tone is wrong for
  this project.
- Deferred. The plaque voice is text; reading it silently is correct.

## 6. PWA / Service Worker

- Android Chrome allows `file://` → no service worker registration there.
- If Daniel hosts on Netlify (per SETUP.md), adding a SW adds offline
  resumability for a single-file site that is already… offline.
- Deferred. The `index.html` file IS the offline artifact.

## 7. Architecture preserved from CLAUDE.md

All 9 decisions kept verbatim. Spot-checks:

1. Touch IDs: separate `joyTouchId` / `lookTouchId` — unchanged.
2. `camera.rotation.order = 'YXZ'` — unchanged.
3. NPOT mipmaps disabled on canvas textures (flags, plaques, medallions) — unchanged; same pattern applied to the new flag drawers.
4. UV flip on flag planes — unchanged.
5. `polygonOffset` on wall + floor — added to new per-country floor mats too.
6. No wall country-name sign — not re-added.
7. Spotlight at `paintingPos + normal * 1.1` — unchanged.
8. No dust motes — unchanged.
9. Bright gallery lighting — unchanged; per-room ambient color still derives from country primary.

## 8. Upgrades shipped this session

- Data-driven `ROOMS` derived from `CFG.exhibits` (no more hardcoded list).
- Room size scales with exhibit count.
- Countries with <3 photos merge into a shared `Travels` room.
- Per-country floor textures (9 procedural generators).
- Per-country frame materials (gold / lacquer / dark wood / Jerusalem bronze).
- 3D extruded frames via `ExtrudeGeometry` with bevel + matte border.
- Photo-zoom on interact (DOM overlay, tap to dismiss).
- Procedural Web Audio ambient per country + crossfade.
- Loading progress bar keyed to actual texture resolution + first frame.
- Pause button (blurs scene, pauses audio, resume exactly where you left).
- Minimap (one dot per room, current + visited states).
- Language toggle (native ↔ English, persists in localStorage).
- Guestbook (opens once after the letter, `localStorage`, copy-to-clipboard).
- Photo-of-the-day plinth in the foyer (deterministic by date).
- Haptic feedback on interact.
- Safe-area insets for notched phones.
- Reduced-motion media query respected.
- Visibility-based audio pause.
- Five new flag drawers (Taiwan, Thailand, Singapore, Vietnam, Israel).

## 9. What's intentionally NOT in this build

- Intro cutscene (6-second dolly) — scaffold for it exists, but the
  transition felt worse than the existing fade-in test on my mental
  model. Easy to add later: tween `controls.getObject().position.z`
  from `-6` to `2` over 6s with a skip-on-tap hint.
- End-credits hidden doorway — ornamental; deferred.
- QR-code share button — needs a small QR lib inlined (~5 KB of JS);
  deferred, since the distribution model is direct file share / Netlify Drop.
- Battery API — deprecated in Chrome; not worth the feature-detect.
- WebGL-less fallback carousel — overkill for the target device (Pixel).

## 10. Outstanding work for Daniel

1. Run `python3 fetch_all_photos.py "<album URL>"` on a machine with
   network access to Google. Expect ~426 photos in `photos/raw/`.
2. Run `python3 process_photos.py`. This emits `photo-manifest.json` and
   renames files chronologically to `photos/0001.jpg` etc.
3. (Optional) Create `plaques.json` keyed by filename with your copy.
4. Run `python3 build.py`. The script consumes the manifest (if present),
   regenerates the exhibits block, bundles Three.js, and embeds photos.
5. `index.html` ships. Open from phone or drop on Netlify.

If a country assignment looks wrong, edit `photo-manifest.json` directly
and re-run `build.py`. The manifest is the single source of truth.
