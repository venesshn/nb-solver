"""Scrape original-game mission data from the Naruto Blazing Fandom wiki (CC BY-SA)."""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup, Tag

from nbsolver.missions import ClearCondition, Mission, Rank, Stage, UnitBoost
from nbsolver.models import Element

API = "https://naruto-blazing.fandom.com/api.php"
ATTRIBUTION = "Naruto Blazing Wiki (Fandom), CC BY-SA 3.0"
USER_AGENT = "nbsolver/0.1 (mission solver; personal project)"

STAGE_RE = re.compile(r"^Stage\s+\d+:\s*(.+)$")
RANK_ICON_RE = re.compile(r"mission difficulty icon\s+(\w+)", re.IGNORECASE)
ELEMENT_ICON_RE = re.compile(
    r"^(heart|skill|body|bravery|wisdom)\s+icon$", re.IGNORECASE
)
REWARD_RE = re.compile(r"x\s*(\d+)")


def fetch_page_html(page: str, client: httpx.Client | None = None) -> str:
    owned = client is None
    client = client or httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT})
    try:
        response = client.get(
            API,
            params={"action": "parse", "page": page, "prop": "text", "format": "json"},
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
        by_rank.setdefault(current, []).append(
            ClearCondition.parse(description, pearls)
        )

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


UNIT_LINK_RE = re.compile(r'link=([^"|\]]+?)\s+"([^"]+)"\s*\(★(\d)\)')
ROWSPAN_RE = re.compile(r'^\s*rowspan="(\d+)"\s*\|(.*)$', re.DOTALL)
TIMES_RE = r"'*(\d+(?:\.\d+)?)x'*\s*{}"


def fetch_wikitext(page: str, client: httpx.Client | None = None) -> str:
    owned = client is None
    client = client or httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT})
    try:
        response = client.get(
            API,
            params={
                "action": "parse",
                "page": page,
                "prop": "wikitext",
                "format": "json",
            },
        )
        response.raise_for_status()
        return response.json()["parse"]["wikitext"]["*"]
    finally:
        if owned:
            client.close()


def _table_rows(section: str, columns: int) -> list[list[str]]:
    """A wikitable's body rows with every rowspan filled in, so each row is complete."""
    carried: list[tuple[str, int]] = [("", 0)] * columns
    rows = []
    for chunk in section.split("\n|-")[1:]:
        lines = chunk.strip("\n").splitlines()
        if any(line.startswith("!") for line in lines):
            continue
        cells = [
            line[1:]
            for line in lines
            if line.startswith("|") and line[:2] not in ("|}", "|-")
        ]
        row = []
        for column in range(columns):
            text, left = carried[column]
            if left > 0:
                row.append(text)
                carried[column] = (text, left - 1)
                continue
            if not cells:
                row.append("")
                continue
            cell = cells.pop(0)
            if found := ROWSPAN_RE.match(cell):
                span, cell = int(found.group(1)), found.group(2)
                carried[column] = (cell, span - 1)
            row.append(cell)
        rows.append(row)
    return rows


def parse_ninja_road_boosts(wikitext: str) -> dict[int, list[UnitBoost]]:
    """Featured units per Ninja Road number, from the wiki's Extra Effects table.

    Only health and strength multipliers matter to a battle; coin-only effects
    are skipped. Every rarity of a featured unit gets the same multipliers.
    """
    start = wikitext.find("Extra Effects")
    if start < 0:
        return {}
    section = wikitext[start : wikitext.find("|}", start)]
    boosts: dict[int, list[UnitBoost]] = {}
    for number, characters, effect in _table_rows(section, 3):
        if not number.strip().isdigit():
            continue
        health = re.search(TIMES_RE.format("Health"), effect)
        strength = re.search(TIMES_RE.format("Strength"), effect)
        if not (health or strength):
            continue
        seen = set()
        for name, title, _ in UNIT_LINK_RE.findall(characters):
            if (name, title) in seen:
                continue
            seen.add((name, title))
            boosts.setdefault(int(number), []).append(
                UnitBoost(
                    name=name.strip(),
                    title=title.strip(),
                    health=float(health.group(1)) if health else 1.0,
                    attack=float(strength.group(1)) if strength else 1.0,
                )
            )
    return boosts
