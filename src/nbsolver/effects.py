"""Combat effects: every status, buff and resistance a skill description can carry."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field

from nbsolver.enums import Element


class EffectKind(StrEnum):
    SLIP_DAMAGE = "Slip damage"
    IMMOBILIZATION = "Immobilization"
    JUTSU_SEAL = "Jutsu sealing"
    HEALTH_RECOVERY_SEAL = "Health recovery sealing"
    CHAKRA_RECOVERY_SEAL = "Chakra recovery sealing"
    SWITCH_SEAL = "Switch sealing"
    ATTACK_REDUCTION = "Attack reduction"
    SPEED_REDUCTION = "Speed reduction"
    MOVEMENT_RESTRICTION = "Movement restriction"
    HEAL_TO_DAMAGE = "Health recovery to damage conversion"
    STATUS_AILMENT = "Status ailment"
    BARRIER = "Barrier"
    SUBSTITUTION = "Substitution"
    DODGE = "Dodge"
    COUNTER = "Counter"
    ATTACK_BOOST = "Attack boost"
    CRITICAL_RATE_BOOST = "Critical rate boost"
    ELEMENT_CHANGE = "Element change"
    NULLIFY_ELEMENT_REDUCTION = "Nullifies element affinity damage reduction"
    NULLIFY_JUTSU_DAMAGE = "Nullifies ninjutsu damage received"
    HEALTH_RECOVERY = "Health recovery"
    CHAKRA_RECOVERY = "Chakra recovery"
    DAMAGE_REDUCTION = "Damage reduction"
    PERFECT_DODGE = "Perfect dodge"
    LIFESTEAL = "Health recovery from damage dealt"
    KNOCKBACK = "Knock back"
    PULL = "Pull"
    CHAKRA_DRAIN = "Chakra gauge reduction"
    CHAKRA_COST_REDUCTION = "Chakra cost reduction"
    IGNORE_SUBSTITUTION = "Ignores substitution"
    IGNORE_PERFECT_DODGE = "Ignores perfect dodge"
    IGNORE_DAMAGE_REDUCTION = "Ignores damage reduction"
    REMOVE_BARRIER = "Removes barrier"
    OTHER = "Other"


class EffectMode(StrEnum):
    INFLICT = "Inflict"
    RESIST = "Resist"
    GRANT = "Grant"
    # An attack that bypasses a defence rather than applying anything itself.
    PIERCE = "Pierce"


# Longest phrases first so "health recovery sealing" wins over "health recovery".
AILMENT_PHRASES: list[tuple[str, EffectKind]] = [
    ("health recovery to damage conversion", EffectKind.HEAL_TO_DAMAGE),
    ("health recovery sealing", EffectKind.HEALTH_RECOVERY_SEAL),
    ("chakra recovery sealing", EffectKind.CHAKRA_RECOVERY_SEAL),
    ("switch function sealing", EffectKind.SWITCH_SEAL),
    ("switch sealing", EffectKind.SWITCH_SEAL),
    ("movement restriction", EffectKind.MOVEMENT_RESTRICTION),
    ("restricting movement", EffectKind.MOVEMENT_RESTRICTION),
    ("speed reduction", EffectKind.SPEED_REDUCTION),
    ("attack reduction", EffectKind.ATTACK_REDUCTION),
    ("attack weakened", EffectKind.ATTACK_REDUCTION),
    ("attack being reduced", EffectKind.ATTACK_REDUCTION),
    ("reducing their attack", EffectKind.ATTACK_REDUCTION),
    ("reducing the attack", EffectKind.ATTACK_REDUCTION),
    ("recovery sealing", EffectKind.HEALTH_RECOVERY_SEAL),
    ("jutsu sealing", EffectKind.JUTSU_SEAL),
    ("sealing jutsu", EffectKind.JUTSU_SEAL),
    ("immobilization", EffectKind.IMMOBILIZATION),
    ("immobilizing", EffectKind.IMMOBILIZATION),
    ("slip damage", EffectKind.SLIP_DAMAGE),
    ("status ailment", EffectKind.STATUS_AILMENT),
    ("substitution", EffectKind.SUBSTITUTION),
    ("health recovery", EffectKind.HEALTH_RECOVERY),
    ("chakra recovery", EffectKind.CHAKRA_RECOVERY),
    ("dodging", EffectKind.DODGE),
    ("attacking back when receiving an attack", EffectKind.COUNTER),
    ("chakra gauge", EffectKind.CHAKRA_RECOVERY),
]

CHANCE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*chance of\s+(.+)", re.IGNORECASE)
RESISTANCE_RE = re.compile(r"([A-Za-z ]+?)\s+Resistance:\s*(\d+)\s*%", re.IGNORECASE)
# Enemy data words it the other way round: "100% resistance to immobilization".
RESISTANCE_TO_RE = re.compile(
    r"(\d+)\s*%\s*resistance to\s+([A-Za-z ]+)", re.IGNORECASE
)
BARRIER_RE = re.compile(r"Barrier:\s*(\d+)", re.IGNORECASE)
DURATION_RE = re.compile(r"for\s+(\d+)\s*turn", re.IGNORECASE)
TIER_RE = re.compile(r"tier\s*(\d+)", re.IGNORECASE)
PERCENT_BY_RE = re.compile(r"by\s+(\d+(?:\.\d+)?)\s*%", re.IGNORECASE)
CHAKRA_AMOUNT_RE = re.compile(r"restoring\s+(\d+)\s*chakra", re.IGNORECASE)
BY_AMOUNT_RE = re.compile(r"by\s+(\d+)(?!\s*%)")
PLUS_PERCENT_RE = re.compile(r"\+\s*(\d+(?:\.\d+)?)\s*%")
DODGE_BY_RE = re.compile(r"chance to dodge by (\d+(?:\.\d+)?)\s*%", re.IGNORECASE)
ELEMENT_CHANGE_RE = re.compile(
    r"changes the element to\s+(Heart|Skill|Body|Bravery|Wisdom)", re.IGNORECASE
)
MULTIPLIER_RE = re.compile(r"([\d.]+)\s*x\s*attack", re.IGNORECASE)

# Matched in order against a clause, each hit blanking its own span so that a
# broad phrase cannot re-fire inside a specific one it is nested in.
FLAG_PHRASES: list[tuple[str, EffectKind, EffectMode]] = [
    ("knock back and draw", EffectKind.PULL, EffectMode.RESIST),
    ("nullifies knock back", EffectKind.KNOCKBACK, EffectMode.RESIST),
    (
        "damage reduction effects (reduce damage)",
        EffectKind.IGNORE_DAMAGE_REDUCTION,
        EffectMode.PIERCE,
    ),
    ("ignores damage reduction", EffectKind.IGNORE_DAMAGE_REDUCTION, EffectMode.PIERCE),
    ("ignore damage reduction", EffectKind.IGNORE_DAMAGE_REDUCTION, EffectMode.PIERCE),
    ("ignores perfect dodge", EffectKind.IGNORE_PERFECT_DODGE, EffectMode.PIERCE),
    ("ignore perfect dodge", EffectKind.IGNORE_PERFECT_DODGE, EffectMode.PIERCE),
    ("ignores substitution", EffectKind.IGNORE_SUBSTITUTION, EffectMode.PIERCE),
    ("ignore substitution", EffectKind.IGNORE_SUBSTITUTION, EffectMode.PIERCE),
    ("removes barrier", EffectKind.REMOVE_BARRIER, EffectMode.PIERCE),
    ("remove barrier", EffectKind.REMOVE_BARRIER, EffectMode.PIERCE),
    (
        "nullifies damage you receive from ninjutsu",
        EffectKind.NULLIFY_JUTSU_DAMAGE,
        EffectMode.GRANT,
    ),
    ("knocks them back", EffectKind.KNOCKBACK, EffectMode.INFLICT),
    ("draws them closer", EffectKind.PULL, EffectMode.INFLICT),
    ("recovers health in proportion to damage", EffectKind.LIFESTEAL, EffectMode.GRANT),
    ("restores health by", EffectKind.LIFESTEAL, EffectMode.GRANT),
    ("reduces damage by", EffectKind.DAMAGE_REDUCTION, EffectMode.GRANT),
    ("reduce damage", EffectKind.DAMAGE_REDUCTION, EffectMode.GRANT),
    ("perfect dodge", EffectKind.PERFECT_DODGE, EffectMode.GRANT),
    ("reduces the chakra gauge", EffectKind.CHAKRA_DRAIN, EffectMode.INFLICT),
    ("chakra consumed", EffectKind.CHAKRA_COST_REDUCTION, EffectMode.GRANT),
]

# How far past a phrase to look for the number that qualifies it.
FLAG_WINDOW = 60

# Things the wearer gains; "receiving" in these means a trigger, not a resistance.
GRANT_KINDS = {
    EffectKind.DODGE,
    EffectKind.SUBSTITUTION,
    EffectKind.COUNTER,
    EffectKind.CHAKRA_RECOVERY,
    EffectKind.HEALTH_RECOVERY,
}


class Effect(BaseModel):
    kind: EffectKind
    mode: EffectMode = EffectMode.INFLICT
    chance: float = 100.0
    duration: int | None = None
    # Barrier HP, a reduction percentage, or a substitution bonus, depending on kind.
    magnitude: float | None = None
    tier: int | None = None
    element: Element | None = None
    targets_caster: bool = False
    source: str = ""


def _kind_for(text: str) -> EffectKind | None:
    lowered = text.lower()
    for phrase, kind in AILMENT_PHRASES:
        if phrase in lowered:
            return kind
    return None


def _split_clauses(description: str) -> list[str]:
    parts = re.split(r";|(?<=\))\s*,\s*|,\s*(?=\d+\s*%\s*chance)", description)
    return [part.strip() for part in parts if part and part.strip()]


def _chance_effect(clause: str, caster: bool) -> Effect | None:
    match = CHANCE_RE.search(clause)
    if not match:
        return None

    chance, remainder = float(match.group(1)), match.group(2)
    kind = _kind_for(remainder)
    if kind is None:
        return Effect(
            kind=EffectKind.OTHER,
            chance=chance,
            targets_caster=caster,
            source=clause.strip(),
        )

    # "chance of receiving X by 50%" reduces how often X lands on you.
    if kind in GRANT_KINDS:
        mode = EffectMode.GRANT
    elif "receiving" in remainder.lower():
        mode = EffectMode.RESIST
    else:
        mode = EffectMode.INFLICT

    reduction = PERCENT_BY_RE.search(remainder)
    duration = DURATION_RE.search(remainder)
    tier = TIER_RE.search(remainder)

    magnitude = float(reduction.group(1)) if reduction else None
    if kind is EffectKind.CHAKRA_RECOVERY and (
        amount := CHAKRA_AMOUNT_RE.search(remainder)
    ):
        magnitude = float(amount.group(1))

    return Effect(
        kind=kind,
        mode=mode,
        chance=chance,
        duration=int(duration.group(1)) if duration else None,
        magnitude=magnitude,
        tier=int(tier.group(1)) if tier else None,
        targets_caster=caster,
        source=clause.strip(),
    )


def _flag_effects(clause: str, caster: bool) -> list[Effect]:
    remaining = clause.lower()
    found: list[Effect] = []

    for phrase, kind, mode in FLAG_PHRASES:
        start = remaining.find(phrase)
        if start < 0:
            continue
        remaining = (
            remaining[:start] + " " * len(phrase) + remaining[start + len(phrase) :]
        )

        window = clause[start : start + len(phrase) + FLAG_WINDOW]
        percent = PERCENT_BY_RE.search(window)
        amount = BY_AMOUNT_RE.search(window)
        duration = DURATION_RE.search(window)

        magnitude = None
        if percent:
            magnitude = float(percent.group(1))
        elif amount and kind is EffectKind.CHAKRA_DRAIN:
            magnitude = float(amount.group(1))

        found.append(
            Effect(
                kind=kind,
                mode=mode,
                duration=int(duration.group(1)) if duration else None,
                magnitude=magnitude,
                targets_caster=caster,
                source=clause.strip(),
            )
        )

    return found


def parse_effects(description: str) -> list[Effect]:
    """Pull every status, buff and resistance out of a skill description."""
    if not description:
        return []

    effects: list[Effect] = []
    for clause in _split_clauses(description):
        caster = clause.lower().startswith("caster:") or "caster:" in clause.lower()

        if effect := _chance_effect(clause, caster):
            effects.append(effect)

        for name, value in RESISTANCE_RE.findall(clause):
            kind = _kind_for(name) or EffectKind.OTHER
            effects.append(
                Effect(
                    kind=kind,
                    mode=EffectMode.RESIST,
                    magnitude=float(value),
                    targets_caster=caster,
                    source=clause.strip(),
                )
            )

        for value, name in RESISTANCE_TO_RE.findall(clause):
            effects.append(
                Effect(
                    kind=_kind_for(name) or EffectKind.OTHER,
                    mode=EffectMode.RESIST,
                    magnitude=float(value),
                    targets_caster=caster,
                    source=clause.strip(),
                )
            )

        if barrier := BARRIER_RE.search(clause):
            duration = DURATION_RE.search(clause)
            effects.append(
                Effect(
                    kind=EffectKind.BARRIER,
                    mode=EffectMode.GRANT,
                    magnitude=float(barrier.group(1)),
                    duration=int(duration.group(1)) if duration else None,
                    targets_caster=caster,
                    source=clause.strip(),
                )
            )

        if element := ELEMENT_CHANGE_RE.search(clause):
            duration = DURATION_RE.search(clause)
            effects.append(
                Effect(
                    kind=EffectKind.ELEMENT_CHANGE,
                    mode=EffectMode.GRANT,
                    element=Element(element.group(1).capitalize()),
                    duration=int(duration.group(1)) if duration else None,
                    targets_caster=caster,
                    source=clause.strip(),
                )
            )

        lowered = clause.lower()
        if "nullifies element affinity" in lowered:
            effects.append(
                Effect(
                    kind=EffectKind.NULLIFY_ELEMENT_REDUCTION,
                    mode=EffectMode.GRANT,
                    targets_caster=caster,
                    source=clause.strip(),
                )
            )

        if "attack boost" in lowered:
            duration = DURATION_RE.search(clause)
            effects.append(
                Effect(
                    kind=EffectKind.ATTACK_BOOST,
                    mode=EffectMode.GRANT,
                    duration=int(duration.group(1)) if duration else None,
                    targets_caster=caster,
                    source=clause.strip(),
                )
            )

        if "critical rate boost" in lowered:
            effects.append(
                Effect(
                    kind=EffectKind.CRITICAL_RATE_BOOST,
                    mode=EffectMode.GRANT,
                    targets_caster=caster,
                    source=clause.strip(),
                )
            )

        if (bonus := PLUS_PERCENT_RE.search(clause)) and "substitution" in lowered:
            duration = DURATION_RE.search(clause)
            effects.append(
                Effect(
                    kind=EffectKind.SUBSTITUTION,
                    mode=EffectMode.GRANT,
                    # "+20%" is the dodge chance itself; leaving the default 100%
                    # made every holder dodge every hit.
                    chance=float(bonus.group(1)),
                    magnitude=float(bonus.group(1)),
                    duration=int(duration.group(1)) if duration else None,
                    targets_caster=caster,
                    source=clause.strip(),
                )
            )

        if dodge := DODGE_BY_RE.search(clause):
            duration = DURATION_RE.search(clause)
            effects.append(
                Effect(
                    kind=EffectKind.DODGE,
                    mode=EffectMode.GRANT,
                    chance=float(dodge.group(1)),
                    magnitude=float(dodge.group(1)),
                    duration=int(duration.group(1)) if duration else None,
                    targets_caster=caster,
                    source=clause.strip(),
                )
            )

        effects.extend(_flag_effects(clause, caster))

    return effects


def attack_multiplier(description: str) -> float | None:
    match = MULTIPLIER_RE.search(description or "")
    return float(match.group(1)) if match else None


class EffectSet(BaseModel):
    """Everything one skill does, split into the parts a simulator treats differently."""

    multiplier: float | None = None
    effects: list[Effect] = Field(default_factory=list)

    @classmethod
    def parse(cls, description: str) -> EffectSet:
        return cls(
            multiplier=attack_multiplier(description),
            effects=parse_effects(description),
        )

    def of_kind(self, kind: EffectKind) -> list[Effect]:
        return [effect for effect in self.effects if effect.kind == kind]

    @property
    def inflicted(self) -> list[Effect]:
        return [effect for effect in self.effects if effect.mode == EffectMode.INFLICT]
