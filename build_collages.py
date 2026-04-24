#!/usr/bin/env python3
"""
Generate creative collages from clusters of similar photos.

Outputs to photos/:
    collage-christmas.jpg     # 2x2 grid of photos 02-05
    collage-avocado.jpg       # filmstrip with sprocket holes, photos 06-13
    collage-arcade.jpg        # horizontal triptych, photos 22-24
    collage-hotel.jpg         # overlapping polaroid pile, photos 26-30
"""
from __future__ import annotations
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

PHOTOS = Path("photos")
random.seed(42)  # deterministic layout

# ---------- helpers ----------

def load(n: int) -> Image.Image:
    return Image.open(PHOTOS / f"{n:02d}.jpg")

def fit_in(img: Image.Image, w: int, h: int) -> Image.Image:
    iw, ih = img.size
    s = min(w / iw, h / ih)
    return img.resize((max(1, int(iw * s)), max(1, int(ih * s))), Image.LANCZOS)

def cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale to cover (w, h), center-crop overflow."""
    iw, ih = img.size
    s = max(w / iw, h / ih)
    nw, nh = int(iw * s), int(ih * s)
    resized = img.resize((nw, nh), Image.LANCZOS)
    x = (nw - w) // 2
    y = (nh - h) // 2
    return resized.crop((x, y, x + w, y + h))

# ---------- collage 1: proof-sheet grid ----------

def proof_grid(photos, cols, rows, cell_w, cell_h,
               gap=36, bg=(13, 11, 8), border=(196, 160, 90), border_w=3,
               label=None):
    """Gallery proof-sheet layout. Cells fit with aspect preserved, gold hairline border."""
    outer_pad = 60
    label_h = 100 if label else 0
    W = outer_pad * 2 + cols * cell_w + (cols - 1) * gap
    H = outer_pad * 2 + rows * cell_h + (rows - 1) * gap + label_h
    out = Image.new('RGB', (W, H), bg)
    draw = ImageDraw.Draw(out)
    for i, p in enumerate(photos[:cols * rows]):
        c, r = i % cols, i // cols
        p2 = fit_in(p, cell_w, cell_h)
        nw, nh = p2.size
        x = outer_pad + c * (cell_w + gap) + (cell_w - nw) // 2
        y = outer_pad + r * (cell_h + gap) + (cell_h - nh) // 2
        out.paste(p2, (x, y))
        draw.rectangle([x - 2, y - 2, x + nw + 1, y + nh + 1],
                       outline=border, width=border_w)
    # Outer hairline border + corner accents
    draw.rectangle([outer_pad - 20, outer_pad - 20, W - outer_pad + 20, H - outer_pad + 20 - label_h],
                   outline=border, width=1)
    return out

# ---------- collage 2: filmstrip with sprocket holes ----------

def filmstrip(photos, frame_w=440, frame_h=620, frames_per_row=4,
              sprocket_h=60, sprocket_count=6, inner_pad=14,
              bg=(10, 9, 8), film_bg=(18, 16, 14),
              sprocket_color=(240, 232, 210)):
    """Classic 35mm filmstrip aesthetic. Two rows of 4 (for 8 photos).
    Sprocket holes at top and bottom of each row."""
    n = len(photos)
    rows = 2
    cols = frames_per_row

    # Per-row dimensions
    row_w = cols * frame_w + (cols + 1) * inner_pad
    row_h = sprocket_h + frame_h + sprocket_h + inner_pad * 2
    gap_between_rows = 30
    total_h = rows * row_h + (rows - 1) * gap_between_rows
    total_w = row_w

    out = Image.new('RGB', (total_w, total_h), bg)

    def draw_row(row_idx, photos_for_row, y_off):
        row_img = Image.new('RGB', (row_w, row_h), film_bg)
        draw = ImageDraw.Draw(row_img)
        # Sprocket holes top
        hole_w = int(frame_w * 0.45)
        hole_h = int(sprocket_h * 0.55)
        for c in range(cols):
            cx = inner_pad + c * (frame_w + inner_pad) + frame_w // 2
            # top sprocket
            draw.rounded_rectangle(
                [cx - hole_w // 2, (sprocket_h - hole_h) // 2,
                 cx + hole_w // 2, (sprocket_h + hole_h) // 2],
                radius=8, fill=sprocket_color)
            # bottom sprocket
            cy2 = sprocket_h + frame_h + sprocket_h + (sprocket_h - hole_h) // 2
            bot_y = row_h - sprocket_h + (sprocket_h - hole_h) // 2
            draw.rounded_rectangle(
                [cx - hole_w // 2, bot_y,
                 cx + hole_w // 2, bot_y + hole_h],
                radius=8, fill=sprocket_color)
        # Photos in cells
        for c, photo in enumerate(photos_for_row):
            cell_x = inner_pad + c * (frame_w + inner_pad)
            cell_y = sprocket_h + inner_pad
            # White frame border
            draw.rectangle([cell_x, cell_y, cell_x + frame_w, cell_y + frame_h],
                           outline=(230, 222, 200), width=2)
            # Fill frame with cover-cropped photo (like film frame fully exposed)
            p_cover = cover(photo, frame_w - 4, frame_h - 4)
            row_img.paste(p_cover, (cell_x + 2, cell_y + 2))
        out.paste(row_img, (0, y_off))

    for i in range(rows):
        row_photos = photos[i * cols:(i + 1) * cols]
        draw_row(i, row_photos, i * (row_h + gap_between_rows))

    return out

# ---------- collage 3: triptych ----------

def triptych(photos, panel_w=780, panel_h=1320, gap=24, border_w=6,
             bg=(10, 9, 8), frame_color=(196, 160, 90), outer_pad=60):
    """3-panel horizontal triptych with gold dividers."""
    assert len(photos) >= 3
    W = outer_pad * 2 + 3 * panel_w + 2 * gap
    H = outer_pad * 2 + panel_h
    out = Image.new('RGB', (W, H), bg)
    draw = ImageDraw.Draw(out)
    for i, p in enumerate(photos[:3]):
        x = outer_pad + i * (panel_w + gap)
        y = outer_pad
        cropped = cover(p, panel_w, panel_h)
        out.paste(cropped, (x, y))
        # Gold frame around each panel
        draw.rectangle([x - border_w // 2, y - border_w // 2,
                        x + panel_w + border_w // 2, y + panel_h + border_w // 2],
                       outline=frame_color, width=border_w)
    # Outer hairline
    draw.rectangle([outer_pad - 30, outer_pad - 30, W - outer_pad + 30, H - outer_pad + 30],
                   outline=frame_color, width=1)
    return out

# ---------- collage 4: polaroid pile ----------

def polaroid(photo: Image.Image, size=560, caption_h=130, border=20,
             bg=(245, 234, 213)):
    """Single polaroid-style frame."""
    frame_w = size + 2 * border
    frame_h = size + border + caption_h
    out = Image.new('RGB', (frame_w, frame_h), bg)
    # Cover-crop photo into square window
    p = cover(photo, size, size)
    out.paste(p, (border, border))
    # Faint inner shadow (classic polaroid edge)
    d = ImageDraw.Draw(out)
    d.rectangle([border - 1, border - 1, border + size, border + size],
                outline=(120, 100, 70), width=1)
    return out

def polaroid_pile(photos, canvas=(2400, 1600), bg=(13, 11, 8)):
    """5 polaroids scattered on a dark surface at varied rotations, with soft shadows."""
    out = Image.new('RGBA', canvas, bg + (255,))
    W, H = canvas
    # Manual layout to avoid random collisions; spread across canvas in a relaxed arc
    layouts = [
        dict(pos=(0.18, 0.58), angle=-13, scale=1.00),
        dict(pos=(0.36, 0.42), angle=+7,  scale=1.08),
        dict(pos=(0.54, 0.55), angle=-5,  scale=1.02),
        dict(pos=(0.72, 0.40), angle=+9,  scale=1.05),
        dict(pos=(0.87, 0.60), angle=-8,  scale=0.98),
    ]
    for photo, lay in zip(photos, layouts):
        pol = polaroid(photo, size=int(560 * lay['scale']),
                       caption_h=int(130 * lay['scale']),
                       border=int(20 * lay['scale']))
        pol_rgba = pol.convert('RGBA')
        # Build a soft drop shadow layer
        sh = Image.new('RGBA', pol_rgba.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rectangle(
            [0, 0, pol_rgba.size[0], pol_rgba.size[1]],
            fill=(0, 0, 0, 140))
        sh = sh.filter(ImageFilter.GaussianBlur(radius=18))
        # Rotate both
        pol_rot = pol_rgba.rotate(lay['angle'], expand=True, resample=Image.BICUBIC)
        sh_rot = sh.rotate(lay['angle'], expand=True, resample=Image.BICUBIC)
        pw, ph = pol_rot.size
        cx, cy = int(W * lay['pos'][0]), int(H * lay['pos'][1])
        # Paste shadow offset, then polaroid on top
        out.paste(sh_rot, (cx - pw // 2 + 18, cy - ph // 2 + 22), sh_rot)
        out.paste(pol_rot, (cx - pw // 2, cy - ph // 2), pol_rot)
    return out.convert('RGB')

# ---------- main ----------

def main():
    if not PHOTOS.exists():
        raise SystemExit(f"No photos/ folder found in {Path.cwd()}")

    print("Generating collages...\n")

    # 1) Christmas tree: 2x2 proof grid (photos 02-05, portrait)
    xmas = [load(i) for i in range(2, 6)]
    img = proof_grid(xmas, cols=2, rows=2, cell_w=850, cell_h=1135)
    img.save(PHOTOS / "collage-christmas.jpg", quality=85, optimize=True, progressive=True)
    print(f"  collage-christmas.jpg  {img.size[0]}x{img.size[1]}  (2x2 proof grid)")

    # 2) Avocado House: 2x4 filmstrip with sprocket holes (photos 06-13, portrait)
    avo = [load(i) for i in range(6, 14)]
    img = filmstrip(avo, frame_w=440, frame_h=620, frames_per_row=4)
    img.save(PHOTOS / "collage-avocado.jpg", quality=85, optimize=True, progressive=True)
    print(f"  collage-avocado.jpg    {img.size[0]}x{img.size[1]}  (2x4 filmstrip w/ sprockets)")

    # 3) China arcade: horizontal triptych (photos 22-24, portrait)
    arc = [load(i) for i in range(22, 25)]
    img = triptych(arc, panel_w=780, panel_h=1320)
    img.save(PHOTOS / "collage-arcade.jpg", quality=85, optimize=True, progressive=True)
    print(f"  collage-arcade.jpg     {img.size[0]}x{img.size[1]}  (horizontal triptych)")

    # 4) Hotel: polaroid pile (photos 26-30, portrait)
    hot = [load(i) for i in range(26, 31)]
    img = polaroid_pile(hot, canvas=(2400, 1500))
    img.save(PHOTOS / "collage-hotel.jpg", quality=85, optimize=True, progressive=True)
    print(f"  collage-hotel.jpg      {img.size[0]}x{img.size[1]}  (polaroid pile, 5 frames)")

    print("\nDone. Collages saved alongside source photos.")

if __name__ == "__main__":
    main()
