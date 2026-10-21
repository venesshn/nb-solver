"""Build the local mission catalogue from blazingonline's published data."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

from nbsolver.missions import Mission, MissionCatalogue
from nbsolver.models import Unit
from nbsolver.scrape import blazingonline, hideoutgacha
from nbsolver.scrape.blazingonline import BlazingOnline
from nbsolver.scrape.hideoutgacha import HideoutGacha

ROOT = Path(__file__).resolve().parents[2]
CATALOGUE_PATH = ROOT / "data" / "catalogue.json"
UNITS_PATH = ROOT / "data" / "units.json"
CACHE_DIR = ROOT / "data" / "cache" / "missions"
UNIT_CACHE_DIR = ROOT / "data" / "cache" / "units"
HIDEOUT_CACHE_DIR = ROOT / "data" / "cache" / "hideout"

REQUEST_DELAY = 0.3


def _cached_raw(api: BlazingOnline, page: str, *, refresh: bool) -> dict:
    path = CACHE_DIR / f"{page}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))

    raw = api.raw_mission(page)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw), encoding="utf-8")
    time.sleep(REQUEST_DELAY)
    return raw


def build(
    *,
    pages: list[str] | None = None,
    refresh: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> MissionCatalogue:
    with BlazingOnline() as api:
        targets = pages or api.mission_pages()
        missions: list[Mission] = []

        for index, page in enumerate(targets, start=1):
            try:
                mission = blazingonline.parse_mission(
                    _cached_raw(api, page, refresh=refresh)
                )
            except Exception as exc:  # noqa: BLE001 - one bad page must not sink the run
                if on_progress:
                    on_progress(index, len(targets), f"{page}: FAILED ({exc})")
                continue

            missions.append(mission)
            if on_progress:
                on_progress(
                    index,
                    len(targets),
                    f"{page}: {mission.name} ({len(mission.stages)})",
                )

    return MissionCatalogue(missions=missions)


def _cached_unit(api: BlazingOnline, unit_id: int, *, refresh: bool) -> dict:
    path = UNIT_CACHE_DIR / f"{unit_id}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))

    raw = api.raw_unit(unit_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw), encoding="utf-8")
    time.sleep(REQUEST_DELAY)
    return raw


def build_units(
    *,
    refresh: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[Unit]:
    with BlazingOnline() as api:
        summaries = api.unit_index().get("units", [])
        units: list[Unit] = []

        for index, summary in enumerate(summaries, start=1):
            unit_id = summary.get("id")
            try:
                detail = _cached_unit(api, unit_id, refresh=refresh)
                unit = blazingonline.parse_unit(summary, detail)
            except Exception as exc:  # noqa: BLE001 - one bad unit must not sink the run
                if on_progress:
                    on_progress(index, len(summaries), f"{unit_id}: FAILED ({exc})")
                continue

            units.append(unit)
            if on_progress:
                on_progress(
                    index, len(summaries), f"{unit_id}: {unit.name} ({unit.title})"
                )

    return units


def load_units(
    path: Path = UNITS_PATH, *, revival_only: bool = True
) -> dict[int, Unit]:
    """Every unit the player could own, keyed by id."""
    records = json.loads(path.read_text(encoding="utf-8"))
    units = (Unit.model_validate(record) for record in records)
    return {u.unit_id: u for u in units if u.in_revival or not revival_only}


def _cached_page(api: HideoutGacha, mission_id: str, *, refresh: bool) -> str:
    path = HIDEOUT_CACHE_DIR / f"{mission_id}.html"
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")

    html = api.mission_html(mission_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    time.sleep(REQUEST_DELAY)
    return html


def add_hideoutgacha(
    catalogue: MissionCatalogue,
    *,
    refresh: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> int:
    """Lay on the battlefield geometry, defense and spawn timing blazingonline omits.

    Returns the number of maps that took the detail. A mission the site does not
    carry, or whose line-up no longer matches ours, is skipped rather than guessed at.
    """
    total = 0
    with HideoutGacha() as api:
        for index, mission in enumerate(catalogue.missions, start=1):
            page = hideoutgacha.mission_id(mission.slug)
            try:
                stages = hideoutgacha.parse_mission(
                    _cached_page(api, page, refresh=refresh)
                )
                merged = hideoutgacha.merge_mission(mission, stages)
            except Exception as exc:  # noqa: BLE001 - one bad page must not sink the run
                if on_progress:
                    on_progress(
                        index, len(catalogue.missions), f"{page}: FAILED ({exc})"
                    )
                continue

            total += merged
            if on_progress:
                on_progress(
                    index,
                    len(catalogue.missions),
                    f"{page}: {mission.name} ({merged} maps)",
                )

    return total


def main() -> None:
    # Mission titles contain characters the Windows console codec cannot encode.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    def report(index: int, total: int, message: str) -> None:
        print(f"[{index:>3}/{total}] {message}")

    catalogue = build(on_progress=report)
    maps = add_hideoutgacha(catalogue, on_progress=report)
    catalogue.save(CATALOGUE_PATH)

    stages = sum(len(m.stages) for m in catalogue.missions)
    random_stages = sum(
        1 for m in catalogue.missions for s in m.stages if s.has_random_sets
    )
    print(
        f"\n{len(catalogue.missions)} missions, {stages} stages "
        f"({random_stages} with random enemy sets, {maps} maps with geometry) "
        f"-> {CATALOGUE_PATH}"
    )

    units = build_units(on_progress=report)
    UNITS_PATH.parent.mkdir(parents=True, exist_ok=True)
    UNITS_PATH.write_text(
        json.dumps([u.model_dump(mode="json") for u in units], indent=2),
        encoding="utf-8",
    )
    print(f"\n{len(units)} units -> {UNITS_PATH}")


if __name__ == "__main__":
    main()
