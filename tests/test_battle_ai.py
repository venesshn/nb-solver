"""The enemy phase, driven by the state machine the game publishes."""

from __future__ import annotations

import random

from nbsolver.ai import parse_script
from nbsolver.battle import (
    BattleState,
    Fighter,
    Order,
    Side,
    Team,
    Technique,
    enemy_fighter,
    take_turn,
)
from nbsolver.effects import Effect, EffectKind, EffectMode
from nbsolver.enums import Element
from nbsolver.missions import EnemySkill, EnemyStats


class NoLuck(random.Random):
    def uniform(self, a: float, b: float) -> float:
        return 99.999

    def random(self) -> float:
        return 0.0


def _hero(key: str = "hero", **kwargs) -> Fighter:
    base = {
        "key": key,
        "side": Side.PLAYER,
        "element": Element.HEART,
        "attack": 1000,
        "max_health": 5000,
        "health": 5000,
    }
    return Fighter(**{**base, **kwargs})


def _state(enemy: Fighter, *heroes: Fighter) -> BattleState:
    # Damage to the player comes off one shared pool, not the individual unit.
    team = Team(
        members=list(heroes),
        on_field=[h.key for h in heroes],
        health=sum(h.max_health for h in heroes),
    )
    return BattleState(team=team, enemies=[enemy])


def _stall(key: str = "hero") -> Order:
    return Order(fighter=key)


SWITCH_ON_HEALTH = (
    "state 0 [Init]: no action -> by HP: HP <= 100% -> state 1, HP <= 50% -> state 2"
)
LIMITED_HEAL = (
    'state 0 [Init]: skill 300100 "Cellular Activation"'
    " (countdown 1, max 1 uses) -> state 0"
)
FARTHEST = (
    "state 0 [Init]: Attack (countdown 1, target FarTarget (farthest ninja)) -> state 0"
)
SEEKS_BRAVERY = (
    "state 0 [Init]: Attack (countdown 1, target Attr4 (Bravery ninja first))"
    " -> state 0"
)
KUSANAGI = (
    'state 1 [Init]: skill 300271 "Kusanagi Blade" (countdown 1, Danger) -> state 1'
)


def test_an_enemy_waits_out_its_countdown_before_it_strikes():
    enemy = Fighter(
        key="foe",
        side=Side.ENEMY,
        element=Element.SKILL,
        attack=500,
        max_health=9000,
        health=9000,
        ai=parse_script(["state 0 [Init]: Attack (countdown 3) -> state 0"]),
    )
    hero = _hero()
    state = _state(enemy, hero)

    take_turn(state, _stall(), NoLuck())
    assert state.team.health == 5000, "countdown 3 must not land on the first turn"
    take_turn(state, _stall(), NoLuck())
    assert state.team.health == 5000
    take_turn(state, _stall(), NoLuck())
    assert state.team.health < 5000, "it strikes when the countdown runs out"


def test_a_switch_state_decides_at_once_rather_than_costing_a_turn():
    enemy = Fighter(
        key="foe",
        side=Side.ENEMY,
        element=Element.SKILL,
        attack=500,
        max_health=100,
        health=40,
        ai=parse_script(
            [
                SWITCH_ON_HEALTH,
                "state 1: Attack (countdown 9) -> state 0",
                "state 2: Attack (countdown 1) -> state 0",
            ]
        ),
    )
    hero = _hero()
    state = _state(enemy, hero)

    take_turn(state, _stall(), NoLuck())

    # At 40% health it must fall through the switch into the fast state and act.
    assert state.team.health < 5000


def test_a_use_limit_stops_a_heal_repeating():
    script = parse_script([LIMITED_HEAL])
    enemy = Fighter(
        key="foe",
        side=Side.ENEMY,
        element=Element.SKILL,
        attack=500,
        max_health=10000,
        health=1000,
        ai=script,
        techniques=[Technique(skill_id=300100, name="Cellular Activation", heals=6000)],
    )
    hero = _hero()
    state = _state(enemy, hero)

    take_turn(state, _stall(), NoLuck())
    assert enemy.health == 7000

    take_turn(state, _stall(), NoLuck())
    take_turn(state, _stall(), NoLuck())
    assert enemy.health == 7000, "it only ever gets the one heal"


