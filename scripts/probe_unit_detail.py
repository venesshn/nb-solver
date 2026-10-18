import json
import re

import httpx

HEADERS = {"User-Agent": "nbsolver/0.1 (personal project)"}
BASE = "https://www.blazingonline.wiki/"

js = httpx.get(BASE + "assets/js/character.js", headers=HEADERS, timeout=60).text
for snippet in set(re.findall(r'.{70}"data/units/.{90}', js)):
    print("CTX:", snippet.replace("\n", " "))

for candidate in ("data/units/10013.json", "data/units/10013/index.json"):
    response = httpx.get(BASE + candidate, headers=HEADERS, timeout=60, follow_redirects=True)
    print(f"\n[{response.status_code}] {candidate} ({len(response.content)} bytes)")
    if response.status_code == 200:
        print(json.dumps(response.json(), indent=1)[:2000])
