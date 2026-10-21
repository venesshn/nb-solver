"""Solve one stage for one roster from the command line.

    python scripts/solve.py MISSION_SLUG "STAGE NAME" [--condition N] [--helper ID|none] [--tries N]

Without --condition the team only has to clear ("beat"); with it, the team must
also meet that numbered objective ("complete"). Writes the full report to
data/analysis/solve_report.json and prints a summary.
"""

import json
import sys
import time
from pathlib import Path

from nbsolver.missions import MissionCatalogue
from nbsolver.models import Unit
from nbsolver.roster import Roster
from nbsolver.solver import solve

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]


def option(name: str, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    catalogue = MissionCatalogue.load(ROOT / "data" / "catalogue.json")
    mission = catalogue.get(sys.argv[1])
    if mission is None:
        raise SystemExit(f"no mission {sys.argv[1]}")
    stage = mission.stage(sys.argv[2])
    if stage is None:
        raise SystemExit(
            f"no stage {sys.argv[2]!r}; have {[s.name for s in mission.stages]}"
        )
    units = {
        u.unit_id: u
        for u in (
            Unit.model_validate(r)
            for r in json.loads(
                (ROOT / "data" / "units.json").read_text(encoding="utf-8")
            )
        )
    }
    roster = Roster.load(ROOT / "data" / "rosters" / "example.json")
    index = option("--condition")
    condition = stage.conditions[int(index)] if index is not None else None
    helper = option("--helper", "auto")
    helper = None if helper == "none" else ("auto" if helper == "auto" else int(helper))

    started = time.perf_counter()
    report = solve(
        stage,
        roster,
        units,
        condition=condition,
        helper=helper,
        tries=int(option("--tries", 40)),
    )
    took = time.perf_counter() - started
    out = ROOT / "data" / "analysis" / "solve_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"{mission.name} / {stage.name}  ({took:.1f}s)")
    print("objective:", condition.description if condition else "beat")
    print(
        "status:",
        report["status"],
        report.get("message") or "",
        report.get("reason") or "",
    )
    if "team" in report:
        team = report["team"]
        print(
            f"likelihood {report['likelihood']:.0%}  95% {report['interval']}  over {report['tries']} tries;"
            f" median turns {report['median_turns']}; cost {team['cost']}/{team['cost_limit']}"
        )
        for slot in ("front", "back"):
            for c in team[slot]:
                print(
                    f"  {slot:5} {c['name']} '{c['title']}' {c['element']} lv{c['level']} cost {c['cost']}"
                )
        if team["helper"]:
            h = team["helper"]
            print(f"  help  {h['name']} '{h['title']}' {h['element']} lv{h['level']}")
        for note in report["depends_on"]:
            print("  depends:", note)
        for frame in report["showcase"]["frames"][:6]:
            print(f"  turn {frame['turn']}: {frame['instruction']}")
    for r in report.get("recommendations", []):
        print(f"  try: {r['step']} -> {r['likelihood']:.0%}")


if __name__ == "__main__":
    main()
