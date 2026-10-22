# Handover — Naruto Blazing Mission Solver

Written 2026-10-21 at commit `62a8dfc`. Read this top to bottom in a fresh chat
and you will not need to re-derive anything.

Companion file: `/memories/repo/nbsolver.md` (repository memory, ~420 lines).
That file is the **verified-facts reference**; this file is the **narrative and
plan**. Where they disagree, the memory file is more precise about mechanics and
this file is more current about status.

---

## 1. What we are building

A website where a player selects a mission, loads their own collection, and gets
a personalised, turn-by-turn solved walkthrough.

These are the user's requirements, kept verbatim because the wording matters:

- "allows users to select a mission (whether that's a weekly, emergency, impact,
  super impact etc. mission) and load up their profile using their profile id"
- "the user will be given the specific team and a live playback of what to do
  each turn to beat the mission e.g. turn 1: move this character top right, not
  attakcing the unit (stalling) etc."
- "The engine that processes this shoud the user's characters and the levels they
  are currently at, instead of the maximum level possible for each character
  i.e. this engine should be user specific."
- "If there is no possible way to beat the level using the pool of characters
  available, there should be a message displayed, saying 'Not possible to
  complete - keep grinding!'. Underneath this, it should recommend what
  characters to unlock and how to enable the user to complete the mission in the
  simplest way."
- "sometimes a lot depends on randomness - this engine should account for that,
  and give a completion likelihood, and what it depends on"
- "i want the solver to use friend/helper characters"
- "use duplicate units, if the user actually has multiple of the same unit - also
  ensure you account for the user's team cost limit as well"
- "give the user the option to either 'beat' or 'complete'. if the user selects
  beat, they will be given the team that most easily beats the mission. if the
  user selects complete, the user will be allowed to select which specific
  objective they want to complete using e.g. heart only, then the engine will
  adapt and give the user a full heart team"
- "simplest should mean least grinding and fastest completion"
- Playback format: "an animated top-down grid which we step through turn by turn"
- Stack: "6. whatever you propose"
- "remember there's also slip damage that you have to account for as well. when
  theres typing advantage, damage is reported as red. when theres no advantage it
  is grey, whem there is typing disadvantage the damage is reported as blue. slip
  damage is reported as purple. healing is reported as green."
- "ensure you factor in all possibilities when going into a mission i.e. all
  different types of damage, immobilisation, jutsu sealing, etc."

**Standing honesty rule, agreed explicitly:** failing to find a winning strategy
is *not* proof that none exists. "Not possible to complete — keep grinding!" is
reserved for provable cases. Otherwise the wording is **"No winning strategy
found."**

---

## 2. Stack, environment, conventions

| Thing | Value |
|---|---|
| Language | Python 3.12, package `nbsolver`, build backend `uv_build` |
| Package manager | **uv**. Call `uv` directly — `python -m uv` does **not** work |
| Lint/format | **ruff** |
| Tests | **pytest** — **211 passing** |
| Models | **pydantic v2** |
| Scraping | httpx, beautifulsoup4, lxml |
| Imaging | opencv-python-headless, numpy, Pillow |
| OS | Windows, PowerShell 5.1 |
| Workspace | `c:\Users\venes\Documents\Naruto Blazing Mission Solver` |
| Python exe | `.\.venv\Scripts\python.exe` |

**Architecture decision:** a curated static site, no backend. Versioned JSON
ships in the repo; the player's roster stays in their browser. **Built** as a
plain static site (no framework, no build step beyond `scripts/build_web.py`):
`web/` sources, Pyodide 314.0.7 runs the Python solver in a Web Worker, canvas
playback over the recorded frames.

**Git:** `main` pushes to **https://github.com/venesshn/nb-solver** (public).
Identity is repo-local `VN <venesshn@users.noreply.github.com>`. `gh` is at
`C:\Program Files\GitHub CLI\gh.exe`, logged in as venesshn (repo, workflow).
**History was rewritten on 2026-10-21 to drop the game portraits** before going
public, so commit hashes quoted elsewhere in this file from before then are
stale; find commits by message. Pre-rewrite backup: `data/raw/nbsolver-before-public.bundle`.
Node 24 is at `C:\Program Files\nodejs`.

### User's working preferences (from user memory, always apply)

- Handle git unprompted: pull/rebase, stage, commit, push. Don't ask, don't hand
  over commands for them to run.
- Lint and verify before committing; never push untested code.
- Edit and test locally, then push. Don't commit blind via the GitHub web/API.
- The user doesn't use their machine often — favour automation that runs without
  them.
- No markdown docs unless requested (this file was requested).
- Comments only where the code can't speak for itself, one short line.
- Delete ad-hoc probe scripts when finished with them.

### PowerShell gotchas (these cost real time — read them)

- **Use `mode=async` for `run_in_terminal`, then poll `get_terminal_output`.**
  The user asked for this directly. Sync mode here swallows or lags output.
- **Use `Set-Location`, not `cd`** — `cd` intermittently reports "not recognized".
- **Never use `>` redirection** — it writes UTF-16.
- **Avoid here-strings.** PowerShell echoes the whole script before any output,
  which is very expensive in tokens. Write probe files with `create_file` instead.
- Any script printing unit or mission titles needs
  `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` — titles contain
  `★` and cp1252 raises. Use `flush=True` in long-running scripts.
- `grep_search` and `file_search` **cannot see gitignored paths** such as
  `data/analysis/`, `data/cache/`, `data/frames/`. Use `read_file` / `list_dir`.

### The image budget — the single biggest trap

`view_image` returns **"Image omitted — context image budget exceeded"** once a
conversation has spent its budget, and **`runSubagent` shares the same budget** —
this was tested; the subagent reported seeing nothing and correctly refused to
invent a description. **Starting a new chat is the only reset.**

