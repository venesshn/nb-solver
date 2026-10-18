"""Measure how much of the real description corpus the effect parser understands."""

import json
import re
import sys
from collections import Counter
from pathlib import Path

from nbsolver.effects import EffectKind, parse_effects

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "effect_coverage.txt"

CHANCE_RE = re.compile(r"\d+(?:\.\d+)?\s*%\s*chance of", re.IGNORECASE)


def as_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(
            str(v) for v in (value.get("name"), value.get("description")) if v
        )
    return "" if value is None else str(value)


def all_descriptions() -> list[str]:
    found: list[str] = []
    raw = json.loads((ROOT / "data" / "catalogue.json").read_text(encoding="utf-8"))
    missions = raw.get("missions", []) if isinstance(raw, dict) else raw
    for mission in missions:
        for stage in mission.get("stages", []):
            enemies = list(stage.get("enemies", []))
            for battle_map in stage.get("maps", []):
                for enemy_set in battle_map.get("sets", []):
                    enemies.extend(enemy_set.get("enemies", []))
            for enemy in enemies:
                found += [as_text(s) for s in enemy.get("skills", [])]
                found.append(as_text(enemy.get("field_skill")))

    units = json.loads((ROOT / "data" / "units.json").read_text(encoding="utf-8"))
    for unit in units:
        for key in ("ninjutsu", "secret_technique", "field_skill", "buddy_skill"):
            found.append(as_text(unit.get(key)))
        found += [as_text(a) for a in unit.get("abilities", [])]

    return sorted({text for text in found if text.strip()})


def main() -> None:
    texts = all_descriptions()
    with_chance = [t for t in texts if CHANCE_RE.search(t)]

    kinds: Counter = Counter()
    unparsed: list[str] = []
    other_examples: list[str] = []

    for text in texts:
        effects = parse_effects(text)
        for effect in effects:
            kinds[effect.kind] += 1
            if effect.kind is EffectKind.OTHER and len(other_examples) < 40:
                other_examples.append(f"{effect.source[:160]}")
        if CHANCE_RE.search(text) and not effects:
            unparsed.append(text)

    recognised = sum(c for k, c in kinds.items() if k is not EffectKind.OTHER)

    with OUT.open("w", encoding="utf-8") as handle:
        handle.write(f"unique descriptions      : {len(texts)}\n")
        handle.write(f"containing '% chance of' : {len(with_chance)}\n")
        handle.write(f"effects recognised       : {recognised}\n")
        handle.write(f"effects as OTHER         : {kinds[EffectKind.OTHER]}\n")
        handle.write(f"chance-bearing but empty : {len(unparsed)}\n")

        handle.write("\n===== effects by kind =====\n")
        for kind, count in kinds.most_common():
            handle.write(f"  {count:>6}  {kind}\n")

        handle.write("\n===== OTHER examples =====\n")
        for example in other_examples:
            handle.write(f"  {example}\n")

        handle.write("\n===== chance-bearing yet unparsed =====\n")
        for example in unparsed[:40]:
            handle.write(f"  {example[:200]}\n")

    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
