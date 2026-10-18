"""The battle engine, checked against the mechanics the game actually shows."""

from __future__ import annotations

import random

import pytest

from nbsolver.battle import (
    BattleState,
    Fighter,
    Order,
    Side,
    Team,
    resolve_attack,
    take_turn,
    tick_slip_damage,
)
from nbsolver.combat import DamageColour
from nbsolver.effects import Effect, EffectKind, EffectMode
from nbsolver.enums import Element


class NoLuck(random.Random):
    """Every roll misses, so only certainties happen."""

    def uniform(self, a: float, b: float) -> float:
        return 99.999


class AllLuck(random.Random):
    """Every roll lands, including the 2.5% critical."""

    def uniform(self, a: float, b: float) -> float:
        return 0.0


def hero(**kwargs) -> Fighter:
    base = {
        "key": "hero",
        "side": Side.PLAYER,
        "element": Element.HEART,
        "attack": 1000,
        "max_health": 2000,
    }
    return Fighter(**{**base, **kwargs})


def foe(**kwargs) -> Fighter:
    base = {
        "key": "foe",
        "side": Side.ENEMY,
        "element": Element.SKILL,
        "attack": 500,
        "max_health": 5000,
        "health": 5000,
    }
    return Fighter(**{**base, **kwargs})


def battle(members: list[Fighter], enemies: list[Fighter]) -> BattleState:
    team = Team(members=members, on_field=[m.key for m in members][:3])
    team.health = team.max_health
    return BattleState(team=team, enemies=enemies)


def test_player_damage_comes_off_the_shared_pool_not_the_unit():
    state = battle(
        [hero(max_health=2000), hero(key="second", max_health=1000)], [foe()]
    )
    assert state.team.max_health == 3000

    resolve_attack(state, state.enemies[0], state.team.members[0], 1.0, NoLuck())

    # Skill into Heart is a disadvantage, so 500 x 0.5.
    assert state.team.health == 3000 - 250
    assert state.team.members[0].health == 0


def test_a_hit_is_coloured_by_the_raw_matchup():
    state = battle([hero()], [foe()])
    events = resolve_attack(
        state, state.team.members[0], state.enemies[0], 1.0, NoLuck()
    )
    assert events[0].colour is DamageColour.ADVANTAGE
    assert events[0].amount == 1500


def test_a_critical_multiplies_the_number_it_would_have_dealt():
    state = battle([hero()], [foe()])
    events = resolve_attack(
        state, state.team.members[0], state.enemies[0], 1.0, AllLuck()
    )
    assert events[0].amount == 2250
    assert events[0].note == "critical"


def test_a_barrier_soaks_damage_before_health_does():
    state = battle([hero()], [foe(barrier=1000.0)])
    resolve_attack(state, state.team.members[0], state.enemies[0], 1.0, NoLuck())
    assert state.enemies[0].barrier == 0
    assert state.enemies[0].health == 5000 - 500


def test_removing_a_barrier_happens_on_a_later_hit_not_the_one_that_strips_it():
    breaker = hero(on_hit=[Effect(kind=EffectKind.REMOVE_BARRIER)])
    state = battle([breaker], [foe(barrier=2000.0)])
    resolve_attack(state, state.team.members[0], state.enemies[0], 1.0, NoLuck())
    assert state.enemies[0].barrier == 0
    assert state.enemies[0].health == 5000


def test_substitution_avoids_a_hit_unless_the_attacker_ignores_it():
    guarded = foe()
    guarded.gain(Effect(kind=EffectKind.SUBSTITUTION, mode=EffectMode.GRANT))
    state = battle([hero()], [guarded])
    events = resolve_attack(state, state.team.members[0], guarded, 1.0, NoLuck())
    assert events[0].kind == "avoided"
    assert guarded.health == 5000

    piercer = state.team.members[0]
    piercer.gain(Effect(kind=EffectKind.IGNORE_SUBSTITUTION, mode=EffectMode.PIERCE))
    resolve_attack(state, piercer, guarded, 1.0, NoLuck())
    assert guarded.health == 5000 - 1500


def test_damage_reduction_is_a_percentage_a_pierce_can_cancel():
    tough = foe()
    tough.gain(
        Effect(kind=EffectKind.DAMAGE_REDUCTION, mode=EffectMode.GRANT, magnitude=50.0)
    )
    state = battle([hero()], [tough])
    resolve_attack(state, state.team.members[0], tough, 1.0, NoLuck())
    assert tough.health == 5000 - 750

    piercer = state.team.members[0]
    piercer.gain(
        Effect(kind=EffectKind.IGNORE_DAMAGE_REDUCTION, mode=EffectMode.PIERCE)
    )
    resolve_attack(state, piercer, tough, 1.0, NoLuck())
    assert tough.health == 5000 - 750 - 1500


def test_nullifying_element_reduction_restores_full_damage_without_colouring_it_red():
    attacker = foe(key="striker", element=Element.SKILL)
    attacker.gain(
        Effect(kind=EffectKind.NULLIFY_ELEMENT_REDUCTION, mode=EffectMode.GRANT)
    )
    state = battle([hero()], [attacker])
    events = resolve_attack(state, attacker, state.team.members[0], 1.0, NoLuck())
    assert events[0].amount == 500
    assert events[0].colour is DamageColour.DISADVANTAGE


