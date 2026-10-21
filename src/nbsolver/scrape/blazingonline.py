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
from nbsolver.models import (
    Ability,
    AttackRange,
    Element,
    Jutsu,
    JutsuShape,
    Skill,
    StatLevel,
    Unit,
)

BASE = "https://www.blazingonline.wiki/"
ATTRIBUTION = "blazingonline.wiki (Project: Rebirth server data)"
USER_AGENT = "nbsolver/0.1 (mission solver; personal project)"

RANGE_RE = re.compile(r"^(short|mid|long|vast)", re.IGNORECASE)


def _text(value: Any) -> str:
    """Published records use null for absent text as often as they omit the key."""
    return "" if value is None else str(value)


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

    def unit_index(self) -> dict[str, Any]:
        return self._get("data/units.json")

    def raw_unit(self, unit_id: int) -> dict[str, Any]:
        return self._get(f"data/units/{unit_id}.json")

    def unit(self, summary: dict[str, Any]) -> Unit:
        return parse_unit(summary, self.raw_unit(summary["id"]))


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
    name = _text(value).strip().upper()
    return Rank[name] if name in Rank.__members__ else Rank.C


def _conditions(raw: list[dict[str, Any]] | None) -> list[ClearCondition]:
    conditions: list[ClearCondition] = []
    for item in raw or []:
        pearls = sum(
            reward.get("q", 0) or 0
            for reward in item.get("r") or []
            if reward.get("c") == "pearl"
        )
        conditions.append(ClearCondition.parse(_text(item.get("t")), pearls))
    return conditions


def _skills(raw: list[dict[str, Any]] | None) -> list[EnemySkill]:
    return [
        EnemySkill(
            slot=_text(skill.get("slot")),
            name=_text(skill.get("n")),
            description=_text(skill.get("d")),
            range=_text(skill.get("rng")),
            targets=_text(skill.get("tgt")),
        )
        for skill in raw or []
    ]


def _enemy(entry: dict[str, Any], foes: dict[str, Any]) -> EnemyStats:
    detail = foes.get(_text(entry.get("k")), {})
    field = detail.get("field") or {}
    raw = detail.get("raw") or {}
    range_text = _text(detail.get("range"))

    return EnemyStats(
        key=_text(entry.get("k")),
        name=_text(entry.get("n") or detail.get("n")),
        element=_element(entry.get("el") or detail.get("el")) or Element.HEART,
        hp=entry.get("hp") or detail.get("hp") or 0,
        attack=entry.get("atk") or detail.get("atk") or 0,
        level=entry.get("lv") or 1,
        # One entry can stand for several identical enemies arriving together.
        count=entry.get("x") or 1,
        range=_range(range_text),
        range_text=range_text,
        is_boss=bool(entry.get("boss") or detail.get("boss")),
        carries=_text(entry.get("carries")),
        skills=_skills(detail.get("sk")),
        field_skill=_text(field.get("n")),
        field_skill_description=_text(field.get("d")),
        defences=sorted(
            {
                _text(line)
                for line in (detail.get("def") or []) + (detail.get("ab") or [])
            }
        ),
        ai_summary=[_text(line) for line in detail.get("ai") or []],
        ai_states=[_text(line) for line in raw.get("aiStates") or []],
    )


def _maps(raw: list[dict[str, Any]] | None, foes: dict[str, Any]) -> list[BattleMap]:
    maps: list[BattleMap] = []
    for index, node in enumerate(raw or [], start=1):
        sets = [
            EnemySet(
                weight=group.get("w") or 100.0,
                enemies=[_enemy(entry, foes) for entry in group.get("e") or []],
                waves=[
                    WaveSpawn(
                        number=wave.get("n") or 0,
                        trigger=_text(wave.get("t")),
                        rows=wave.get("rows") or 0,
                    )
                    for wave in group.get("waves") or []
                ],
            )
            for group in node.get("sets") or []
        ]
        maps.append(
            BattleMap(
                number=node.get("no") or index,
                clear=_text(node.get("clear")),
                sets=sets,
            )
        )
    return maps


def _stage(entry: dict[str, Any], foes: dict[str, Any]) -> Stage | None:
    server = entry.get("server")
    if not server:
        return None

    maps = _maps(server.get("maps"), foes)
    enemies = [e for m in maps for s in m.sets for e in s.enemies]
    boss = next((e for e in reversed(enemies) if e.is_boss), None)

    return Stage(
        name=_text(server.get("name") or entry.get("name")),
        rank=_rank(server.get("rank")),
        stamina=server.get("stamina") or 0,
        stage_id=server.get("id"),
        clear=_text(server.get("clear")),
        availability=_text(server.get("availability")),
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
        slug=_text(raw.get("id")),
        name=_text(raw.get("title")),
        mode=_text(raw.get("mode")),
        stages=stages,
        sources=sources,
    )


def _shape(value: Any) -> JutsuShape | None:
    try:
        return JutsuShape(_text(value).strip().capitalize())
    except ValueError:
        return None


def _jutsu(raw: dict[str, Any] | None) -> Jutsu | None:
    if not raw:
        return None
    return Jutsu(
        name=_text(raw.get("n")),
        description=_text(raw.get("d")),
        chakra=raw.get("c"),
        shape=_shape(raw.get("shape")),
        position=_text(raw.get("position")),
    )


def _skill(raw: dict[str, Any] | None) -> Skill | None:
    if not raw:
        return None
    return Skill(name=_text(raw.get("n")), description=_text(raw.get("d")))


def parse_unit(summary: dict[str, Any], detail: dict[str, Any]) -> Unit:
    """`summary` is an entry from units.json; `detail` is units/<id>.json."""
    stats = detail.get("stats") or {}
    forms = detail.get("forms") or {}

    return Unit(
        unit_id=summary["id"],
        name=_text(summary.get("n")),
        title=_text(summary.get("t")),
        element=_element(summary.get("e")) or Element.HEART,
        rarity=summary.get("r") or 0,
        range=_range(_text(summary.get("rg"))),
        cost=stats.get("cost") or summary.get("c") or 0,
        cost_all_abilities=stats.get("costAllAbilities"),
        max_level=stats.get("maxLevel") or detail.get("lv") or 1,
        max_level_limit_break=(
            stats.get("maxLevelLimitBreak")
            or stats.get("maxLevel")
            or detail.get("lv")
            or 1
        ),
        luck_max=stats.get("luckMax") or 0,
        speed=stats.get("speed") or 0,
        levels=[
            StatLevel(
                label=_text(entry.get("label")),
                level=entry.get("lv") or 0,
                health=entry.get("hp") or 0,
                attack=entry.get("atk") or 0,
                speed=entry.get("spd") or 0,
            )
            for entry in stats.get("levels") or []
        ],
        ninjutsu=_jutsu(detail.get("ninjutsu")),
        secret_technique=_jutsu(detail.get("ultimate") or detail.get("secret")),
        field_skill=_skill(detail.get("field")),
        buddy_skill=_skill(detail.get("buddy")),
        abilities=[
            Ability(
                name=_text(item.get("n")),
                description=_text(item.get("d")),
                unlock=_text(item.get("u")),
            )
            for item in detail.get("abilities") or []
        ],
        awaken_to=forms.get("awakenTo"),
        family=list(forms.get("family") or []),
    )
