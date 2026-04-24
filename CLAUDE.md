# Memory Museum — Project Context for Claude Code

## What this is

A 3D walkable web museum, self-contained in a single HTML file. Built in Three.js.
A love gift from **Daniel** (Senior Staff SRE, Israel, starting at Palo Alto Networks May 17 2026) to his long-distance partner **Alena** (East-Asian, lives separately from Daniel).

She walks through country-themed galleries, each filled with photos of the two of them on trips together, each with a curator's plaque written in the same intimate, specific voice.

The HTML must open from `file://` on a mobile phone with no server. Target device: her Pixel/Android, but must work anywhere.

## Current state (what's already built)

**Works. Shipped. Don't rebuild from scratch.**

- Engine: Three.js r161 via ES module import map
- Self-contained single HTML, ~9 MB with 30 embedded photos as base64
- Mobile-first controls: left virtual joystick (avocado SVG), right-side touch to look (yaw-only, pitch and roll hard-locked to 0 — she's not a gamer)
- Desktop controls: WASD + mouse via PointerLock
- Rooms laid out linearly along +Z axis with walls + doorways
- Every country room has: entrance flag above doorway, floor medallion with native script, chapter overlay (country name) fades in when entering
- Painting system with emissive textures, spotlights, and interact prompt at close range
- Opens a letter room at the end with a typewriter-animated letter

## THE PROBLEM TO SOLVE (primary task)

**The album has ~426 photos. Only the first 30 are currently on disk.**

`import_from_google_photos.py` has a known limitation stated in its own docstring: it can only read the initial HTML of a Google Photos shared album, which only contains the first 30–100 photos. The rest lazy-load on scroll and are unreachable from a plain HTTP fetch.

**First task: write a Playwright script that fetches ALL photos from the album.**

Approach:
1. `pip install playwright && playwright install chromium`
2. Launch a headless browser
3. Navigate to the shared album URL (Daniel will provide)
4. Scroll to the bottom repeatedly, waiting for `networkidle`, until no new images load
5. Extract every thumbnail's `srcset` or `data-url`, convert to a 2048px download URL
6. Download all into `photos/`, resize/re-encode
7. Save the URL list to `fetched-photo-urls.txt` for provenance

Once photos are on disk:
8. Use EXIF GPS (if present) to **auto-assign each photo to a country** — no more guessing whether the hotel mirror series is Korea, Taiwan, or Thailand
9. If no GPS, use EXIF timestamps to cluster photos by trip (same day/week = same country room)
10. Regenerate `photos/{NN}.jpg` naming consistently
11. Update `exhibits` array in `index-source.html` to distribute ALL photos across their country rooms
12. Regenerate collages for photo clusters via `build_collages.py` (or individual exhibits for standout photos)
13. Re-run `embed_photos.py` to produce the shipped `index.html`

## User's stated requirements (verbatim, important)

- **"Every room should be a different country"** — country-room structure, not event-themed
- **"Each room has numerous of photos"** — many exhibits per room, not one
- **"Put them all"** — every single photo from the album must end up in the museum
- Non-gamer girlfriend — mobile controls must be dead simple, yaw-only
- Brief explanations, masterful code, proactive extra analysis

## File layout

```
memory-museum/
├── index-source.html       ← edit this; has <img src="photos/NN.jpg"> refs
├── index.html              ← generated; photos embedded as base64 via embed_photos.py
├── embed_photos.py         ← injects PHOTO_DATA map, patches TextureLoader
├── import_from_google_photos.py  ← broken for >30 photos (Playwright replaces this)
├── import_photos.py        ← helper: PLAQUES, ROOMS constants, image resize
├── build_collages.py       ← Pillow compositor: christmas grid, avocado filmstrip, arcade triptych, hotel polaroid pile
├── verify.js               ← post-embed sanity check
├── photos/
│   ├── 01.jpg..30.jpg      ← only 30 there currently
│   └── collage-*.jpg       ← christmas, avocado, arcade, hotel
└── CLAUDE.md               ← this file
```

## Build workflow (every iteration)

```bash
# 1. Parse check (catches JS errors before embedding)
node -e "const fs=require('fs'); const m=fs.readFileSync('index-source.html','utf8').match(/<script type=\"module\">([\\s\\S]*?)<\\/script>/); new Function(m[1].replace(/^import.*$/gm,'// $&')); console.log('ok')"

# 2. Embed photos into standalone HTML
python3 embed_photos.py -i index-source.html -o index.html

# 3. Test open (Daniel does this on his phone)
```

Never ship `index-source.html` — it has `src="photos/NN.jpg"` paths that only work with a web server. `index.html` has them inlined as `data:image/jpeg;base64,...`.

## Architectural decisions to preserve (DO NOT revert these)

### 1. Mobile touch: separate joystick and look touch IDs

Earlier `touchend` cleared `joyActive` on ANY release, including look touches. Fix:
```js
let joyTouchId = null, lookTouchId = null;
// touchstart: assign ID based on left/right half
// touchmove: only update the matching touch
// touchend: only clear if the ending touch ID matches
// touchcancel: also handled
```

### 2. Camera Euler order for yaw-only look

Default XYZ Euler causes Z-roll when yaw is applied with non-zero pitch:
```js
camera.rotation.order = 'YXZ';
```
Mobile touchmove explicitly locks pitch and roll:
```js
camera.rotation.x = 0;
camera.rotation.z = 0;
// Only .y updates on mobile
```

### 3. NPOT texture mipmaps cause silent failures on mobile

Canvas-generated textures (flags, country names, plaques) can have non-power-of-2 dimensions. On mobile, enabling mipmaps on these causes silent black-texture failures. ALWAYS:
```js
tex.generateMipmaps = false;
tex.minFilter = THREE.LinearFilter;
tex.magFilter = THREE.LinearFilter;
```

### 4. UV flip instead of texture.repeat.x = -1

The old `texture.repeat.x = -1` trick for mirroring text is unreliable across mobile browsers. Use geometry UV flip:
```js
const geom = new THREE.PlaneGeometry(w, h);
const uvAttr = geom.attributes.uv;
for (let i = 0; i < uvAttr.count; i++) uvAttr.setX(i, 1 - uvAttr.getX(i));
uvAttr.needsUpdate = true;
```

### 5. polygonOffset on wall/floor materials prevents Z-fighting

Paintings, signs, flags, and trim all sit <=5cm from wall surfaces. Z-fight stripes appeared as the camera moved. Fix — on every wall/floor material:
```js
polygonOffset: true,
polygonOffsetFactor: 1,
polygonOffsetUnits: 1
```
This pushes wall depth values back so overlaid elements always win the depth test. Don't remove this — overlap geometry is mathematically guaranteed to win regardless of coordinate precision.

### 6. Wall country-name sign is REMOVED on purpose

Earlier a wall sign showed the room's country name. It sat at `z = zEnd - 0.2` of each country room, which is IDENTICAL to `z = zStart - 0.2` of the next country — where the next country's flag lives. They overlapped on the same wall at the same y, causing "JAPAN" text to render on top of the China flag. The HUD Roman numeral badge + chapter overlay + floor medallion + flag above each doorway collectively identify each country. Don't re-add the wall sign.

### 7. Spotlight offset direction

`lightPos = paintingPos + normal * 1.1` (NOT `- normal`). Subtracting puts the spotlight behind the wall, so with shadow mapping enabled every painting shadows itself. This was a multi-turn bug.

### 8. No dust motes

Three.js `Points` with hard GL point sprites render as ugly pixelated yellow squares on mobile. Dust motes were removed for this reason. Don't re-add without dealing with point-sprite scaling on mobile.

### 9. Lighting is "bright gallery", not dark cave

```
ambient = 0xfff1d8 @ 1.2
hemisphere = 0xfff1d8/0x6a5344 @ 0.85
directional (sun) = 0xfff1d8 @ 0.7 from (8,20,-5)
per-room point = 1.6 intensity, range 50, decay 0.5
painting spot = 11 intensity, PI/5 cone
toneMappingExposure = 1.5
MAT.wall emissive = 0xf4ead5 @ 0.18
MAT.floor emissive = 0x5a3f28 @ 0.1
```

## Current room structure (what exists in source right now)

```
I.   Foyer         (warm tone, 8x8)    — entrance, no photos
II.  Japan         (country, 16x24)    — 22 exhibits (all Japan photos as individuals)
III. China         (country, 11x12)    — 3 exhibits (arcade photos)
IV.  Korea         (country, 11x13)    — 5 exhibits (hotel mirror photos; COUNTRY IS A GUESS)
V.   Yet to Come   (night tone, 12x10) — letter room, no photos
```

Korea's country assignment is a guess because the hotel photos lack clear country indicators. EXIF GPS from the Playwright fetch should definitively resolve this.

## Photo inventory (the 30 on disk)

- `01.jpg` — Osaka Dotonbori (Japan)
- `02-05.jpg` — Christmas tree selfie series (Japan)
- `06-13.jpg` — Avocado House Mexican restaurant dinner (Japan)
- `14-17.jpg` — "Four Strangers" bar in Japan, 5 people with Bushmills, blue lights
- `18-21.jpg` — "Second Bar" in Japan with the silver-beanie stranger
- `22-24.jpg` — CheeseZ arcade (China), Tom & Jerry walls
- `25.jpg` — Shinkansen (Japan)
- `26-30.jpg` — Hotel mirror selfies, 5 frames, same hotel (country unknown)

All 30 currently used as individual exhibits.

## Plaque voice (match this tone for new exhibits)

Short. Specific. Intimate. Present-tense observational, past-tense concrete. No metaphors about travel or love unless earned. One small specific detail (the Bushmills bottle, the silver beanie, the yellow Ebisu Tower) grounds each plaque.

Example:
> "The first bar had closed. This one hadn't. This is how good nights reshape themselves — they relocate. The lights were darker. The music was louder. We found a corner."

## What's explicitly NOT wanted

- No event-themed rooms like "Four Strangers" or "The Red Tree" as standalone rooms. User explicitly rejected this approach.
- No collage-only rooms. Individual photos as exhibits is preferred.
- No generic AI-slop plaques. Must reference specific details visible in the photo.
- No wall country-name signs (see decision #6).

## After photos are fetched — immediate next steps

1. Group photos by EXIF GPS country → assign `room:` in exhibits
2. Group photos by EXIF timestamp clusters → write unique plaque per photo (or small groups where a series makes sense)
3. Room sizes may need to grow for countries with many photos: Japan is already 16x24 to hold 22 exhibits; if it grows to 80+ photos, consider 20x40 or splitting into Japan-North and Japan-South wings
4. Flag functions currently exist for japan, china, korea, plus a generic `drawSimpleBanner`. New countries need a flag function or can use `drawSimpleBanner` with their colors + native script
5. Re-run verify (`node verify.js`) — confirms photo count, embedded count, and room structure match
6. Ship `index.html` to the user

## Testing

Daniel tests on his Pixel phone. Screenshots drive iteration. When he reports a visual bug, trace it with NUMBERS — actual coordinates, z-positions, y-ranges — not guesses. Past bugs resolved by coordinate math:
- Japan name sign at z=25.8 overlapping China flag at z=25.8 (both wrote to same pixel)
- Trim back face 1cm from wall face → full-length vertical Z-fight stripes
- Flag plane at z=zEnd-0.115 overlapping 20cm-thick wall box → flag pulled to zEnd-0.2

Every new fix should document the coordinate math in a comment.

## Deployment target

Single HTML file shipped to Daniel. He opens on his phone. He shares with Alena via direct file transfer or by hosting somewhere (previously Netlify Drop for similar projects).

---

## April 2026 session — major upgrade pass

### Pipeline changes

- `fetch_all_photos.py` — Playwright-driven album scraper, replaces the static-HTML `import_from_google_photos.py` for albums larger than ~100 photos.
- `process_photos.py` — EXIF GPS → bounded-box country detection, timestamp chronological sort, 2048px longest-edge re-encode. Writes `photo-manifest.json` as the source of truth.
- `build.py` — compiles `index-source.html` → `index.html`: inlines Three.js + PointerLockControls as importmap data URIs (no CDN at runtime), regenerates the `exhibits` block from `photo-manifest.json` (if present) and `plaques.json` (optional copy overrides), embeds every referenced photo as base64.
- Legacy `embed_photos.py` is kept for the one-file embed path; `build.py` supersedes it.

### Engine changes

- `ROOMS` is now derived from `CFG.exhibits` — country rooms are created per unique `room:` key, sized by exhibit count (1–5 / 6–15 / 16–30 / 31–60 / 60+), ordered chronologically by the first exhibit that lands in each bucket. Countries with <3 photos merge into a shared "Travels" room.
- `COUNTRY_THEMES` replaces the hardcoded three-country setup. Adding a country is one entry in the table + (optional) a flag drawer. 23 keys shipped.
- Five new flag drawers: `drawTaiwanFlag`, `drawThailandFlag`, `drawSingaporeFlag`, `drawVietnamFlag`, `drawIsraelFlag`. Dispatch table in `buildCountryAccents` falls back to `drawSimpleBanner` for anything unknown.
- Per-country procedural floor textures: tatami, lacquer, hanji, terracotta, stone, teak, jerusalem, sand, marble. Each uses `THREE.RepeatWrapping` and respects the `polygonOffset` architectural decision.
- 3D frames via `ExtrudeGeometry` — shape with rectangular hole extrudes into a beveled molding. `FRAME_THEMES` keyed by country (gold for Thailand, dark wood for Japan, deep lacquer red for China, Jerusalem bronze for Israel, brass for foyer).
- Ivory matte border between each photo and its frame (4 cm step).
- Photo-of-the-day plinth in the foyer: tall pedestal with an extruded brass frame displaying a day-of-year-seeded photo from the collection. Registered as interactable.

### Audio

- `AudioManager` — procedural Web Audio ambience. One patch per country, each schedules 8-second loops of plucked pentatonic/bell-tone notes in the country's musical scale. Zero shipped bytes. Crossfades between rooms with a 2 s linear gain ramp (200 ms under `prefers-reduced-motion`). Foyer = Satie-style major thirds. Letter room = silence on purpose.
- Old `musicUrl` in `MUSEUM_CONFIG` removed — `AudioManager.toggle()` drives the button.
- Audio pauses when the tab is hidden.

### UX additions

- **Loading cartouche**: gold-stroked progress bar + live percentage + "Daniel · Alena" line. Hard timeout at 12s so a stuck texture never traps Alena on the loading screen. Progress ticks through a wrapped `loader.load`.
- **Minimap**: one brass dot per room, top-right. Current room is highlighted + scaled; visited rooms fill in; fades to 22% opacity after 5s of no movement.
- **Pause overlay**: blurs scene, suspends audio, unlocks PointerLock. `Resume` restores exactly where she left.
- **Language toggle**: native script ↔ English on chapter overlays. Persists in `localStorage`. Re-flashes the current chapter when toggled.
- **Guestbook**: opens once after she closes the letter. Textarea + `Copy to clipboard` button + "Close" button. Stored in `localStorage`, never sent anywhere.
- **Photo zoom**: interacting with an artwork opens both the plaque (as before) AND a large photo overlay. Tap dismisses both.
- **Haptic**: `navigator.vibrate(20)` on every interact tap.
- **Safe-area insets**: HUD, control strip, and minimap respect `env(safe-area-inset-*)`.
- **Reduced motion**: a `@media (prefers-reduced-motion: reduce)` clause disables long animations and shortens transitions to 150ms.

### New architectural decisions (session 2)

#### 10. No CDN at runtime — inline importmap via `build.py`

The shipped `index.html` carries Three.js and PointerLockControls as inline data URIs inside an importmap. Opening from `file://` works; opening offline works; no jsdelivr outage can break it. `build.py` performs the inlining; `index-source.html` retains a CDN-based importmap for dev convenience only (`python3 -m http.server 8000`).

#### 11. Ambient music is procedural, not downloaded

No audio files ship. `AudioManager` builds every note via `OscillatorNode` + `BiquadFilterNode` + `GainNode`. This keeps the file under budget, dodges licensing entirely, and gives each visit a slightly different soundscape within the same scale. If Daniel later wants a specific track, drop a base64 URL in a `musicUrl` config and tee it through a parallel `<audio>` element — `AudioManager` doesn't prevent it.

#### 12. Country data-driven

Rooms, flags, floors, and frame materials all derive from the `room:` key on each exhibit + the `COUNTRY_THEMES` table. Adding a new country means one row in the table and optionally one new flag drawer. No further engine edits required.

#### 13. Letter room keeps silence

The letter room's audio patch is explicitly `null`. Silence has weight in that room. Do not add ambient music there.

### What is intentionally NOT in this build

- Intro cutscene (6s camera dolly) — the existing intro modal is the beat we want; a dolly over it felt tacked on.
- End-credits hidden doorway — ornamental, not essential.
- QR code share — the distribution model is direct file share; adds JS weight for minor value.
- WebGL-less carousel fallback — target device (Pixel) has WebGL.
- Battery API — deprecated; visibility-based pause covers the common case.
- Dust motes — architectural decision #8 still stands.

### Pipeline for Daniel

```bash
# one time (local machine, network-reachable):
pip install playwright pillow piexif aiohttp && playwright install chromium
npm install three@0.161.0  # provides node_modules/three/ for build.py

# whenever the album changes:
python3 fetch_all_photos.py "https://photos.app.goo.gl/XXXX"
python3 process_photos.py
python3 build.py
# ship index.html
```

`build.py` ignores `photo-manifest.json` automatically if it doesn't exist — so the file also builds from the 30-photo inline set in `index-source.html` (current dev state).