**Therefore: do any looking-at-pictures work EARLY in a session.** The whole of
the previous session's geometry work was done blind, statistically, because the
budget was gone. That is why the icon box below is "best found" rather than
"confirmed by eye".

Workarounds that function without the budget (all proven, all coarse):
ASCII luminance rendering of a frame (~78 cols); cross-page variance maps as
digit grids; autocorrelation on row/column edge projections; row-strip
correlation between frames to detect scrolling; connected-component analysis of a
thresholded variance map.

---

## 3. Repository layout

```
src/nbsolver/
  ai.py            enemy AI script parser -> state machine
  battle.py        turn engine, AI-driven enemy phase, Event stream
  catalogue.py     MissionCatalogue, add_hideoutgacha()
  combat.py        the published damage formula and its constants
  effects.py       status-effect taxonomy parser
  enums.py  extract.py  missions.py  models.py  roster.py
  scrape/blazingonline.py   scrape/fandom.py   scrape/hideoutgacha.py
tests/             16 files, 211 tests
scripts/           ~22 scripts (see below)
data/              catalogue, units, portraits, rosters, caches, analysis
```

### Scripts that matter

| Script | Purpose |
|---|---|
| `fetch_portraits.py` | Downloads 551 character icons from hideoutgacha. Exports `slug_for(name, title)` — reused elsewhere |
| `box_scan.py` | Screen recording -> still frames worth reading |
| `box_pages.py` | Stills -> one sharpest frame per character detail page |
| `read_box.py` | **The current roster reader.** Pages -> named characters with confidence |
| `crop_frame.py` | `crop_frame.py x0 y0 x1 y1 frame.png` dumps an upscaled crop for viewing. **Use this first thing in a fresh chat** |
| `dump_validation_stage.py` | Dumps the validation mission's real data |
| `catalogue_stats.py`, `effect_coverage.py`, `probe_missing_effects.py` | Coverage checks after parser changes |

### Commit history (most recent first)

```
62a8dfc  Read characters off the box recording, with honest confidence
e71bc45  Cut the recording into one page per character
6ad1e39  Build a portrait library so a roster can be read, not typed
7f682fa  Let enemies follow their published scripts
a3d95fa  Read the enemy AI scripts into a state machine
3422654  Bring in the battlefield itself from hideoutgacha
46df438  Keep Rebirth-only units out of a Revival player's pool
fa9bf68  Turn a box recording into frames worth reading
12b5a71  Read the skill name too, where the real numbers hide
33ba856  Confirm the combo chakra payout, and dump the stage we have footage of
7a8dfdd  Keep what an enemy resists and what its field skill actually does
79db20c  Use the game's published damage formula and turn rule
```

---

## 4. Data sources — three fan projects exist, keep them straight

1. **Revival** — what the **user actually plays**. Roster frozen at the original
   game's shutdown.
2. **Project:Rebirth / BLAZING:ONLINE** — `blazingonline.wiki`, our data backbone.
   Adds new units, but has **not** rebalanced the original missions (verified).
3. **The original dead game** — documented by hideoutgacha.

| Source | What it gives |
|---|---|
| `https://www.blazingonline.wiki/` | **Backbone.** `data/missions.json` (166 events), `data/m/{page}.json`, `data/units.json` (1,100), `data/units/{id}.json`. Foe records stamped `raw.origin = "original-2.28.0"`, carrying `raw.skillIds` and **`raw.aiStates`**. SPA — does **not** expose portrait URLs |
| `https://www.hideoutgacha.com/games/naruto-blazing` | **Original-game ground truth + map geometry + PORTRAITS.** Battle Mechanics (15 chapters in one 240KB HTML), Damage Calculator, Enemies DB, per-mission enemy/map detail, `/characters` with 551 icons |
| `https://naruto-blazing.fandom.com/api.php` | Status-effect taxonomy only. Use `action=query&prop=revisions&rvprop=content&rvslots=main`; `prop=extracts` returns empty. **Its 2.5% crit rate is WRONG** |
| `https://gachawiki.net/naruto-blazing` | Supabase-backed SPA, no static JSON. **User chose to skip it** |

**Parity verified** on mission 3003: every HP/ATK figure, every objective and the
enemy order per map match between blazingonline and hideoutgacha. Treat
blazingonline mission data as original-game-accurate. The only divergence is 11
Rebirth-only units, excluded by `load_units(revival_only=True)`.

### `data/` contents

- `data/catalogue.json` (~37 MB) — 241 missions, 869 stages (see §10); emergency
  maps carry battlefield geometry from hideoutgacha, other modes don't
- `data/units.json` — 1,100 units (1,084 obtainable on Revival)
- `data/portraits/*.webp` — **551 icons**, kept locally and git-ignored (game art);
  `index.json` = `{slug: icon}` is tracked
- `data/rosters/example.json` — the player's 83-unit box, no player details
- `data/cache/missions/*.json` (166), `data/cache/hideout/*.html` (166)
- `data/analysis/box/*.png` — 165 stills from the recording
- `data/analysis/pages/*.png` — **138 per-character detail pages**
- `data/analysis/box_reading.json` — output of `read_box.py`

---

## 5. Verified game mechanics

The memory file has the full detail. The essentials:

### Damage formula (authoritative, from hideoutgacha)

```
Raw = (ATK + flat Attack Boosts) × skill × Attack Boost × Attack Weakened × other × critical
Dmg = ceil(Raw × element × (1 − damage reduction)) − Defense        [minimum 1]
```

- **Flat Attack Boosts join ATK *before* the multipliers**, so a 2.2× ninjutsu
  scales them too.
- **Defense is subtracted per hit, after rounding up** — many small combination
  hits lose most of their damage to it; one big secret loses least.
