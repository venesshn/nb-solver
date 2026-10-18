import pytest

from nbsolver.combat import (
    ADVANTAGE,
    DISADVANTAGE,
    NEUTRAL,
    damage,
    element_multiplier,
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
    assert damage(1318, 3.0, Element.HEART, Element.SKILL) == pytest.approx(5931.0)
    assert damage(
        1318, 3.0, Element.HEART, Element.SKILL, critical=True
    ) == pytest.approx(8896.5)
    assert damage(1318, 3.0, Element.HEART, Element.BODY) == pytest.approx(1977.0)
