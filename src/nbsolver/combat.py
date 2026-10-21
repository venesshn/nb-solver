"""Damage arithmetic: how an attack's number is actually produced."""

from __future__ import annotations

import math
from enum import StrEnum

from nbsolver.enums import Element

CRITICAL_MULTIPLIER = 1.5
# One in thirty-two. Critical rate boosts multiply this; they do not add to it.
BASE_CRITICAL_RATE = 3.125

ADVANTAGE = 1.5
NEUTRAL = 1.0
DISADVANTAGE = 0.5

# Ranks a technique can apply, as the game's own tables list them.
ATTACK_BOOST_RANKS = (1.25, 1.5, 1.75, 2.0, 2.25, 2.5)
ATTACK_WEAKENED_RANKS = (0.85, 0.7, 0.55, 0.4, 0.25)
CRITICAL_RATE_RANKS = (1.5, 2.0, 2.5, 3.0, 3.5, 4.0)
SLIP_DAMAGE_RANKS = (0.02, 0.04, 0.06, 0.08)

# A combination hit is worth this share of the ally's normal attack, by its range.
COMBINATION_VALUE = {"Short": 0.8, "Mid": 0.7, "Long": 0.6, "Vast": 0.5}

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


def rank_value(ranks: tuple[float, ...], rank: int | None) -> float:
    """Rank 1 is the first entry; anything past the table clamps to the cap."""
    if not rank or rank < 1:
        return 1.0
    return ranks[min(rank, len(ranks)) - 1]


def critical_rate(boost: float = 1.0) -> float:
    return BASE_CRITICAL_RATE * boost


def damage(
    attack: int,
    skill_multiplier: float,
    attacker: Element,
    defender: Element,
    *,
    flat_attack_boost: float = 0.0,
    attack_boost: float = 1.0,
    attack_weakened: float = 1.0,
    other_bonuses: float = 1.0,
    critical: bool = False,
    critical_damage: float = CRITICAL_MULTIPLIER,
    nullify_reduction: bool = False,
    damage_reduction: float = 0.0,
    defense: int = 0,
) -> int:
    """Flat boosts join ATK before the multipliers, so the multipliers scale them too."""
    raw = (attack + flat_attack_boost) * skill_multiplier
    raw *= attack_boost * attack_weakened * other_bonuses
    if critical:
        raw *= critical_damage

    raw *= element_multiplier(attacker, defender, nullify_reduction=nullify_reduction)
    raw *= 1 - damage_reduction

    # The game rounds up, then subtracts defence, and never lets a hit do nothing.
    return max(1, math.ceil(raw) - defense)


def slip_damage(current_health: int, rank: int | None) -> int:
    """A share of what the target has left, so it shrinks as the target does."""
    return math.ceil(current_health * rank_value(SLIP_DAMAGE_RANKS, rank or 1))


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
