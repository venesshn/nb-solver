import sys
from collections import Counter

from nbsolver.catalogue import CATALOGUE_PATH, add_hideoutgacha, build

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
failures = []


def report(index: int, total: int, message: str) -> None:
    if "FAILED" in message:
        failures.append(message)
    if index % 25 == 0 or index == total:
        print(f"[{index}/{total}] {message}", flush=True)


catalogue = build(on_progress=report)
geometry = add_hideoutgacha(catalogue, on_progress=report)
catalogue.missions = [m for m in catalogue.missions if any(s.maps for s in m.stages)]
catalogue.save(CATALOGUE_PATH)
stages = [s for m in catalogue.missions for s in m.stages]
print("missions by mode:", Counter(m.mode for m in catalogue.missions))
print(
    f"{len(catalogue.missions)} missions, {len(stages)} stages, geometry on {geometry} maps"
)
names = Counter((m.slug, s.name) for m in catalogue.missions for s in m.stages)
print("duplicate stage names:", [k for k, n in names.items() if n > 1][:10])
print("build failures:", [f for f in failures if "hideout" not in f.lower()][:10])