- Critical ×1.5; **base rate 3.125% (1 in 32)**; Critical Rate Boost
  **multiplies** the base. **Enemies never crit.**
- Element ×1.5 / ×0.5 / ×1. Heart > Skill > Body > Heart;
  **Bravery ↔ Wisdom is ×1.5 in both directions.**

`src/nbsolver/combat.py` constants: `CRITICAL_MULTIPLIER=1.5`,
`BASE_CRITICAL_RATE=3.125`, `ADVANTAGE/NEUTRAL/DISADVANTAGE=1.5/1.0/0.5`,
`ATTACK_BOOST_RANKS=(1.25,1.5,1.75,2.0,2.25,2.5)`,
`ATTACK_WEAKENED_RANKS=(0.85,0.7,0.55,0.4,0.25)`,
`CRITICAL_RATE_RANKS=(1.5,2.0,2.5,3.0,3.5,4.0)`,
`SLIP_DAMAGE_RANKS=(0.02,0.04,0.06,0.08)`,
`COMBINATION_VALUE={"Short":0.8,"Mid":0.7,"Long":0.6,"Vast":0.5}`.
`DamageColour(StrEnum)`: ADVANTAGE="red", NEUTRAL="grey", DISADVANTAGE="blue",
SLIP="purple", HEALING="green".

### Turn structure

**A turn is ONE character's action**, not a round of three. "Complete within 20
turns" counts single actions, and enemy countdowns drop by one per single action.

### Battle engine structure (`battle.py`)

- **`Team.health` is a SINGLE SHARED POOL.** A test that forgets to set
  `team.health` makes `state.over` true immediately and the enemy phase never
  runs — this previously caused 7 false test failures. Remember it.
- `take_turn(state, order, rng)`: increment turn → `_act` → `_enemy_phase` →
  `tick_slip_damage` → chakra to actor **and its buddy** → combo bonus → `expire()`.
- `Event(turn, kind, actor, target, amount, colour, note)` — this is the stream
  the frontend will replay.
- `MAX_SWITCHES = 16`. `_scripted_turn` countdown semantics: countdown 1 acts on
  the first phase; countdown 2 waits one phase.

### AI script grammar — fully solved (`ai.py`)

- Form: `state <N>[ [Init|Switch]]: <actions> -> <transition>`
- **6,315 states across 1,110 of 7,169 enemies, 100% parsed.**
- **Chance percentages are RELATIVE WEIGHTS, not independent rolls** — use
  `AiState.odds` / `.roll()`. `100% state 4, 100% state 5` is 50/50.
- **Health/turn thresholds are listed loosest first — take the LAST one still
  satisfied**, not the first.
- 24 lines end at a bare `then randomly:` — truncated at source; **do not "fix"**.
- Reaction branches are parsed but **not yet triggered** by the engine (1 enemy).
- `EnemyStats.ai` is a `cached_property`. HP field is `hp`, not `health`. The
  catalogue class is `MissionCatalogue`, not `Catalogue`.

### Status effects

Attack Boost ×1.25–2.5 (6 ranks) | Attack Weakened ×0.85–0.25 (5) |
**Slip Damage 2/4/6/8% of CURRENT HP — only 4 ranks** | Barrier 1,000–50,000 |
**Perfect Dodge is a COUNT, up to 12** | Dodge 5–45% | Damage Reduction 5–100% |
Crit Rate ×1.5–4 | Crit Damage ×1.1–2.

**Stacking RAISES THE RANK, it does not multiply. Durations add, 20 turns max.**

**Defensive check order:** Nullify → damage → Dodge chance → Perfect Dodge
(spends one) → Barrier (overflow passes through) → Absorption.

### Chakra — fully solved

Ninjutsu 2–9; **Secret = exactly ×2 (573/573 units, no exceptions)**; all units
start at cost−1; **refill 1 bar per action turn; a unit's buddy gains alongside
it**; **combo past 15 hits gives one extra bar**.

### Open discrepancy (unresolved)

Our mission data reports **slip damage tiers up to 6**; hideoutgacha documents
only **4 ranks**. Check what `TIER_RE` in `effects.py` is actually matching.

### Known data gap

**"Perimeter Barrier" has an empty description** on every Sound Ninja carrying it.
It is **not** a barrier — it is an **attack**, 2.5× (20 copies) or 3× (3 copies).
An earlier guess that it was protective was wrong; 202 copies are blank, assume
2.5×.

---

## 6. Validation target — fully characterised

**Mission "Shadow of the Vile Serpent"**, slug `e3003` / hideoutgacha `3003`.
The user's recorded clear is **"The Evil Snake Shows its Fangs [B]"**, 20 stamina,
3 maps. Dump it with `scripts/dump_validation_stage.py`.

- Three mutually-exclusive objectives: **Heart only / Skill only / Body only** —
  a good test for "complete" mode.
- **Every enemy is Skill.** The user's all-Heart team gets ×1.5 attacking and
  ×0.5 received. That is *why* their team works.
- Map 1/3 chaff: Sound Ninja 3,200 HP / 240 ATK; 3,600/200 carrying
  "Perimeter Barrier".
- Map 2 boss: **Kabuto 17,500/320** — heals 6,000 HP, `max 1 uses`, only below 50% HP.
- Map 3 boss: **Orochimaru 27,500/410**, 50/50 between two 2.5× jutsu — skill
  300271 = 50% jutsu sealing, 300270 = 50% immobilization.
- **Live simulation already verified correct:** 513 = 410 × 2.5 × 0.5 and
  205 = 410 × 1.0 × 0.5; seal and immobilise procs observed.
- **`x` is an enemy QUANTITY field** (`EnemyStats.count`). Only 2 of 166 missions
  use it — and one of them is this one. Map 2 is 14 enemies, not 7. **Always
  expand by `count` when simulating.**

