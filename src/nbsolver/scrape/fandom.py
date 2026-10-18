"""Scrape original-game mission data from the Naruto Blazing Fandom wiki (CC BY-SA)."""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup, Tag

from nbsolver.missions import ClearCondition, Mission, Rank, Stage
from nbsolver.models import Element

API = "https://naruto-blazing.fandom.com/api.php"
ATTRIBUTION = "Naruto Blazing Wiki (Fandom), CC BY-SA 3.0"
USER_AGENT = "nbsolver/0.1 (mission solver; personal project)"

STAGE_RE = re.compile(r"^Stage\s+\d+:\s*(.+)$")
RANK_ICON_RE = re.compile(r"mission difficulty icon\s+(\w+)", re.IGNORECASE)
ELEMENT_ICON_RE = re.compile(r"^(heart|skill|body|bravery|wisdom)\s+icon$", re.IGNORECASE)
REWARD_RE = re.compile(r"x\s*(\d+)")


def fetch_page_html(page: str, client: httpx.Client | None = None) -> str:
    owned = client is None
    client = client or httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT})
    try:
        response = client.get(
            API, params={"action": "parse", "page": page, "prop": "text", "format": "json"}
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise ValueError(f"wiki error for {page!r}: {payload['error'].get('info')}")
        return payload["parse"]["text"]["*"]
    finally:
        if owned:
            client.close()


def _img_alts(cell: Tag) -> list[str]:
    return [img.get("alt", "") for img in cell.find_all("img")]


def _rank_from(cell: Tag) -> Rank | None:
    for alt in _img_alts(cell):
        if match := RANK_ICON_RE.search(alt):
            letter = match.group(1).upper()
            if letter in Rank.__members__:
                return Rank[letter]
    return None


def _element_from(cell: Tag) -> Element | None:
    for alt in _img_alts(cell):
        if match := ELEMENT_ICON_RE.match(alt.strip()):
            return Element(match.group(1).capitalize())
    return None


def _parse_stages(table: Tag) -> list[Stage]:
    stages: list[Stage] = []
    pending_name: str | None = None

    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if not cells:
            continue

        text = cells[0].get_text(" ", strip=True)
        if len(cells) == 1 and (match := STAGE_RE.match(text)):
            pending_name = match.group(1).strip()
            continue

        rank = _rank_from(cells[0])
        if pending_name is None or rank is None:
            continue

        stamina = 0
        if len(cells) > 1 and (digits := cells[1].get_text(strip=True)).isdigit():
            stamina = int(digits)

        element = next(
            (el for cell in cells[2:5] if (el := _element_from(cell)) is not None), None
        )
        stages.append(
            Stage(name=pending_name, rank=rank, stamina=stamina, boss_element=element)
        )
        pending_name = None

    return stages


def _parse_conditions(table: Tag) -> dict[Rank, list[ClearCondition]]:
    by_rank: dict[Rank, list[ClearCondition]] = {}
    current: Rank | None = None

    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if not cells:
            continue

        if rank := _rank_from(cells[0]):
            current = rank
            cells = cells[1:]
        if current is None or len(cells) < 3:
            continue

        description = cells[1].get_text(" ", strip=True)
        if not description:
            continue

        reward = cells[2].get_text(" ", strip=True)
        pearls = int(match.group(1)) if (match := REWARD_RE.search(reward)) else 0
        by_rank.setdefault(current, []).append(ClearCondition.parse(description, pearls))

    return by_rank


def parse_mission(page: str, html: str) -> Mission:
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")

    stages: list[Stage] = []
    conditions: dict[Rank, list[ClearCondition]] = {}
    for table in tables:
        if not stages:
            stages = _parse_stages(table)
        if "special reward condition" in table.get_text(" ", strip=True)[:60].lower():
            conditions = _parse_conditions(table)

    for stage in stages:
        stage.conditions = conditions.get(stage.rank, [])

    return Mission(
        slug=page.replace(" ", "_"),
        name=page.replace("_", " "),
        stages=stages,
        sources=[ATTRIBUTION],
    )


def scrape_mission(page: str, client: httpx.Client | None = None) -> Mission:
    return parse_mission(page, fetch_page_html(page, client))
