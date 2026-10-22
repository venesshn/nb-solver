"""Choose a team from a player's box and say how likely it is to clear a stage.

The search is honest about what it is: a heuristic shortlist of teams, each
played many times with fresh dice. Failing to find a win is reported as exactly
that. Only when no legal team can even be formed is a stage called impossible.
"""

from __future__ import annotations

import itertools
import math
import random
from collections import defaultdict
from dataclasses import asdict, dataclass, field

from nbsolver.combat import element_multiplier
from nbsolver.missions import ClearCondition, ConditionKind, Stage, UnitBoost
from nbsolver.models import OwnedUnit, Unit
from nbsolver.roster import Roster
from nbsolver.simulate import (
    STYLE,
    STYLES,
    UNVERIFIED,
    Member,
    Run,
    Style,
    play_road,
    play_stage,
)

IMPOSSIBLE = "Not possible to complete - keep grinding!"
NOT_FOUND = "No winning strategy found."
# A team is always three pairs: a front unit and the support behind it. A
# friend's helper takes the front of one pair, so the box then fills two fronts.
PAIRS = 3
SHORTLIST = 10
FINALISTS = 3
# Grinding advice: teams tried per suggestion, and how much a suggestion must raise
# the clear rate before it is shown at all.
ADVICE_TEAMS = 2
ADVICE_MARGIN = 0.05
# Suggestions of each kind tried: levelling, ability unlocks, units to get.
ADVICE_STEPS = 3
# Below this clear rate the report also says what grinding would raise it.
ADVISE_BELOW = 0.8
# Play styles: how many leading teams try every style, and the clear rate above
# which the default style is good enough to skip the search.
STYLE_TEAMS = 2
STYLE_SKIP_ABOVE = 0.95
# Conditions the simulator cannot judge yet; the report says so rather than guess.
UNJUDGED = {ConditionKind.OTHER}


@dataclass
class Choice:
    """A copy from the box, or a friend's helper, as the search sees it."""

    unit: Unit
    level: int
    cost: int
    copy: int | None = None
    helper: bool = False
    abilities: int = 0
    # Multipliers a mission grants this unit, e.g. Ninja Road's featured units.
    health_x: float = 1.0
    attack_x: float = 1.0
    # A helper made by copying one of the player's own units (Revival lets you).
    mine: bool = False
    # What the character itself costs, which per-character caps judge; a helper
    # adds nothing to the team total, but its own cost still has to pass a cap.
    card_cost: int | None = None

    @property
    def own_cost(self) -> int:
        return self.cost if self.card_cost is None else self.card_cost

    def member(self, key: str) -> Member:
        return Member(
            key=key,
            unit=self.unit,
            level=self.level,
            helper=self.helper,
            copy=self.copy,
            abilities=self.abilities,
            health_x=self.health_x,
            attack_x=self.attack_x,
        )


@dataclass
class Plan:
    front: list[Choice]
    back: list[Choice]
    helper: Choice | None
    runs: list[Run] = field(default_factory=list)
    successes: int = 0
    style: Style = STYLE

    @property
    def tries(self) -> int:
        return len(self.runs)

    @property
    def rate(self) -> float:
        return self.successes / self.tries if self.tries else 0.0

    @property
    def cost(self) -> int:
        return sum(c.cost for c in [*self.front, *self.back])

    def members(self, prefix: str = "") -> tuple[list[Member], list[Member | None]]:
        front = [c.member(f"{prefix}p{i + 1}") for i, c in enumerate(self.front)]
        if self.helper is not None:
            front.append(self.helper.member(f"{prefix}helper"))
        back: list[Member | None] = [
            c.member(f"{prefix}s{i + 1}") for i, c in enumerate(self.back)
        ]
        return front, back

    @property
    def copies(self) -> set[int]:
        return {c.copy for c in [*self.front, *self.back] if c.copy is not None}


@dataclass
class Road:
    """Several teams sharing one mission, each with its own health bar."""

    plans: list[Plan]
    runs: list[Run] = field(default_factory=list)
    successes: int = 0

    @property
    def tries(self) -> int:
        return len(self.runs)

    @property
    def rate(self) -> float:
        return self.successes / self.tries if self.tries else 0.0

    @property
    def cost(self) -> int:
        return max(p.cost for p in self.plans)

    def lineup(self):
        return [p.members(f"t{i + 1}") for i, p in enumerate(self.plans)]