### The confirmed team (the players own, recorded at Ninja Rank 89)

| Unit | id | Element | Level | HP | ATK |
|---|---|---|---|---|---|
| Tsunade 'The Slug Ninja' | 11066 | Heart | 150 (LB10) | 2216 | 2482 |
| Itachi Uchiha 'Beyond the Sharingan' | 10966 | Heart | 100 | 1108 | 1318 |
| Deidara 'Ephemeral Art' | 12416 | Heart | 135 (LB7) | 1522 | 1924 |
| Hiruzen Sarutobi 'Ninja Clothes' | 10906 | Heart | 100 | 1212 | 1520 |
| Hinata Hyuga 'Blooming Talent' | 12636 | Heart | 100 | 1604 | 1234 |
| Naruto Uzumaki 'Unshakeable Will' (helper) | 12666 | **Wisdom** | 100 | 1634 | 2110 |

HP sums to **9,296** = the observed max team HP. **Team HP = sum of all six
members including the helper.**

> **Governing principle:** the simulator must reproduce a clear the user has
> already achieved before we trust it to invent new ones.

---

## 7. Current work stream — roster ingestion

This is **the product blocker**. A solver choosing from 5 units can never answer
"what team beats this".

### What the recording is (corrected twice by the user — believe this version)

It is **not** a scrolling box grid. The player **taps into each character's
detail page** one at a time, because "thats the only way to see their level and
abilities, as well as cost". Confirmed computationally: frame-to-frame vertical
shift is **0 px at 0.99 confidence** throughout; nothing scrolls anywhere.

The player **filtered the list to 4★ and above** ("as 3 stars are useless").

The detail page **shows the small square roster icon** (so portrait matching is
viable) and **shows LEVEL but NOT abilities**. So only two things need reading per
page: **which unit**, and **what level**. Cost, abilities, HP, ATK and element all
come from `data/units.json` once the unit is identified.

### The pipeline as built

```
screen recording
  -> box_scan.py   -> 165 full-resolution stills (1180x2556)   data/analysis/box/
  -> box_pages.py  -> 138 per-character pages                  data/analysis/pages/
  -> read_box.py   -> 54 named characters + confidence         data/analysis/box_reading.json
```

`box_scan.py`: `SAMPLE_FPS=4.0`, `STILL=1.2`, `NOVEL=4.0`, `MAX_GAP_SECONDS=1.5`.
Writes **full-resolution** frames; the 160×284 grey thumbnail is only used for
motion detection. Naming `box_{saved:03d}_{seconds:07.2f}s.png`.

`box_pages.py`: groups consecutive stills, new run when mean abs diff > `NEW_PAGE
= 18.0`, keeps the sharpest of each run by Laplacian variance. Result:
"165 stills -> 138 pages", min 1 / median 1 / max 5 frames per page.

> **DESTRUCTIVE — read before re-running either script.** `box_scan.py` clears
> `*.png` from `data/analysis/box/` and `box_pages.py` does `rmtree` on
> `data/analysis/pages/`. Both output directories are **hard-coded**; only the
> input video is an argument. Running them on a new recording overwrites the
> previous run in place.
>
> **Run 1 is already archived** — `data/analysis/box_v1/` (165 stills),
> `data/analysis/pages_v1/` (138 pages) and `data/analysis/box_reading_v1.json`.
> That archive is the only copy of the dataset every confirmed match in this
> document rests on. **Do not delete or overwrite the `_v1` files.**
>
> Before a third recording, give both scripts an output-directory argument
> rather than archiving by hand again.

### The second recording — PROCESSED 2026-10-21 (afternoon session)

**Corrected later the same session — the first pass below was wrong.** The
user pointed out duplicates. Each move to the next unit fades to black; v2 has
exactly **83 black transitions → 83 visits** (2.1–4.3 s each). The old pipeline
merged duplicates, and the name-banner crop includes "No.###" and the stars, so
it also merged rarity forms of one character. `scripts/box_visits.py` now splits
on the blacks: one page per visit.

All 83 visits were then **labelled by eye** (name, title, No., level) →
`data/analysis/visits_v2_truth.json`: **61 distinct units, 57 characters, 22
extra copies.** Scored against that, the **icon matcher is right 32/83**, and
only 15/34 in the "trusted" ≥0.05 band — so the margin rule does not hold.
**`data/rosters/example.json` is now the real roster** (83 copies, 61 unit_ids),
and all 5 hand-entered placeholder units reappear with identical level and LB.

**Automatic reader — `src/nbsolver/box_reader.py` + `scripts/read_visits.py`.**
Tesseract on the banner (name rows 558–616, title rows 622–660, white text via
the darkest channel > 170, 2× upscale) snapped to the closed set of units of the
counted rarity; stars counted as yellow blobs; level plaque OCR'd with a
`0-9/MAX` whitelist (a faint red "M" can drop out — the parser accepts `AX`).
**83/83 exact on v2** (tuned there), and on **run 1 as a held-out set**
(`box_visits.py` → 83 visits too) its 83 reads equal v2's labels exactly as a
multiset — box order differed between the recordings. Pipeline now:
`box_visits.py VIDEO OUT` → `read_visits.py OUT report.json --roster
data/rosters/example.json` (refuses to write if any page is flagged).
`build_roster.py` no longer writes the roster; it checks the confirmed team is
in it and the team HP still matches.

**Decided by the user (2026-10-21): on the site, players load their roster by
uploading a box recording, processed entirely in the browser** (no server; the
video never leaves the device). Port the pipeline to the frontend: decode
frames via `<video>` + canvas, split on the black fades, crop banner/stars/level
at the boxes above, OCR with tesseract.js, snap to the shipped unit list, and
show flagged pages for the player to confirm. Before trusting it, re-validate
tesseract.js against the 166 labelled pages (v2 + run 1). Geometry is only known
for 1180×2556; other screen sizes need a scaled layout and a recording to test.

