import json
import sys
from collections import Counter

from nbsolver.catalogue import UNITS_PATH
from nbsolver.models import Unit

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

units = [
    Unit.model_validate(u) for u in json.loads(UNITS_PATH.read_text(encoding="utf-8"))
]
print(f"units: {len(units)}")
print("rarities:", dict(sorted(Counter(u.rarity for u in units).items())))
print("elements:", dict(Counter(str(u.element) for u in units)))
print("with ninjutsu:", sum(1 for u in units if u.ninjutsu))
print("with multiplier:", sum(1 for u in units if u.ninjutsu and u.ninjutsu.multiplier))
print("with level curve:", sum(1 for u in units if len(u.levels) >= 2))
print("with cost floor:", sum(1 for u in units if u.cost_all_abilities is not None))

six_plus = [u for u in units if u.rarity >= 6]
print(f"\n6*+ units: {len(six_plus)}")
for unit in sorted(six_plus, key=lambda u: -u.cost)[:5]:
    top = unit.stats_at(unit.max_level)
    mult = unit.ninjutsu.multiplier if unit.ninjutsu else None
    print(
        f"  {unit.name} '{unit.title}' {unit.element} r{unit.rarity} "
        f"cost {unit.cost}->{unit.min_cost} lv{unit.max_level} "
        f"hp {top.health} atk {top.attack} spd {top.speed} ninjutsu x{mult}"
    )
