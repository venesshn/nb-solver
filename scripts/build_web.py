"""Assemble the static site: hand-written pages plus generated data and engine.

    python scripts/build_web.py [out_dir]

Writes to site/ by default. The engine ships as a zip of the pure-Python
modules the solver needs; Pyodide unpacks it in the browser. Missions are split
one file per mission so a visitor only downloads what they pick.
"""

import json
import shutil
import sys
import zipfile
from pathlib import Path

from nbsolver.missions import MissionCatalogue

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
ENGINE = ROOT / "src" / "nbsolver"
# Only what the solver imports; scrapers and the OpenCV reader stay behind.
MODULES = (
    "__init__.py",
    "ai.py",
    "battle.py",
    "combat.py",
    "effects.py",
    "enums.py",
    "missions.py",
    "models.py",
    "roster.py",
    "simulate.py",
    "solver.py",
    "webapi.py",
)


def compact(value) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def build(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(WEB, out)
    data = out / "data"
    (data / "missions").mkdir(parents=True, exist_ok=True)

    units = json.loads((ROOT / "data" / "units.json").read_text(encoding="utf-8"))
    (data / "units.json").write_text(compact(units), encoding="utf-8")

    catalogue = MissionCatalogue.load(ROOT / "data" / "catalogue.json")
    index = []
    for mission in catalogue.missions:
        (data / "missions" / f"{mission.slug}.json").write_text(
            mission.model_dump_json(exclude_defaults=True), encoding="utf-8"
        )
        index.append(
            {
                "slug": mission.slug,
                "name": mission.name,
                "mode": mission.mode,
                "stages": [
                    {
                        "name": s.name,
                        "rank": s.rank,
                        "stamina": s.stamina,
                        "boss": s.boss_name,
                        "boss_element": s.boss_element,
                        "maps": len(s.maps),
                        "conditions": [
                            {
                                "kind": c.kind,
                                "description": c.description,
                                "pearls": c.pearls,
                            }
                            for c in s.conditions
                        ],
                    }
                    for s in mission.stages
                ],
                "sources": mission.sources,
            }
        )
    (data / "missions" / "index.json").write_text(compact(index), encoding="utf-8")

    example = json.loads(
        (ROOT / "data" / "rosters" / "example.json").read_text(encoding="utf-8")
    )
    example["player_id"] = ""
    (data / "example-roster.json").write_text(compact(example), encoding="utf-8")

    py = out / "py"
    py.mkdir(exist_ok=True)
    with zipfile.ZipFile(py / "nbsolver.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in MODULES:
            archive.write(ENGINE / name, f"nbsolver/{name}")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(
        f"built {out}: {len(index)} missions, {len(units)} units, {size / 1e6:.1f} MB"
    )


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "site")