First pass, superseded: 166 stills → 157 pages → 57 name clusters, "the same 54
as run 1 plus 3". Outputs in `data/analysis/box_v2/`, `pages_v2/`,
`box_reading_v2.json`, `visits_v2/`.

Original notes on the file, kept for reference:

It exists in **two copies**, both in `C:\Users\venes\Downloads\`, both decoding
fine. Same stem: `621D54D7-6AC5-4490-92F2-2E7D08C49467 Copy`.

| | `.mov` | `.mp4` |
|---|---|---|
| Size | **431.3 MB** | 95.0 MB |
| Resolution | 1180×2556 | 1180×2556 |
| Frame rate | 60.03 fps | 60.00 fps |
| Frames | 14,335 | 14,299 |
| Duration | 238.8 s | 238.3 s |
| First-frame sharpness | 715.9 | 713.6 |

**Use the `.mov`** — it is the original capture at ~4.5× the bitrate; the `.mp4`
is a transcode of it. Measured sharpness is near-identical (715.9 vs 713.6), so
the transcode is not visibly degrading anything and the `.mp4` is a fine
fallback if the `.mov` gives trouble.

**Resolution is identical to the first recording**, so **`ICON` and `NAME` should
carry over unchanged** — but verify that on a page from *this* recording rather
than assuming it.

**Measured, worth noting:** 238.8 s. If it covers all 83 units that is **2.9 s per
character**, against 5.0 s per character in the first recording (270 s / 54).
So it is *faster* per unit, not slower. The advice given was to pause about a
second on each — 2.9 s is still workable, but if `box_pages.py` yields far fewer
than 83 pages, or many pages come out blurred, under-sampling is the first thing
to suspect. **Do not assume it covers 83; count the pages and check.**

Unknown until asked or measured: whether the player kept a fixed sort order and
skipped nobody. That matters a lot — see the sequence trick in §8.

### Portrait library — complete and validated

| Fact | Detail |
|---|---|
| Listing | `https://www.hideoutgacha.com/games/naruto-blazing/characters` (200 OK, 942 KB) |
| Icon URL | `/images/naruto-blazing/icons/{N}.webp` |
| Pairing regex | `r'/games/naruto-blazing/characters/([a-z0-9\-]+)".{0,800}?/images/naruto-blazing/icons/(\d+)\.webp'` with `re.DOTALL` → **551 pairs**. Reverse order yields 0 |
| Numbering | hideoutgacha's own, **not** blazingonline `unit_id` — only 3 of 551 collide |
| Native size | 128×128 RGBA |
| **Slug match rate** | **551/551** after the apostrophe fix |
| **Unit coverage** | **1,089 of 1,100 units** |
| The 11 misses | 19001, 19002, 19004, 19006, 19007, 19008, 19009, 19013, 19014, 19022, 88020 — Sarada, Eida, Shisui, Shisui & Itachi. **Exactly the Rebirth-only units Revival lacks.** A clean cross-validation of both datasets |

`slug_for` detail: the site's slug is name and title run together with punctuation
dropped, **and an apostrophe closes up rather than splitting** — "The Sound's Spy"
→ `the-sounds-spy`, not `the-sound-s-spy`. That fix took matching from 526/551 to
551/551.

### How the page geometry was found (blind, no images)

Stacked all 138 pages, took the across-page standard deviation, thresholded at
35% and 50% of max, closed with a 9×9 kernel, ran
`cv2.connectedComponentsWithStats`, and listed components over 4,000 px.

Resulting boxes, now in `read_box.py`:

- **`ICON = (79, 1740, 157)`** — x, y, size. The small square roster icon.
  **Confirmed by eye** on two pages since: on target, a few px low/left.
- **`NAME = (170, 500, 740, 670)`** — x0, y0, x1, y1. Name + title text.
- **`LEVEL_PLAQUE = (320, 1680, 725, 1762)`**, **`LEVEL_VALUE = (480, 1700,
  700, 1740)`** — found by eye. The value is not fixed-position, and comes in
  white, yellow (`MAX`) and red (limit-broken) variants.
- The large character illustration occupies roughly rows 657–1622.
- Rows 0–123 are static chrome; rows ~2308–2556 are the static bottom nav.

### The two-signal method, and why it is trusted

1. **Name text is a near-perfect fingerprint for "same character".** Greyscale,
   resized to 142×42, zero-mean, unit-norm; correlation ≥ **0.90** clusters pages
   into visits. Gives **54 characters** + 4 non-detail frames (flat crop, score
   exactly 0.000 — a useful filter).
2. **Icon matching** against the 551-portrait library, colour, resized to 24×24,
   zero-mean, unit-norm, matched by **vectorised dot product** (not
   `matchTemplate`). Independently yields **54 distinct characters**, with
   **49 of 58 clusters unanimous**.

Two independent signals landing on the same count is what proved the box is right.

### Accuracy — measured, not assumed

Confidence is the **margin over the runner-up**, never the raw score.

| Sample | Result |
|---|---|
| Top 4 reads, user-confirmed | **4 / 4 correct** |
| 5 weakest reads, user-confirmed | **1 / 5 correct** (only Mizuki) |

`TRUSTED = 0.05` margin → **21 of 54** entries trusted. The tail is not usable.

Confirmed correct: Naruto *Rasengan Mastered*, Haku *The Icy Mask's Blades*,
Kushina *The Red-Hot Habanero*, Hashirama *Father of Leaf Village*,
Mizuki *Hidden Treachery*.

