"""Player roster: built once from a box scan, then kept current by hand."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from nbsolver.models import MAX_LEVEL, OwnedUnit, Unit

DEFAULT_TEAM_COST_LIMIT = 200


class Roster(BaseModel):
    """Every copy a player owns. Duplicate slugs are allowed and meaningful."""

    player_id: str = ""
    team_cost_limit: int = DEFAULT_TEAM_COST_LIMIT
    units: list[OwnedUnit] = Field(default_factory=list)

    def add(
        self,
        slug: str,
        *,
        level: int = MAX_LEVEL,
        luck: int = 0,
        dupes: int = 0,
        limit_break: int = 0,
        manual: bool = True,
    ) -> OwnedUnit:
        owned = OwnedUnit(
            slug=slug,
            level=level,
            luck=luck,
            dupes=dupes,
            limit_break=limit_break,
            manually_added=manual,
        )
        self.units.append(owned)
        return owned

    def remove(self, slug: str) -> bool:
        for i, owned in enumerate(self.units):
            if owned.slug == slug:
                del self.units[i]
                return True
        return False

    def copies_of(self, slug: str) -> list[OwnedUnit]:
        return [u for u in self.units if u.slug == slug]

    def merge_scan(self, scanned: list[OwnedUnit]) -> tuple[int, int]:
        """Fold box-scan results in without discarding hand-entered copies.

        Returns (added, skipped). A re-scan tops up counts per slug rather than
        replacing them, so manual corrections survive later scans.
        """
        added = skipped = 0
        for slug in {u.slug for u in scanned}:
            have = len(self.copies_of(slug))
            incoming = [u for u in scanned if u.slug == slug]
            for owned in incoming[have:]:
                owned.manually_added = False
                self.units.append(owned)
                added += 1
            skipped += min(have, len(incoming))
        return added, skipped

    def team_cost(self, team: list[OwnedUnit], catalogue: dict[str, Unit]) -> int:
        return sum(u.cost(catalogue[u.slug]) for u in team)

    def fits_cost_limit(self, team: list[OwnedUnit], catalogue: dict[str, Unit]) -> bool:
        return self.team_cost(team, catalogue) <= self.team_cost_limit

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Roster:
        if not path.exists():
            return cls()
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
