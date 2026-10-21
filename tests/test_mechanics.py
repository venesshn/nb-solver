import random

import pytest

from nbsolver.ai import parse_script
from nbsolver.battle import BattleState, Fighter, Order, Side, Team, take_turn
from nbsolver.effects import Effect, EffectKind, EffectMode
from nbsolver.enums import Element
from nbsolver.models import Jutsu
from nbsolver.passives import parse_passive
from nbsolver.simulate import parse_move


def fighter(key: str, side: Side, position=(0.0, 0.0), **extra) -> Fighter:
    base = {
        "key": key,
        "side": side,
        "element": Element.HEART,
        "attack": 1000,
        "max_health": 50000,
        "health": 50000,
        "position": position,
    }
    return Fighter(**{**base, **extra})


def battle(players: list[Fighter], enemies: list[Fighter]) -> BattleState:
    team = Team(members=players, on_field=[p.key for p in players])
    team.health = team.max_health
    return BattleState(team=team, enemies=enemies)


# ---------- passives ----------


@pytest.mark.parametrize(
    "text, check",
    [
        ("Boosts attack by 100.", lambda p: p.flat_attack == 100),
        ("Boosts attack by 100-300", lambda p: p.flat_attack == 100),
        (
            "Boosts attack by 1.5x during Combinations.",
            lambda p: p.combo_boost == 1.5 and p.flat_attack == 0,
        ),
        ("Boosts health by 150.", lambda p: p.flat_health == 150),
        (
            "25%-50% chance of attacking back when receiving an attack.",
            lambda p: p.counter == 25,
        ),
        ("Restores 300 health every turn.", lambda p: p.regen == 300),
        (
            "Increases damage dealt to Skill Elementals by 20%.",
            lambda p: p.damage_vs == {"Skill": 20},
        ),
        (
            "Reduces Heart and Wisdom elemental damage by 10%-15%.",
            lambda p: p.reduce_from == {"Heart": 10, "Wisdom": 10},
        ),
        ("Boosts Body attacks by 100-200", lambda p: p.element_attack == {"Body": 100}),
        (
            "Restores one bar of chakra when moving to a new map.",
            lambda p: p.map_chakra == 1,
        ),
        (
            "50% chance to reduce chakra consumed by Ninjutsu to 2",
            lambda p: p.ninjutsu_cut == (50, 2),
        ),
        (
            "Boosts rate of immobilization by 10%.",
            lambda p: p.inflict_boost == {"Immobilization": 10},
        ),
        (
            "Lowers rate of getting immobilized by 30% (Not F. Skills).",
            lambda p: (
                [(e.kind, e.mode, e.chance) for e in p.effects]
                == [(EffectKind.IMMOBILIZATION, EffectMode.RESIST, 30)]
            ),
        ),
        (
            "Reduces damage by 6%.",
            lambda p: (
                [(e.kind, e.magnitude) for e in p.effects]
                == [(EffectKind.DAMAGE_REDUCTION, 6)]
            ),
        ),
    ],
)
def test_passive_wordings(text, check):
    passive = parse_passive(text)
    assert passive.understood and check(passive), passive


def test_unknown_wording_is_skipped_not_guessed():
    passive = parse_passive("Does something nobody has written a rule for.")
    assert passive.understood == 0 and passive.skipped


# ---------- jutsu parsing ----------


def test_buff_secret_restores_chakra_and_hurts_its_user():
    move = parse_move(
        Jutsu(
            name="Eight Gates",
            chakra=10,
            description="Gives you an attack boost of 150%, for 10 turn(s), restores Chakra Gauge by 4,"
            " and gives you slip damage for 10 turn(s).",
        ),
        secret=True,
    )
    assert not move.strikes and move.boost == 150 and move.chakra_gain == 4
    assert [(e.kind, e.duration) for e in move.self_inflicts] == [
        (EffectKind.SLIP_DAMAGE, 10)
    ]


def test_percentage_and_self_cost_jutsu():
    move = parse_move(
        Jutsu(
            name="Curse",
            chakra=6,
            description="Deals 20% of enemy's remaining health as damage to 1 enemy(s) in range,"
            " but your remaining health is depleted by 10%. 5x attack, but depletes your remaining Health by 15%.",
        )
    )
    assert move.percent == 20 and move.self_cost == 15


# ---------- engine ----------


def test_percentage_hit_ignores_the_damage_formula():
    actor = fighter("a", Side.PLAYER, chakra=9)
    enemy = fighter("e", Side.ENEMY, max_health=10000, health=8000, defense=5000)
    state = battle([actor], [enemy])
    take_turn(
        state,
        Order(fighter="a", target="e", jutsu=True, chakra_cost=5, percent=20),
        random.Random(1),
    )
    assert enemy.health == 6400


def test_self_cost_takes_a_share_but_never_the_last_point():
    actor = fighter("a", Side.PLAYER)
    state = battle([actor], [fighter("e", Side.ENEMY, max_health=10**6, health=10**6)])
    state.team.health = 10000
    take_turn(state, Order(fighter="a", target="e", self_cost=15), random.Random(1))
    assert state.team.health == 8500