Confirmed **not** owned: Kurotsuchi *Magnanimous Tomboy of the Stone*, Suigetsu
*The Demon Lives On*, Rasa *Family Values*, Akatsuchi *Unyielding Stone*.

### Coverage

**The user owns 83 units at 4★ and above.** (They first said 52 + 13 + 53 = 118,
then corrected it to 83.) The recording visits **54**, so roughly **two-thirds**
is captured and ~29 units are missing. Known-owned units being absent from the
reading is therefore expected, **not** a failure of the matcher.

### Things tried that did NOT help (don't redo them)

- Higher comparison resolution — 24px already best; 32/48/64/96 all slightly worse.
- Sobel edge features — markedly worse (0/5 on known units).
- A learned overlay mask from match residuals — no gain. **The theory that the
  game stamps rarity/element/level over the icon was wrong**; residuals were
  spread through the middle, not concentrated at edges.
- Restricting the library to rarity ≥ 4 — removes only 33 of 551, no real gain.

### The false-match lesson (important, cost an hour)

Early portrait matching with `TM_CCOEFF_NORMED` produced 1,194 "hits" above 0.60
with top scores ~0.84 — but **six different characters all peaked at essentially
the same pixel (~344, 52)**. That is a correlation metric locking onto a flat,
low-variance UI region, not artwork.

**Never trust a bare correlation score. Always check (a) the margin over the
runner-up, (b) that different templates land in different places, and (c) that the
matched region has real local variance.** Prefer colour over greyscale and a known
crop box over a free search.

Also too slow: brute-force multi-scale `matchTemplate` over full 1180×2556 frames
(40 portraits × 35 scales never finished). **Find the geometry first, crop, then
match at one known scale.**

---

## 8. Next steps, in order

### Immediate — do this FIRST in the fresh chat, while the image budget is intact

1. **Look at two or three pages** from `data/analysis/pages/` with `view_image`,
   or use `scripts/crop_frame.py x0 y0 x1 y1 <page>.png` to dump an upscaled crop.
2. **Confirm or correct `ICON = (79, 1740, 157)` by eye.** It was found
   statistically and never visually verified. If it is even slightly off, that
   alone may explain the weak tail.
3. **Find the level box by eye** and add it as a constant.

### Then

4. **Process the second recording.** Run 1 is already archived as `*_v1`, so just
   run `box_scan.py` → `box_pages.py` → `read_box.py` on the `.mov`. Compare:
   how many pages, how many distinct characters, how the confidence margins
   compare to run 1's (top 4 correct, bottom 4 of 5 wrong). Run 1's 54 confirmed
   names in `box_reading_v1.json` are a **free regression test** — any character
   appearing in both recordings should be read the same way twice.
5. **Read the level.** Tesseract has already failed on this stylised font — do
   **not** retry it. Cut digit templates from a few pages and match; levels are a
   small closed set (1–150).
6. **If coverage is still short of 83**, ask for another pass. Recording advice
   already given to the user:
   - Sort the box by the default order and don't change it mid-recording. **If the
     order is deterministic and nobody is skipped, the sequence itself carries
     identity information** — matching the run against known unit ordering could
     turn the ~33 shaky reads into near-certainties. This is the biggest available
     accuracy lever.
   - Go through every unit in that order, skipping none.
   - Pause ~1s per character so at least two clean frames land.
   - Don't scroll back or re-open anyone (creates phantom duplicates).
   - Set the 4★+ filter before starting and leave it alone.
   - One continuous recording ideally; if split, say where.
7. **Write the real roster** to `data/rosters/example.json`, replacing the 5-unit
   placeholder. Merge both recordings — between them they may cover all 83 even
   if neither does alone. Keep cost / abilities / HP / ATK sourced from
   `data/units.json` by **`unit_id`** — units are keyed by unit_id, never by name
   or slug, because many units share a name.

### Then, the engine (ordered by value)

7. Reaction branches firing on being hit (parsed but inert).
8. Combination / follow-up / counter attacks.
9. Field Skills (a circle, 6 steps of falloff), Buddy Skills (vertical pairs; none
   in Phantom Castle), Sync Skills (when the three front units share
   element/affiliation/range) — these feed `flat_attack_boost`.
10. Perfect Dodge as a **count**, not a chance.
11. Percentage attacks, fixed-damage areas, self-cost techniques.
12. **The solver**: beam search / MCTS plus Monte Carlo over weighted enemy sets,
    AI branch probabilities via `AiState.odds`, 3.125% crit, ailment procs.
    Must support "beat" vs "complete" modes, helper characters, duplicate units,
    and the **team cost limit of 200**. Must output a **completion likelihood and
    what it depends on**.
13. **Frontend**: animated top-down grid, stepping turn by turn over the `Event`
    stream.
14. **Catalogue expansion**: story (161), story-hard (161), gaiden (21 + 23),
    ninja-road (42), trial (10).

---

## 9. Dead ends — do not retry

- Team HP bar pixel width — the bar **animates and lags** the number beside it; a
  3-point fit disagreed with itself (8 vs 12 HP/px).
- Colour-blob popup detection, with or without background subtraction — sprites
  are vivid *and* moving, so every hit was a sprite.
- The Fandom wiki's damage formula — it does not document one, and its 2.5% crit
  rate is wrong.
- **Tesseract on the stylised HUD font** — `data/analysis/hud_timeline.csv` is
  mostly garbage, don't trust it. (Reading numbers off a cropped screenshot with
  my own vision *does* work.)
- blazingonline portrait URLs — it's a SPA, they aren't exposed.
- gachawiki static JSON — there is none.
- **Decompiling the game binary** — asked and settled twice. Off the table, and
  pointless: the balance numbers were server-side master data, which is exactly
  what blazingonline serves, stamped `original-2.28.0`.
