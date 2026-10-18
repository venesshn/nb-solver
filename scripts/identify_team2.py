import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import pytesseract
from PIL import Image

from nbsolver.catalogue import UNITS_PATH
from nbsolver.models import Unit

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

FOLDER = Path(r"C:\Users\venes\Downloads\Photos-1-001")
units = [Unit.model_validate(u) for u in json.loads(UNITS_PATH.read_text(encoding="utf-8"))]
NAMES = sorted({u.name for u in units})

DIGIT_FIXES = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "S": "5", "B": "8"})


def ocr_lines(path: Path) -> list[str]:
    """Colour at native size reads the stat panel; 2x reads the stylised header."""
    image = Image.open(path)
    passes = [image, image.resize((image.width * 2, image.height * 2), Image.LANCZOS)]
    lines: list[str] = []
    for variant in passes:
        text = pytesseract.image_to_string(variant)
        lines.extend(ln.strip() for ln in text.splitlines() if ln.strip())
    return lines


def partial_ratio(needle: str, haystack: str) -> float:
    """Best similarity of `needle` against any same-length window of `haystack`."""
    needle, haystack = needle.lower(), haystack.lower()
    if not needle or not haystack:
        return 0.0
    if len(haystack) <= len(needle):
        return SequenceMatcher(None, needle, haystack).ratio()
    return max(
        SequenceMatcher(None, needle, haystack[i : i + len(needle)]).ratio()
        for i in range(len(haystack) - len(needle) + 1)
    )


def best_match(options: list[str], lines: list[str]) -> tuple[str, float]:
    best, score = "", 0.0
    for option in options:
        hit = max((partial_ratio(option, line) for line in lines), default=0.0)
        if hit > score:
            best, score = option, hit
    return best, score


def labelled_number(lines: list[str], *fragments: str) -> int | None:
    for line in lines:
        cleaned = line.translate(DIGIT_FIXES)
        lowered = cleaned.lower()
        for fragment in fragments:
            idx = lowered.find(fragment)
            if idx >= 0 and (digits := re.findall(r"\d{1,5}", cleaned[idx:])):
                return int(digits[0])
    return None


def best_level(unit: Unit, health: int | None, strength: int | None) -> tuple[int, float]:
    if health is None and strength is None:
        return unit.max_level, float("inf")
    best, best_error = unit.max_level, float("inf")
    for level in range(1, unit.max_level + 1):
        stats = unit.stats_at(level)
        error = 0.0
        if health is not None:
            error += abs(stats.health - health) / max(health, 1)
        if strength is not None:
            error += abs(stats.attack - strength) / max(strength, 1)
        if error < best_error:
            best, best_error = level, error
    return best, best_error


for path in sorted(FOLDER.glob("*.PNG")):
    lines = ocr_lines(path)

    name, name_score = best_match(NAMES, lines)
    cost = labelled_number(lines, "cost")
    level = labelled_number(lines, "level", "evel", "vevel")
    health = labelled_number(lines, "health", "ealth", "ona ")
    strength = labelled_number(lines, "strength", "ength", "engih", "treng")
    luck = labelled_number(lines, "luck", "lodk", "uck")

    print(f"\n===== {path.name} =====")
    print(
        f"  name={name!r} ({name_score:.2f}) cost={cost} level={level}"
        f" health={health} strength={strength} luck={luck}"
    )

    candidates = [u for u in units if u.name == name]
    titles = sorted({u.title for u in candidates})
    title, title_score = best_match(titles, lines)
    print(f"  title={title!r} ({title_score:.2f})")

    if title_score > 0.6:
        candidates = [u for u in candidates if u.title == title]
    if cost and (exact := [u for u in candidates if u.cost == cost]):
        candidates = exact
        print(f"  cost {cost} narrows to {len(candidates)}")

    ranked = sorted(
        ((u, *best_level(u, health, strength)) for u in candidates), key=lambda row: row[2]
    )
    for unit, solved_level, error in ranked[:3]:
        stats = unit.stats_at(solved_level)
        print(
            f"    err={error:.3f} id={unit.unit_id:<6} '{unit.title}' {unit.element}"
            f" r{unit.rarity} cost {unit.cost}->{unit.min_cost}"
            f" | lv{solved_level} hp={stats.health} atk={stats.attack}"
        )
