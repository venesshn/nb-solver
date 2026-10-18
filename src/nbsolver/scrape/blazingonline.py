"""Read mission and enemy data from blazingonline.wiki's static JSON files."""

from __future__ import annotations

import re
from typing import Any, Self

import httpx

from nbsolver.missions import (
    BattleMap,
    ClearCondition,
    EnemySet,
    EnemySkill,
    EnemyStats,
    Mission,
    Rank,
    Stage,
    WaveSpawn,
)
from nbsolver.models import AttackRange, Element

BASE = "https://www.blazingonline.wiki/"
ATTRIBUTION = "blazingonline.wiki (Project: Rebirth server data)"
USER_AGENT = "nbsolver/0.1 (mission solver; personal project)"

RANGE_RE = re.compile(r"^(short|mid|long|vast)", re.IGNORECASE)


class BlazingOnline:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            base_url=BASE, timeout=60, headers={"User-Agent": USER_AGENT}
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()

    def _get(self, path: str) -> Any:
        response = self._client.get(path, follow_redirects=True)
        response.raise_for_status()
        return response.json()

    def mission_pages(self) -> list[str]:
        """Page ids such as 'e3013', one per event in the index."""
        events = self._get("data/missions.json").get("events", [])
        return [event["page"] for event in events if event.get("page")]

    def raw_mission(self, page: str) -> dict[str, Any]:
        return self._get(f"data/m/{page}.json")

    def mission(self, page: str) -> Mission:
        return parse_mission(self.raw_mission(page))


def _element(value: str | None) -> Element | None:
    if not value:
        return None
    try:
        return Element(value.strip().capitalize())
    except ValueError:
        return None


def _range(text: str) -> AttackRange | None:
    if match := RANGE_RE.match(text.strip()):
        try:
            return AttackRange(match.group(1).capitalize())
        except ValueError:
            return None
    return None


def _rank(value: str | None) -> Rank:
    name = (value or "").strip().upper()
    return Rank[name] if name in Rank.__members__ else Rank.C


def _conditions(raw: list[dict[str, Any]] | None) -> list[ClearCondition]:
    conditions: list[ClearCondition] = []
    for item in raw or []:
        pearls = sum(
            reward.get("q", 0) for reward in item.get("r", []) if reward.get("c") == "pearl"
        )
        conditions.append(ClearCondition.parse(item.get("t", ""), pearls))
    return conditions


def _skills(raw: list[dict[str, Any]] | None) -> list[EnemySkill]:
    return [
        EnemySkill(
            slot=skill.get("slot", ""),
            name=skill.get("n", ""),
            description=skill.get("d", ""),
            range=skill.get("rng", ""),
            targets=skill.get("tgt", ""),
        )
        for skill in raw or []
    ]


def _enemy(entry: dict[str, Any], foes: dict[str, Any]) -> EnemyStats:
    detail = foes.get(str(entry.get("k", "")), {})
    field = detail.get("field") or {}
    raw = detail.get("raw") or {}
    range_text = detail.get("range", "")

    return EnemyStats(
        key=str(entry.get("k", "")),
        name=entry.get("n") or detail.get("n", ""),
        element=_element(entry.get("el") or detail.get("el")) or Element.HEART,
        hp=entry.get("hp", detail.get("hp", 0)),
        attack=entry.get("atk", detail.get("atk", 0)),
        level=entry.get("lv", 1),
        range=_range(range_text),
        range_text=range_text,
        is_boss=bool(entry.get("boss") or detail.get("boss")),
        carries=entry.get("carries", ""),
        skills=_skills(detail.get("sk")),
        field_skill=field.get("n", ""),
        ai_summary=list(detail.get("ai") or []),
        ai_states=list(raw.get("aiStates") or []),
    )


def _maps(raw: list[dict[str, Any]] | None, foes: dict[str, Any]) -> list[BattleMap]:
    maps: list[BattleMap] = []
    for index, node in enumerate(raw or [], start=1):
        sets = [
            EnemySet(
                weight=group.get("w", 100.0),
                enemies=[_enemy(entry, foes) for entry in group.get("e", [])],
                waves=[
                    WaveSpawn(
                        number=wave.get("n", 0),
                        trigger=wave.get("t", ""),
                        rows=wave.get("rows", 0),
                    )
                    for wave in group.get("waves", [])
                ],
            )
            for group in node.get("sets", [])
        ]
        maps.append(BattleMap(number=node.get("no", index), clear=node.get("clear", ""), sets=sets))
    return maps


def _stage(entry: dict[str, Any], foes: dict[str, Any]) -> Stage | None:
    server = entry.get("server")
    if not server:
        return None

    maps = _maps(server.get("maps"), foes)
    enemies = [e for m in maps for s in m.sets for e in s.enemies]
    boss = next((e for e in reversed(enemies) if e.is_boss), None)

    return Stage(
        name=server.get("name") or entry.get("name", ""),
        rank=_rank(server.get("rank")),
        stamina=server.get("stamina", 0),
        stage_id=server.get("id"),
        clear=server.get("clear", ""),
        availability=server.get("availability", ""),
        boss_name=boss.name if boss else "",
        boss_element=boss.element if boss else None,
        enemies=enemies,
        maps=maps,
        conditions=_conditions(server.get("conds")),
    )


def parse_mission(raw: dict[str, Any]) -> Mission:
    foes = raw.get("foes") or {}
    stages = [
        stage
        for tab in raw.get("tabs", [])
        for entry in tab.get("missions", [])
        if (stage := _stage(entry, foes)) is not None
    ]

    sources = [ATTRIBUTION]
    if url := (raw.get("wiki") or {}).get("url"):
        sources.append(f"Naruto Blazing Wiki (Fandom), CC BY-SA 3.0 - {url}")

    return Mission(
        slug=raw.get("id", ""),
        name=raw.get("title", ""),
        mode=raw.get("mode", ""),
        stages=stages,
        sources=sources,
    )
