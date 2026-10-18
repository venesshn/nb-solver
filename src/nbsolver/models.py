"""Core domain model: units as the game defines them, and what a player owns."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

MAX_LEVEL = 100
MAX_LUCK = 99
MAX_DUPES = 5


class Element(StrEnum):
    HEART = "Heart"
    SKILL = "Skill"
    BODY = "Body"
    BRAVERY = "Bravery"
    WISDOM = "Wisdom"


class AttackRange(StrEnum):
    SHORT = "Short"
    MID = "Mid"
    LONG = "Long"
    VAST = "Vast"


class JutsuShape(StrEnum):
    CIRCLE = "Circle"
    CONE = "Cone"
    LINE = "Line"
    SELF = "Self"


class Jutsu(BaseModel):
    name: str
    chakra: int
    shape: JutsuShape
    range: AttackRange
    hits: int | None = None
    description: str = ""


class Unit(BaseModel):
    """A ninja as defined by the game, independent of any player."""

    slug: str
    name: str
    title: str
    element: Element
    rarity: int
    range: AttackRange
    base_health: int
    base_strength: int
    hits: int = 1
    # Index i is the cost after i dupes, so cost_by_dupes[0] is the un-duped cost.
    cost_by_dupes: list[int]
    ninjutsu: Jutsu | None = None
    secret_technique: Jutsu | None = None
    field_skill: str = ""
    buddy_skill: str = ""

    @property
    def min_cost(self) -> int:
        return min(self.cost_by_dupes)


class OwnedUnit(BaseModel):
    """A specific copy in a player's box, at its current progression."""

    slug: str
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
        if not 1 <= v <= MAX_LEVEL:
            raise ValueError(f"level must be 1..{MAX_LEVEL}, got {v}")
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

    def cost(self, unit: Unit) -> int:
        return unit.cost_by_dupes[min(self.dupes, len(unit.cost_by_dupes) - 1)]