- **Subagents as an image-budget workaround** — they share the budget.

---

## 10. Status summary

**Live:** https://venesshn.github.io/nb-solver/ (preview). Every push to `main`
runs `.github/workflows/pages.yml`: ruff → pytest → `build_web.py` → Pages.

**Done**

- Mission catalogue: **241 missions, 869 stages** — emergency 167, Ninja Road
  42, story 23 (normal + "(Hard)" stages), trials 5, gaiden 3 (normal + Hard),
  Captain Exam 1. Rebuild with `scripts/build_catalogue.py`. Only emergency
  missions have battlefield geometry (hideoutgacha); others use a generic layout
  and say so. **Not buildable from the source:** boss raids (no maps). Phantom
  Castle: not wanted by the user.
- Unit catalogue: 1,100 units; **Revival = no 7★ and no Rebirth-only units**
  (`Unit.in_revival`), so the site ships 1,084.
- `combat.py` implements the published formula, pinned by worked examples
- AI parser: 6,315 states, 100% parsed; AI-driven enemy phase wired into
  `battle.py` and verified against real Orochimaru data; reaction branches fire
- **Roster**: 83 units read from the recording (Python and browser readers
  both 83/83, held-out run 1 identical) → `data/rosters/example.json`, no player
  details, **team cost limit 329** (user, Ninja Rank 90).
- **Engine** (`battle.py`): combinations (+ "during Combinations" boosts),
  counters, element damage bonuses/reductions, regeneration, perfect dodge as a
  count, percentage-of-health attacks, health self-costs, chakra cuts and
  chakra-restoring power-ups, self-inflicted ailments, reactions, enemies close
  in on their turn, script-less enemies alternate attack/skill, Perimeter
  Barrier 2.5×.
- **Passives** (`passives.py`): abilities (only as many as the box says are
  unlocked — evidence says the user's are mostly locked), field skills (every
  front unit's, weakest end of the range), buddy skills. Coverage: field 93%,
  buddy 95%, abilities 75% of clauses; unknown wording is skipped, never guessed.
- **Solver**: buff jutsu are cast; supports chosen for health within budget;
  supports switch in on their pair's turn when their move is worth more
  (and still act); every objective kind
  is judged (combination finish = boss killed by a 3+ unit action; drop complete
  = every carrier defeated, boss held back until then). **Reproduces both
  user-confirmed clears of e3003: Heart team 100%** (tests). Body-only: see
  the CORRECTION below.
- **Website**: also an abilities-unlocked column and a mission-type filter;
  results note Ninja Road and missing-layout assumptions.
- **Bosses**: the map data marks bosses explicitly (`role` from the entry's
  `boss` field); only those count when any are marked — e3003 map 3 now ends
  when Orochimaru falls, not after every Sound Ninja. **Giant bosses** are
  several same-named boss lines, one per part, each acting on its own
  countdown with its own HP; **the first-listed line is the head, and beating
  the head ends the giant** (user-confirmed). Evidence for head = first line:
  hideoutgacha labels 58 maps 'Boss' + 'Boss part' and in ALL 58 the 'Boss'
  (head) line is listed first and the parts share its name. The remaining
  147 multi-line giant occurrences, counted per map variant (127 Ninja Road, 14 Giant Boss Rush, 4 gaiden, 2
  story) carry no part label, so for them it is still inferred.
  Boss marking is now read per MAP: a wave without the marked boss must be
  cleared (it used to fall back to 'any scripted enemy' per wave).
- **Ninja Road** (user-confirmed rules): **3 teams of 6 from separate copies**,
  each with its **own health bar** carried across the maps it fights; each map
  goes to the team best placed (health × element matchup); **a beaten team is
  out, the others carry on**. **Featured units** per road (2x HP/1.5x STR or
  3x HP/2x STR) parsed from the Fandom "Extra Effects" table → 14 roads have
  boosts; applied to owned units and helpers; advice mentions them.
- **Every mission**: completing a map restores **half the missing health**,
  MEASURED on both map changes of the user's e3003 clear recording (8540→8918
  and 8026→8661 of 9296: exactly 378/756 and 635/1270), plus "Restores N
  health when moving to a new map" abilities. Percentage attacks stop at 1 HP.
- **Teams are always 3 pairs (6 units)** — front + support each. A friend's
  helper is the FRONT of one pair, so the box fills 2 fronts + 3 supports;
  without a helper, 3 + 3. **Ninja Road teams get no helper.** (User-confirmed;
  the solver previously fielded up to 4 fronts + 4 supports — that was wrong.)
- The HUD counter under "MAP 1/3" with a scroll icon counts **drops collected,
  not turns** (seen by eye; `hud_timeline.py` used to call it TURN_BOX). Enemy
  countdowns drop **per unit action** (user-confirmed again).
