"""Read a roster off the recording of someone paging through their box.

Two independent signals are combined. The name text is a near-perfect
fingerprint for "same character", so clustering on it says how many characters
the recording actually visits. The small square icon says which character each
one is, by comparison against the portrait library.

The icon comparison is the weaker of the two, so every entry carries the margin
by which it beat the runner-up. Sampling against units the player confirmed
owning showed the top of the list is reliable and the bottom is not, which is
why nothing here is written out as fact.
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_portraits import slug_for

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "data" / "analysis" / "pages"
PORTRAITS = ROOT / "data" / "portraits"
OUT = ROOT / "data" / "analysis" / "box_reading.json"

# Found by stacking the pages and looking for what varies; checked by eye since.
ICON = (79, 1740, 157)
NAME = (170, 500, 740, 670)
# The "Level 100/100" plaque, and within it the current/max value text.
LEVEL_PLAQUE = (320, 1680, 725, 1762)
LEVEL_VALUE = (480, 1700, 700, 1740)
SIDE = 24
SAME_NAME = 0.90
# Below this the runner-up is too close to call; sampling showed these are
# wrong more often than right.
TRUSTED = 0.05


def unit_vector(values: np.ndarray) -> np.ndarray:
    flat = values.astype(np.float32).ravel()
    flat -= flat.mean()
    norm = np.linalg.norm(flat)
    return flat / norm if norm else flat


def icon_vector(image: np.ndarray) -> np.ndarray:
    return unit_vector(cv2.resize(image, (SIDE, SIDE), interpolation=cv2.INTER_AREA))


def name_vector(image: np.ndarray) -> np.ndarray:
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return unit_vector(cv2.resize(grey, (142, 42), interpolation=cv2.INTER_AREA))


def library() -> tuple[list[str], np.ndarray]:
    """Portraits of everything a player could own, as comparable vectors."""
    index = json.loads((PORTRAITS / "index.json").read_text(encoding="utf-8"))
    units = json.loads((ROOT / "data" / "units.json").read_text(encoding="utf-8"))
    playable = {
        slug_for(u["name"], u.get("title") or "")
        for u in units
        if (u.get("rarity") or 0) >= 4
    }
    slugs, rows = [], []
    for slug, icon in index.items():
        if slug not in playable:
            continue
        raw = cv2.imread(str(PORTRAITS / f"{icon}.webp"), cv2.IMREAD_UNCHANGED)
        if raw.shape[2] == 4:
            raw = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
        slugs.append(slug)
        rows.append(icon_vector(raw))
    return slugs, np.stack(rows)


def visits(names: np.ndarray) -> list[list[int]]:
    """Group pages showing the same name text; a group is one character."""
    similarity = names @ names.T
    taken = [False] * len(names)
    groups = []
    for i in range(len(names)):
        if taken[i]:
            continue
        members = [
            j
            for j in range(len(names))
            if not taken[j] and similarity[i, j] >= SAME_NAME
        ]
        for j in members:
            taken[j] = True
        if members:
            groups.append(members)
    return groups


def read(pages_dir: Path = PAGES) -> list[dict]:
    slugs, tiles = library()
    x, y, size = ICON
    nx0, ny0, nx1, ny1 = NAME

    paths = sorted(pages_dir.glob("*.png"))
    icons, names = [], []
    for path in paths:
        page = cv2.imread(str(path))
        icons.append(icon_vector(page[y : y + size, x : x + size]))
        names.append(name_vector(page[ny0:ny1, nx0:nx1]))

    scores = tiles @ np.stack(icons).T
    ranked = np.argsort(scores, axis=0)[::-1]
    pages = range(scores.shape[1])
    best, second = scores[ranked[0], pages], scores[ranked[1], pages]

    found = []
    for group in visits(np.stack(names)):
        page = max(group, key=lambda j: best[j] - second[j])
        margin = float(best[page] - second[page])
        if best[page] == 0:  # a flat crop: this page is not a character page
            continue
        found.append(
            {
                "slug": slugs[ranked[0][page]],
                "score": round(float(best[page]), 3),
                "margin": round(margin, 3),
                "pages": len(group),
                "trusted": margin >= TRUSTED,
                "runner_up": slugs[ranked[1][page]],
                "page": paths[page].name,
            }
        )
    return sorted(found, key=lambda f: -f["margin"])


def main(pages_dir: Path = PAGES, out: Path = OUT) -> None:
    found = read(pages_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(found, indent=2), encoding="utf-8")
    trusted = sum(1 for f in found if f["trusted"])
    print(f"{len(found)} characters visited, {trusted} read confidently")
    for entry in found:
        mark = " " if entry["trusted"] else "?"
        print(f" {mark} {entry['score']:.3f} +{entry['margin']:.3f}  {entry['slug']}")


if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(Path(sys.argv[1]), Path(sys.argv[2]))
    elif len(sys.argv) == 1:
        main()
    else:
        raise SystemExit("usage: read_box.py [pages_dir out_json]")
