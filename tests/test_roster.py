from pathlib import Path

import pytest

from nbsolver.models import Ability, AttackRange, Element, OwnedUnit, StatLevel, Unit
from nbsolver.roster import Roster

SAKURA = 10542
NARUTO = 10013
HINATA = 10100


def make_unit(unit_id: int = SAKURA) -> Unit:
    return Unit(
        unit_id=unit_id,
        name="Sakura Haruno",
        title="Unrelenting Commitment",
        element=Element.SKILL,
        rarity=6,
        range=AttackRange.MID,
        cost=60,
        cost_all_abilities=30,
        max_level=100,
        levels=[
            StatLevel(label="Lv 1", level=1, health=500, attack=400, speed=50),
            StatLevel(label="Max Lv 100", level=100, health=1554, attack=1662, speed=150),
        ],
        abilities=[
            Ability(name="a", unlock="Ability unlock 1 of 3"),
            Ability(name="b", unlock="Ability unlock 2 of 3"),
            Ability(name="c", unlock="Ability unlock 3 of 3"),
        ],
    )


def test_cost_falls_as_abilities_unlock():
    unit = make_unit()

    assert OwnedUnit(unit_id=unit.unit_id, dupes=0).cost(unit) == 60
    assert OwnedUnit(unit_id=unit.unit_id, dupes=3).cost(unit) == 30
    assert OwnedUnit(unit_id=unit.unit_id, dupes=5).cost(unit) == 30


def test_stats_interpolate_between_level_one_and_max():
    unit = make_unit()

    assert unit.stats_at(1).health == 500
    assert unit.stats_at(100).attack == 1662
    assert unit.stats_at(50).health == pytest.approx(1021, abs=1)


def make_limit_broken_unit() -> Unit:
    unit = make_unit()
    unit.max_level_limit_break = 150
    unit.levels += [
        StatLevel(label="Limit Break 1 (Lv 105)", level=105, health=1600, attack=1700, speed=152),
        StatLevel(label="Limit Break 2 (Lv 110)", level=110, health=1700, attack=1800, speed=154),
        # The Ultimate row repeats the top level with different numbers.
        StatLevel(label="Ultimate", level=110, health=2000, attack=2100, speed=184),
    ]
    return unit


def test_limit_break_levels_are_exact_at_each_anchor():
    unit = make_limit_broken_unit()

    assert unit.stats_at(105).attack == 1700
    assert unit.stats_at(110).health == 1700


def test_stats_follow_the_bracketing_anchors_not_the_whole_range():
    unit = make_limit_broken_unit()

    # Between Lv 105 and Lv 110, so halfway between 1600 and 1700.
    assert unit.stats_at(107).health == pytest.approx(1640, abs=1)


def test_a_limit_broken_copy_is_allowed():
    owned = OwnedUnit(unit_id=SAKURA, level=150, limit_break=10)

    assert owned.level == 150


def test_rejects_levels_beyond_full_limit_break():
    with pytest.raises(ValueError):
        OwnedUnit(unit_id=SAKURA, level=151)


def test_duplicate_copies_are_kept_separately():
    roster = Roster()
    roster.add(NARUTO)
    roster.add(NARUTO, level=80)

    assert len(roster.copies_of(NARUTO)) == 2


def test_rescan_does_not_duplicate_existing_copies():
    roster = Roster()
    roster.add(NARUTO, level=72, manual=True)

    added, skipped = roster.merge_scan([OwnedUnit(unit_id=NARUTO), OwnedUnit(unit_id=HINATA)])

    assert (added, skipped) == (1, 1)
    assert roster.copies_of(NARUTO)[0].level == 72
    assert roster.copies_of(NARUTO)[0].manually_added is True
    assert len(roster.copies_of(HINATA)) == 1


def test_rescan_tops_up_when_player_pulled_more():
    roster = Roster()
    roster.add(NARUTO)

    added, _ = roster.merge_scan([OwnedUnit(unit_id=NARUTO), OwnedUnit(unit_id=NARUTO)])

    assert added == 1
    assert len(roster.copies_of(NARUTO)) == 2


def test_team_cost_limit():
    unit = make_unit()
    catalogue = {unit.unit_id: unit}
    roster = Roster(team_cost_limit=120)
    team = [OwnedUnit(unit_id=unit.unit_id), OwnedUnit(unit_id=unit.unit_id, dupes=5)]

    assert roster.team_cost(team, catalogue) == 90
    assert roster.fits_cost_limit(team, catalogue)


def test_round_trip(tmp_path: Path):
    roster = Roster(player_id="REDACTED")
    roster.add(NARUTO, level=95, luck=40, dupes=2)
    path = tmp_path / "roster.json"
    roster.save(path)

    assert Roster.load(path).units[0].level == 95


@pytest.mark.parametrize("level", [0, 151])
def test_rejects_impossible_levels(level: int):
    with pytest.raises(ValueError):
        OwnedUnit(unit_id=NARUTO, level=level)
