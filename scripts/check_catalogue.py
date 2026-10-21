"""Refuse a rebuilt catalogue that lost missions or stages.

    python scripts/check_catalogue.py

Compares data/catalogue.json with the committed copy. A fan site being down or
changing shape shows up as missing missions, which must never be published.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]


def counts(catalogue: dict) -> tuple[int, int]:
    missions = catalogue.get("missions", [])
    return len(missions), sum(len(m.get("stages", [])) for m in missions)


def main() -> None:
    before = json.loads(
        subprocess.run(
            ["git", "show", "HEAD:data/catalogue.json"],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
            encoding="utf-8",
        ).stdout
    )
    after = json.loads((ROOT / "data" / "catalogue.json").read_text(encoding="utf-8"))
    (old_missions, old_stages), (new_missions, new_stages) = (
        counts(before),
        counts(after),
    )
    print(
        f"missions {old_missions} -> {new_missions}, stages {old_stages} -> {new_stages}"
    )
    lost = {m["slug"] for m in before["missions"]} - {
        m["slug"] for m in after["missions"]
    }
    if new_missions < old_missions or new_stages < old_stages or lost:
        raise SystemExit(f"refusing: the rebuild lost data {sorted(lost)[:10]}")


if __name__ == "__main__":
    main()
