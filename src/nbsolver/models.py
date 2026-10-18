"""Core domain model: units as the game defines them, and what a player owns."""

from __future__ import annotations

from functools import cached_property
from itertools import pairwise

from pydantic import BaseModel, Field, field_validator

from nbsolver.effects import EffectSet
from nbsolver.enums import AttackRange, Element, JutsuShape

MAX_LEVEL = 100
# Ten limit breaks of five levels each sit on top of the base cap.
MAX_LIMIT_BREAK_LEVEL = 150
MAX_LUCK = 99
MAX_DUPES = 5

__all__ = [
    "MAX_DUPES",
    "MAX_LEVEL",
    "MAX_LIMIT_BREAK_LEVEL",
    "MAX_LUCK",
    "Ability",
    "AttackRange",
    "Element",
    "Jutsu",
    "JutsuShape",
    "OwnedUnit",
    "Skill",
    "StatLevel",
    "Unit",
]


class Skill(BaseModel):
    name: str = ""
    description: str = ""

    @cached_property
    def effects(self) -> EffectSet:
        return EffectSet.parse(self.description)


class Ability(Skill):
    unlock: str = ""


class Jutsu(Skill):
    chakra: int | None = None
    shape: JutsuShape | None = None
    position: str = ""

    @property
    def multiplier(self) -> float | None:
        return self.effects.multiplier


class StatLevel(BaseModel):
    label: str = ""
    level: int
    health: int
    attack: int
    speed: int = 0


class Unit(BaseModel):
    """A ninja as defined by the game, independent of any player."""

    unit_id: int
    name: str
    title: str = ""
    element: Element
    rarity: int = 0
    range: AttackRange | None = None
    affiliations: list[str] = Field(default_factory=list)

    cost: int = 0
    # Cost once every ability is unlocked, which is the floor a duped copy reaches.
    cost_all_abilities: int | None = None
    max_level: int = MAX_LEVEL
    max_level_limit_break: int = MAX_LEVEL
    luck_max: int = MAX_LUCK
    speed: int = 0
    levels: list[StatLevel] = Field(default_factory=list)

    ninjutsu: Jutsu | None = None
    secret_technique: Jutsu | None = None
    field_skill: Skill | None = None
    buddy_skill: Skill | None = None
    abilities: list[Ability] = Field(default_factory=list)

    awaken_to: int | None = None
    family: list[int] = Field(default_factory=list)

    @property
    def min_cost(self) -> int:
        return (
            self.cost_all_abilities
            if self.cost_all_abilities is not None
            else self.cost
        )

    @property
    def _growth_points(self) -> list[StatLevel]:
        """One entry per distinct level, keeping the first (pre-Ultimate) reading."""
        seen: dict[int, StatLevel] = {}
        for entry in self.levels:
            seen.setdefault(entry.level, entry)
        return sorted(seen.values(), key=lambda e: e.level)

    def stats_at(self, level: int) -> StatLevel:
        """Exact at every published anchor, linear between neighbouring ones."""
        points = self._growth_points
        if not points:
            return StatLevel(level=level, health=0, attack=0)
        if len(points) == 1:
            return points[0]

        level = max(points[0].level, min(level, points[-1].level))
        low, high = points[0], points[-1]
        for left, right in pairwise(points):
            if left.level <= level <= right.level:
                low, high = left, right
                break

        span = high.level - low.level
        ratio = 0.0 if span == 0 else (level - low.level) / span

        def lerp(a: int, b: int) -> int:
            return round(a + (b - a) * ratio)

        return StatLevel(
            label=f"Lv {level}",
            level=level,
            health=lerp(low.health, high.health),
            attack=lerp(low.attack, high.attack),
            speed=lerp(low.speed, high.speed),
        )

    def cost_with_abilities(self, unlocked: int) -> int:
        """Interpolated between base and all-abilities cost; exact steps unverified."""
        floor = self.min_cost
        total = len(self.abilities)
        if total == 0 or unlocked <= 0:
            return self.cost
        if unlocked >= total:
            return floor
        return round(self.cost + (floor - self.cost) * (unlocked / total))


class OwnedUnit(BaseModel):
    """A specific copy in a player's box, at its current progression."""

    unit_id: int
    level: int = MAX_LEVEL
    luck: int = 0
    dupes: int = 0
    limit_break: int = 0
    abilities_unlocked: list[str] = Field(default_factory=list)
    # Set when the player typed this in rather than it coming from a box scan.
    manually_added: bool = False

    @field_validator("level")
    @classmethod
    def _check_level(cls, v: int) -> int:
        if not 1 <= v <= MAX_LIMIT_BREAK_LEVEL:
            raise ValueError(f"level must be 1..{MAX_LIMIT_BREAK_LEVEL}, got {v}")
        return v

    @field_validator("luck")
    @classmethod
    def _check_luck(cls, v: int) -> int:
        if not 0 <= v <= MAX_LUCK:
            raise ValueError(f"luck must be 0..{MAX_LUCK}, got {v}")
        return v

    @field_validator("dupes")
    @classmethod
    def _check_dupes(cls, v: int) -> int:
        if not 0 <= v <= MAX_DUPES:
            raise ValueError(f"dupes must be 0..{MAX_DUPES}, got {v}")
        return v

    def unlocked_count(self, unit: Unit) -> int:
        named = len(self.abilities_unlocked)
        return min(max(named, self.dupes), len(unit.abilities))

    def cost(self, unit: Unit) -> int:
        return unit.cost_with_abilities(self.unlocked_count(unit))

    def stats(self, unit: Unit) -> StatLevel:
        return unit.stats_at(self.level)