def test_the_farthest_target_is_picked_when_the_script_says_so():
    enemy = Fighter(
        key="foe",
        side=Side.ENEMY,
        element=Element.SKILL,
        attack=500,
        max_health=9000,
        health=9000,
        position=(0.0, 0.0),
        ai=parse_script([FARTHEST]),
    )
    near = _hero("near", position=(1.0, 0.0))
    far = _hero("far", position=(9.0, 0.0))
    state = _state(enemy, near, far)

    events = take_turn(state, _stall("near"), NoLuck())

    struck = [e.target for e in events if e.kind == "damage"]
    assert struck == ["far"]


def test_an_element_seeking_jutsu_prefers_that_element():
    enemy = Fighter(
        key="foe",
        side=Side.ENEMY,
        element=Element.SKILL,
        attack=500,
        max_health=9000,
        health=9000,
        ai=parse_script([SEEKS_BRAVERY]),
    )
    close = _hero("close", position=(1.0, 0.0))
    brave = _hero("brave", element=Element.BRAVERY, position=(9.0, 0.0))
    state = _state(enemy, close, brave)

    events = take_turn(state, _stall("close"), NoLuck())

    struck = [e.target for e in events if e.kind == "damage"]
    assert struck == ["brave"]


def test_a_jutsu_carries_its_own_ailment_without_the_enemy_owning_it():
    enemy = Fighter(
        key="foe",
        side=Side.ENEMY,
        element=Element.SKILL,
        attack=500,
        max_health=9000,
        health=9000,
        ai=parse_script(
            ['state 0 [Init]: skill 300271 "Kusanagi" (countdown 1) -> state 0']
        ),
        techniques=[
            Technique(
                skill_id=300271,
                name="Kusanagi",
                multiplier=2.5,
                effects=[
                    Effect(
                        kind=EffectKind.JUTSU_SEAL,
                        mode=EffectMode.INFLICT,
                        chance=100.0,
                    )
                ],
            )
        ],
    )
    hero = _hero()
    state = _state(enemy, hero)

    take_turn(state, _stall(), NoLuck())

    assert hero.has(EffectKind.JUTSU_SEAL, EffectMode.INFLICT)


def test_an_enemy_with_no_script_still_uses_its_printed_countdown():
    enemy = Fighter(
        key="foe",
        side=Side.ENEMY,
        element=Element.SKILL,
        attack=500,
        max_health=9000,
        health=9000,
        countdown=2,
        attack_interval=2,
    )
    hero = _hero()
    state = _state(enemy, hero)

    take_turn(state, _stall(), NoLuck())
    assert state.team.health == 5000
    take_turn(state, _stall(), NoLuck())
    assert state.team.health < 5000


def test_a_catalogue_enemy_arrives_with_its_script_and_skills():
    stats = EnemyStats(
        name="Orochimaru",
        element=Element.SKILL,
        hp=27500,
        attack=410,
        defense=0,
        skills=[
            EnemySkill(
                slot="ai",
                name="Kusanagi Blade: Single Swing",
                description="2.5x attack, 50% chance of jutsu sealing",
                skill_id=300271,
            )
        ],
        ai_states=[KUSANAGI],
    )

    fighter = enemy_fighter(stats, "boss", (4.0, 3.0))

    assert fighter.ai is not None
    assert fighter.ai.start is not None
    assert fighter.ai.start.number == 1
    technique = fighter.technique(300271)
    assert technique is not None
    assert technique.multiplier == 2.5
    assert technique.strikes
    assert [e.kind for e in technique.effects] == [EffectKind.JUTSU_SEAL]
