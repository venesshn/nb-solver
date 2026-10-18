"""Build contact sheets of the playfield so popups can be spotted by eye."""

import sys
from pathlib import Path

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "data" / "frames" / "battle"
OUT_DIR = ROOT / "data" / "analysis" / "sheets"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FIELD_TOP, FIELD_BOTTOM = 560, 1760
STEP = 3
COLS, ROWS = 5, 5
TILE = (236, 236)

frames = sorted(FRAMES.glob("*.jpg"))[::STEP]
per_sheet = COLS * ROWS

for sheet_index in range(0, len(frames), per_sheet):
    batch = frames[sheet_index : sheet_index + per_sheet]
    tiles = []
    for frame in batch:
        image = cv2.imread(str(frame))[FIELD_TOP:FIELD_BOTTOM]
        tile = cv2.resize(image, TILE, interpolation=cv2.INTER_AREA)
        cv2.putText(
            tile, frame.stem[2:], (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3
        )
        cv2.putText(
            tile,
            frame.stem[2:],
            (4, 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
        )
        tiles.append(tile)

    while len(tiles) < per_sheet:
        tiles.append(np.zeros((TILE[1], TILE[0], 3), dtype=np.uint8))

    grid = np.vstack([np.hstack(tiles[r * COLS : (r + 1) * COLS]) for r in range(ROWS)])
    number = sheet_index // per_sheet + 1
    cv2.imwrite(str(OUT_DIR / f"sheet_{number:02d}.png"), grid)

print(f"wrote {len(range(0, len(frames), per_sheet))} sheets from {len(frames)} frames")
