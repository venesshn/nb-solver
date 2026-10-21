"""Assemble the static site: hand-written pages plus generated data and engine.

    python scripts/build_web.py [out_dir]

Writes to site/ by default. The engine ships as a zip of the pure-Python
modules the solver needs; Pyodide unpacks it in the browser. Missions are split
one file per mission so a visitor only downloads what they pick.
"""

import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

from nbsolver.missions import MissionCatalogue
from nbsolver.models import Unit

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
ENGINE = ROOT / "src" / "nbsolver"
# Everything in the package ships except these: scraping, OpenCV reading and asset
# extraction need libraries a browser doesn't have, and the solver never imports them.
LEFT_OUT = {"box_reader.py", "catalogue.py", "extract.py"}


def engine_modules() -> list[str]:
    modules = sorted(p.name for p in ENGINE.glob("*.py") if p.name not in LEFT_OUT)
    shipped = {name.removesuffix(".py") for name in modules}
    for name in modules:
        text = (ENGINE / name).read_text(encoding="utf-8")
        for needed in re.findall(r"^\s*from nbsolver\.(\w+)", text, re.MULTILINE):
            if needed not in shipped:
                raise SystemExit(
                    f"{name} imports nbsolver.{needed}, which is not shipped"
                )
    return modules


def write_engine(path: Path) -> None:
    """The package as the browser gets it: a zip Pyodide unpacks onto its path."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in engine_modules():
            archive.write(ENGINE / name, f"nbsolver/{name}")


def compact(value) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def build(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(WEB, out)
    data = out / "data"
    (data / "missions").mkdir(parents=True, exist_ok=True)

    units = [
        row
        for row in json.loads(
            (ROOT / "data" / "units.json").read_text(encoding="utf-8")
        )
        if Unit.model_validate(row).in_revival
    ]
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
    write_engine(py / "nbsolver.zip")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(
        f"built {out}: {len(index)} missions, {len(units)} units, {size / 1e6:.1f} MB"
    )


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "site")
