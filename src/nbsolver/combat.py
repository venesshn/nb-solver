"""Damage arithmetic: how an attack's number is actually produced."""

from __future__ import annotations

from enum import StrEnum

from nbsolver.enums import Element

CRITICAL_MULTIPLIER = 1.5
# Every character starts here; abilities and field skills raise it.
BASE_CRITICAL_RATE = 2.5

ADVANTAGE = 1.5
NEUTRAL = 1.0
DISADVANTAGE = 0.5

# Heart beats Skill beats Body beats Heart.
_BEATS = {
    Element.HEART: Element.SKILL,
    Element.SKILL: Element.BODY,
    Element.BODY: Element.HEART,
}

# Bravery and Wisdom sit outside that ring and hit each other hard both ways,
# so neither is ever at a disadvantage.
_MUTUAL = frozenset({Element.BRAVERY, Element.WISDOM})


def element_multiplier(
    attacker: Element,
    defender: Element,
    *,
    nullify_reduction: bool = False,
) -> float:
    """How the elements alone scale an attack, before any other modifier."""
    if attacker != defender and {attacker, defender} == _MUTUAL:
        return ADVANTAGE
    if _BEATS.get(attacker) is defender:
        return ADVANTAGE
    if _BEATS.get(defender) is attacker:
        return NEUTRAL if nullify_reduction else DISADVANTAGE
    return NEUTRAL


def damage(
    attack: int,
    skill_multiplier: float,
    attacker: Element,
    defender: Element,
    *,
    critical: bool = False,
    nullify_reduction: bool = False,
) -> float:
    """No source gives units or enemies a defence stat, so none appears here."""
    dealt = attack * skill_multiplier
    dealt *= element_multiplier(attacker, defender, nullify_reduction=nullify_reduction)
    if critical:
        dealt *= CRITICAL_MULTIPLIER
    return dealt


class DamageColour(StrEnum):
    """The colour the game prints a number in, so playback can match what players see."""

    ADVANTAGE = "red"
    NEUTRAL = "grey"
    DISADVANTAGE = "blue"
    SLIP = "purple"
    HEALING = "green"


def damage_colour(attacker: Element, defender: Element) -> DamageColour:
    """Read from the raw matchup, since nullifying a penalty still shows grey."""
    match element_multiplier(attacker, defender):
        case x if x == ADVANTAGE:
            return DamageColour.ADVANTAGE
        case x if x == DISADVANTAGE:
            return DamageColour.DISADVANTAGE
        case _:
            return DamageColour.NEUTRAL
