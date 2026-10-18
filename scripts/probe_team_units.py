import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache" / "units"
OUT = ROOT / "team_probe.txt"

WANTED = [
    ("Tsunade", "The Slug Ninja"),
    ("Itachi Uchiha", "Beyond the Sharingan"),
    ("Deidara", "Ephemeral Art"),
    ("Hiruzen Sarutobi", "Ninja Clothes"),
    ("Naruto Uzumaki", "Unshakeable Will"),
    ("Hinata Hyuga", "Blooming Talent"),
]

index = json.loads((ROOT / "data" / "cache" / "units" / "index.json").read_text("utf-8")) if (
    ROOT / "data" / "cache" / "units" / "index.json"
).exists() else None

units = json.loads((ROOT / "data" / "units.json").read_text(encoding="utf-8"))

with OUT.open("w", encoding="utf-8") as handle:
    for name, title in WANTED:
        matches = [
            u
            for u in units
            if u["name"] == name and title.lower() in u["title"].lower() and u["rarity"] == 6
        ]
        handle.write(f"\n===== {name} '{title}' -> {len(matches)} match(es) =====\n")
        for unit in matches:
            handle.write(
                f"  id={unit['unit_id']} '{unit['title']}' {unit['element']}"
                f" cost {unit['cost']}->{unit['cost_all_abilities']}"
                f" max_level={unit['max_level']} luck_max={unit['luck_max']}\n"
            )
            for level in unit["levels"]:
                handle.write(
                    f"      {level['label']:<22} lv={level['level']:<4}"
                    f" hp={level['health']:<6} atk={level['attack']:<6} spd={level['speed']}\n"
                )
            raw_path = CACHE / f"{unit['unit_id']}.json"
            if raw_path.exists():
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                handle.write(f"      RAW stats keys: {list((raw.get('stats') or {}).keys())}\n")
                handle.write(
                    f"      RAW levels: {json.dumps((raw.get('stats') or {}).get('levels'))}\n"
                )

sys.stdout.write(f"wrote {OUT}\n")