def test_counter_hits_back_when_struck():
    defender = fighter("p", Side.PLAYER, counter_chance=100)
    script = parse_script(["state 0 [Init]: Attack (countdown 1) -> state 0"])
    enemy = fighter(
        "e",
        Side.ENEMY,
        ai=script,
        max_health=10**6,
        health=10**6,
        element=Element.BRAVERY,
    )
    state = battle([defender], [enemy])
    events = take_turn(state, Order(fighter="p"), random.Random(2))
    counters = [e for e in events if e.kind == "damage" and "counter" in e.note]
    assert counters and counters[0].actor == "p" and counters[0].target == "e"


def test_perfect_dodge_is_spent_one_attack_at_a_time():
    target = fighter("e", Side.ENEMY)
    target.gain(
        Effect(kind=EffectKind.PERFECT_DODGE, mode=EffectMode.GRANT, magnitude=2)
    )
    state = battle([fighter("a", Side.PLAYER)], [target])
    outcomes = [
        [
            e.kind
            for e in take_turn(state, Order(fighter="a", target="e"), random.Random(k))
        ]
        for k in range(3)
    ]
    assert "avoided" in outcomes[0] and "avoided" in outcomes[1]
    assert "damage" in outcomes[2]


def test_element_bonuses_and_reductions():
    actor = fighter("a", Side.PLAYER, damage_vs={"Bravery": 50})
    plain = fighter("e", Side.ENEMY, element=Element.BRAVERY)
    shielded = fighter(
        "f", Side.ENEMY, element=Element.BRAVERY, reduce_from={"Heart": 50}
    )
    state = battle([actor], [plain, shielded])
    rng = random.Random(7)
    hit = next(
        e
        for e in take_turn(state, Order(fighter="a", target="e"), rng)
        if e.kind == "damage"
    )
    blocked = next(
        e
        for e in take_turn(state, Order(fighter="a", target="f"), rng)
        if e.kind == "damage"
    )
    assert hit.amount in (1500, 2250)
    assert blocked.amount in (750, 1125)


def test_buff_jutsu_restores_chakra_and_applies_self_ailment():
    actor = fighter("a", Side.PLAYER, chakra=10)
    state = battle([actor], [fighter("e", Side.ENEMY, position=(9.0, 9.0))])
    slip = Effect(
        kind=EffectKind.SLIP_DAMAGE,
        mode=EffectMode.INFLICT,
        duration=10,
        tier=1,
        targets_caster=True,
    )
    boost = Effect(
        kind=EffectKind.ATTACK_BOOST, mode=EffectMode.GRANT, duration=10, magnitude=150
    )
    order = Order(
        fighter="a",
        jutsu=True,
        chakra_cost=10,
        grants=[boost],
        chakra_gain=4,
        self_inflicts=[slip],
    )
    events = take_turn(state, order, random.Random(1))
    assert actor.chakra == pytest.approx(5.0)  # 10 - 10 + 4, then +1 for the turn
    assert actor.has(EffectKind.ATTACK_BOOST) and actor.has(EffectKind.SLIP_DAMAGE)
    assert any(e.kind == "slip" for e in events)


def test_regeneration_tops_up_the_pool_when_its_owner_acts():
    healer = fighter("a", Side.PLAYER, regen=300)
    state = battle([healer], [fighter("e", Side.ENEMY, position=(9.0, 9.0))])
    state.team.health = 1000
    take_turn(state, Order(fighter="a"), random.Random(1))
    assert state.team.health == 1300


def test_reaction_branch_fires_on_the_matching_hit():
    script = parse_script(
        [
            "state 0 [Init]: Attack (countdown 5) -> state 3",
            (
                "state 3 [Switch]: no action -> reaction: when hit by normal attack by Heart -> state 6,"
                " when hit by jutsu by Heart -> state 7"
            ),
            "state 6: Attack (countdown 9) -> state 3",
            "state 7: Attack (countdown 9) -> state 3",
        ]
    )
    enemy = fighter(
        "e", Side.ENEMY, ai=script, ai_state=3, max_health=10**6, health=10**6
    )
    state = battle([fighter("a", Side.PLAYER)], [enemy])
    take_turn(state, Order(fighter="a", target="e"), random.Random(1))
    assert enemy.ai_state == 6


def test_combination_boost_scales_only_combination_hits():
    actor = fighter("a", Side.PLAYER, reach=2.0, attack_range="Short")
    ally = fighter(
        "b",
        Side.PLAYER,
        position=(1.0, 0.0),
        reach=2.0,
        attack_range="Short",
        combo_boost=2.0,
    )
    enemy = fighter("e", Side.ENEMY, position=(1.0, 1.0), element=Element.BRAVERY)
    state = battle([actor, ally], [enemy])
    events = take_turn(state, Order(fighter="a", target="e"), random.Random(11))
    joined = [e for e in events if e.kind == "damage" and "combination" in e.note]
    assert joined and joined[0].amount in (1600, 2400)
