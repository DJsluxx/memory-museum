# Setup — Memory Museum

**Everything's already wired up.** 30 photos imported from the `My love and I` album, consolidated into **8 exhibits across 2 country rooms (Japan + China)**, similar-scene photos combined into creative collages.

The museum opens as-is. Below is what you need to know, and what's worth editing before sending it.

---

## What you're getting

Four rooms: **Foyer → Japan → China → Yet to Come** (letter room).

Each country room has:
- Its flag displayed above the entrance doorway (visible before you walk in)
- Its name in both scripts (日本 / JAPAN, 中国 / CHINA) above the exit
- A floor medallion near the entrance in that country's colors
- Trim tinted to the flag's accent color (red for Japan, gold for China)
- A cinematic chapter-title overlay that fades in as you cross the threshold

**The 8 exhibits:**

| Room | Exhibit | Source |
|---|---|---|
| Japan | Dotonbori (solo) | photo 01 |
| Japan | The Red Tree (2×2 grid) | photos 02–05 |
| Japan | Avocado House (filmstrip w/ sprockets) | photos 06–13 |
| Japan | Four Strangers, Then Four Friends (solo) | photo 14 |
| Japan | The Second Bar (solo) | photo 18 |
| Japan | Shinkansen (solo) | photo 25 |
| China | CheeseZ (horizontal triptych) | photos 22–24 |
| China | The Room with the Teal Wall (polaroid pile) | photos 26–30 |

The collages live in `photos/collage-*.jpg`. The source photos (07–13, 15–17, 19–21, 23–24, 27–30) are still in `photos/` — unused, but kept in case you want to reference them or swap individual frames back in.

---

## Try it right now

```bash
cd memory-museum
python3 -m http.server 8000
```

Open `http://localhost:8000`. WASD + mouse on desktop. Tap-to-start on mobile gets you a virtual joystick and drag-to-look.

(You need HTTP — opening `index.html` directly as `file://` blocks subdirectory image loads in most browsers.)

---

## Make it personal (the part that matters)

Photos alone aren't the gift. **The plaques are placeholders** — atmospherically decent but generic. Spend 30 minutes rewriting them with real memories. Names, places, inside jokes, what she said, what the weather was.

In `index.html`, find `MUSEUM_CONFIG.exhibits` near the top. Eight entries. Rewrite each `title`, `date`, and `plaque`.

While you're there:
- Edit `letter:` — the final-room letter. The default is a template.
- Optional: set `musicUrl:` to a royalty-free piano track (try [FreePD](https://freepd.com/) → Solo Piano).

---

## Send it to her

**Netlify Drop.** Drag the whole `memory-museum` folder onto [app.netlify.com/drop](https://app.netlify.com/drop). You get a URL. Send it. (You've used this for projects before.)

---

## If you want to re-run the pipeline

**From a new Google Photos album URL:**
```bash
python3 import_from_google_photos.py "https://photos.app.goo.gl/NEW_LINK"
python3 build_collages.py        # regenerate collages
```
This overwrites photos/ and rewrites `index.html`'s exhibits block. **Your custom plaque edits will be lost** — back up index.html first if you've written real ones.

**From a local folder** (e.g. Takeout export):
```bash
python3 import_photos.py /path/to/folder
python3 build_collages.py
```

**Edit which photos go into which collage:**
Edit `build_collages.py` at the bottom — change the range()s. For example, to make the Christmas collage use photos 10–13 instead:
```python
xmas = [load(i) for i in range(10, 14)]
```

---

## Adding a third country (or more)

Open `index.html`, find the `ROOMS` array (~line 535). Add a new entry between "china" and "letter":

```javascript
{ key: "thailand", name: "Thailand", w: 12, d: 14, tone: "country",
  country: { native: "ประเทศไทย", english: "THAILAND",
             primary: 0xED1A3B, secondary: 0xFFFFFF, accent: 0x00247D,
             flagFn: "thailand" } },
```

Then add a `drawThailandFlag()` function in the flag canvas section (search for `drawJapanFlag`). Tag exhibits with `room: "thailand"` in the config.

---

## Troubleshooting

**Photos don't show up when opening index.html directly:**
Run a server — `python3 -m http.server 8000` — or host on Netlify.

**Mouse doesn't capture on desktop:**
Click "Enter the Gallery" first. Escape releases.

**Flag or text appears backwards:**
Shouldn't happen — the textures are pre-flipped to counter the 180° rotation used to mount them. If you see mirrored text, check that your `tex.repeat.x = -1; tex.offset.x = 1;` lines are still intact in `buildCountryAccents()` and the letter room.

**Country name or flag doesn't show:**
Every country room needs a `country` object with `native`, `english`, `primary`, `secondary`, `accent`, and `flagFn`. The `flagFn` value must match a case in the `drawFlagTexture`-style logic in `buildCountryAccents` (`"japan"` or `"china"` currently).

**She wants to see a photo again:**
Walk back. The museum is open in both directions.
