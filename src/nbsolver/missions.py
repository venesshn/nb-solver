"""Mission structure: stages, the enemies in them, and the optional clear conditions."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from functools import cached_property, partial
from pathlib import Path

from pydantic import BaseModel, Field

from nbsolver.effects import Effect, EffectMode, EffectSet
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
    AFFILIATION_ONLY = "affiliation_only"
    REQUIRE_UNITS = "require_units"
    TURN_LIMIT = "turn_limit"
    NO_CONTINUES = "no_continues"
    NO_AILMENTS = "no_ailments"
    NINJUTSU_FINISH = "ninjutsu_finish"
    COMBO_FINISH = "combo_finish"
    DEFEAT_ALL = "defeat_all"
    DROP_COMPLETE = "drop_complete"
    OTHER = "other"


class ClearCondition(BaseModel):
    """An optional objective, e.g. 'Skill elementals only' for 3 Ninja Pearls."""

    kind: ConditionKind
    description: str
    pearls: int = 0
    element: Element | None = None
    max_cost: int | None = None
    max_turns: int | None = None
    affiliation: str = ""
    required_unit: str = ""
    required_count: int | None = None

    @classmethod
    def parse(cls, text: str, pearls: int = 0) -> ClearCondition:
        cleaned = " ".join(text.split())
        lowered = cleaned.lower()
        build = partial(cls, description=cleaned, pearls=pearls)

        if match := re.match(r"(heart|skill|body|bravery|wisdom)\s+elementals?\s+only", lowered):
            return build(
                kind=ConditionKind.ELEMENT_ONLY, element=Element(match.group(1).capitalize())
            )
        if match := re.search(r"cost\s+(\d+)\s+or\s+lower", lowered):
            return build(kind=ConditionKind.COST_CAP, max_cost=int(match.group(1)))
        if match := re.search(r"within\s+(\d+)\s+turns?", lowered):
            return build(kind=ConditionKind.TURN_LIMIT, max_turns=int(match.group(1)))
        if match := re.search(r"use only\s+(.+?)\s+characters", cleaned, re.IGNORECASE):
            return build(kind=ConditionKind.AFFILIATION_ONLY, affiliation=match.group(1))
        if match := re.search(r"have\s+(\d+)\+?\s+(.+?)\s+characters", cleaned, re.IGNORECASE):
            return build(
                kind=ConditionKind.REQUIRE_UNITS,
                required_count=int(match.group(1)),
                required_unit=match.group(2),
            )
        if "no continues" in lowered:
            return build(kind=ConditionKind.NO_CONTINUES)
        if "status ailment" in lowered:
            return build(kind=ConditionKind.NO_AILMENTS)
        if "using ninjutsu" in lowered:
            return build(kind=ConditionKind.NINJUTSU_FINISH)
        if "combination" in lowered:
            return build(kind=ConditionKind.COMBO_FINISH)
        if "defeat all enemies" in lowered:
            return build(kind=ConditionKind.DEFEAT_ALL)
        if "drop complete" in lowered:
            return build(kind=ConditionKind.DROP_COMPLETE)
        return build(kind=ConditionKind.OTHER)


class EnemySkill(BaseModel):
    slot: str = ""
    name: str = ""
    description: str = ""
    range: str = ""
    targets: str = ""

    @cached_property
    def effects(self) -> EffectSet:
        return EffectSet.parse(self.description)


class EnemyStats(BaseModel):
    """An enemy as it appears in one specific map."""

    key: str = ""
    name: str
    element: Element
    hp: int
    attack: int
    level: int = 1
    range: AttackRange | None = None
    range_text: str = ""
    is_boss: bool = False
    carries: str = ""
    skills: list[EnemySkill] = Field(default_factory=list)
    field_skill: str = ""
    # Human-readable AI summary, plus the underlying state machine when published.
    ai_summary: list[str] = Field(default_factory=list)
    ai_states: list[str] = Field(default_factory=list)

    @cached_property
    def threats(self) -> list[Effect]:
        """Everything this enemy can do to the player, skills and field skill alike."""
        found = [e for skill in self.skills for e in skill.effects.effects]
        found += EffectSet.parse(self.field_skill).effects
        return [e for e in found if e.mode in (EffectMode.INFLICT, EffectMode.PIERCE)]


class WaveSpawn(BaseModel):
    number: int
    trigger: str = ""
    rows: int = 0


class EnemySet(BaseModel):
    """One possible enemy line-up for a map; `weight` is its chance of being rolled."""

    weight: float = 100.0
    enemies: list[EnemyStats] = Field(default_factory=list)
    waves: list[WaveSpawn] = Field(default_factory=list)


class BattleMap(BaseModel):
    number: int
    clear: str = ""
    sets: list[EnemySet] = Field(default_factory=list)

    @property
    def is_random(self) -> bool:
        return len(self.sets) > 1


class Stage(BaseModel):
    name: str
    rank: Rank
    stamina: int
    stage_id: int | None = None
    clear: str = ""
    availability: str = ""
    boss_name: str = ""
    boss_element: Element | None = None
    enemies: list[EnemyStats] = Field(default_factory=list)
    maps: list[BattleMap] = Field(default_factory=list)
    conditions: list[ClearCondition] = Field(default_factory=list)

    def conditions_for(self, kind: ConditionKind) -> list[ClearCondition]:
        return [c for c in self.conditions if c.kind == kind]

    @property
    def has_random_sets(self) -> bool:
        return any(m.is_random for m in self.maps)


class Mission(BaseModel):
    slug: str
    name: str
    mode: str = ""
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
