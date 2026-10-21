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
from nbsolver.missions import ClearCondition, ConditionKind, Stage
from nbsolver.models import OwnedUnit, Unit
from nbsolver.roster import Roster
from nbsolver.simulate import UNVERIFIED, Member, Run, play_stage

IMPOSSIBLE = "Not possible to complete - keep grinding!"
NOT_FOUND = "No winning strategy found."
FRONT_SLOTS = 3
BACK_SLOTS = 4
SHORTLIST = 10
FINALISTS = 3
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

    def member(self, key: str) -> Member:
        return Member(
            key=key,
            unit=self.unit,
            level=self.level,
            helper=self.helper,
            copy=self.copy,
            abilities=self.abilities,
        )


@dataclass
class Plan:
    front: list[Choice]
    back: list[Choice]
    helper: Choice | None
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
        return sum(c.cost for c in [*self.front, *self.back])

    def members(self) -> tuple[list[Member], list[Member | None]]:
        front = [c.member(f"p{i + 1}") for i, c in enumerate(self.front)]
        if self.helper is not None:
            front.append(self.helper.member("helper"))
        back: list[Member | None] = [
            c.member(f"s{i + 1}") for i, c in enumerate(self.back)
        ]
        return front, back


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


def _allowed(unit: Unit, condition: ClearCondition | None) -> bool:
    if condition is None:
        return True
    if condition.kind == ConditionKind.ELEMENT_ONLY:
        return unit.element == condition.element
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
    return stats.attack * affinity * (1 + 0.35 * jutsu) + 0.3 * stats.health


def _choices(roster: Roster, catalogue: dict[int, Unit]) -> list[Choice]:
    out = []
    for index, owned in enumerate(roster.units):
        unit = catalogue.get(owned.unit_id)
        if unit is None or not unit.in_revival:
            continue
        out.append(
            Choice(
                unit=unit,
                level=owned.level,
                cost=owned.cost(unit),
                copy=index,
                abilities=owned.unlocked_count(unit),
            )
        )
    return out


def pick_helper(
    catalogue: dict[int, Unit], stage: Stage, condition: ClearCondition | None
) -> Choice | None:
    elements = _enemy_elements(stage)
    pool = [
        Choice(unit=u, level=u.max_level, cost=0, helper=True)
        for u in catalogue.values()
        if u.in_revival and u.rarity >= 6 and u.levels and _allowed(u, condition)
    ]
    return max(pool, key=lambda c: power(c, elements), default=None)


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
        return plan.cost <= condition.max_cost
    return True


