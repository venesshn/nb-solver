"""Dump an upscaled crop of a frame region so it can be inspected directly."""

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "data" / "frames" / "battle"
OUT = ROOT / "data" / "analysis" / "crop.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

x0, y0, x1, y1 = (int(v) for v in sys.argv[1:5])
names = sys.argv[5:] or ["b_0150.jpg"]

tiles = []
for name in names:
    crop = cv2.imread(str(FRAMES / name))[y0:y1, x0:x1]
    scale = max(1, 1400 // max(1, crop.shape[1]))
    tiles.append(
        cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    )

cv2.imwrite(str(OUT), np.vstack(tiles))
print(f"wrote {OUT} {tiles[0].shape}")
