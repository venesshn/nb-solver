import numpy as np
import pytest

from nbsolver.box_reader import (
    STAR_BOX,
    count_stars,
    identify,
    limit_breaks,
    parse_level,
)
from nbsolver.models import Element, Unit


def unit(unit_id, name, title, rarity, max_level, max_lb):
    return Unit(
        unit_id=unit_id,
        name=name,
        title=title,
        element=Element.BODY,
        rarity=rarity,
        max_level=max_level,
        max_level_limit_break=max_lb,
    )


HASHIRAMA_4 = unit(1, "Hashirama Senju", "Father of Leaf Village", 4, 50, 50)
HASHIRAMA_6 = unit(2, "Hashirama Senju", "Father of Leaf Village", 6, 100, 150)
TOBIRAMA_6 = unit(3, "Tobirama Senju", "Father of Reanimation", 6, 100, 150)
NARUTO_6 = unit(4, "Naruto Uzumaki", "Rasengan Mastered", 6, 100, 150)
NARUTO_6B = unit(5, "Naruto Uzumaki", "No. 1 Maverick", 6, 100, 150)
SAKURA_5 = unit(6, "Sakura Haruno", "Dancing Cherry Blossoms", 5, 70, 100)
UNITS = [HASHIRAMA_4, HASHIRAMA_6, TOBIRAMA_6, NARUTO_6, NARUTO_6B, SAKURA_5]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("31/50", (31, 50)),
        ("1/50", (1, 50)),
        ("100/100", (100, 100)),
        ("MAX/70", (70, 70)),
        ("MAX/150", (150, 150)),
        ("AX/150", (150, 150)),  # the faint red M drops out of the OCR
        ("135 / 135", (135, 135)),
        ("", None),
        ("150150", None),
    ],
)
def test_parse_level(text, expected):
    assert parse_level(text) == expected


def test_limit_breaks_from_six_star_cap():
    assert limit_breaks(HASHIRAMA_6, 100) == 0
    assert limit_breaks(HASHIRAMA_6, 105) == 1
    assert limit_breaks(HASHIRAMA_6, 135) == 7
    assert limit_breaks(HASHIRAMA_6, 150) == 10


def test_limit_breaks_unknown_below_six_stars():
    assert limit_breaks(SAKURA_5, 70) == 0
    assert limit_breaks(SAKURA_5, 80) is None


def test_identify_uses_rarity_to_pick_the_form():
    four, _, _ = identify("Hashirama Senju", "Father of Leaf Village", 4, UNITS)
    six, _, _ = identify("Hashirama Senju", "Father of Leaf Village", 6, UNITS)
    assert (four.unit_id, six.unit_id) == (1, 2)


def test_identify_tolerates_misread_letters():
    found, score, margin = identify("Naruto Uzumaki ,", "Nn o|l Vaerwtk", 6, UNITS)
    assert found is NARUTO_6B
    assert score < 1 and margin > 0


def test_identify_without_candidates():
    assert identify("Anyone", "Anything", 3, UNITS) == (None, 0.0, 0.0)


def test_count_stars_counts_only_lit_ones():
    page = np.zeros((2556, 1180, 3), np.uint8)
    x0, y0, x1, y1 = STAR_BOX
    page[y0:y1, x0:x1] = (40, 70, 200)  # banner orange, BGR
    for k in range(6):
        x = x0 + 120 + k * 30
        colour = (40, 220, 250) if k < 4 else (30, 60, 90)  # lit yellow / dull outline
        page[y0 + 10 : y0 + 30, x : x + 20] = colour
    assert count_stars(page) == 4