def wilson(successes: int, tries: int, z: float = 1.96) -> tuple[float, float]:
    """A 95% interval for a success rate that stays sensible near 0% and 100%."""
    if tries == 0:
        return 0.0, 1.0
    p = successes / tries
    centre = (p + z * z / (2 * tries)) / (1 + z * z / tries)
    spread = (
        z
        * math.sqrt(p * (1 - p) / tries + z * z / (4 * tries * tries))
        / (1 + z * z / tries)
    )
    return max(0.0, centre - spread), min(1.0, centre + spread)


def _allowed(
    unit: Unit, condition: ClearCondition | None, cost: int | None = None
) -> bool:
    if condition is None:
        return True
    if condition.kind == ConditionKind.ELEMENT_ONLY:
        return unit.element == condition.element
    if condition.kind == ConditionKind.COST_CAP and condition.max_cost:
        # "Character cost 28 or lower only" limits every character, not the team.
        return (unit.cost if cost is None else cost) <= condition.max_cost
    if condition.kind == ConditionKind.AFFILIATION_ONLY:
        wanted = condition.affiliation.lower()
        return any(
            wanted in a.lower() or a.lower() in wanted for a in unit.affiliations
        )
    return True


def _requires(unit: Unit, condition: ClearCondition | None) -> bool:
    if condition is None or condition.kind != ConditionKind.REQUIRE_UNITS:
        return False
    wanted = condition.required_unit.lower()
    return wanted in unit.name.lower() or any(
        wanted in a.lower() for a in unit.affiliations
    )


def _enemy_elements(stage: Stage) -> dict:
    weights: dict = defaultdict(float)
    for battle_map in stage.maps:
        total = sum(s.weight for s in battle_map.sets) or 1.0
        for enemy_set in battle_map.sets:
            for enemy in enemy_set.enemies:
                weights[enemy.element] += (
                    enemy.hp * max(1, enemy.count) * enemy_set.weight / total
                )
    return weights


def power(choice: Choice, elements: dict) -> float:
    """How hard this unit hits this stage's enemies, jutsu included."""
    stats = choice.unit.stats_at(choice.level)
    total = sum(elements.values()) or 1.0
    affinity = (
        sum(w * element_multiplier(choice.unit.element, e) for e, w in elements.items())
        / total
    )
    jutsu = (
        choice.unit.ninjutsu.multiplier
        if choice.unit.ninjutsu and choice.unit.ninjutsu.multiplier
        else 1.0
    )
    return (
        stats.attack * choice.attack_x * affinity * (1 + 0.35 * jutsu)
        + 0.3 * stats.health * choice.health_x
    )


Boosts = dict[tuple[str, str], tuple[float, float]]


def boost_table(boosts: list[UnitBoost] | None) -> Boosts:
    return {(b.name, b.title): (b.health, b.attack) for b in boosts or []}


def _boosted(choice: Choice, boosts: Boosts) -> Choice:
    health, attack = boosts.get((choice.unit.name, choice.unit.title), (1.0, 1.0))
    choice.health_x, choice.attack_x = health, attack
    return choice


def _choices(
    roster: Roster, catalogue: dict[int, Unit], boosts: Boosts | None = None
) -> list[Choice]:
    out = []
    for index, owned in enumerate(roster.units):
        unit = catalogue.get(owned.unit_id)
        if unit is None or not unit.in_revival:
            continue
        out.append(
            _boosted(
                Choice(
                    unit=unit,
                    level=owned.level,
                    cost=owned.cost(unit),
                    copy=index,
                    abilities=owned.unlocked_count(unit),
                ),
                boosts or {},
            )
        )
    return out


def pick_helper(
    catalogue: dict[int, Unit],
    stage: Stage,
    condition: ClearCondition | None,
    boosts: Boosts | None = None,
) -> Choice | None:
    found = helper_candidates(catalogue, stage, condition, boosts, 1)
    return found[0] if found else None


def helper_candidates(
    catalogue: dict[int, Unit],
    stage: Stage,
    condition: ClearCondition | None,
    boosts: Boosts | None = None,
    count: int = 4,
) -> list[Choice]:
    """The hardest hitters a friend might lend; raw power alone is a poor judge,
    so the solver plays each before choosing."""
    elements = _enemy_elements(stage)
    pool = [
        _boosted(
            Choice(unit=u, level=u.max_level, cost=0, helper=True, card_cost=u.cost),
            boosts or {},
        )
        for u in catalogue.values()
        if u.in_revival and u.rarity >= 6 and u.levels and _allowed(u, condition)
    ]
    return sorted(pool, key=lambda c: -power(c, elements))[:count]


