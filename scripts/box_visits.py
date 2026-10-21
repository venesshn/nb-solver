"""Cut a box recording into one page per unit visited.

Moving to the next unit fades the screen to black, so the black frames mark the
boundaries exactly. Splitting on them, rather than on how different consecutive
frames look, keeps duplicate units apart: two copies of the same unit look
identical but are still separated by a fade.

    python scripts/box_visits.py path/to/recording.mov out_dir

out_dir is deleted and recreated.
"""

import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Rows outside the status bar, sampled sparsely; enough to tell black from not.
ROWS = slice(130, 2300, 8)
DARK = 10.0
# Fades in and out are excluded by keeping only frames this close to the
# visit's full brightness.
BRIGHT = 0.97
MIN_VISIT_SECONDS = 0.5
STEP = 3


def brightness(frame: np.ndarray) -> float:
    return float(frame[ROWS, ::8].mean())


def sharpness(frame: np.ndarray) -> float:
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(grey, cv2.CV_64F).var())


def segments(levels: np.ndarray, min_frames: int) -> list[tuple[int, int]]:
    """Runs of non-black frames, each one unit's page."""
    lit = levels >= DARK
    runs, start = [], None
    for i, on in enumerate(lit):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(lit)))
    return [(a, b) for a, b in runs if b - a >= min_frames]


def candidates(video: Path) -> tuple[float, np.ndarray]:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise SystemExit(f"could not open {video}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    levels = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        levels.append(brightness(frame))
    capture.release()
    return fps, np.array(levels)


def main(video: Path, out_dir: Path) -> None:
    fps, levels = candidates(video)
    visits = segments(levels, round(MIN_VISIT_SECONDS * fps))
    print(f"{len(levels)} frames, {len(visits)} visits", flush=True)

    wanted: dict[int, int] = {}
    for number, (a, b) in enumerate(visits):
        peak = levels[a:b].max()
        for i in range(a, b, STEP):
            if levels[i] >= BRIGHT * peak:
                wanted[i] = number

    best: dict[int, tuple[float, int, np.ndarray]] = {}
    capture = cv2.VideoCapture(str(video))
    index = 0
    while True:
        if index not in wanted:
            if not capture.grab():
                break
            index += 1
            continue
        ok, frame = capture.read()
        if not ok:
            break
        number = wanted[index]
        score = sharpness(frame)
        if number not in best or score > best[number][0]:
            best[number] = (score, index, frame)
        index += 1
    capture.release()

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    for number, (_, index, frame) in sorted(best.items()):
        cv2.imwrite(
            str(out_dir / f"visit_{number:03d}_{index / fps:07.2f}s.png"), frame
        )
    lengths = [(b - a) / fps for a, b in visits]
    print(
        f"wrote {len(best)} pages to {out_dir}; visit length "
        f"min {min(lengths):.2f}s median {np.median(lengths):.2f}s max {max(lengths):.2f}s",
        flush=True,
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
