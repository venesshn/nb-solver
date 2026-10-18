"""Pull raw wikitext for the Blazing wiki's mechanics pages."""

import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "wiki_pages.txt"
API = "https://naruto-blazing.fandom.com/api.php"

PAGES = [
    "Critical hit",
    "Slip Damage",
    "Status Effects",
    "Abilities",
    "Elemental Affinity Damage Boost",
    "Nullifies Element Affinity-based Damage Reduction",
    "Chakra Gauge Reduction",
    "Immobilization",
    "Jutsu Sealing",
    "Element",
    "Elements",
    "Stats",
    "Battle",
]


def wikitext(client: httpx.Client, title: str) -> str:
    response = client.get(
        API,
        params={
            "action": "query",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "titles": title,
            "format": "json",
            "redirects": 1,
        },
    )
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {})
    for page in pages.values():
        for revision in page.get("revisions", []):
            return revision["slots"]["main"].get("*", "")
    return ""


with (
    httpx.Client(timeout=30.0, follow_redirects=True) as client,
    OUT.open("w", encoding="utf-8") as handle,
):
    for title in PAGES:
        text = wikitext(client, title)
        handle.write(f"\n\n===== {title} ({len(text)} chars) =====\n")
        handle.write(text[:8000])

print(f"wrote {OUT}")