def _legal(plan: Plan, limit: int, condition: ClearCondition | None) -> bool:
    if plan.cost > limit:
        return False
    capped = (
        condition and condition.kind == ConditionKind.COST_CAP and condition.max_cost
    )
    if capped and plan.cost > condition.max_cost:
        return False
    if condition and condition.kind == ConditionKind.REQUIRE_UNITS:
        everyone = [*plan.front, *plan.back, *([plan.helper] if plan.helper else [])]
        if sum(_requires(c.unit, condition) for c in everyone) < (
            condition.required_count or 1
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
    pool = [c for c in choices if _allowed(c.unit, condition)]
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
    size = min(FRONT_SLOTS, len(top))
    for front in itertools.combinations(top, size):
        front = list(front)
        budget = limit - sum(c.cost for c in front)
        if (
            condition
            and condition.kind == ConditionKind.COST_CAP
            and condition.max_cost
        ):
            budget = min(budget, condition.max_cost - sum(c.cost for c in front))
        if budget < 0:
            continue
        back = _fill_back(front, pool, budget, BACK_SLOTS)
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
) -> dict:
    """The whole answer the site shows for one stage and one player."""
    if condition is not None and condition.kind in UNJUDGED:
        return {
            "status": "unsupported",
            "message": f"The objective '{condition.description}' can't be checked by the simulator yet.",
        }
    choices = _choices(roster, catalogue)
    eligible = [c for c in choices if _allowed(c.unit, condition)]
    if not eligible:
        return {
            "status": "impossible",
            "message": IMPOSSIBLE,
            "reason": "You own no unit this objective allows.",
            "recommendations": recommend(
                stage, roster, catalogue, condition, None, tries, seed
            ),
        }

    helper_choice: Choice | None = None
    if helper == "auto":
        helper_choice = pick_helper(catalogue, stage, condition)
    elif isinstance(helper, int) and helper in catalogue:
        unit = catalogue[helper]
        if _allowed(unit, condition):
            helper_choice = Choice(unit=unit, level=unit.max_level, cost=0, helper=True)

    plans = shortlist(choices, helper_choice, stage, roster.team_cost_limit, condition)
    if not plans:
        return {
            "status": "impossible",
            "message": IMPOSSIBLE,
            "reason": "No team you own fits the cost limit and this objective together.",
            "recommendations": recommend(
                stage, roster, catalogue, condition, helper_choice, tries, seed
            ),
        }

    contenders = plans[: max(FINALISTS * 3, 6)]
    for n, plan in enumerate(contenders):
        _play(plan, stage, max(6, tries // 4), seed, condition)
        if progress:
            progress(n + 1, len(contenders) + FINALISTS)
    finalists = sorted(contenders, key=lambda p: (-p.rate, _mean_turns(p)))[:FINALISTS]
    for n, plan in enumerate(finalists):
        _play(plan, stage, tries, seed + 1, condition)
        if progress:
            progress(len(contenders) + n + 1, len(contenders) + FINALISTS)
    best = max(finalists, key=lambda p: (p.rate, -_mean_turns(p)))

    low, high = wilson(best.successes, best.tries)
    front, back = best.members()
    objective = condition.kind if condition else None
    showcase = None
    for k in range(60):
        run = play_stage(
            stage,
            front,
            back,
            random.Random(10_000 + k),
            record=True,
            objective=objective,
        )
        if _satisfied(run, best, condition):
            showcase = run
            break
    if showcase is None:
        showcase = play_stage(
            stage, front, back, random.Random(10_000), record=True, objective=objective
        )

    report = {
        "status": "found" if best.successes else "not_found",
        "message": None if best.successes else NOT_FOUND,
        "likelihood": round(best.rate, 3),
        "interval": [round(low, 3), round(high, 3)],
        "tries": best.tries,
        "team": {
            "front": [_describe(c) for c in best.front],
            "helper": _describe(best.helper) if best.helper else None,
            "back": [_describe(c) for c in best.back],
            "cost": best.cost,
            "cost_limit": roster.team_cost_limit,
        },
        "median_turns": _median([r.turns for r in best.runs if r.won]),
        "depends_on": _depends_on(best, stage, condition),
        "showcase": {
            "won": showcase.won,
            "turns": showcase.turns,
            "max_health": showcase.max_health,
            "roster": showcase.roster,
            "frames": _instructions(showcase),
        },
        "assumptions": list(UNVERIFIED),
    }
    if not best.successes:
        report["recommendations"] = recommend(
            stage, roster, catalogue, condition, helper_choice, tries, seed
        )
    return report


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


def recommend(
    stage: Stage,
    roster: Roster,
    catalogue: dict[int, Unit],
    condition: ClearCondition | None,
    helper: Choice | None,
    tries: int,
    seed: int,
) -> list[dict]:
    """The least grinding that would turn this into a clear, cheapest first."""
    elements = _enemy_elements(stage)
    ideas: list[tuple[int, str, Roster]] = []

    # Levelling something already owned is the least grinding there is.
    under = [
        (i, o, catalogue[o.unit_id])
        for i, o in enumerate(roster.units)
        if o.unit_id in catalogue
        and _allowed(catalogue[o.unit_id], condition)
        and o.level < catalogue[o.unit_id].max_level
    ]
    under.sort(
        key=lambda t: -power(Choice(unit=t[2], level=t[2].max_level, cost=0), elements)
    )
    for index, owned, unit in under[:3]:
        changed = roster.model_copy(deep=True)
        changed.units[index].level = unit.max_level
        ideas.append(
            (
                1,
                f"Level {unit.name} '{unit.title}' from {owned.level} to {unit.max_level}",
                changed,
            )
        )

    owned_ids = {o.unit_id for o in roster.units}
    wanted = sorted(
        (
            u
            for u in catalogue.values()
            if u.in_revival
            and u.rarity >= 5
            and u.levels
            and u.unit_id not in owned_ids
            and _allowed(u, condition)
        ),
        key=lambda u: -power(Choice(unit=u, level=u.max_level, cost=0), elements),
    )
    for unit in wanted[:3]:
        changed = roster.model_copy(deep=True)
        changed.units.append(OwnedUnit(unit_id=unit.unit_id, level=unit.max_level))
        ideas.append(
            (
                2,
                f"Get {unit.name} '{unit.title}' ({unit.rarity}★, {unit.element}) and level it to {unit.max_level}",
                changed,
            )
        )

    results = []
    for effort, text, changed in ideas:
        plans = shortlist(
            _choices(changed, catalogue),
            helper,
            stage,
            changed.team_cost_limit,
            condition,
        )
        if not plans:
            continue
        plan = plans[0]
        _play(plan, stage, max(6, tries // 3), seed + 3, condition)
        results.append(
            {"step": text, "effort": effort, "likelihood": round(plan.rate, 3)}
        )
    results.sort(key=lambda r: (r["likelihood"] < 0.5, r["effort"], -r["likelihood"]))
    return results
