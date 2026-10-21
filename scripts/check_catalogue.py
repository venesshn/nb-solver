"""Refuse a rebuilt catalogue that lost anything the committed copy had.

    python scripts/check_catalogue.py

Compares data/catalogue.json with the committed copy. A fan site being down,
dropping one connection, or changing shape shows up as something missing -
a mission, a stage, a map, a battlefield layout, a source - and must never
be published. Additions and changed numbers pass; losses do not.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]


def _stage_key(stage: dict) -> str:
    return str(stage.get("stage_id") or stage.get("name"))


def _map_losses(where: str, old: dict, new: dict) -> list[str]:
    found = []
    if old.get("grid") and not new.get("grid"):
        found.append(f"{where}: battlefield layout")
    if old.get("sets") and not any(s.get("enemies") for s in new.get("sets") or []):
        found.append(f"{where}: enemies")
    return found


def losses(before: dict, after: dict) -> list[str]:
    """Everything the old catalogue had that the new one does not."""
    found = []
    new_missions = {m["slug"]: m for m in after.get("missions", [])}
    for old in before.get("missions", []):
        slug = old["slug"]
        new = new_missions.get(slug)
        if new is None:
            found.append(f"{slug}: whole mission")
            continue
        for source in set(old.get("sources") or []) - set(new.get("sources") or []):
            found.append(f"{slug}: source {source}")
        if len(new.get("unit_boosts") or []) < len(old.get("unit_boosts") or []):
            found.append(f"{slug}: featured-unit boosts")
        new_stages = {_stage_key(s): s for s in new.get("stages", [])}
        for stage in old.get("stages", []):
            key = _stage_key(stage)
            twin = new_stages.get(key)
            if twin is None:
                found.append(f"{slug}/{key}: whole stage")
                continue
            new_maps = {m.get("number"): m for m in twin.get("maps") or []}
            for battle_map in stage.get("maps") or []:
                where = f"{slug}/{key} map {battle_map.get('number')}"
                other = new_maps.get(battle_map.get("number"))
                if other is None:
                    found.append(f"{where}: whole map")
                else:
                    found += _map_losses(where, battle_map, other)
    return found


def main() -> None:
    before = json.loads(
        subprocess.run(
            ["git", "show", "HEAD:data/catalogue.json"],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
            encoding="utf-8",
        ).stdout
    )
    after = json.loads((ROOT / "data" / "catalogue.json").read_text(encoding="utf-8"))
    print(f"missions {len(before['missions'])} -> {len(after['missions'])}")
    found = losses(before, after)
    if found:
        print("\n".join(found[:20]))
        raise SystemExit(f"refusing: the rebuild lost {len(found)} thing(s)")
    print("nothing lost")


if __name__ == "__main__":
    main()
