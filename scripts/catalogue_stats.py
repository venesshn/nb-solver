import sys
from collections import Counter

from nbsolver.catalogue import CATALOGUE_PATH
from nbsolver.missions import ConditionKind, MissionCatalogue

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

catalogue = MissionCatalogue.load(CATALOGUE_PATH)
stages = [s for m in catalogue.missions for s in m.stages]

print(f"missions:        {len(catalogue.missions)}")
print(f"stages:          {len(stages)}")
print(f"maps:            {sum(len(s.maps) for s in stages)}")
print(f"enemy instances: {sum(len(s.enemies) for s in stages)}")
print(f"stages with random enemy sets: {sum(1 for s in stages if s.has_random_sets)}")
print(f"stages with AI scripts:        {sum(1 for s in stages if any(e.ai_states for e in s.enemies))}")

print("\nmodes:", dict(Counter(m.mode for m in catalogue.missions)))
print("ranks:", dict(Counter(str(s.rank) for s in stages)))

conditions = [c for s in stages for c in s.conditions]
print(f"\nconditions: {len(conditions)}")
print("by kind:", dict(Counter(c.kind.value for c in conditions)))

unparsed = Counter(c.description for c in conditions if c.kind is ConditionKind.OTHER)
print(f"\nunrecognised condition texts ({len(unparsed)} distinct):")
for text, count in unparsed.most_common(15):
    print(f"  {count:>4}x  {text}")
