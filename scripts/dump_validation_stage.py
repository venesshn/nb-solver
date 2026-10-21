"""Pull apart the stage we have footage of, so the simulator can be checked."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from nbsolver.missions import MissionCatalogue

NEEDLE = "vile serpent"
out = Path("data/analysis/validation_stage.txt")
out.parent.mkdir(parents=True, exist_ok=True)

catalogue = MissionCatalogue.load(Path("data/catalogue.json"))
lines: list[str] = []

for mission in catalogue.missions:
    if NEEDLE not in mission.name.lower():
        continue
    lines.append(f"MISSION {mission.name}  (slug {mission.slug})")
    for stage in mission.stages:
        lines.append(f"\n  [{stage.rank}] {stage.name}  stamina {stage.stamina}")
        for condition in stage.conditions:
            lines.append(f"    condition: {condition.kind} — {condition.description}")
        for i, battle_map in enumerate(stage.maps, 1):
            lines.append(f"    map {i}: {len(battle_map.sets)} possible set(s)")
            for enemy_set in battle_map.sets:
                lines.append(f"      set weight {enemy_set.weight}")
                for enemy in enemy_set.enemies:
                    flag = " BOSS" if enemy.is_boss else ""
                    lines.append(
                        f"        {enemy.name} ({enemy.element}) "
                        f"hp {enemy.hp} atk {enemy.attack}{flag}"
                    )
                    for line in enemy.ai_states:
                        lines.append(f"          ai: {line}")
                    for skill in enemy.skills:
                        lines.append(f"          sk: {skill.name} — {skill.description}")
                    for line in enemy.defences:
                        lines.append(f"          def: {line}")

out.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {out} ({len(lines)} lines)")
