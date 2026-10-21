"""Read mission pages from hideoutgacha, for the details blazingonline omits.

blazingonline publishes the enemy AI scripts; this site publishes the
battlefield itself, enemy defense and when reinforcements walk on. The two
agree on every stat we have compared, so they merge rather than compete.
"""

from __future__ import annotations

import re
from typing import Self

import httpx
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, Field

from nbsolver.enums import Element
from nbsolver.missions import (
    BattleMap,
    EnemySkill,
    EnemyStats,
    GroupSpawn,
    MapGrid,
    Mission,
    SpawnRule,
    Tile,
    WaveSpawn,
)

BASE = "https://www.hideoutgacha.com"
ATTRIBUTION = "hideoutgacha.com (Hideout Guides)"
USER_AGENT = "nbsolver/0.1 (mission solver; personal project)"

# Tiles are drawn as a fixed-pitch SVG grid, so a coordinate divides straight
# back into a column and row.
TILE_PITCH = 20
PLAYER_FILL = "fill-state-info"
SPAWN_FILL = "fill-primary"

_GROUP_RE = re.compile(r"Group\D*(\d+)")
_COUNT_RE = re.compile(r"[x\u00d7]\s*(\d+)")
_WAVE_RE = re.compile(r"Wave\s+(\d+)")


def _classes(tag: Tag) -> list[str]:
    value = tag.get("class") or []
    return list(value) if isinstance(value, list) else [value]


def _has_class(tag: Tag, name: str) -> bool:
    """Classes are CSS-module hashed as `name__hash`; match the name exactly."""
    return any(c.startswith(f"{name}__") for c in _classes(tag))


def _find_all(root: Tag, name: str) -> list[Tag]:
    return [t for t in root.find_all(True) if _has_class(t, name)]


def _find(root: Tag, name: str) -> Tag | None:
    return next(iter(_find_all(root, name)), None)


def _int(text: str) -> int:
    digits = re.sub(r"[^\d-]", "", text)
    return int(digits) if digits else 0


class MapDetail(BaseModel):
    number: int
    grid: MapGrid | None = None
    enemies: list[EnemyStats] = Field(default_factory=list)
    waves: list[WaveSpawn] = Field(default_factory=list)
    spawn_rules: list[SpawnRule] = Field(default_factory=list)


class StageDetail(BaseModel):
    name: str = ""
    stamina: int = 0
    maps: list[MapDetail] = Field(default_factory=list)


class HideoutGacha:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            base_url=BASE,
            headers={"User-Agent": USER_AGENT},
            timeout=60,
            follow_redirects=True,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def mission_html(self, mission_id: int | str) -> str:
        response = self._client.get(f"/games/naruto-blazing/missions/{mission_id}")
        response.raise_for_status()
        return response.text


def parse_grid(svg: Tag) -> MapGrid:
    """Blue tiles are where your front row starts, numbered red tiles are spawns."""
    columns = rows = 0
    starts: list[Tile] = []
    groups: dict[int, list[Tile]] = {}

    for cell in svg.find_all("g"):
        rect = cell.find("rect")
        if rect is None:
            continue
        tile = Tile(
            column=_int(str(rect.get("x", 0))) // TILE_PITCH,
            row=_int(str(rect.get("y", 0))) // TILE_PITCH,
        )
        columns = max(columns, tile.column + 1)
        rows = max(rows, tile.row + 1)

        fills = _classes(rect)
        if PLAYER_FILL in fills:
            starts.append(tile)
        elif SPAWN_FILL in fills:
            label = cell.find("text")
            if label is not None:
                groups.setdefault(_int(label.get_text()), []).append(tile)

    return MapGrid(
        columns=columns,
        rows=rows,
        player_starts=starts,
        spawns=[GroupSpawn(group=n, tiles=t) for n, t in sorted(groups.items())],
    )


def _element(row: Tag) -> Element:
    for span in row.find_all("span"):
        text = span.get_text(strip=True)
        if text in Element.__members__.values() or text in {e.value for e in Element}:
            return Element(text)
    raise ValueError("no element on enemy row")


def _jutsu(row: Tag) -> list[EnemySkill]:
    return [
        EnemySkill(name=chip.get_text(strip=True))
        for chip in _find_all(row, "jutsu_chip")
    ]


def _field_skill(row: Tag) -> str:
    for sub in _find_all(row, "stage_whoSub"):
        text = sub.get_text(" ", strip=True)
        if text.startswith("Field Skill:"):
            return text.removeprefix("Field Skill:").strip()
    return ""


def parse_enemy(row: Tag) -> EnemyStats:
    name_tag = _find(row, "stage_whoName")
    role_tag = _find(row, "stage_role")
    group_tag = _find(row, "stage_grp")

    stats: dict[str, int] = {}
    block = _find(row, "stage_stats")
    if block is not None:
        for entry in block.find_all("span", recursive=False):
            label = entry.find("small")
            value = entry.find("b")
            if label is not None and value is not None:
                stats[label.get_text(strip=True).lower()] = _int(value.get_text())

    line = _find(row, "stage_whoLine")
    count = 1
    if line is not None:
        found = _COUNT_RE.search(line.get_text(" ", strip=True))
        count = int(found.group(1)) if found else 1

    group = None
    if group_tag is not None:
        found = _GROUP_RE.search(group_tag.get_text(" ", strip=True))
        group = int(found.group(1)) if found else None

    return EnemyStats(
        name=name_tag.get_text(strip=True) if name_tag else "",
        element=_element(row),
        hp=stats.get("hp", 0),
        attack=stats.get("atk", 0),
        defense=stats.get("def", 0),
        role=role_tag.get_text(strip=True) if role_tag else "",
        is_boss=bool(role_tag) and "boss" in role_tag.get_text(strip=True).lower(),
        spawn_group=group,
        count=count,
        skills=_jutsu(row),
        field_skill=_field_skill(row),
    )


