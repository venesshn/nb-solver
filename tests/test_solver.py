import json
import random
from functools import cache
from pathlib import Path

import pytest

from nbsolver.battle import BattleState, Fighter, Order, Side, Team, take_turn
from nbsolver.enums import Element
from nbsolver.missions import ClearCondition, ConditionKind, MissionCatalogue
from nbsolver.models import Jutsu, OwnedUnit, Unit
from nbsolver.roster import Roster
from nbsolver.simulate import Member, helper_member, parse_move, play_stage
from nbsolver.solver import IMPOSSIBLE, NOT_FOUND, solve, wilson

DATA = Path(__file__).resolve().parents[1] / "data"
STAGE = ("e3003", "The Evil Snake Shows its Fangs [B]")


@cache
def units() -> dict[int, Unit]:
    rows = json.loads((DATA / "units.json").read_text(encoding="utf-8"))
    return {r["unit_id"]: Unit.model_validate(r) for r in rows}


@cache
def stage():
    return MissionCatalogue.load(DATA / "catalogue.json").get(STAGE[0]).stage(STAGE[1])


def fighter(key: str, side: Side, position, **extra) -> Fighter:
    base = {
        "key": key,
        "side": side,
        "element": Element.HEART,
        "attack": 1000,
        "max_health": 1000,
        "health": 1000,
        "position": position,
    }
    return Fighter(**{**base, **extra})


def test_wilson_interval_brackets_the_rate():
    low, high = wilson(40, 40)
    assert 0.9 < low < 1.0 and high == 1.0
    assert wilson(0, 40)[0] == 0.0
    assert wilson(0, 0) == (0.0, 1.0)


def test_parse_move_reads_targets_heals_and_boosts():
    move = parse_move(
        Jutsu(
            name="Test",
            chakra=4,
            description="Gives you an attack boost of 50% for 3 turn(s), 3x attack toward 3 enemy(s) in range.",
        )
    )
    assert move.targets == 3 and move.multiplier == 3.0
    assert move.grants and move.grants[0].magnitude == 50.0
    heal = parse_move(
        Jutsu(name="Heal", chakra=6, description="Restores 2,500 HP to all allies.")
    )
    assert heal.heal_flat == 2500 and not heal.strikes
    assert parse_move(None) is None


def test_allies_in_range_join_a_combination():
    actor = fighter("a", Side.PLAYER, (0.0, 0.0), reach=2.0, attack_range="Short")
    near = fighter("b", Side.PLAYER, (1.0, 0.0), reach=2.0, attack_range="Short")
    far = fighter("c", Side.PLAYER, (9.0, 9.0), reach=2.0, attack_range="Short")
    enemy = fighter(
        "e",
        Side.ENEMY,
        (1.0, 1.0),
        element=Element.BRAVERY,
        max_health=99999,
        health=99999,
    )
    team = Team(members=[actor, near, far], on_field=["a", "b", "c"])
    team.health = team.max_health
    state = BattleState(team=team, enemies=[enemy])
    events = take_turn(state, Order(fighter="a", target="e"), random.Random(5))
    joined = [e for e in events if e.kind == "damage" and "combination" in e.note]
    assert [e.actor for e in joined] == ["b"]
    assert (
        joined[0].amount == pytest.approx(1000 * 0.8, abs=1)
        or "critical" in joined[0].note
    )


def test_support_jutsu_heals_without_a_target():
    healer = fighter("h", Side.PLAYER, (0.0, 0.0), chakra=5.0)
    team = Team(members=[healer], on_field=["h"])
    team.health = 400
    state = BattleState(team=team, enemies=[fighter("e", Side.ENEMY, (5.0, 5.0))])
    take_turn(
        state, Order(fighter="h", jutsu=True, chakra_cost=5, heal=300), random.Random(1)
    )
    assert state.team.health == 700 and healer.chakra == pytest.approx(1.0)


