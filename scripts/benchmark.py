"""Solve a fixed spread of stages with the example box and report the clear rates.

    python scripts/benchmark.py [--stages N] [--tries T] [--out FILE]

The same stages every time (seeded), so runs before and after an engine change
compare like for like. Uses every core; each stage is solved with no helper,
which is how the player usually plays.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_cache: dict = {}


def _load():
    if not _cache:
        from nbsolver.missions import MissionCatalogue
        from nbsolver.models import Unit
        from nbsolver.roster import Roster

        rows = json.loads((ROOT / "data" / "units.json").read_text(encoding="utf-8"))
        _cache["units"] = {r["unit_id"]: Unit.model_validate(r) for r in rows}
        _cache["catalogue"] = MissionCatalogue.load(ROOT / "data" / "catalogue.json")
        _cache["roster"] = Roster.load(ROOT / "data" / "rosters" / "example.json")
    return _cache


def pick_stages(count: int, seed: int = 7) -> list[tuple[str, str, int]]:
    """A seeded spread across modes; Ninja Road and boss raids excluded."""
    from nbsolver.missions import MissionCatalogue

    catalogue = MissionCatalogue.load(ROOT / "data" / "catalogue.json")
    pool = [
        (m.slug, s.name, m.mode)
        for m in catalogue.missions
        if m.mode not in ("ninja_road",)
        for s in m.stages
        if s.maps
    ]
    rng = random.Random(seed)
    by_mode: dict[str, list] = {}
    for item in pool:
        by_mode.setdefault(item[2], []).append(item)
    picked = []
    while len(picked) < count and any(by_mode.values()):
        for items in by_mode.values():
            if items and len(picked) < count:
                picked.append(items.pop(rng.randrange(len(items))))
    return [(slug, name, -1) for slug, name, _ in picked]


# Stages the player can't clear yet and wants the solver to crack, with every
# objective each one offers (the player's own list, 2026-10-22).
PLAYER_STAGES = [
    ("e7001", "Revival of Legends [S]"),
    ("e7002", "Night of Tragedy [S] *Recommended Range: Mid, Long"),
    ("e7003", "Broadminded [S]"),
    ("e3016", "Connected Brothers [A]"),
    ("e3018", "Cold Eyes [A]"),
    ("e4004", "The Sand's Final Weapon [A]"),
    ("e4009", "Creeping Dark Clouds [A]"),
    ("e4015", "Proof of Hard Work [A]"),
]


def player_stages() -> list[tuple[str, str, int]]:
    return [(slug, name, k) for slug, name in PLAYER_STAGES for k in range(3)]


def solve_one(job: tuple[str, str, int, int, str, float | None]) -> dict:
    from nbsolver import simulate
    from nbsolver.solver import solve

    slug, name, condition, tries, helper, area = job
    if area is not None:
        simulate.ENEMY_AREA = area
    data = _load()
    mission = data["catalogue"].get(slug)
    stage = mission.stage(name)
    chosen = (
        stage.conditions[condition] if 0 <= condition < len(stage.conditions) else None
    )
    start = time.perf_counter()
    report = solve(
        stage,
        data["roster"],
        data["units"],
        condition=chosen,
        helper=None if helper == "none" else helper,
        tries=tries,
    )
    return {
        "slug": slug,
        "mode": mission.mode,
        "stage": name + (f" / {chosen.description}" if chosen else ""),
        "rank": str(stage.rank),
        "maps": len(stage.maps),
        "status": report["status"],
        "likelihood": report.get("likelihood", 0.0),
        "reached": report.get("reached"),
        "seconds": round(time.perf_counter() - start, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stages", type=int, default=48)
    parser.add_argument("--tries", type=int, default=12)
    parser.add_argument("--set", choices=["spread", "player"], default="spread")
    parser.add_argument("--helper", default="none", help="none, self or auto")
    parser.add_argument("--enemy-area", type=float, default=None)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    stages = player_stages() if args.set == "player" else pick_stages(args.stages)
    jobs = [
        (slug, name, k, args.tries, args.helper, args.enemy_area)
        for slug, name, k in stages
    ]
    with ProcessPoolExecutor() as pool:
        results = list(pool.map(solve_one, jobs))
    for r in sorted(results, key=lambda r: (r["mode"], r["likelihood"])):
        reach = r.get("reached")
        close = (
            f"best loss: map {reach['map']}/{reach['maps']}, {reach['enemy_left']:.0%} left"
            if reach and r["likelihood"] == 0
            else ""
        )
        print(
            f"{r['likelihood']:5.0%}  {r['status']:10} {r['mode']:9} {r['rank']:>4}"
            f"  {r['slug']:10} {r['stage'][:70]}  {close} ({r['seconds']}s)"
        )
    statuses = Counter(r["status"] for r in results)
    mean = sum(r["likelihood"] for r in results) / len(results)
    print(f"\n{dict(statuses)}  mean likelihood {mean:.0%}")
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