- **CORRECTION (2026-10-21 night): the Body-only 100% was FALSE.** Wave 1 of
  e3003 [B] map 3 is four scripted Sound Ninja; reading that wave alone made
  one the 'boss' (head) and the rest its parts, so killing it ended the map
  and Orochimaru (wave 6) NEVER spawned (0/20 runs). Only 3 maps affected
  (e3003 [C]/[B] map 3, e7001 [B] map 3) - unluckily the validation stage.
  Also found: NO unit heal ever fired (data says 'Restores N health', regex
  wanted 'HP'; 76 jutsu now parse) and player barriers ('protects you from N
  damage') did nothing. Fixed all three.
- User rules applied the same night: units AND enemies move anywhere; an
  enemy attack hits EVERY unit inside its range (each hit off the shared
  pool); supports switch in on their pair's turn whenever and still act;
  combos pass 15 hits 'sometimes' -> ATTACK_HITS 6, JUTSU_HITS 10 (21% of
  Body attacks). Policy now spreads units around the target (_attack_spot).
- Body-only NOW: hand-picked team (Lee, Guy, Sakura / Tobirama, Haku,
  Naruto) 9/20; solver's pick 27% [14-46%]. Heart team 20/20, 93% HP left.
  User says Body-only is near-certain -> recorded as an xfail test. Likely
  causes: unlocked abilities (box says 0), life-drain jutsu (10 units, not
  modelled), policy weaker than a human.
- (Superseded) Body-only had read 100% without a helper; the earlier 32% came
  from the auto-helper: it picked by raw power
  (Might Guy 'Deep Crimson Youth': 708 HP, ninjutsu costs 15% of team health).
  Auto-helper is now chosen by PLAY: no helper plus the top 4 by power, 6 quick
  runs each. NR: user has never finished one; the solver agrees (NR #1 stops
  at map 15, NR #10 at map 20).
- (Superseded: run on the broken map 3) Calibration sweep: every knob left
  both at 100% except ENEMY_STEP 0. Knobs live in simulate.py (PLAIN_INTERVAL,
  PLAIN_SKILL_EVERY, ENEMY_STEP, COMBO_REACH_BONUS) and passives.RANGE_POINT.
- Site: helper defaults to none and remembers the pick (user's friend pool is
  limited). Weekly `.github/workflows/refresh-data.yml` rebuilds the catalogue,
  refuses losses (`scripts/check_catalogue.py`), tests, commits, then
  dispatches pages.yml (bot pushes don't trigger workflows).
  Its FIRST run lost e7034's layouts (one hideoutgacha connection dropped;
  the check only counted missions). Fixed: fetches retry transient errors
  (`scrape/http.py`, never a 404), the check compares every stage, map,
  layout, enemy list, source and boost, data restored; re-run was clean.
- Abilities: user says "some, on main units" but which is unknown; the box
  keeps 0 and the user sets them per unit in the site's Abilities column.
- **2026-10-22 (player's feedback after using the site):**
  - Helper default = a COPY OF ONE OF YOUR OWN UNITS (Revival feature,
    player-confirmed free on cost): `helper="self"`, `as_helper`,
    `own_helper_candidates`; naming an owned unit copies the player's own.
    Site key `helper-mode-2` so old 'none' choices don't hide the default.
  - Teams render as 3 pair columns (front over support; helper = pair 3).
  - Advice only if it beats the current rate by >5 points; runs below 80%;
    now also limit break (to `max_level_limit_break`, 150) and ability
    unlocks; 2 teams tried per idea. `reached` = closest losing attempt.
  - BUG: 'Character cost 28 or lower only' was a TEAM total of 28 -> always
    impossible. Now per character (`_allowed(..., cost)`, `Choice.own_cost`).
  - BUG: 'Substitution +N%' gave chance 100 -> 24 enemies dodged every hit.
  - hideoutgacha battle guide (data/analysis/hideout_bm.txt): a NORMAL ATTACK
    LANDS ON EVERY ENEMY IN RANGE; chakra gauge caps at 2x ninjutsu cost.
    Both now modelled (`_caught`, `chakra_max`). 'all enemies in range'
    jutsu used to hit the whole map; now within the unit's reach.
  - Heals: 'all allies in range' adds the amount PER ALLY reached
    (player-confirmed: 1280 x3 = 3,840); healer moves to cover most.
    More barrier ('barrier blocking N', 'block up to N') and dodge
    ('chance to dodge by N%') wordings parsed.
  - Policy: chakra cheap on bosses, free when the gauge is full; 4 play
    STYLES (balanced/all-out/careful/boss rush) tried on the 2 leading teams;
    teams ranked by clear rate, then PROGRESS (how close losses got).
  - ENEMY_AREA = 0.75 (other units caught within 0.75 x enemy reach).
    Sensitivity: enemy hitting only its target took the e3003 Body team
    from 5/40 to 26/40 - the dominant unknown. Calibrated: area <= 0.75 ->
    Body 65-80%, 1.0 -> 10-20%; Heart 100% throughout.
  - Speed: per-run 149 -> ~75 ms (CPython) by weighing only 4 targets per
    decision and checking a switch only when it could matter.
  - `scripts/benchmark.py`: `--set player` = the player's 8 unbeaten
    missions x 3 objectives (24); `--set spread` = 48 seeded stages.
    Player set: clears found 8 -> 14 of 24, mean 19% -> 38%. Spread: 42 ->
    44 of 48, mean 80% -> 86%. 10 player objectives still 0%.
- TURN ORDER (player-confirmed): pair 1, pair 2, pair 3 (the helper's) - fixed slot
  order every round. It used to sort by Speed, which only Ninja World uses.
- **211 tests passing, ruff clean.** `tests/test_build_web.py` imports the solver
  from the shipped zip alone — a module left out of the browser build fails CI
  (it happened once: `passives.py`).

**Known weaknesses (say so to the user, don't hide them)**

- Unpublished numbers stay estimates, listed in `UNVERIFIED` and on the site:
  attack distances, combination joining rule, script-less enemy rhythm (3;
  ~75% of distinct enemies, almost all ordinary - 1 of ~1,384 bosses), hits
  per attack (6, jutsu 10).
- Body-only e3003 now ~65-80% (calibrated); the player says near-certain.
- ENEMY_AREA rests on one calibration stage; the 8 unbeaten missions only
  bound it from the other side (they must not come out easy).
- Ninja Road: the team-to-map choice is a heuristic; NR #1 still ends at map
  15 in simulation.
- Two calibration points (both e3003) can't prove accuracy everywhere.
- The repo was deleted and recreated with the scrubbed history; old commit
  SHAs verified gone (HTTP 422).

**Open questions for the user**

- None outstanding.
