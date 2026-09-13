#!/usr/bin/env python3
"""
Photomosaic with balanced tile usage.

For each cell of the mosaic:
  1) Choose a source image — by default the next one from a shuffled sequence
     that uses every tile about equally, rather than whichever happens to be
     closest in colour.
  2) Recolour it so its statistics match the target patch.
  3) Paste.

Both steps are switchable, which is what makes the comparison in the README
reproducible from this one script:

  --select balanced   every tile used about equally (default)
  --select nearest    the conventional photomosaic: closest tile by mean colour
  --no-recolor        paste tiles untouched

Usage:
  python photomosaic.py target.jpg ./tiles \
    --tile-size 50 --enlargement 8 --mode meanstd --seed 123 \
    --out mosaic.jpeg

`fetch_example.py` will download a public-domain target and a tile set to try
it on.

Requires: Pillow, numpy
  pip install pillow numpy
"""

import os
import sys
import math
import random
import argparse
from typing import List, Tuple
import numpy as np
from PIL import Image, ImageOps

# ------------- color matching helpers -------------
EPS = 1e-6  # numeric stability

def _to_np_rgb(pixels: List[Tuple[int, int, int]]) -> np.ndarray:
    # pixels: list of (R,G,B) uint8
    arr = np.frombuffer(bytearray([c for px in pixels for c in px]), dtype=np.uint8)
    return arr.reshape(-1, 3).astype(np.float32)

def _clip_back(arr: np.ndarray) -> List[Tuple[int, int, int]]:
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return [tuple(px) for px in arr.tolist()]

def _rgb_to_yuv(rgb: np.ndarray) -> np.ndarray:
    M = np.array([[ 0.299,  0.587,  0.114],
                  [-0.147, -0.289,  0.436],
                  [ 0.615, -0.515, -0.100]], dtype=np.float32)
    return rgb @ M.T

def _yuv_to_rgb(yuv: np.ndarray) -> np.ndarray:
    M = np.array([[1.0,  0.0,     1.13983],
                  [1.0, -0.39465, -0.58060],
                  [1.0,  2.03211,  0.0    ]], dtype=np.float32)
    return yuv @ M.T

def color_match_pixels(tile_pixels: List[Tuple[int,int,int]],
                       target_pixels: List[Tuple[int,int,int]],
                       mode: str = "meanstd") -> List[Tuple[int,int,int]]:
    """
    Match tile_pixels' color statistics to those of target_pixels.
    mode: "mean" | "meanstd" | "luma"
    """
    t = _to_np_rgb(tile_pixels)
    g = _to_np_rgb(target_pixels)

    if mode == "luma":
        yuv_t = _rgb_to_yuv(t); yuv_g = _rgb_to_yuv(g)
        y_t = yuv_t[:, 0]; y_g = yuv_g[:, 0]
        mu_t, mu_g = y_t.mean(), y_g.mean()
        sd_t, sd_g = y_t.std(), y_g.std()
        gain = (sd_g / (sd_t + EPS)) if sd_t > EPS else 1.0
        bias = mu_g - mu_t * gain
        yuv_t[:, 0] = y_t * gain + bias
        rgb_new = _yuv_to_rgb(yuv_t)
        return _clip_back(rgb_new)

    mu_t = t.mean(axis=0)
    mu_g = g.mean(axis=0)

    if mode == "mean":
        out = t + (mu_g - mu_t)
        return _clip_back(out)

    # "meanstd"
    sd_t = t.std(axis=0)
    sd_g = g.std(axis=0)
    gain = sd_g / (sd_t + EPS)
    out = (t - mu_t) * gain + mu_g
    return _clip_back(out)

# ------------- IO + prep -------------
def load_target(path: str, enlargement: int, tile_size: int) -> Image.Image:
    img = Image.open(path).convert("RGB")
    w = img.size[0] * enlargement
    h = img.size[1] * enlargement
    big = img.resize((w, h), Image.LANCZOS)

    # Crop so dimensions are exact multiples of tile_size
    w_diff = (w % tile_size) // 2
    h_diff = (h % tile_size) // 2
    if w_diff or h_diff:
        big = big.crop((w_diff, h_diff, w - w_diff, h - h_diff))
    return big

def crop_square(im: Image.Image) -> Image.Image:
    w, h = im.size
    s = min(w, h)
    x = (w - s) // 2
    y = (h - s) // 2
    return im.crop((x, y, x + s, y + s))

def load_tiles(tiles_dir: str, tile_size: int) -> List[Image.Image]:
    tiles: List[Image.Image] = []
    print(f"Reading tiles from {tiles_dir} ...")
    for root, _, files in os.walk(tiles_dir):
        for name in files:
            p = os.path.join(root, name)
            try:
                im = Image.open(p)
                im = ImageOps.exif_transpose(im).convert("RGB")
                im = crop_square(im).resize((tile_size, tile_size), Image.LANCZOS)
                tiles.append(im)
                if len(tiles) % 100 == 0:
                    print(f"  loaded {len(tiles)} tiles...", end="\r")
            except Exception:
                # skip unreadable/corrupt or unsupported files
                pass
    print(f"Loaded {len(tiles)} tiles total.")
    if not tiles:
        raise RuntimeError("No valid tiles found.")
    return tiles

