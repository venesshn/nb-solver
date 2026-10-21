"""Read every unit off a box recording's visit pages, and optionally save them.

    python scripts/read_visits.py pages_dir out_json [--roster roster.json]

pages_dir holds one page per unit visited, as written by box_visits.py. The
roster is only written when every page reads cleanly; anything doubtful is
listed instead so it can be checked by eye first.
"""

import json
import sys
from dataclasses import asdict
from pathlib import Path

import cv2

from nbsolver.box_reader import read_page
from nbsolver.catalogue import UNITS_PATH
from nbsolver.models import Unit
from nbsolver.roster import Roster

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main(pages_dir: Path, out: Path, roster_path: Path | None) -> None:
    units = [
        Unit.model_validate(r)
        for r in json.loads(UNITS_PATH.read_text(encoding="utf-8"))
        if (r.get("rarity") or 0) >= 4
    ]
    paths = sorted(pages_dir.glob("*.png"))
    readings = []
    for number, path in enumerate(paths):
        reading = read_page(cv2.imread(str(path)), units)
        readings.append({"visit": number, "page": path.name, **asdict(reading)})
        mark = " " if reading.certain else "?"
        print(
            f"{mark} {number:3d} {reading.rarity}* {reading.name} '{reading.title}' "
            f"lv{reading.level}/{reading.level_cap} +{reading.margin:.2f}",
            flush=True,
        )
        for problem in reading.problems:
            print(f"        {problem}", flush=True)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(readings, indent=2), encoding="utf-8")
    doubtful = [r for r in readings if r["problems"]]
    print(
        f"{len(readings)} pages, {len(readings) - len(doubtful)} read cleanly -> {out}"
    )

    if roster_path is None:
        return
    if doubtful:
        raise SystemExit(f"roster not written: {len(doubtful)} pages need checking")
    old = Roster.load(roster_path)
    roster = Roster(player_id=old.player_id, team_cost_limit=old.team_cost_limit)
    for r in readings:
        roster.add(
            r["unit_id"], level=r["level"], limit_break=r["limit_break"], manual=False
        )
    roster.save(roster_path)
    print(f"roster of {len(roster.units)} units written to {roster_path}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--roster"]
    roster_arg = None
    if "--roster" in sys.argv:
        raw = sys.argv[sys.argv.index("--roster") + 1]
        args.remove(raw)
        roster_arg = Path(raw)
    if len(args) != 2:
        raise SystemExit(__doc__)
    main(Path(args[0]), Path(args[1]), roster_arg)