def as_helper(choice: Choice) -> Choice:
    """Revival lets a player copy one of their own units into the helper slot: the
    same level and abilities, free on the team cost (player-confirmed)."""
    return Choice(
        unit=choice.unit,
        level=choice.level,
        cost=0,
        helper=True,
        abilities=choice.abilities,
        health_x=choice.health_x,
        attack_x=choice.attack_x,
        mine=True,
        card_cost=choice.cost,
    )


def own_helper_candidates(
    choices: list[Choice],
    stage: Stage,
    condition: ClearCondition | None,
    count: int = 4,
) -> list[Choice]:
    """The player's own strongest eligible units, as copies for the helper slot."""
    elements = _enemy_elements(stage)
    best: dict[int, Choice] = {}
    for c in choices:
        if not _allowed(c.unit, condition, c.cost):
            continue
        if c.unit.unit_id not in best or power(c, elements) > power(
            best[c.unit.unit_id], elements
        ):
            best[c.unit.unit_id] = c
    ranked = sorted(best.values(), key=lambda c: -power(c, elements))
    return [as_helper(c) for c in ranked[:count]]


def _trial_helper(
    choices: list[Choice],
    candidates: list[Choice | None],
    stage: Stage,
    limit: int,
    condition: ClearCondition | None,
    seed: int,
) -> Choice | None:
    """Play a few quick runs with each candidate, going without included."""
    best: tuple[tuple[float, float, float], Choice | None] | None = None
    for candidate in candidates:
        plans = shortlist(choices, candidate, stage, limit, condition)
        if not plans:
            continue
        plan = plans[0]
        _play(plan, stage, 6, seed + 11, condition)
        score = _rank(plan)
        if best is None or score > best[0]:
            best = (score, candidate)
    return best[1] if best else None


def _satisfied(run: Run, plan: Plan, condition: ClearCondition | None) -> bool:
    if not run.won:
        return False
    if condition is None:
        return True
    kind = condition.kind
    if kind == ConditionKind.TURN_LIMIT and condition.max_turns:
        return run.turns <= condition.max_turns
    if kind == ConditionKind.NINJUTSU_FINISH:
        return run.finished_by_jutsu
    if kind == ConditionKind.NO_AILMENTS:
        return run.ailments_taken == 0
    if kind == ConditionKind.COMBO_FINISH:
        return run.finished_by_combination
    if kind == ConditionKind.DROP_COMPLETE:
        return run.all_drops
    if kind == ConditionKind.COST_CAP and condition.max_cost:
        everyone = [*plan.front, *plan.back, *([plan.helper] if plan.helper else [])]
        return all(c.own_cost <= condition.max_cost for c in everyone)
    return True


def _legal(plan: Plan, limit: int, condition: ClearCondition | None) -> bool:
    if plan.cost > limit:
        return False
    capped = (
        condition and condition.kind == ConditionKind.COST_CAP and condition.max_cost
    )
    everyone = [*plan.front, *plan.back, *([plan.helper] if plan.helper else [])]
    if capped and any(c.own_cost > condition.max_cost for c in everyone):
        return False
    if (
        condition
        and condition.kind == ConditionKind.REQUIRE_UNITS
        and sum(_requires(c.unit, condition) for c in everyone)
        < (condition.required_count or 1)
    ):
        return False
    ids = [c.unit.unit_id for c in [*plan.front, *plan.back]]
    return len(ids) == len(set(ids))


def _fill_back(
    front: list[Choice], pool: list[Choice], budget: int, slots: int
) -> list[Choice]:
    """Supports add their health to the shared pool; take the sturdiest that fit."""
    used = {c.unit.unit_id for c in front}
    spare = sorted(
        (c for c in pool if c.unit.unit_id not in used),
        key=lambda c: -c.unit.stats_at(c.level).health,
    )
    back: list[Choice] = []
    for candidate in spare:
        if len(back) >= slots:
            break
        if candidate.unit.unit_id in used or candidate.cost > budget:
            continue
        back.append(candidate)
        used.add(candidate.unit.unit_id)
        budget -= candidate.cost
    return back


