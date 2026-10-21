"""Fetch the character portraits hideoutgacha serves, keyed to our own units.

Reading a roster off a screen recording needs something to compare against.
The site lists every character with a small square icon, which is the same
artwork the game puts in the box, so one download gives us a template library.

    python scripts/fetch_portraits.py
"""

import json
import re
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "portraits"
INDEX = OUT_DIR / "index.json"

BASE = "https://www.hideoutgacha.com"
LISTING = f"{BASE}/games/naruto-blazing/characters"
ICON = f"{BASE}/images/naruto-blazing/icons/{{icon}}.webp"
HEADERS = {"User-Agent": "nbsolver/0.1 (mission solver; personal project)"}

PAIR_RE = re.compile(
    r'/games/naruto-blazing/characters/([a-z0-9\-]+)"'
    r".{0,800}?/images/naruto-blazing/icons/(\d+)\.webp",
    re.DOTALL,
)


def listing(client: httpx.Client) -> dict[str, str]:
    page = client.get(LISTING, timeout=60, follow_redirects=True)
    page.raise_for_status()
    return dict(PAIR_RE.findall(page.text))


def slug_for(name: str, title: str) -> str:
    """The site's slug is the name and title run together, punctuation dropped."""
    joined = f"{name} {title}".lower().replace("&", " and ")
    # An apostrophe closes up rather than splitting: "Sound's Spy" -> sounds-spy.
    joined = re.sub(r"[''\u2019]", "", joined)
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", joined)).strip("-")


def fetch(refresh: bool = False) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers=HEADERS) as client:
        pairs = listing(client)
        print(f"{len(pairs)} characters listed")
        INDEX.write_text(json.dumps(pairs, indent=1), encoding="utf-8")

        saved = 0
        for position, (slug, icon) in enumerate(sorted(pairs.items()), start=1):
            target = OUT_DIR / f"{icon}.webp"
            if target.exists() and not refresh:
                continue
            reply = client.get(ICON.format(icon=icon), timeout=60)
            if reply.status_code != 200:
                print(f"  missed {slug} ({icon}): {reply.status_code}")
                continue
            target.write_bytes(reply.content)
            saved += 1
            if position % 50 == 0:
                print(f"  [{position}/{len(pairs)}]")
            time.sleep(0.05)
    return saved


if __name__ == "__main__":
    count = fetch(refresh="--refresh" in sys.argv)
    print(f"saved {count} portraits to {OUT_DIR}")
