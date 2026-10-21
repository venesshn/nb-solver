"""Read a unit's identity and level off its detail page in the character box.

The page is 1180x2556. The banner names the unit in plain white text and shows
its rarity as lit stars; the plaque under the portrait shows its level. Text is
read with Tesseract and then snapped to the closed set of real units, so a few
misread letters cannot produce a unit that does not exist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np
import pytesseract

from nbsolver.models import Unit

TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
if TESSERACT.exists():
    pytesseract.pytesseract.tesseract_cmd = str(TESSERACT)

TEXT_COLS = (215, 830)
NAME_ROWS = (558, 616)
TITLE_ROWS = (622, 660)
STAR_BOX = (215, 500, 830, 545)
LEVEL_BOX = (470, 1696, 720, 1744)
# The banner text is white over orange; the darkest channel separates them.
WHITE = 170
# Level digits are white, yellow or red over a dark plaque.
BRIGHT = 170
STAR_AREA = 120
# 6-star units gain 5 levels per limit break, 100 -> 150 over 10 breaks.
SIX_STAR_STEP = 5
# Below this gap to the runner-up, a read is flagged for a human to check.
CLEAR = 0.15


@dataclass
class Reading:
    unit_id: int | None
    name: str
    title: str
    rarity: int
    level: int | None
    level_cap: int | None
    limit_break: int | None
    match: float
    margin: float
    raw_name: str
    raw_title: str
    raw_level: str
    problems: list[str]

    @property
    def certain(self) -> bool:
        return not self.problems


def normalise(text: str) -> str:
    return "".join(c for c in text.lower() if c.isalnum())


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalise(a), normalise(b)).ratio()


def _ocr(image: np.ndarray, config: str) -> str:
    image = cv2.copyMakeBorder(image, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    return pytesseract.image_to_string(image, config=config).strip()


def _white_text(page: np.ndarray, rows: tuple[int, int]) -> str:
    crop = page[rows[0] : rows[1], TEXT_COLS[0] : TEXT_COLS[1]]
    grey = cv2.resize(crop.min(axis=2), None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    ink = np.where(grey > WHITE, 0, 255).astype(np.uint8)
    return _ocr(ink, "--psm 7")


def count_stars(page: np.ndarray) -> int:
    x0, y0, x1, y1 = STAR_BOX
    hsv = cv2.cvtColor(page[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    lit = (
        (hsv[..., 0] >= 18)
        & (hsv[..., 0] <= 35)
        & (hsv[..., 1] >= 120)
        & (hsv[..., 2] >= 200)
    ).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(lit, connectivity=8)
    return int(sum(1 for s in stats[1:] if s[cv2.CC_STAT_AREA] >= STAR_AREA))


def read_level_text(page: np.ndarray) -> str:
    x0, y0, x1, y1 = LEVEL_BOX
    value = cv2.cvtColor(page[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)[..., 2]
    ink = np.where(value >= BRIGHT, 0, 255).astype(np.uint8)
    ink = cv2.resize(ink, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    return _ocr(ink, "--psm 7 -c tessedit_char_whitelist=0123456789/MAX")


def parse_level(text: str) -> tuple[int, int] | None:
    """'31/50' -> (31, 50); 'MAX/70' -> (70, 70). A faint red M can drop out."""
    match = re.search(r"(M?A?X|\d{1,3})/(\d{2,3})", text.replace(" ", ""))
    if not match:
        return None
    cap = int(match.group(2))
    current = cap if "X" in match.group(1) else int(match.group(1))
    return current, cap


def limit_breaks(unit: Unit, cap: int) -> int | None:
    """Breaks implied by the level cap; None where the step is not known."""
    if cap == unit.max_level:
        return 0
    if unit.rarity == 6:
        return (cap - unit.max_level) // SIX_STAR_STEP
    return None


def identify(
    name: str, title: str, rarity: int, units: list[Unit]
) -> tuple[Unit | None, float, float]:
    """Best unit of this rarity for the OCR'd name and title, with its lead."""
    pool = [u for u in units if u.rarity == rarity]
    scored = sorted(
        ((similarity(name, u.name) + similarity(title, u.title)) / 2, i)
        for i, u in enumerate(pool)
    )
    if not scored:
        return None, 0.0, 0.0
    best, index = scored[-1]
    second = scored[-2][0] if len(scored) > 1 else 0.0
    return pool[index], best, best - second


def read_page(page: np.ndarray, units: list[Unit]) -> Reading:
    raw_name = _white_text(page, NAME_ROWS)
    raw_title = _white_text(page, TITLE_ROWS)
    raw_level = read_level_text(page)
    rarity = count_stars(page)
    unit, match, margin = identify(raw_name, raw_title, rarity, units)

    problems = []
    if unit is None:
        problems.append(f"no {rarity}-star unit to match")
    elif margin < CLEAR:
        problems.append(f"close call: lead over runner-up only {margin:.2f}")

    level = parse_level(raw_level)
    current = cap = breaks = None
    if level is None:
        problems.append(f"level unreadable: {raw_level!r}")
    else:
        current, cap = level
        if unit is not None:
            if not unit.max_level <= cap <= unit.max_level_limit_break:
                problems.append(
                    f"level cap {cap} outside {unit.max_level}-{unit.max_level_limit_break}"
                )
            else:
                breaks = limit_breaks(unit, cap)
                if breaks is None:
                    problems.append(
                        f"limit breaks unknown for {unit.rarity}-star cap {cap}"
                    )
            if current > cap:
                problems.append(f"level {current} above cap {cap}")

    return Reading(
        unit_id=unit.unit_id if unit else None,
        name=unit.name if unit else "",
        title=unit.title if unit else "",
        rarity=rarity,
        level=current,
        level_cap=cap,
        limit_break=breaks,
        match=round(match, 3),
        margin=round(margin, 3),
        raw_name=raw_name,
        raw_title=raw_title,
        raw_level=raw_level,
        problems=problems,
    )
