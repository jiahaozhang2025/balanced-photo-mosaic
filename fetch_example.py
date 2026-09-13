#!/usr/bin/env python3
"""Download a public-domain target picture and a set of tiles to build it from.

Nothing here is redistributed with the repository: the paintings come from
Wikimedia Commons and are old enough to be in the public domain everywhere, the
emoji come from OpenMoji, and the photographs come from CIFAR-10.

    python fetch_example.py --target wave --tiles emoji

writes `examples/wave-emoji/target.jpg` and `examples/wave-emoji/tiles/`, which
is what `photomosaic.py` wants.

Requires only Pillow and numpy, like the rest of the project.
"""

from __future__ import annotations

import argparse
import io
import pickle
import shutil
import tarfile
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
# Wikimedia turns away requests with no User-Agent, and its /thumb/ paths are not
# reliably reachable; Special:FilePath is the documented way to ask for a size.
AGENT = "balanced-photo-mosaic/1.0 (https://github.com/jiahaozhang2025/balanced-photo-mosaic)"
WIKIMEDIA = "https://commons.wikimedia.org/wiki/Special:FilePath/{file}?width={width}"
OPENMOJI = "https://github.com/hfg-gmuend/openmoji/releases/latest/download/openmoji-72x72-color.zip"
CIFAR = "https://www.cs.toronto.edu/~kriz/cifar-10-python.tar.gz"

TARGETS = {
    "wave": ("Tsunami_by_hokusai_19th_century.jpg",
             "The Great Wave off Kanagawa, Hokusai, c. 1831"),
    "pearl": ("Meisje_met_de_parel.jpg",
              "Girl with a Pearl Earring, Vermeer, c. 1665"),
    "starry": ("Van_Gogh_-_Starry_Night_-_Google_Art_Project.jpg",
               "The Starry Night, Van Gogh, 1889"),
}


def fetch(url: str, timeout: int = 600):
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    return urllib.request.urlopen(request, timeout=timeout)


def get_target(name: str, width: int, out: Path) -> None:
    file, credit = TARGETS[name]
    print(f"Target: {credit}")
    with fetch(WIKIMEDIA.format(file=file, width=width)) as answer:
        picture = Image.open(io.BytesIO(answer.read())).convert("RGB")
    picture.save(out, quality=92)
    print(f"  {picture.width}x{picture.height} -> {out}")


def get_emoji_tiles(out: Path, limit: int, size: int) -> int:
    """OpenMoji's colour PNGs, flattened onto white.

    They arrive with an alpha channel, and a mosaic tile has to be opaque. Left
    alone, PIL drops alpha by keeping the RGB underneath it, which for a
    transparent pixel is black — every emoji would become a black square with a
    small coloured blob in the middle.
    """
    print(f"Fetching OpenMoji (~8 MB)...")
    with fetch(OPENMOJI) as answer:
        blob = io.BytesIO(answer.read())
    written = 0
    with zipfile.ZipFile(blob) as bundle:
        names = sorted(n for n in bundle.namelist() if n.lower().endswith(".png"))
        step = max(1, len(names) // limit) if limit else 1
        for name in names[::step][:limit or None]:
            with bundle.open(name) as handle:
                art = Image.open(handle).convert("RGBA")
            flat = Image.new("RGB", art.size, "white")
            flat.paste(art, mask=art.getchannel("A"))
            flat.resize((size, size), Image.LANCZOS).save(out / f"{Path(name).stem}.png")
            written += 1
    return written


def get_cifar_tiles(out: Path, limit: int, size: int) -> int:
    """CIFAR-10 photographs, read out of the tarball without downloading all of it.

    The archive is 163 MB of six batches; one batch is 10,000 images and is the
    first member in the stream, so reading in streaming mode and stopping there
    costs about 30 MB.
    """
    print("Streaming the first CIFAR-10 batch (~30 MB of a 163 MB archive)...")
    with fetch(CIFAR) as answer:
        with tarfile.open(fileobj=answer, mode="r|gz") as archive:
            for member in archive:
                if not member.name.endswith("data_batch_1"):
                    continue
                payload = pickle.load(archive.extractfile(member), encoding="bytes")
                break
            else:
                raise RuntimeError("data_batch_1 not found in the CIFAR-10 archive")

    flat = payload[b"data"]
    pictures = flat.reshape(-1, 3, 32, 32).transpose(0, 2, 3, 1).astype(np.uint8)
    if limit:
        pictures = pictures[:limit]
    for index, art in enumerate(pictures):
        Image.fromarray(art).resize((size, size), Image.LANCZOS).save(out / f"cifar_{index:05d}.png")
    return len(pictures)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Fetch a public-domain target and a tile set for photomosaic.py.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--target", choices=tuple(TARGETS), default="wave")
    p.add_argument("--tiles", choices=("emoji", "cifar"), default="emoji")
    p.add_argument("--tile-count", type=int, default=1200,
                   help="How many tiles to keep. 0 keeps every one, which is slower to load.")
    p.add_argument("--tile-size", type=int, default=64,
                   help="Edge of each written tile. photomosaic.py resizes again, so this "
                        "only needs to be at least as large as the --tile-size you build with.")
    p.add_argument("--width", type=int, default=900, help="Width to fetch the target at.")
    p.add_argument("--out", type=Path, default=None, help="Defaults to examples/<target>-<tiles>/")
    args = p.parse_args()

    out = args.out or ROOT / "examples" / f"{args.target}-{args.tiles}"
    tiles_dir = out / "tiles"
    shutil.rmtree(tiles_dir, ignore_errors=True)
    tiles_dir.mkdir(parents=True, exist_ok=True)

    get_target(args.target, args.width, out / "target.jpg")
    getter = get_emoji_tiles if args.tiles == "emoji" else get_cifar_tiles
    count = getter(tiles_dir, args.tile_count, args.tile_size)
    print(f"  {count} tiles -> {tiles_dir}")

    print("\nNext:")
    print(f"  python photomosaic.py {out / 'target.jpg'} {tiles_dir} "
          f"--tile-size 32 --enlargement 6 --mode meanstd --out {out / 'mosaic_meanstd.jpg'}")


if __name__ == "__main__":
    main()
