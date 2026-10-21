"""Reduce the recording's stills to one frame per character viewed.

The player opens each character in turn, so the stills come in runs: several
near-identical frames while a page is open, then a jump to the next character.
Keeping the sharpest frame of each run gives one picture per unit.

    python scripts/box_pages.py [in_dir out_dir]

out_dir is deleted and recreated.
"""

import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
IN_DIR = ROOT / "data" / "analysis" / "box"
OUT_DIR = ROOT / "data" / "analysis" / "pages"

# Below this the two stills are the same page; above it the player has moved on.
NEW_PAGE = 18.0


def thumb(frame: np.ndarray) -> np.ndarray:
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.resize(grey, (64, 128), interpolation=cv2.INTER_AREA).astype(np.float32)


def sharpness(frame: np.ndarray) -> float:
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(grey, cv2.CV_64F).var())


def group(in_dir: Path = IN_DIR) -> list[list[Path]]:
    stills = sorted(in_dir.glob("*.png"))
    runs: list[list[Path]] = []
    current: list[Path] = []
    previous: np.ndarray | None = None
    for path in stills:
        small = thumb(cv2.imread(str(path)))
        if previous is not None and float(np.mean(np.abs(small - previous))) > NEW_PAGE:
            runs.append(current)
            current = []
        current.append(path)
        previous = small
    if current:
        runs.append(current)
    return runs


def main(in_dir: Path = IN_DIR, out_dir: Path = OUT_DIR) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    runs = group(in_dir)
    print(f"{sum(len(r) for r in runs)} stills -> {len(runs)} pages", flush=True)
    for number, run in enumerate(runs):
        best = max(run, key=lambda p: sharpness(cv2.imread(str(p))))
        shutil.copy(best, out_dir / f"page_{number:03d}_{best.stem}.png")
    print(f"wrote {len(runs)} pages to {out_dir}", flush=True)
    sizes = [len(r) for r in runs]
    print(
        f"frames per page: min {min(sizes)} median {int(np.median(sizes))} max {max(sizes)}",
        flush=True,
    )


if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(Path(sys.argv[1]), Path(sys.argv[2]))
    elif len(sys.argv) == 1:
        main()
    else:
        raise SystemExit(__doc__)
