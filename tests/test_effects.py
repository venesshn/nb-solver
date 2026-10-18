from nbsolver.effects import EffectKind, EffectMode, EffectSet, parse_effects
from nbsolver.models import Element


def test_parses_multiplier_and_single_ailment():
    parsed = EffectSet.parse(
        "Water Style: Giant Vortex Jutsu 2.5x attack, 30% chance of jutsu sealing"
    )

    assert parsed.multiplier == 2.5
    assert len(parsed.effects) == 1
    effect = parsed.effects[0]
    assert effect.kind is EffectKind.JUTSU_SEAL
    assert effect.mode is EffectMode.INFLICT
    assert effect.chance == 30.0


def test_slip_damage_tier_is_captured():
    effects = parse_effects(
        "Clone Jutsu: Super Explosion 2.2x attack, 60% chance of slip damage (tier 1)"
    )

    assert effects[0].kind is EffectKind.SLIP_DAMAGE
    assert effects[0].tier == 1


def test_two_clauses_each_become_an_effect():
    parsed = EffectSet.parse(
        "Uchiha Reflection 2x attack, 40% chance of chakra recovery sealing for 3 turn(s);"
        " 40% chance of health recovery sealing for 3 turn(s)"
    )

    kinds = {effect.kind for effect in parsed.effects}
    assert kinds == {EffectKind.CHAKRA_RECOVERY_SEAL, EffectKind.HEALTH_RECOVERY_SEAL}
    assert all(effect.duration == 3 for effect in parsed.effects)


def test_longer_phrase_wins_over_its_prefix():
    effects = parse_effects(
        "Piercing Needle Fangs 2.3x attack, 50% chance of health recovery sealing"
    )

    assert effects[0].kind is EffectKind.HEALTH_RECOVERY_SEAL


def test_barrier_carries_its_hp_and_duration():
    effects = parse_effects("Sand Shield / (Barrier: 3000) Barrier for 5 turn(s)")

    barrier = next(e for e in effects if e.kind is EffectKind.BARRIER)
    assert barrier.magnitude == 3000
    assert barrier.duration == 5
    assert barrier.mode is EffectMode.GRANT


def test_resistance_is_not_read_as_an_inflicted_ailment():
    effects = parse_effects(
        "Jutsu Sealing Resistance: 100% / Immobilization Resistance: 100%"
        " / Nullifies Element Affinity-based Damage Reduction"
    )

    seal = next(e for e in effects if e.kind is EffectKind.JUTSU_SEAL)
    assert seal.mode is EffectMode.RESIST
    assert seal.magnitude == 100
    assert any(e.kind is EffectKind.NULLIFY_ELEMENT_REDUCTION for e in effects)


def test_receiving_phrasing_is_a_resistance():
    effects = parse_effects("70% chance of receiving immobilization by 50%")

    assert effects[0].kind is EffectKind.IMMOBILIZATION
    assert effects[0].mode is EffectMode.RESIST


def test_caster_buff_with_element_change():
    parsed = EffectSet.parse(
        "Rasengan 2x attack; caster: Substitution chance +4% for 4 turn(s);"
        " changes the element to Skill for 6 turn(s)"
    )

    substitution = next(e for e in parsed.effects if e.kind is EffectKind.SUBSTITUTION)
    assert substitution.magnitude == 4
    assert substitution.duration == 4

    change = next(e for e in parsed.effects if e.kind is EffectKind.ELEMENT_CHANGE)
    assert change.element is Element.SKILL
    assert change.duration == 6


def test_inflicted_excludes_resistances_and_buffs():
    parsed = EffectSet.parse(
        "Tail Swipe 3x attack, 60% chance of immobilization; Slip Damage Resistance: 100%"
    )

    assert [effect.kind for effect in parsed.inflicted] == [EffectKind.IMMOBILIZATION]


def test_plain_attack_has_no_effects():
    parsed = EffectSet.parse(
        "Fire Style: Burning Ash 2.7x attack toward all enemies in range."
    )

    assert parsed.multiplier == 2.7
    assert parsed.effects == []


def test_chakra_restoration_is_a_grant_not_a_resistance():
    effects = parse_effects(
        "Chakra Recovery When Receiving Direct Attacks 20% chance of restoring"
        " 2 Chakra Gauge when receiving direct attacks."
    )

    assert effects[0].kind is EffectKind.CHAKRA_RECOVERY
    assert effects[0].mode is EffectMode.GRANT
    assert effects[0].magnitude == 2
    assert effects[0].chance == 20.0


def test_knockback_is_captured_because_it_moves_the_target():
    effects = parse_effects(
        "8 Trigrams 64 Palms 5.5x attack to 1 Skill elemental enemy(s) in range"
        " and knocks them back."
    )

    assert [e.kind for e in effects] == [EffectKind.KNOCKBACK]
    assert effects[0].mode is EffectMode.INFLICT


def test_pierces_are_not_mistaken_for_the_defence_they_bypass():
    effects = parse_effects(
        "C3 ignores damage reduction; ignores Perfect Dodge; ignores Substitution;"
        " 4x attack, 100% chance of slip damage (tier 4)"
    )
    pierced = {e.kind for e in effects if e.mode is EffectMode.PIERCE}

    assert pierced == {
        EffectKind.IGNORE_DAMAGE_REDUCTION,
        EffectKind.IGNORE_PERFECT_DODGE,
        EffectKind.IGNORE_SUBSTITUTION,
    }
    assert EffectKind.PERFECT_DODGE not in {e.kind for e in effects}
    assert EffectKind.DAMAGE_REDUCTION not in {e.kind for e in effects}


def test_parenthesised_reduce_damage_does_not_become_its_own_buff():
    effects = parse_effects(
        "8 Trigrams Air Palm Ignores Substitution and damage reduction effects"
        " (Reduce Damage) for 1 enemy(s) in range with 4.1x attack toward them."
    )
    kinds = {e.kind for e in effects}

    assert kinds == {EffectKind.IGNORE_SUBSTITUTION, EffectKind.IGNORE_DAMAGE_REDUCTION}


def test_barrier_removal_and_pull_travel_together():
    effects = parse_effects(
        "Absolute: Fang Over Fang Boosts your own attack by 25% for 7 turn(s)."
        " Removes Barrier of all enemies in range, 5.4x attack and draws them closer."
    )
    kinds = {e.kind for e in effects}

    assert EffectKind.REMOVE_BARRIER in kinds
    assert EffectKind.PULL in kinds


def test_chakra_drain_keeps_its_gauge_count():
    effects = parse_effects("Arhat Fist 2x attack; reduces the chakra gauge by 2")

    drain = next(e for e in effects if e.kind is EffectKind.CHAKRA_DRAIN)
    assert drain.mode is EffectMode.INFLICT
    assert drain.magnitude == 2


def test_damage_reduction_keeps_its_percentage():
    effects = parse_effects("Reduce Damage Reduces damage by 10%-15%.")

    assert effects[0].kind is EffectKind.DAMAGE_REDUCTION
    assert effects[0].mode is EffectMode.GRANT
    assert effects[0].magnitude == 10.0