def test_confirmed_clear_is_reproduced():
    """The player's own Heart team beat this stage; the simulator must agree."""
    u = units()
    front = [
        Member("tsunade", u[11066], 150),
        Member("deidara", u[12416], 135),
        helper_member(u[12666]),
    ]
    back = [
        Member("itachi", u[10966], 100),
        Member("hiruzen", u[10906], 100),
        Member("hinata", u[12636], 100),
    ]
    assert len(front) == len(back) == 3  # always three pairs, helper in front
    wins = sum(
        play_stage(stage(), front, back, random.Random(s)).won for s in range(30)
    )
    assert wins >= 27


def test_solver_finds_a_clear_for_the_example_box():
    roster = Roster.load(DATA / "rosters" / "example.json")
    report = solve(stage(), roster, units(), tries=12)
    assert report["status"] == "found" and report["likelihood"] >= 0.9
    assert report["team"]["cost"] <= roster.team_cost_limit == 329
    owned = {o.unit_id for o in roster.units}
    picked = [*report["team"]["front"], *report["team"]["back"]]
    assert all(c["unit_id"] in owned for c in picked)
    assert len({c["unit_id"] for c in picked}) == len(picked)
    assert report["showcase"]["frames"]


def test_body_only_clear_the_player_confirmed_is_found():
    """The player clears this Body-only, without a helper, almost every time."""
    roster = Roster.load(DATA / "rosters" / "example.json")
    body_only = next(c for c in stage().conditions if c.element == Element.BODY)
    report = solve(stage(), roster, units(), condition=body_only, helper=None, tries=20)
    assert report["status"] == "found" and report["likelihood"] >= 0.8
    picked = [*report["team"]["front"], *report["team"]["back"]]
    assert {c["element"] for c in picked} == {"Body"}


def test_auto_helper_is_chosen_by_play_not_raw_power():
    """A glass-cannon helper that drains the team must not beat going without."""
    roster = Roster.load(DATA / "rosters" / "example.json")
    body_only = next(c for c in stage().conditions if c.element == Element.BODY)
    report = solve(
        stage(), roster, units(), condition=body_only, helper="auto", tries=20
    )
    assert report["likelihood"] >= 0.8


def test_impossible_only_when_no_legal_team_exists():
    roster = Roster(units=[OwnedUnit(unit_id=11066, level=150)])
    wisdom_only = ClearCondition(
        kind=ConditionKind.ELEMENT_ONLY,
        description="Wisdom elementals only",
        element=Element.WISDOM,
    )
    report = solve(stage(), roster, units(), condition=wisdom_only, tries=6)
    assert report["status"] == "impossible" and report["message"] == IMPOSSIBLE


def test_losing_is_reported_as_not_found_with_advice():
    roster = Roster(units=[OwnedUnit(unit_id=10314, level=1)])
    report = solve(stage(), roster, units(), helper=None, tries=6)
    assert report["status"] == "not_found" and report["message"] == NOT_FOUND
    assert report["recommendations"]


def test_teams_are_always_three_pairs():
    roster = Roster.load(DATA / "rosters" / "example.json")
    with_helper = solve(stage(), roster, units(), helper=12666, tries=6)
    team = with_helper["team"]
    assert team["helper"]["unit_id"] == 12666
    assert len(team["front"]) == 2 and len(team["back"]) == 3
    alone = solve(stage(), roster, units(), helper=None, tries=6)
    assert len(alone["team"]["front"]) == 3 and len(alone["team"]["back"]) == 3


def test_completing_a_map_restores_half_the_missing_health():
    """Measured on the player's e3003 clear: 8540 -> 8918 and 8026 -> 8661 of 9296."""
    from nbsolver.simulate import _restore, make_squad

    u = units()
    squad = make_squad([Member("a", u[11066], 150)], [None])
    team = squad.state.team
    team.health = team.max_health - 756
    _restore(squad)
    assert team.max_health - team.health == 378
