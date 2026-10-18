import json
import re

import httpx

HEADERS = {"User-Agent": "nbsolver/0.1 (personal project)"}
BASE = "https://www.blazingonline.wiki/"


def get_text(path):
    response = httpx.get(BASE + path, headers=HEADERS, timeout=60, follow_redirects=True)
    return response.status_code, response.text


for page in ("units.html", "unit.html?id=10013", "character.html?id=10013"):
    status, html = get_text(page)
    print(f"[{status}] {page} ({len(html)} bytes)")
    if status != 200:
        continue
    for src in sorted(set(re.findall(r"<script[^>]+src=[\"']([^\"'?]+)", html))):
        print("    script:", src)

for js in ("assets/js/units.js", "assets/js/unit.js", "assets/js/character.js"):
    status, text = get_text(js)
    print(f"\n[{status}] {js} ({len(text)} bytes)")
    if status != 200:
        continue
    for path in sorted(set(re.findall(r"""["'`]((?:data|api)/[^"'`\s]{0,60})["'`]""", text))):
        print("    path:", path)

status, raw = get_text("data/u/10013.json")
print(f"\n[{status}] data/u/10013.json")
if status == 200:
    print(json.dumps(json.loads(raw), indent=1)[:1200])
