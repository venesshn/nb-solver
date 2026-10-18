"""Write the roster confirmed from the player's screenshots and validate it."""

import json
import sys
from pathlib import Path

from nbsolver.catalogue import UNITS_PATH
from nbsolver.models import Unit
from nbsolver.roster import Roster

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "rosters" / "example.json"

# unit_id, level, limit breaks, is helper
TEAM = [
    (11066, 150, 10, False),  # Tsunade 'The Slug Ninja'
    (10966, 100, 0, False),  # Itachi Uchiha 'Beyond the Sharingan'
    (12416, 135, 7, False),  # Deidara 'Ephemeral Art'
    (10906, 100, 0, False),  # Hiruzen Sarutobi 'Ninja Clothes'
    (12636, 100, 0, False),  # Hinata Hyuga 'Blooming Talent'
    (12666, 100, 0, True),  # Naruto Uzumaki 'Unshakeable Will' - friend's unit
]

OBSERVED_TEAM_HP = 9296

catalogue = {
    u.unit_id: u for u in (Unit.model_validate(r) for r in json.loads(UNITS_PATH.read_text("utf-8")))
}

roster = Roster(player_id="REDACTED")
total_hp = 0
for unit_id, level, limit_break, helper in TEAM:
    unit = catalogue[unit_id]
    if not helper:
        roster.add(unit_id, level=level, limit_break=limit_break, manual=True)
    stats = unit.stats_at(level)
    total_hp += stats.health
    tag = " (helper)" if helper else ""
    print(
        f"{unit.name:<18} {unit.title:<24} {unit.element:<8} lv{level:<4}"
        f" hp={stats.health:<6} atk={stats.attack:<6} cost={unit.cost}{tag}"
    )

OUT.parent.mkdir(parents=True, exist_ok=True)
roster.save(OUT)

print(f"\nteam HP from model : {total_hp}")
print(f"team HP observed   : {OBSERVED_TEAM_HP}")
print("MATCH" if total_hp == OBSERVED_TEAM_HP else "MISMATCH")
print(f"\nsaved {OUT}")
