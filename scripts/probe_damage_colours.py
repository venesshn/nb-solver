"""Learn the on-screen colours of damage popups by hue-clustering vivid pixels."""

import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data" / "frames" / "battle"
OUT = ROOT / "colour_probe.txt"

# The playfield, excluding the top HUD band and the bottom unit bar.
FIELD = (0, 430, 1180, 1850)

VIVID_SAT = 110
VIVID_VAL = 150


def hue_histogram(path: Path) -> tuple[Counter, int]:
    image = Image.open(path).convert("RGB").crop(FIELD)
    hsv = np.asarray(image.convert("HSV"), dtype=np.int16)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    vivid = (sat > VIVID_SAT) & (val > VIVID_VAL)
    buckets = Counter((hue[vivid] // 10 * 10).tolist())
    return buckets, int(vivid.sum())


frames = sorted(FOLDER.glob("*.jpg"))
totals: Counter = Counter()

with OUT.open("w", encoding="utf-8") as handle:
    handle.write(f"frames available: {len(frames)}\n")
    for frame in frames[:: max(1, len(frames) // 40)][:40]:
        buckets, vivid = hue_histogram(frame)
        totals.update(buckets)
        top = ", ".join(f"h{h}:{c}" for h, c in buckets.most_common(6))
        handle.write(f"\n{frame.name} vivid={vivid:>7}  {top}")

    handle.write("\n\n===== overall hue buckets (PIL hue 0-255) =====\n")
    for hue, count in sorted(totals.items()):
        bar = "#" * min(60, count // 4000)
        handle.write(f"  h{hue:>3}: {count:>9}  {bar}\n")

print(f"wrote {OUT}")
