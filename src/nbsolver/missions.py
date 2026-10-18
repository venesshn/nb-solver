"""Mission structure: stages, the enemies in them, and the optional clear conditions."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from nbsolver.models import AttackRange, Element


class Rank(StrEnum):
    C = "C"
    B = "B"
    A = "A"
    S = "S"
    SS = "SS"


class ConditionKind(StrEnum):
    ELEMENT_ONLY = "element_only"
    COST_CAP = "cost_cap"
    DROP_COMPLETE = "drop_complete"
    OTHER = "other"


class ClearCondition(BaseModel):
    """An optional objective, e.g. 'Skill elementals only' for 3 Ninja Pearls."""

    kind: ConditionKind
    description: str
    pearls: int = 0
    element: Element | None = None
    max_cost: int | None = None

    @classmethod
    def parse(cls, text: str, pearls: int = 0) -> ClearCondition:
        cleaned = text.strip()
        lowered = cleaned.lower()

        if match := re.match(r"(heart|skill|body|bravery|wisdom)\s+elementals?\s+only", lowered):
            return cls(
                kind=ConditionKind.ELEMENT_ONLY,
                description=cleaned,
                pearls=pearls,
                element=Element(match.group(1).capitalize()),
            )
        if match := re.search(r"cost\s+(\d+)\s+or\s+lower", lowered):
            return cls(
                kind=ConditionKind.COST_CAP,
                description=cleaned,
                pearls=pearls,
                max_cost=int(match.group(1)),
            )
        if "drop complete" in lowered:
            return cls(kind=ConditionKind.DROP_COMPLETE, description=cleaned, pearls=pearls)
        return cls(kind=ConditionKind.OTHER, description=cleaned, pearls=pearls)


class EnemyStats(BaseModel):
    """An enemy as it appears in one specific stage."""

    name: str
    element: Element
    hp: int
    attack: int
    range: AttackRange | None = None
    is_boss: bool = False


class Stage(BaseModel):
    name: str
    rank: Rank
    stamina: int
    boss_name: str = ""
    boss_element: Element | None = None
    enemies: list[EnemyStats] = Field(default_factory=list)
    conditions: list[ClearCondition] = Field(default_factory=list)

    def conditions_for(self, kind: ConditionKind) -> list[ClearCondition]:
        return [c for c in self.conditions if c.kind == kind]


class Mission(BaseModel):
    slug: str
    name: str
    stages: list[Stage] = Field(default_factory=list)
    # Where the numbers came from, since CC BY-SA requires attribution.
    sources: list[str] = Field(default_factory=list)

    def stage(self, name: str) -> Stage | None:
        target = name.casefold()
        return next((s for s in self.stages if s.name.casefold() == target), None)


class MissionCatalogue(BaseModel):
    missions: list[Mission] = Field(default_factory=list)

    def get(self, slug: str) -> Mission | None:
        return next((m for m in self.missions if m.slug == slug), None)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> MissionCatalogue:
        if not path.exists():
            return cls()
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