def test_slip_damage_ticks_on_its_own_and_prints_purple():
    poisoned = foe()
    poisoned.gain(Effect(kind=EffectKind.SLIP_DAMAGE, tier=2, duration=2))
    state = battle([hero()], [poisoned])
    events = tick_slip_damage(state, NoLuck())
    assert events[0].colour is DamageColour.SLIP
    assert poisoned.health == 5000 - state.rules.slip_damage_by_tier[2]


def test_heal_to_damage_turns_recovery_against_the_team():
    cursed = hero()
    cursed.gain(Effect(kind=EffectKind.HEAL_TO_DAMAGE))
    healer = hero(key="healer", on_hit=[])
    state = battle([cursed, healer], [foe()])
    cursed.gain(
        Effect(kind=EffectKind.LIFESTEAL, mode=EffectMode.GRANT, magnitude=100.0)
    )
    resolve_attack(state, cursed, state.enemies[0], 1.0, NoLuck())
    assert state.team.health == 4000 - 1500


def test_health_recovery_sealing_stops_lifesteal_entirely():
    sealed = hero()
    sealed.gain(Effect(kind=EffectKind.HEALTH_RECOVERY_SEAL))
    sealed.gain(
        Effect(kind=EffectKind.LIFESTEAL, mode=EffectMode.GRANT, magnitude=100.0)
    )
    state = battle([sealed], [foe()])
    state.team.health = 500
    resolve_attack(state, sealed, state.enemies[0], 1.0, NoLuck())
    assert state.team.health == 500


def test_an_immobilised_unit_loses_its_turn():
    stuck = hero()
    stuck.gain(Effect(kind=EffectKind.IMMOBILIZATION, duration=1))
    state = battle([stuck], [foe()])
    take_turn(state, [Order(fighter="hero", target="foe")], NoLuck())
    assert state.enemies[0].health == 5000


def test_a_jutsu_sealed_unit_cannot_spend_chakra():
    sealed = hero(chakra=5.0)
    sealed.gain(Effect(kind=EffectKind.JUTSU_SEAL, duration=3))
    state = battle([sealed], [foe()])
    events = take_turn(
        state,
        [
            Order(
                fighter="hero",
                target="foe",
                jutsu=True,
                chakra_cost=3.0,
                multiplier=3.0,
            )
        ],
        NoLuck(),
    )
    assert any(e.kind == "sealed" for e in events)
    assert state.enemies[0].health == 5000


def test_a_jutsu_spends_chakra_and_a_discount_makes_it_cheaper():
    thrifty = hero(chakra=3.0)
    thrifty.gain(
        Effect(
            kind=EffectKind.CHAKRA_COST_REDUCTION, mode=EffectMode.GRANT, magnitude=50.0
        )
    )
    state = battle([thrifty], [foe()])
    take_turn(
        state,
        [
            Order(
                fighter="hero",
                target="foe",
                jutsu=True,
                chakra_cost=3.0,
                multiplier=2.0,
            )
        ],
        NoLuck(),
    )
    assert thrifty.chakra == pytest.approx(3.0 - 1.5 + state.rules.chakra_per_turn)
    assert state.enemies[0].health == 5000 - 3000


def test_switch_sealing_pins_a_unit_on_the_field():
    first, second = hero(), hero(key="bench")
    state = battle([first, second], [foe()])
    state.team.on_field = ["hero"]
    assert state.team.switch("hero", "bench") is True

    state.team.on_field = ["hero"]
    first.gain(Effect(kind=EffectKind.SWITCH_SEAL))
    assert state.team.switch("hero", "bench") is False


def test_an_enemy_strikes_when_its_printed_countdown_reaches_zero():
    clocked = foe(countdown=2, attack_interval=2)
    state = battle([hero()], [clocked])

    take_turn(state, [Order(fighter="hero")], NoLuck())
    assert state.team.health == state.team.max_health

    take_turn(state, [Order(fighter="hero")], NoLuck())
    assert state.team.health == state.team.max_health - 250
    assert clocked.countdown == 2


def test_knockback_pushes_the_target_away_from_whoever_hit_it():
    shover = hero(
        position=(0.0, 0.0), on_hit=[Effect(kind=EffectKind.KNOCKBACK, magnitude=2.0)]
    )
    target = foe(position=(3.0, 0.0))
    state = battle([shover], [target])
    resolve_attack(state, shover, target, 1.0, NoLuck())
    assert target.position == (5.0, 0.0)


def test_an_attack_boost_and_reduction_cancel_out():
    boosted = hero()
    boosted.gain(
        Effect(kind=EffectKind.ATTACK_BOOST, mode=EffectMode.GRANT, magnitude=50.0)
    )
    assert boosted.attack_power == 1500
    boosted.gain(Effect(kind=EffectKind.ATTACK_REDUCTION, magnitude=50.0))
    assert boosted.attack_power == 1000


def test_effects_wear_off_after_their_stated_turns():
    stuck = hero()
    stuck.gain(Effect(kind=EffectKind.IMMOBILIZATION, duration=1))
    state = battle([stuck], [foe()])
    take_turn(state, [Order(fighter="hero", target="foe")], NoLuck())
    assert not stuck.has(EffectKind.IMMOBILIZATION)

    take_turn(state, [Order(fighter="hero", target="foe")], NoLuck())
    assert state.enemies[0].health == 5000 - 1500


def test_the_battle_ends_when_the_last_enemy_falls():
    state = battle([hero(attack=10000)], [foe()])
    take_turn(state, [Order(fighter="hero", target="foe")], NoLuck())
    assert state.cleared
    assert state.over
