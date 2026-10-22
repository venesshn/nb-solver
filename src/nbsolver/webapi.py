"""The solver as the website calls it: JSON text in, JSON text out."""

from __future__ import annotations

import json

from nbsolver.missions import Mission
from nbsolver.models import Unit
from nbsolver.roster import Roster
from nbsolver.solver import solve

_units: dict[int, Unit] = {}
# Confirmed by the player: three teams, each with its own health bar.
NINJA_ROAD_TEAMS = 3


def load_units(text: str) -> int:
    _units.clear()
    for row in json.loads(text):
        unit = Unit.model_validate(row)
        _units[unit.unit_id] = unit
    return len(_units)


def solve_json(
    mission_text: str,
    stage_name: str,
    roster_text: str,
    condition: int = -1,
    helper: str = "auto",
    tries: int = 40,
    progress=None,
) -> str:
    mission = Mission.model_validate_json(mission_text)
    stage = mission.stage(stage_name)
    if stage is None:
        return json.dumps(
            {"status": "error", "message": f"No stage called {stage_name!r}."}
        )
    roster = Roster.model_validate_json(roster_text)
    chosen = (
        stage.conditions[condition] if 0 <= condition < len(stage.conditions) else None
    )
    helping: int | str | None = helper if helper in ("auto", "self") else None
    if helper not in ("auto", "self", "none", ""):
        helping = int(helper)

    def report(done: int, total: int) -> None:
        if progress is not None:
            progress(done, total)

    result = solve(
        stage,
        roster,
        _units,
        condition=chosen,
        helper=helping,
        tries=tries,
        progress=report,
        teams=NINJA_ROAD_TEAMS if mission.mode == "ninja_road" else 1,
        boosts=mission.unit_boosts,
    )
    result["mission"] = {
        "slug": mission.slug,
        "name": mission.name,
        "stage": stage.name,
    }
    notes = []
    if mission.mode == "ninja_road":
        notes.append(
            "Ninja Road uses three separate teams, each keeping its own health bar"
            " across the maps it fights; each map goes to the team best placed for"
            " it, and a beaten team is out while the others carry on."
        )
        if mission.unit_boosts:
            featured = ", ".join(
                f"{b.name} '{b.title}' ({b.health:g}x health, {b.attack:g}x strength)"
                for b in mission.unit_boosts
            )
            notes.append(f"Featured units on this road: {featured}.")
    if any(m.grid is None or not m.grid.columns for m in stage.maps):
        notes.append(
            "No battlefield layout is published for this mission, so a generic one is"
            " used."
        )
    if notes and "assumptions" in result:
        result["assumptions"] = notes + result["assumptions"]
    result["grids"] = [
        {"columns": m.grid.columns, "rows": m.grid.rows} if m.grid else None
        for m in stage.maps
    ]
    return json.dumps(result, default=str)
