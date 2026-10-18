"""Check which wiki-documented status effects actually occur in the game data."""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from effect_coverage import all_descriptions

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "missing_effects.txt"

PHRASES = [
    "draws them closer",
    "draws them in",
    "draws in",
    "draws closer",
    "knocks them back",
    "knocks back",
    "knock back",
    "nullifies knock back",
    "pushes them",
    "reduces damage by",
    "reduce damage",
    "damage reduction",
    "ignores damage reduction",
    "perfect dodge",
    "ignores perfect dodge",
    "ignores substitution",
    "removes barrier",
    "reduces the chakra gauge",
    "chakra consumed",
    "gradually recover",
    "recovers health",
    "restores health",
    "invincible",
]

texts = all_descriptions()
counts: Counter = Counter()
examples: dict[str, str] = {}

for text in texts:
    lowered = text.lower()
    for phrase in PHRASES:
        if phrase in lowered:
            counts[phrase] += 1
            examples.setdefault(phrase, text)

with OUT.open("w", encoding="utf-8") as handle:
    handle.write(f"unique descriptions: {len(texts)}\n\n")
    for phrase in PHRASES:
        handle.write(f"{counts[phrase]:>5}  {phrase}\n")
    handle.write("\n===== examples =====\n")
    for phrase in PHRASES:
        if phrase in examples:
            handle.write(f"\n[{phrase}]\n  {examples[phrase][:400]}\n")

print(f"wrote {OUT}")
