import sys
from collections import Counter

from nbsolver.catalogue import CATALOGUE_PATH, add_hideoutgacha, build
from nbsolver.scrape.fandom import ATTRIBUTION, fetch_wikitext, parse_ninja_road_boosts

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

# Ninja Road's featured units, from the wiki's Extra Effects table.
road_boosts = parse_ninja_road_boosts(fetch_wikitext("Ninja_Road"))
boosted = 0
for mission in catalogue.missions:
    if mission.mode == "ninja_road" and mission.slug.startswith("nr-"):
        found = road_boosts.get(int(mission.slug.split("-")[1]), [])
        mission.unit_boosts = found
        if found:
            boosted += 1
            mission.sources.append(f"{ATTRIBUTION} - Ninja Road extra effects")
print(f"featured-unit boosts on {boosted} Ninja Roads")
catalogue.save(CATALOGUE_PATH)
stages = [s for m in catalogue.missions for s in m.stages]
print("missions by mode:", Counter(m.mode for m in catalogue.missions))
print(
    f"{len(catalogue.missions)} missions, {len(stages)} stages, geometry on {geometry} maps"
)
names = Counter((m.slug, s.name) for m in catalogue.missions for s in m.stages)
print("duplicate stage names:", [k for k, n in names.items() if n > 1][:10])
print("build failures:", [f for f in failures if "hideout" not in f.lower()][:10])