def _play(
    plan: Plan,
    stage: Stage,
    tries: int,
    seed: int,
    condition: ClearCondition | None,
) -> None:
    front, back = plan.members()
    objective = condition.kind if condition else None
    for k in range(tries):
        run = play_stage(
            stage,
            front,
            back,
            random.Random(seed * 7919 + len(plan.runs) + k),
            objective=objective,
            style=plan.style,
        )
        plan.runs.append(run)
        plan.successes += _satisfied(run, plan, condition)


def shortlist(
    choices: list[Choice],
    helper: Choice | None,
    stage: Stage,
    limit: int,
    condition: ClearCondition | None,
) -> list[Plan]:
    elements = _enemy_elements(stage)
    pool = [c for c in choices if _allowed(c.unit, condition, c.cost)]
    best_copy: dict[int, Choice] = {}
    for c in pool:
        if c.unit.unit_id not in best_copy or power(c, elements) > power(
            best_copy[c.unit.unit_id], elements
        ):
            best_copy[c.unit.unit_id] = c
    ranked = sorted(best_copy.values(), key=lambda c: -power(c, elements))
    required = [c for c in ranked if _requires(c.unit, condition)]
    top = ranked[:SHORTLIST] + [c for c in required if c not in ranked[:SHORTLIST]]

    plans = []
    size = min(PAIRS - (1 if helper else 0), len(top))
    for front in itertools.combinations(top, size):
        front = list(front)
        budget = limit - sum(c.cost for c in front)
        if budget < 0:
            continue
        # One support behind every front unit, the helper's included.
        back = _fill_back(front, pool, budget, PAIRS)
        plan = Plan(front=front, back=back, helper=helper)
        if _legal(plan, limit, condition):
            plans.append(plan)
    plans.sort(
        key=lambda p: (
            -(
                sum(power(c, elements) for c in p.front)
                + 0.3 * sum(c.unit.stats_at(c.level).health for c in p.back)
            )
        )
    )
    return plans


def _describe(choice: Choice) -> dict:
    return {
        "unit_id": choice.unit.unit_id,
        "name": choice.unit.name,
        "title": choice.unit.title,
        "element": choice.unit.element,
        "rarity": choice.unit.rarity,
        "level": choice.level,
        "cost": choice.cost,
        "helper": choice.helper,
        "mine": choice.mine,
        "boost": (
            [choice.health_x, choice.attack_x]
            if (choice.health_x, choice.attack_x) != (1.0, 1.0)
            else None
        ),
    }


def _depends_on(
    plan: Plan, stage: Stage, condition: ClearCondition | None
) -> list[str]:
    notes = []
    for number, battle_map in enumerate(stage.maps, start=1):
        if len(battle_map.sets) < 2:
            continue
        by_set: dict[int, list[bool]] = defaultdict(list)
        for run in plan.runs:
            if len(run.sets_rolled) >= number:
                by_set[run.sets_rolled[number - 1]].append(
                    _satisfied(run, plan, condition)
                )
        rates = {k: sum(v) / len(v) for k, v in by_set.items() if v}
        if rates and max(rates.values()) - min(rates.values()) >= 0.15:
            worst = min(rates, key=rates.get)
            names = sorted({e.name for e in battle_map.sets[worst].enemies})
            notes.append(
                f"Map {number}'s enemy line-up: with {', '.join(names[:3])} the clear rate drops to "
                f"{rates[worst]:.0%} (vs {max(rates.values()):.0%} on the best line-up)."
            )
    losses = [r for r in plan.runs if not r.won]
    if losses:
        where = defaultdict(int)
        for r in losses:
            where[r.reached_map] += 1
        worst_map = max(where, key=where.get)
        notes.append(
            f"Most failures happen on map {worst_map} ({where[worst_map]} of {len(losses)} losses): "
            "enemy jutsu choices, ailment procs and critical hits decide those runs."
        )
    if not notes:
        notes.append(
            "Little depends on luck: the result barely changed across random rolls."
        )
    return notes


def _instructions(run: Run) -> list[dict]:
    return [asdict(f) for f in run.frames]


