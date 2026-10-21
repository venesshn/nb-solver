"""Which missions that are open right now inflict slip damage, and at what tier."""

from __future__ import annotations

from pathlib import Path

import httpx

from nbsolver.effects import EffectKind
from nbsolver.missions import MissionCatalogue

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "analysis" / "slip_missions.txt"


def open_events() -> dict[str, dict]:
    raw = httpx.get(
        "https://www.blazingonline.wiki/data/missions.json", timeout=60
    ).json()
    events = (
        raw if isinstance(raw, list) else raw.get("events", raw.get("missions", []))
    )
    return {str(e.get("id")): e for e in events}


def main() -> None:
    catalogue = MissionCatalogue.load(ROOT / "data" / "catalogue.json")
    events = open_events()
    records: list[tuple[bool, int, str, str, str, list[tuple[str, str, str]]]] = []

    for mission in catalogue.missions:
        event = events.get(mission.slug) or next(
            (e for e in events.values() if e.get("name") == mission.name), None
        )
        for stage in mission.stages:
            hits: list[tuple[str, str, str]] = []
            seen: set[tuple[str, int | None]] = set()
            for battle_map in stage.maps:
                for enemy_set in battle_map.sets:
                    for enemy in enemy_set.enemies:
                        for effect in enemy.threats:
                            if effect.kind is not EffectKind.SLIP_DAMAGE:
                                continue
                            key = (enemy.name, effect.tier)
                            if key in seen:
                                continue
                            seen.add(key)
                            hits.append(
                                (
                                    str(effect.tier or "?"),
                                    enemy.name,
                                    effect.source[:120],
                                )
                            )
            if hits:
                records.append(
                    (
                        bool(event and event.get("open")),
                        stage.stamina,
                        str(stage.rank),
                        mission.name,
                        stage.name,
                        sorted(hits),
                    )
                )

    records.sort(key=lambda r: (not r[0], r[1], r[3]))
    lines: list[str] = []
    for is_open, stamina, rank, mission_name, stage_name, hits in records:
        tiers = ",".join(sorted({tier for tier, _, _ in hits}))
        lines.append(
            f"{'OPEN' if is_open else '----'} {stamina:>3} stam  {rank:<2} "
            f"tier {tiers:<6} {mission_name} | {stage_name}"
        )
        for tier, name, source in hits:
            lines.append(f"            tier {tier}  {name}: {source}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    opened = sum(1 for r in records if r[0])
    print(f"{opened} open stages inflict slip damage, of {len(records)} -> {OUT}")


if __name__ == "__main__":
    main()
