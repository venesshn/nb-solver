import pytest

from nbsolver.combat import (
    ADVANTAGE,
    ATTACK_BOOST_RANKS,
    DISADVANTAGE,
    NEUTRAL,
    critical_rate,
    damage,
    element_multiplier,
    rank_value,
    slip_damage,
)
from nbsolver.enums import Element

RING = [
    (Element.HEART, Element.SKILL),
    (Element.SKILL, Element.BODY),
    (Element.BODY, Element.HEART),
]


@pytest.mark.parametrize(("attacker", "defender"), RING)
def test_the_ring_of_three_gives_advantage_one_way(attacker, defender):
    assert element_multiplier(attacker, defender) == ADVANTAGE
    assert element_multiplier(defender, attacker) == DISADVANTAGE


def test_bravery_and_wisdom_are_strong_against_each_other_both_ways():
    assert element_multiplier(Element.BRAVERY, Element.WISDOM) == ADVANTAGE
    assert element_multiplier(Element.WISDOM, Element.BRAVERY) == ADVANTAGE


@pytest.mark.parametrize("element", list(Element))
def test_an_element_is_never_strong_against_itself(element):
    assert element_multiplier(element, element) == NEUTRAL


@pytest.mark.parametrize(
    ("attacker", "defender"),
    [
        (Element.HEART, Element.BRAVERY),
        (Element.WISDOM, Element.BODY),
        (Element.SKILL, Element.WISDOM),
    ],
)
def test_the_two_groups_do_not_interact(attacker, defender):
    assert element_multiplier(attacker, defender) == NEUTRAL
    assert element_multiplier(defender, attacker) == NEUTRAL


def test_nullifying_the_reduction_only_removes_the_penalty():
    assert (
        element_multiplier(Element.SKILL, Element.HEART, nullify_reduction=True)
        == NEUTRAL
    )
    # It is an offensive ability, so it must not inflate an existing advantage.
    assert (
        element_multiplier(Element.HEART, Element.SKILL, nullify_reduction=True)
        == ADVANTAGE
    )


def test_damage_combines_attack_multiplier_element_and_crit():
    # Itachi, Heart, attack 1318, swinging a 3x jutsu into a Skill enemy.
    assert damage(1318, 3.0, Element.HEART, Element.SKILL) == 5931
    # The game rounds up once, at the end, so the half from a crit is kept.
    assert damage(1318, 3.0, Element.HEART, Element.SKILL, critical=True) == 8897
    assert damage(1318, 3.0, Element.HEART, Element.BODY) == 1977


def test_damage_matches_the_published_worked_examples():
    # Level 1 Naruto, 161 attack, a 2.2x ninjutsu into an element he beats.
    assert damage(161, 2.2, Element.HEART, Element.SKILL) == 532
    # A recorded hit: 598 attack lifted by a flat 91, no multipliers anywhere.
    assert damage(598, 1.0, Element.HEART, Element.HEART, flat_attack_boost=91.0) == 689


def test_defense_is_subtracted_per_hit_and_a_hit_always_counts():
    assert damage(2900, 1.0, Element.HEART, Element.HEART, defense=3000) == 1
    assert damage(3400, 1.0, Element.HEART, Element.HEART, defense=3000) == 400


def test_slip_damage_is_a_share_of_what_is_left_rounded_up():
    assert slip_damage(1134, 2) == 46
    assert slip_damage(5000, 4) == 400
    # It shrinks with the target, so it never quite finishes anyone off.
    assert slip_damage(1, 4) == 1
    # An effect we could not read a rank off is read as the weakest one.
    assert slip_damage(5000, None) == 100


def test_a_critical_rate_boost_multiplies_the_base_chance():
    assert critical_rate() == pytest.approx(3.125)
    assert critical_rate(2.0) == pytest.approx(6.25)
    assert critical_rate(4.0) == pytest.approx(12.5)


def test_a_rank_past_the_end_of_a_table_clamps_to_the_cap():
    assert rank_value(ATTACK_BOOST_RANKS, 1) == 1.25
    assert rank_value(ATTACK_BOOST_RANKS, 6) == 2.5
    assert rank_value(ATTACK_BOOST_RANKS, 9) == 2.5
    assert rank_value(ATTACK_BOOST_RANKS, None) == 1.0