def solve(
    stage: Stage,
    roster: Roster,
    catalogue: dict[int, Unit],
    *,
    condition: ClearCondition | None = None,
    helper: int | str | None = "auto",
    tries: int = 40,
    seed: int = 1,
    progress=None,
    teams: int = 1,
    boosts: list[UnitBoost] | None = None,
) -> dict:
    """The whole answer the site shows for one stage and one player.

    `teams` above 1 is Ninja Road: that many separate teams, each with its own
    health bar, share the maps. `boosts` are the units the mission favours.
    """
    table = boost_table(boosts)
    if condition is not None and condition.kind in UNJUDGED:
        return {
            "status": "unsupported",
            "message": f"The objective '{condition.description}' can't be checked by the simulator yet.",
        }
    choices = _choices(roster, catalogue, table)
    eligible = [c for c in choices if _allowed(c.unit, condition, c.cost)]
    if not eligible:
        return {
            "status": "impossible",
            "message": IMPOSSIBLE,
            "reason": "You own no unit this objective allows.",
            "recommendations": recommend(
                stage, roster, catalogue, condition, None, tries, seed, table, teams
            ),
        }

    helper_choice: Choice | None = None
    if teams > 1:
        # Ninja Road teams are the player's own six; no friend comes along.
        helper = None
    if helper in ("auto", "self"):
        # "self": a copy of one of the player's own units; "auto": any unit a
        # friend might lend, or going without.
        candidates: list[Choice | None] = (
            own_helper_candidates(choices, stage, condition)
            if helper == "self"
            else [None, *helper_candidates(catalogue, stage, condition, table)]
        )
        helper_choice = _trial_helper(
            choices,
            candidates or [None],
            stage,
            roster.team_cost_limit,
            condition,
            seed,
        )
    elif isinstance(helper, int) and helper in catalogue:
        unit = catalogue[helper]
        mine = [c for c in choices if c.unit.unit_id == helper]
        if mine:
            # The player owns it, so the helper slot takes a copy of their own.
            helper_choice = as_helper(max(mine, key=lambda c: c.level))
        else:
            helper_choice = _boosted(
                Choice(
                    unit=unit,
                    level=unit.max_level,
                    cost=0,
                    helper=True,
                    card_cost=unit.cost,
                ),
                table,
            )
        if not _allowed(unit, condition, helper_choice.own_cost):
            helper_choice = None

    plans = shortlist(choices, helper_choice, stage, roster.team_cost_limit, condition)
    if not plans:
        return {
            "status": "impossible",
            "message": IMPOSSIBLE,
            "reason": "No team you own fits the cost limit and this objective together.",
            "recommendations": recommend(
                stage,
                roster,
                catalogue,
                condition,
                helper_choice,
                tries,
                seed,
                table,
                teams,
            ),
        }

    contenders = plans[: max(FINALISTS * 3, 6)]
    if teams > 1:
        best = _best_road(
            choices,
            helper_choice,
            stage,
            roster.team_cost_limit,
            condition,
            teams,
            plans,
            tries,
            seed,
            progress,
        )
    else:
        screen = max(6, tries // 4)
        steps = len(contenders) + FINALISTS
        for n, plan in enumerate(contenders):
            _play(plan, stage, screen, seed, condition)
            if progress:
                progress(n + 1, steps)
        # Players beat hard stages by changing how they play as well as who they
        # bring: unless a team already clears nearly always, try the leading teams
        # in every play style and keep whatever works best.
        leaders = sorted(contenders, key=_rank, reverse=True)
        variants: list[Plan] = []
        if leaders and leaders[0].rate < STYLE_SKIP_ABOVE:
            for lead in leaders[:STYLE_TEAMS]:
                for style in STYLES[1:]:
                    variants.append(
                        Plan(
                            front=lead.front,
                            back=lead.back,
                            helper=lead.helper,
                            style=style,
                        )
                    )
            steps += len(variants)
            for n, plan in enumerate(variants):
                _play(plan, stage, screen, seed, condition)
                if progress:
                    progress(len(contenders) + n + 1, steps)
        finalists = sorted([*contenders, *variants], key=_rank, reverse=True)[
            :FINALISTS
        ]
        done = steps - FINALISTS
        for n, plan in enumerate(finalists):
            _play(plan, stage, tries, seed + 1, condition)
            if progress:
                progress(done + n + 1, steps)
        best = max(finalists, key=_rank)

    low, high = wilson(best.successes, best.tries)
    objective = condition.kind if condition else None
    showcase = None
    for k in range(60):
        run = _attempt(best, stage, random.Random(10_000 + k), objective, record=True)
        if _satisfied(run, best, condition):
            showcase = run
            break
    if showcase is None:
        showcase = _attempt(best, stage, random.Random(10_000), objective, record=True)

    lineup = best.plans if isinstance(best, Road) else [best]
    closest = min(
        (r for r in best.runs if not r.won),
        key=lambda r: (-r.reached_map, r.enemy_left),
        default=None,
    )
    report = {
        "status": "found" if best.successes else "not_found",
        "message": None if best.successes else NOT_FOUND,
        "likelihood": round(best.rate, 3),
        "interval": [round(low, 3), round(high, 3)],
        "tries": best.tries,
        "style": None if isinstance(best, Road) else best.style.label,
        "reached": (
            {
                "map": closest.reached_map,
                "maps": len(stage.maps),
                "enemy_left": round(closest.enemy_left, 3),
            }
            if closest is not None
            else None
        ),
        "team": _team(lineup[0], roster),
        "teams": [_team(p, roster) for p in lineup] if len(lineup) > 1 else None,
        "median_turns": _median([r.turns for r in best.runs if r.won]),
        "depends_on": _depends_on(best, stage, condition),
        "showcase": {
            "won": showcase.won,
            "turns": showcase.turns,
            "max_health": showcase.max_health,
            "roster": showcase.roster,
            "frames": _instructions(showcase),
            "teams_by_map": [i + 1 for i in showcase.squad_maps]
            if len(lineup) > 1
            else None,
        },
        "assumptions": list(UNVERIFIED),
    }
    if best.rate < ADVISE_BELOW:
        report["recommendations"] = recommend(
            stage,
            roster,
            catalogue,
            condition,
            helper_choice,
            tries,
            seed,
            table,
            teams,
            baseline=best.rate,
        )
    return report


def _team(plan: Plan, roster: Roster) -> dict:
    return {
        "front": [_describe(c) for c in plan.front],
        "helper": _describe(plan.helper) if plan.helper else None,
        "back": [_describe(c) for c in plan.back],
        "cost": plan.cost,
        "cost_limit": roster.team_cost_limit,
    }


def _attempt(
    best: Plan | Road,
    stage: Stage,
    rng: random.Random,
    objective: ConditionKind | None,
    *,
    record: bool = False,
) -> Run:
    if isinstance(best, Road):
        return play_road(stage, best.lineup(), rng, record=record, objective=objective)
    front, back = best.members()
    return play_stage(
        stage, front, back, rng, record=record, objective=objective, style=best.style
    )


def _best_road(
    choices: list[Choice],
    helper: Choice | None,
    stage: Stage,
    limit: int,
    condition: ClearCondition | None,
    teams: int,
    leads: list[Plan],
    tries: int,
    seed: int,
    progress,
) -> Road:
    """Separate teams from separate copies: a few leads, each filled out greedily."""
    roads = []
    for lead in leads[:FINALISTS]:
        chosen = [Plan(front=lead.front, back=lead.back, helper=lead.helper)]
        used = set(lead.copies)
        while len(chosen) < teams:
            rest = [c for c in choices if c.copy not in used]
            following = shortlist(rest, helper, stage, limit, condition)
            if not following:
                break
            chosen.append(following[0])
            used |= following[0].copies
        roads.append(Road(plans=chosen))
    objective = condition.kind if condition else None
    for n, road in enumerate(roads):
        for k in range(tries):
            run = _attempt(road, stage, random.Random(seed * 7919 + k), objective)
            road.runs.append(run)
            road.successes += _satisfied(run, road, condition)
        if progress:
            progress(n + 1, len(roads))
    return max(roads, key=_rank)


def _median(values: list[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    return (
        float(ordered[middle])
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2
    )


def _mean_turns(plan: Plan) -> float:
    wins = [r.turns for r in plan.runs if r.won]
    return sum(wins) / len(wins) if wins else math.inf


def _progress(plan: Plan | Road) -> float:
    return sum(r.progress for r in plan.runs) / len(plan.runs) if plan.runs else 0.0


def _rank(plan: Plan | Road) -> tuple[float, float, float]:
    """Clear rate first; among teams that clear equally often (often never, on the
    hardest stages), the one that gets closest; then the fastest."""
    return (plan.rate, round(_progress(plan), 3), -_mean_turns(plan))


def recommend(
    stage: Stage,
    roster: Roster,
    catalogue: dict[int, Unit],
    condition: ClearCondition | None,
    helper: Choice | None,
    tries: int,
    seed: int,
    table: Boosts | None = None,
    teams: int = 1,
    baseline: float = 0.0,
) -> list[dict]:
    """The least grinding that would raise the clear rate above `baseline`,
    cheapest first. Steps that leave it no better are dropped."""
    table = table or {}
    elements = _enemy_elements(stage)
    ideas: list[tuple[int, str, Roster]] = []

    def strength(unit: Unit) -> float:
        return power(
            _boosted(Choice(unit=unit, level=unit.max_level, cost=0), table), elements
        )

    # Levelling something already owned is the least grinding there is; limit
    # breaking past the normal cap, then unlocking abilities, come next.
    under = [
        (i, o, catalogue[o.unit_id])
        for i, o in enumerate(roster.units)
        if o.unit_id in catalogue
        and _allowed(catalogue[o.unit_id], condition, o.cost(catalogue[o.unit_id]))
        and o.level < catalogue[o.unit_id].max_level_limit_break
    ]
    under.sort(key=lambda t: -strength(t[2]))
    for index, owned, unit in under[:ADVICE_STEPS]:
        changed = roster.model_copy(deep=True)
        if owned.level < unit.max_level:
            changed.units[index].level = unit.max_level
            text = f"Level {unit.name} '{unit.title}' from {owned.level} to {unit.max_level}"
            ideas.append((1, text, changed))
        else:
            changed.units[index].level = unit.max_level_limit_break
            text = (
                f"Limit break {unit.name} '{unit.title}' from level {owned.level}"
                f" to {unit.max_level_limit_break}"
            )
            ideas.append((2, text, changed))

    locked = [
        (i, o, catalogue[o.unit_id])
        for i, o in enumerate(roster.units)
        if o.unit_id in catalogue
        and _allowed(catalogue[o.unit_id], condition, o.cost(catalogue[o.unit_id]))
        and o.unlocked_count(catalogue[o.unit_id]) < len(catalogue[o.unit_id].abilities)
    ]
    locked.sort(key=lambda t: -strength(t[2]))
    for index, owned, unit in locked[:ADVICE_STEPS]:
        changed = roster.model_copy(deep=True)
        changed.units[index].dupes = len(unit.abilities)
        changed.units[index].abilities_unlocked = []
        text = (
            f"Unlock all {len(unit.abilities)} abilities on {unit.name} '{unit.title}'"
        )
        ideas.append((2, text, changed))

    owned_ids = {o.unit_id for o in roster.units}
    wanted = sorted(
        (
            u
            for u in catalogue.values()
            if u.in_revival
            and u.rarity >= 5
            and u.levels
            and u.unit_id not in owned_ids
            and _allowed(u, condition, u.cost)
        ),
        key=lambda u: -strength(u),
    )
    for unit in wanted[:ADVICE_STEPS]:
        changed = roster.model_copy(deep=True)
        changed.units.append(OwnedUnit(unit_id=unit.unit_id, level=unit.max_level))
        featured = table.get((unit.name, unit.title))
        note = (
            f", featured here: {featured[0]:g}x health, {featured[1]:g}x strength"
            if featured
            else ""
        )
        step = (
            f"Get {unit.name} '{unit.title}' ({unit.rarity}★, {unit.element}{note})"
            f" and level it to {unit.max_level}"
        )
        ideas.append((3, step, changed))

    results = []
    for effort, text, changed in ideas:
        choices = _choices(changed, catalogue, table)
        plans = shortlist(choices, helper, stage, changed.team_cost_limit, condition)
        if not plans:
            continue
        if teams > 1:
            trial = _best_road(
                choices,
                helper,
                stage,
                changed.team_cost_limit,
                condition,
                teams,
                plans,
                max(6, tries // 3),
                seed + 3,
                None,
            )
        else:
            # The strongest-looking team isn't always the winner; try a few.
            for plan in plans[:ADVICE_TEAMS]:
                _play(plan, stage, max(6, tries // 4), seed + 3, condition)
            trial = max(plans[:ADVICE_TEAMS], key=_rank)
        # Only advice that actually moves the simulated clear rate is worth giving.
        if trial.rate <= baseline + ADVICE_MARGIN:
            continue
        results.append(
            {"step": text, "effort": effort, "likelihood": round(trial.rate, 3)}
        )
    results.sort(key=lambda r: (r["likelihood"] < 0.5, r["effort"], -r["likelihood"]))
    return results
