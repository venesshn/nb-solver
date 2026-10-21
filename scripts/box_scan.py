"""Turn a screen recording of the character box into readable stills.

Scrolling footage is mostly motion blur. This keeps the frames where the list
has come to rest, and throws away the ones that only repeat what we already saw.

    python scripts/box_scan.py path/to/recording.mp4
"""

import sys
from pathlib import Path

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "analysis" / "box"

SAMPLE_FPS = 4.0
# Below this much movement between frames the list has settled enough to read.
STILL = 1.2
# A settled frame is only worth keeping if it shows something new.
NOVEL = 4.0
# If the scroll never pauses, take what we can rather than nothing at all.
MAX_GAP_SECONDS = 1.5


def _difference(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(cv2.absdiff(a, b)))


def _thumbnail(frame: np.ndarray) -> np.ndarray:
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.resize(grey, (160, 284), interpolation=cv2.INTER_AREA)


def scan(video: Path) -> int:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise SystemExit(f"could not open {video}")

    source_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(source_fps / SAMPLE_FPS))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUT_DIR.glob("*.png"):
        stale.unlink()

    previous: np.ndarray | None = None
    last_saved: np.ndarray | None = None
    saved = index = since_save = 0

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if index % step:
            index += 1
            continue
        index += 1

        small = _thumbnail(frame)
        motion = _difference(small, previous) if previous is not None else 99.0
        previous = small

        novelty = _difference(small, last_saved) if last_saved is not None else 99.0
        overdue = since_save >= MAX_GAP_SECONDS * SAMPLE_FPS
        if novelty < NOVEL or (motion > STILL and not overdue):
            since_save += 1
            continue

        seconds = index / source_fps
        out = OUT_DIR / f"box_{saved:03d}_{seconds:07.2f}s.png"
        cv2.imwrite(str(out), frame)
        last_saved = small
        saved += 1
        since_save = 0

    capture.release()
    return saved


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    count = scan(Path(sys.argv[1]))
    print(f"kept {count} stills in {OUT_DIR}")
