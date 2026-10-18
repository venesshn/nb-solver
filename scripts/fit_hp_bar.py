"""Fit the team health bar: where it starts, where it ends, how fill maps to HP."""

import sys
from pathlib import Path

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "data" / "frames" / "battle"
OUT = ROOT / "data" / "analysis" / "hp_bar_fit.txt"

# Rows safely inside the bar, and HP read off these frames by eye.
BAR_ROWS = (1872, 1912)
KNOWN = {"b_0032.jpg": 9296, "b_0150.jpg": 8540, "b_0450.jpg": 8339}
MAX_HP = 9296


def rightmost_fill(path: Path) -> tuple[int, np.ndarray]:
    image = cv2.imread(str(path))[BAR_ROWS[0] : BAR_ROWS[1]]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    # The fill is a strongly saturated green; the gold numerals sit well below it in hue.
    green = (hue >= 55) & (hue <= 75) & (sat > 150) & (val > 90)
    columns = green.sum(axis=0)
    filled = np.flatnonzero(columns > 8)
    return (int(filled[-1]) if filled.size else -1), columns


lines = []
points = []
for name, hp in KNOWN.items():
    edge, columns = rightmost_fill(FRAMES / name)
    first = int(np.flatnonzero(columns > 8)[0])
    lines.append(f"{name}  hp={hp:>5}  first_green={first:>5}  last_green={edge:>5}")
    points.append((hp / MAX_HP, edge))

# Two points define the bar; the third is the check that it is really linear.
(f1, x1), (f2, x2), (f3, x3) = points
span = (x1 - x2) / (f1 - f2)
start = x1 - span * f1
predicted = start + span * f3

lines.append("")
lines.append(f"bar start x = {start:.1f}")
lines.append(f"bar span px = {span:.1f}  (so bar ends at {start + span:.1f})")
lines.append(f"check {list(KNOWN)[2]}: predicted edge {predicted:.1f}, measured {x3}")
lines.append(
    f"error = {abs(predicted - x3):.1f}px = {abs(predicted - x3) / span * MAX_HP:.0f} HP"
)

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
