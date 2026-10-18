from pathlib import Path

import pytest

from nbsolver.models import AttackRange, Element, OwnedUnit, Unit
from nbsolver.roster import Roster


def make_unit(slug: str = "sakura-haruno-unrelenting-commitment") -> Unit:
    return Unit(
        slug=slug,
        name="Sakura Haruno",
        title="Unrelenting Commitment",
        element=Element.SKILL,
        rarity=6,
        range=AttackRange.MID,
        base_health=1554,
        base_strength=1662,
        hits=2,
        cost_by_dupes=[60, 54, 48, 42, 36, 30],
    )


def test_cost_falls_with_dupes():
    unit = make_unit()
    assert OwnedUnit(slug=unit.slug, dupes=0).cost(unit) == 60
    assert OwnedUnit(slug=unit.slug, dupes=5).cost(unit) == 30


def test_duplicate_copies_are_kept_separately():
    roster = Roster()
    roster.add("naruto")
    roster.add("naruto", level=80)
    assert len(roster.copies_of("naruto")) == 2


def test_rescan_does_not_duplicate_existing_copies():
    roster = Roster()
    roster.add("naruto", level=72, manual=True)

    added, skipped = roster.merge_scan([OwnedUnit(slug="naruto"), OwnedUnit(slug="hinata")])

    assert (added, skipped) == (1, 1)
    assert roster.copies_of("naruto")[0].level == 72
    assert roster.copies_of("naruto")[0].manually_added is True
    assert len(roster.copies_of("hinata")) == 1


def test_rescan_tops_up_when_player_pulled_more():
    roster = Roster()
    roster.add("naruto")

    added, _ = roster.merge_scan([OwnedUnit(slug="naruto"), OwnedUnit(slug="naruto")])

    assert added == 1
    assert len(roster.copies_of("naruto")) == 2


def test_team_cost_limit():
    unit = make_unit()
    catalogue = {unit.slug: unit}
    roster = Roster(team_cost_limit=120)
    team = [OwnedUnit(slug=unit.slug), OwnedUnit(slug=unit.slug, dupes=5)]

    assert roster.team_cost(team, catalogue) == 90
    assert roster.fits_cost_limit(team, catalogue)


def test_round_trip(tmp_path: Path):
    roster = Roster(player_id="REDACTED")
    roster.add("naruto", level=95, luck=40, dupes=2)
    path = tmp_path / "roster.json"
    roster.save(path)

    assert Roster.load(path).units[0].level == 95


@pytest.mark.parametrize("level", [0, 101])
def test_rejects_impossible_levels(level: int):
    with pytest.raises(ValueError):
        OwnedUnit(slug="naruto", level=level)