# ------------- tile selection -------------
def make_balanced_assignments(num_tiles: int, total_cells: int, rng: random.Random) -> List[int]:
    """
    Repeat [0..num_tiles-1] enough times to cover total_cells, shuffle once,
    and trim. Ensures each tile is used ~equally often.
    """
    repeats = math.ceil(total_cells / num_tiles)
    base = list(range(num_tiles)) * repeats
    rng.shuffle(base)
    return base[:total_cells]


def tile_mean_colors(tiles: List[Image.Image]) -> np.ndarray:
    """Average RGB of every tile, for the conventional nearest-colour search."""
    return np.stack([np.asarray(t, dtype=np.float32).reshape(-1, 3).mean(axis=0) for t in tiles])


def nearest_tile(tile_means: np.ndarray, patch: np.ndarray) -> int:
    """The conventional choice: whichever tile's average colour is closest.

    This is what makes a classic photomosaic repetitive. A large flat region of
    sky asks the same question of the same tile set several thousand times and
    gets the same answer every time.
    """
    return int(np.argmin(((tile_means - patch.mean(axis=0)) ** 2).sum(axis=1)))

# ------------- mosaic builder -------------
def build_mosaic_random(target_big: Image.Image,
                        tiles: List[Image.Image],
                        mode: str,
                        seed: int,
                        out_path: str,
                        tile_size: int,
                        select: str = "balanced",
                        recolor: bool = True):
    W, H = target_big.size
    x_count = W // tile_size
    y_count = H // tile_size
    total_cells = x_count * y_count
    print(f"Grid: {x_count} x {y_count} = {total_cells} tiles "
          f"({select} selection, {'recoloured' if recolor else 'untouched'})")

    rng = random.Random(seed)
    assignments = make_balanced_assignments(len(tiles), total_cells, rng)
    tile_means = tile_mean_colors(tiles) if select == "nearest" else None

    # pre-extract pixel data for tiles to avoid repeated .getdata() calls
    tiles_pixels = [list(t.getdata()) for t in tiles]
    usage = np.zeros(len(tiles), dtype=np.int64)

    mosaic = Image.new("RGB", (W, H))

    # progress printing
    done = 0
    for yi in range(y_count):
        for xi in range(x_count):
            idx = yi * x_count + xi
            tx = xi * tile_size
            ty = yi * tile_size
            box = (tx, ty, tx + tile_size, ty + tile_size)

            # target patch pixels
            target_patch = list(target_big.crop(box).getdata())

            # pick the tile: balanced sequence, or the conventional nearest colour
            if tile_means is None:
                tile_idx = assignments[idx]
            else:
                tile_idx = nearest_tile(tile_means, _to_np_rgb(target_patch))
            usage[tile_idx] += 1
            tile_px = tiles_pixels[tile_idx]

            if recolor:
                tile_px = color_match_pixels(tile_px, target_patch, mode=mode)

            # paste
            tile_img = Image.new("RGB", (tile_size, tile_size))
            tile_img.putdata(tile_px)
            mosaic.paste(tile_img, box)

            done += 1
            if done % max(1, total_cells // 100) == 0:
                pct = (done / total_cells) * 100
                print(f"Progress: {pct:5.1f}%", end="\r")

    mosaic.save(out_path, quality=95)
    used = int((usage > 0).sum())
    print(f"\nTile usage: {used}/{len(tiles)} tiles used, "
          f"most-used appears {int(usage.max()):,} times "
          f"({usage.max() / total_cells:.1%} of the mosaic)")
    print(f"Finished. Wrote {out_path}")

# ------------- CLI -------------
def parse_args():
    p = argparse.ArgumentParser(description="Random-assign mosaic with per-cell color matching.")
    p.add_argument("image", help="Target image path")
    p.add_argument("tiles", help="Directory of tile images (recursively scanned)")
    p.add_argument("--tile-size", type=int, default=50, help="Tile size in pixels (square)")
    p.add_argument("--enlargement", type=int, default=8, help="Scale factor for the output mosaic vs. input")
    p.add_argument("--mode", choices=["mean", "meanstd", "luma"], default="meanstd",
                   help="Color match mode (mean=biased tint; meanstd=match mean+std; luma=match brightness/contrast only)")
    p.add_argument("--select", choices=["balanced", "nearest"], default="balanced",
                   help="balanced uses every tile about equally; nearest is the conventional "
                        "photomosaic, picking the closest tile by mean colour")
    p.add_argument("--no-recolor", action="store_true",
                   help="Paste tiles untouched. With --select nearest that is the classic "
                        "photomosaic; with balanced it is noise.")
    p.add_argument("--seed", type=int, default=12345, help="Random seed for balanced assignment")
    p.add_argument("--out", default="mosaic.jpeg", help="Output filename")
    return p.parse_args()

def main():
    args = parse_args()

    # load & prep
    target_big = load_target(args.image, args.enlargement, args.tile_size)
    tiles = load_tiles(args.tiles, args.tile_size)

    # build
    build_mosaic_random(
        target_big=target_big,
        tiles=tiles,
        mode=args.mode,
        seed=args.seed,
        out_path=args.out,
        tile_size=args.tile_size,
        select=args.select,
        recolor=not args.no_recolor,
    )

if __name__ == "__main__":
    main()