def parse_map(details: Tag, number: int) -> MapDetail:
    svg = details.find("svg", attrs={"aria-label": re.compile("Battlefield")})
    detail = MapDetail(
        number=number,
        grid=parse_grid(svg) if isinstance(svg, Tag) else None,
    )

    for head in _find_all(details, "stage_waveHead"):
        found = _WAVE_RE.search(head.get_text(" ", strip=True))
        if found:
            detail.waves.append(WaveSpawn(number=int(found.group(1))))

    for item in details.find_all("li"):
        if _has_class(item, "stage_row"):
            detail.enemies.append(parse_enemy(item))
        elif _has_class(item, "stage_cmd"):
            number_tag = _find(item, "stage_no")
            texts = [s.get_text(" ", strip=True) for s in item.find_all("span")]
            body = next((t for t in texts if not t.startswith("#")), "")
            detail.spawn_rules.append(
                SpawnRule(
                    index=_int(number_tag.get_text()) if number_tag else 0,
                    text=body,
                    after=len(detail.enemies),
                )
            )

    return detail


def parse_mission(html: str) -> list[StageDetail]:
    """One entry per playable stage of the mission, in the order the site lists them."""
    soup = BeautifulSoup(html, "lxml")
    stages: list[StageDetail] = []

    for panel in _find_all(soup, "stage_panel"):
        title = _find(panel, "stage_pTitle")
        name = ""
        if title is not None:
            # The heading leads with "Mission 1 of 2", which is not part of the name.
            for counter in _find_all(title, "stage_pNo"):
                counter.decompose()
            name = title.get_text(" ", strip=True)

        stamina = 0
        for fact in _find_all(panel, "stage_fact"):
            text = fact.get_text(" ", strip=True)
            if "stamina" in text.lower():
                stamina = _int(text)
                break

        stage = StageDetail(name=name, stamina=stamina)
        for number, details in enumerate(_find_all(panel, "stage_map"), start=1):
            stage.maps.append(parse_map(details, number))
        stages.append(stage)

    return stages


def mission_id(slug: str) -> str:
    """Our slugs carry a mode letter the site's ids leave off: e3003 -> 3003."""
    return re.sub(r"^[a-z]+", "", slug)


def merge_map(target: BattleMap, detail: MapDetail) -> bool:
    """Lay the geometry and per-enemy extras onto a map we already hold.

    Both sites draw on the same master data, so a line-up should match row for
    row. Where a map picks its enemies at random we hold each variant
    separately and the site lists them all end to end. If neither reading
    matches, something has shifted and we leave the map alone rather than
    attach defense figures to the wrong enemy.
    """
    wanted = _lineup(detail.enemies)
    starts: list[int] = []
    if _lineup([e for group in target.sets for e in group.enemies]) == wanted:
        offset = 0
        for group in target.sets:
            starts.append(offset)
            offset += len(group.enemies)
    else:
        index = next(
            (i for i, g in enumerate(target.sets) if _lineup(g.enemies) == wanted), None
        )
        if index is None:
            return False
        starts = [0 if i == index else -1 for i in range(len(target.sets))]

    # The battlefield is the same whichever line-up walks onto it.
    target.grid = detail.grid
    for group, start in zip(target.sets, starts, strict=True):
        if start < 0:
            continue
        stop = start + len(group.enemies)
        group.spawn_rules = [
            rule.model_copy(update={"after": rule.after - start})
            for rule in detail.spawn_rules
            if start <= rule.after <= stop
        ]
        for offset, enemy in enumerate(group.enemies):
            extra = detail.enemies[start + offset]
            enemy.defense = extra.defense
            enemy.role = extra.role
            enemy.spawn_group = extra.spawn_group
    return True


def merge_mission(mission: Mission, stages: list[StageDetail]) -> int:
    """Returns the number of maps that accepted the extra detail.

    A boss rush holds a pool of maps that the two sites neither order nor
    document alike, so each map is placed by its line-up rather than by its
    position, preferring the same slot where that fits.
    """
    merged = 0
    for stage, detail in zip(mission.stages, stages, strict=False):
        taken: set[int] = set()
        for position, source in enumerate(detail.maps):
            order = [position, *range(len(stage.maps))]
            for index in order:
                if index in taken or index >= len(stage.maps):
                    continue
                if merge_map(stage.maps[index], source):
                    taken.add(index)
                    merged += 1
                    break

    if merged and ATTRIBUTION not in mission.sources:
        mission.sources.append(ATTRIBUTION)
    return merged


def _lineup(enemies: list[EnemyStats]) -> list[tuple[str, int, int, int]]:
    return [(e.name, e.hp, e.attack, e.count) for e in enemies]


__all__ = [
    "ATTRIBUTION",
    "BASE",
    "HideoutGacha",
    "MapDetail",
    "StageDetail",
    "merge_map",
    "merge_mission",
    "mission_id",
    "parse_enemy",
    "parse_grid",
    "parse_map",
    "parse_mission",
]
