"""Abilities, field skills and buddy skills: what a unit does without acting.

The game words these in a small number of fixed shapes. Each shape below maps
to a bonus the battle engine understands. Field skills are written as a range
because they weaken with distance; the weakest end is used, so a bonus is never
claimed that the formation might not deliver.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from nbsolver.effects import Effect, EffectKind, EffectMode

NUMBER = r"(\d+(?:\.\d+)?)"
# "100-300", "30%-40%", "1.5-2x": the first number is the weakest reading.
SPAN = rf"{NUMBER}%?(?:\s*-\s*\d+(?:\.\d+)?%?)?"
_ONE = r"(?:Heart|Skill|Body|Bravery|Wisdom)"
ELEMENT = rf"({_ONE}(?:(?:\s*,\s*|\s+and\s+|\s*/\s*){_ONE})*)"

AILMENTS = {
    "immobiliz": EffectKind.IMMOBILIZATION,
    "jutsu seal": EffectKind.JUTSU_SEAL,
    "slip damage": EffectKind.SLIP_DAMAGE,
    "attack weaken": EffectKind.ATTACK_REDUCTION,
    "attack being reduced": EffectKind.ATTACK_REDUCTION,
    "chakra recovery seal": EffectKind.CHAKRA_RECOVERY_SEAL,
    "health recovery seal": EffectKind.HEALTH_RECOVERY_SEAL,
    "switch function seal": EffectKind.SWITCH_SEAL,
    "switch seal": EffectKind.SWITCH_SEAL,
}


@dataclass
class Passive:
    """Everything a set of passive texts adds up to, for one unit."""

    flat_attack: float = 0.0
    flat_health: float = 0.0
    regen: float = 0.0
    map_heal: float = 0.0
    counter: float = 0.0
    combo_boost: float = 1.0
    map_chakra: float = 0.0
    chakra_cut: float = 0.0
    ninjutsu_cut: tuple[float, float] | None = None
    secret_cut: tuple[float, float] | None = None
    damage_vs: dict[str, float] = field(default_factory=dict)
    reduce_from: dict[str, float] = field(default_factory=dict)
    effects: list[Effect] = field(default_factory=list)
    # Field skills that only help allies of one element, e.g. "Boosts Body attacks".
    element_attack: dict[str, float] = field(default_factory=dict)
    # Extra percentage points on the chance of landing each ailment.
    inflict_boost: dict[str, float] = field(default_factory=dict)
    speed: float = 0.0
    chakra_on_hit: tuple[float, float] | None = None
    understood: int = 0
    skipped: list[str] = field(default_factory=list)

    def merge(self, other: Passive) -> None:
        self.flat_attack += other.flat_attack
        self.flat_health += other.flat_health
        self.regen += other.regen
        self.map_heal += other.map_heal
        self.counter = min(100.0, self.counter + other.counter)
        self.combo_boost *= other.combo_boost
        self.map_chakra += other.map_chakra
        self.chakra_cut += other.chakra_cut
        self.ninjutsu_cut = other.ninjutsu_cut or self.ninjutsu_cut
        self.secret_cut = other.secret_cut or self.secret_cut
        self.chakra_on_hit = other.chakra_on_hit or self.chakra_on_hit
        self.speed += other.speed
        for name in ("damage_vs", "reduce_from", "element_attack", "inflict_boost"):
            mine, theirs = getattr(self, name), getattr(other, name)
            for key, value in theirs.items():
                mine[key] = mine.get(key, 0.0) + value
        self.effects += other.effects
        self.understood += other.understood
        self.skipped += other.skipped


def _clauses(text: str) -> list[str]:
    # Asides such as "(Not F. Skills)" carry no numbers and break sentence splitting.
    plain = re.sub(r"\([^)]*\)", "", text or "")
    parts = re.split(r"(?<=[.;])\s+", plain)
    return [p.strip(" .;") for p in parts if p.strip(" .;")]


def _elements(text: str) -> list[str]:
    return [e.capitalize() for e in re.findall(_ONE, text, re.IGNORECASE)]


def _grant(kind: EffectKind, **extra) -> Effect:
    return Effect(kind=kind, mode=EffectMode.GRANT, source="passive", **extra)


def parse_clause(clause: str) -> Passive:
    p = Passive()
    low = clause.lower()

    def hit(pattern: str) -> re.Match | None:
        return re.search(pattern, clause, re.IGNORECASE)

    if "during combination" in low:
        if m := hit(rf"boosts attack by {NUMBER}x"):
            p.combo_boost = float(m.group(1))
        else:
            p.skipped.append(clause)
            return p
    elif m := hit(rf"boosts rate of (.+?) by {SPAN}"):
        kinds = [kind for word, kind in AILMENTS.items() if word in m.group(1).lower()]
        if not kinds and "attack reduction" in m.group(1).lower():
            kinds = [EffectKind.ATTACK_REDUCTION]
        if not kinds:
            p.skipped.append(clause)
            return p
        for kind in dict.fromkeys(kinds):
            p.inflict_boost[str(kind)] = float(m.group(2))
    elif m := hit(rf"boosts (?:{ELEMENT}(?: element's)? )?speed by {SPAN}"):
        p.speed = float(m.group(2))
    elif m := hit(rf"{NUMBER}% chance of restoring {NUMBER} chakra"):
        p.chakra_on_hit = (float(m.group(1)), float(m.group(2)))
    elif m := hit(rf"boosts {ELEMENT}(?: element's)? attacks? by {SPAN}"):
        for name in _elements(m.group(1)):
            p.element_attack[name] = float(m.group(2))
    elif m := hit(rf"boosts attack by {SPAN}(?![\d.%-]*\s*x)"):
        p.flat_attack = float(m.group(1))
    elif m := hit(rf"boosts health by {SPAN}"):
        p.flat_health = float(m.group(1))
    elif m := hit(rf"boosts critical rate by {SPAN}\s*x"):
        p.effects.append(
            _grant(
                EffectKind.CRITICAL_RATE_BOOST, magnitude=(float(m.group(1)) - 1) * 100
            )
        )
    elif m := hit(rf"{SPAN} chance of attacking back"):
        p.counter = float(m.group(1))
    elif m := hit(rf"{SPAN} chance of dodging"):
        p.effects.append(_grant(EffectKind.DODGE, chance=float(m.group(1))))
    elif m := hit(rf"increases damage dealt to {ELEMENT} elementals? by {SPAN}"):
        for name in _elements(m.group(1)):
            p.damage_vs[name] = float(m.group(2))
    elif m := hit(
        rf"reduces {ELEMENT}(?:-|\s)?(?:elemental )?damage(?: taken)? by {SPAN}"
    ):
        for name in _elements(m.group(1)):
            p.reduce_from[name] = float(m.group(2))
    elif m := hit(rf"reduces damage(?: taken)? by {SPAN}"):
        p.effects.append(
            _grant(EffectKind.DAMAGE_REDUCTION, magnitude=float(m.group(1)))
        )
    elif m := hit(rf"restores {SPAN} health when moving to a new map"):
        p.map_heal = float(m.group(1))
    elif m := hit(rf"restores {SPAN} health(?: every turn)?"):
        p.regen = float(m.group(1))
    elif "one bar of chakra when moving to a new map" in low:
        p.map_chakra = 1.0
    elif m := hit(
        rf"{NUMBER}% chance to reduce chakra consumed by ninjutsu to {NUMBER}"
    ):
        p.ninjutsu_cut = (float(m.group(1)), float(m.group(2)))
    elif m := hit(
        rf"{NUMBER}% chance to reduce chakra consumed by secret techniques? to {NUMBER}"
    ):
        p.secret_cut = (float(m.group(1)), float(m.group(2)))
    elif m := hit(rf"reduces chakra consumed by {NUMBER}(?!%)"):
        p.chakra_cut = float(m.group(1))
    elif (
        m := hit(
            rf"(?:lowers rate of getting|reduces the chance of receiving|reduces the chance of your) (.+?) by {SPAN}"
        )
    ) and (
        kinds := [kind for word, kind in AILMENTS.items() if word in m.group(1).lower()]
    ):
        for kind in dict.fromkeys(kinds):
            p.effects.append(
                Effect(
                    kind=kind,
                    mode=EffectMode.RESIST,
                    chance=float(m.group(2)),
                    source="passive",
                )
            )
    else:
        p.skipped.append(clause)
        return p
    p.understood = 1
    return p


def parse_passive(text: str) -> Passive:
    total = Passive()
    for clause in _clauses(text):
        total.merge(parse_clause(clause))
    return total
