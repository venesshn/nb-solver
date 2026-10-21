"""Play a whole stage with a given team, map by map and wave by wave.

The engine resolves one action at a time; this decides what each of the
player's units does, sets out the battlefield, and moves on when a wave or map
is cleared. Where the game's numbers are not published, the guess is named
below and listed in UNVERIFIED so the site can say so.
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field

from nbsolver.battle import (
    BattleState,
    Event,
    Fighter,
    Order,
    Side,
    Team,
    enemy_fighter,
    take_turn,
)
from nbsolver.combat import damage, damage_colour
from nbsolver.effects import Effect, EffectKind, EffectMode
from nbsolver.enums import AttackRange
from nbsolver.missions import BattleMap, EnemyStats, Stage
from nbsolver.models import Jutsu, OwnedUnit, Unit

Position = tuple[float, float]

# How far a unit may travel before it acts, in map tiles.
MOVE_REACH = 3.0
# How close it must then be to hit something, by its attack range.
ATTACK_REACH = {
    AttackRange.SHORT: 1.5,
    AttackRange.MID: 2.5,
    AttackRange.LONG: 3.5,
    AttackRange.VAST: 5.0,
}
# A multi-target jutsu catches enemies this close to its main target.
SPLASH = 2.5
# Long enough for any real clear; anything slower is treated as a loss.
MAX_ACTIONS = 400

UNVERIFIED = (
    "Movement and attack distances are estimates, not published values.",
    "Enemies stay where they spawn; the game moves some of them.",
    "Multi-target jutsu catch enemies near the main target; real shapes vary.",
    "Support units add health and buddy chakra but are never switched in.",
    (
        "Abilities unlocked by duplicates are not applied; field and buddy skills"
        " apply only where their wording is understood."
    ),
    (
        "Combination attacks join when an ally stands within its own attack range"
        " of the target; the game's exact joining rule is not published."
    ),
    "Reaction branches and counter-attacks are not simulated.",
)

TARGETS_RE = re.compile(r"(\d+)\s*enem", re.IGNORECASE)
ALL_RE = re.compile(r"\ball enemies\b", re.IGNORECASE)
HEAL_FLAT_RE = re.compile(
    r"(?:restores?|recovers?)[^.]*?([\d,]{3,})\s*HP", re.IGNORECASE
)
HEAL_PERCENT_RE = re.compile(
    r"(?:restores?|recovers?)[^.]*?(\d+)%\s*of\s*(?:max(?:imum)?\s*)?(?:health|HP)",
    re.IGNORECASE,
)
BOOST_PERCENT_RE = re.compile(r"attack boost of (\d+)%", re.IGNORECASE)


@dataclass
class Move:
    """A jutsu as the policy needs it: cost, punch, reach and side effects."""

    name: str
    chakra: int
    multiplier: float
    targets: int
    inflicts: list[Effect] = field(default_factory=list)
    grants: list[Effect] = field(default_factory=list)
    heal_flat: float = 0.0
    heal_percent: float = 0.0

    @property
    def strikes(self) -> bool:
        return self.multiplier > 0


def parse_move(jutsu: Jutsu | None) -> Move | None:
    if jutsu is None or jutsu.chakra is None:
        return None
    text = jutsu.description or ""
    effects = jutsu.effects.effects
    grants = []
    for effect in effects:
        if effect.mode is not EffectMode.GRANT or effect.kind in (
            EffectKind.HEALTH_RECOVERY,
            EffectKind.CHAKRA_RECOVERY,
        ):
            continue
        if (
            effect.kind == EffectKind.ATTACK_BOOST
            and effect.magnitude is None
            and effect.tier is None
            and (found := BOOST_PERCENT_RE.search(text))
        ):
            effect = effect.model_copy(update={"magnitude": float(found.group(1))})
        grants.append(effect)
    targets = 99 if ALL_RE.search(text) else 1
    if found := TARGETS_RE.search(text):
        targets = int(found.group(1))
    flat = HEAL_FLAT_RE.search(text)
    percent = HEAL_PERCENT_RE.search(text)
    return Move(
        name=jutsu.name,
        chakra=jutsu.chakra,
        multiplier=jutsu.multiplier or 0.0,
        targets=max(1, targets),
        inflicts=[e for e in effects if e.mode is EffectMode.INFLICT],
        grants=grants,
        heal_flat=float(flat.group(1).replace(",", "")) if flat else 0.0,
        heal_percent=float(percent.group(1)) if percent else 0.0,
    )


@dataclass
class Member:
    """One unit on the player's team at the level the player actually has it."""

    key: str
    unit: Unit
    level: int
    helper: bool = False
    copy: int | None = None

    @property
    def stats(self):
        return self.unit.stats_at(self.level)

    @property
    def ninjutsu(self) -> Move | None:
        return parse_move(self.unit.ninjutsu)

    @property
    def secret(self) -> Move | None:
        return parse_move(self.unit.secret_technique)

    @property
    def reach(self) -> float:
        return ATTACK_REACH.get(self.unit.range or AttackRange.SHORT, 1.5)

    @property
    def label(self) -> str:
        tag = " (helper)" if self.helper else ""
        return f"{self.unit.name} '{self.unit.title}'{tag}"


def member_for(
    owned: OwnedUnit, unit: Unit, key: str, copy: int | None = None
) -> Member:
    return Member(key=key, unit=unit, level=owned.level, copy=copy)


def helper_member(unit: Unit, key: str = "helper") -> Member:
    """Friends' units are assumed at their normal maximum level, unbroken."""
    return Member(key=key, unit=unit, level=unit.max_level, helper=True)


def _fighter(member: Member) -> Fighter:
    stats = member.stats
    ninjutsu = member.ninjutsu
    return Fighter(
        key=member.key,
        name=member.label,
        side=Side.PLAYER,
        element=member.unit.element,
        attack=stats.attack,
        max_health=stats.health,
        health=stats.health,
        # Every unit enters a battle one bar short of its ninjutsu.
        chakra=max(0, (ninjutsu.chakra if ninjutsu else 1) - 1),
        attack_range=str(member.unit.range or AttackRange.SHORT),
        reach=member.reach,
    )


def _supporting_effects(member: Member) -> list[Effect]:
    """A support's buddy skill, as lasting effects on the unit it backs."""
    skill = member.unit.buddy_skill
    if skill is None:
        return []
    return [
        e.model_copy(update={"duration": None})
        for e in skill.effects.effects
        if e.mode in (EffectMode.GRANT, EffectMode.RESIST)
    ]


def build_team(front: list[Member], back: list[Member | None]) -> Team:
    members = [_fighter(m) for m in front]
    pairs = []
    for index, partner in enumerate(back):
        if partner is None or index >= len(front):
            continue
        fighter = _fighter(partner)
        members.append(fighter)
        pairs.append((front[index].key, partner.key))
        for effect in _supporting_effects(partner):
            members[index].gain(effect)
    team = Team(members=members, pairs=pairs, on_field=[m.key for m in front])
    team.health = team.max_health
    return team


def _tile(tile) -> Position:
    return (float(tile.column), float(tile.row))


def _player_spots(battle_map: BattleMap, count: int) -> list[Position]:
    grid = battle_map.grid
    starts = [_tile(t) for t in grid.player_starts] if grid else []
    columns = grid.columns if grid and grid.columns else 7
    rows = grid.rows if grid and grid.rows else 7
    spots = list(starts)
    while len(spots) < count:
        k = len(spots)
        spots.append((1.0 + (k * 2) % max(columns - 1, 1), float(rows - 1)))
    return spots[:count]


def _waves(battle_map: BattleMap, entries: list[EnemyStats]) -> list[list[EnemyStats]]:
    sets = battle_map.sets
    waves = sets[0].waves if sets else []
    if len(waves) < 2:
        return [entries]
    out, start = [], 0
    for wave in waves:
        rows = wave.rows or 0
        out.append(entries[start : start + rows])
        start += rows
    if start < len(entries):
        out[-1].extend(entries[start:])
    return [w for w in out if w]


def _spawn(battle_map: BattleMap, wave: list[EnemyStats], prefix: str) -> list[Fighter]:
    grid = battle_map.grid
    columns = grid.columns if grid and grid.columns else 7
    used: dict[int, int] = {}
    fighters = []
    for stats in wave:
        for _ in range(max(1, stats.count)):
            tiles = (
                grid.tiles_for(stats.spawn_group) if grid and stats.spawn_group else []
            )
            taken = used.get(stats.spawn_group or -1, 0)
            used[stats.spawn_group or -1] = taken + 1
            if tiles:
                tile = tiles[taken % len(tiles)]
                position = _tile(tile)
                if taken >= len(tiles):
                    position = (position[0] + 0.5 * (taken // len(tiles)), position[1])
            else:
                k = len(fighters)
                position = (float(k % columns), float(k // columns))
            key = f"{prefix}e{len(fighters) + 1}"
            fighter = enemy_fighter(stats, key, position)
            fighter.attack_interval = 3
            fighter.countdown = 3 if fighter.ai is None else None
            fighters.append(fighter)
    return fighters


def _bosses(fighters: list[Fighter], wave: list[EnemyStats]) -> set[str]:
    by_name = {s.name for s in wave if s.role == "Boss" or (not s.role and s.is_boss)}
    return {f.key for f in fighters if f.name in by_name}


@dataclass
class Frame:
    """What the grid looks like after one action, for playback."""

    turn: int
    map: int
    wave: int
    actor: str
    instruction: str
    events: list[dict]
    positions: dict[str, Position]
    enemy_health: dict[str, int]
    team_health: int


@dataclass
class Run:
    won: bool
    turns: int
    team_health: int
    max_health: int
    reached_map: int
    sets_rolled: list[int]
    finished_by_jutsu: bool = False
    ailments_taken: int = 0
    frames: list[Frame] = field(default_factory=list)
    roster: dict[str, dict] = field(default_factory=dict)


def _estimate(attacker: Fighter, target: Fighter, multiplier: float) -> int:
    reduction = sum(
        e.magnitude or 0.0 for e in target.of_kind(EffectKind.DAMAGE_REDUCTION)
    )
    return damage(
        attacker.attack,
        multiplier,
        attacker.current_element,
        target.current_element,
        flat_attack_boost=attacker.flat_attack_boost,
        attack_boost=attacker.attack_boost,
        attack_weakened=attacker.attack_weakened,
        other_bonuses=attacker.other_bonuses,
        damage_reduction=min(reduction, 100.0) / 100,
        defense=target.defense,
    )


def _approach(start: Position, goal: Position, stop_short: float) -> Position:
    """Walk toward `goal`, stopping `stop_short` away, never past MOVE_REACH."""
    span = math.dist(start, goal)
    travel = min(MOVE_REACH, max(0.0, span - stop_short))
    if span == 0 or travel == 0:
        return start
    ratio = travel / span
    return (
        round(start[0] + (goal[0] - start[0]) * ratio, 2),
        round(start[1] + (goal[1] - start[1]) * ratio, 2),
    )


def _priority(target: Fighter, bosses: set[str]) -> float:
    urgency = 0.0
    if target.countdown is not None:
        urgency = 1.0 / max(1, target.countdown)
    return (2.0 if target.key in bosses else 0.0) + urgency


def decide(state: BattleState, member: Member, bosses: set[str]) -> tuple[Order, str]:
    """Pick the best affordable action, and say it the way a player would."""
    actor = state.team.member(member.key)
    living = state.living_enemies
    if actor is None or not living:
        return Order(fighter=member.key), "waits"

    reach = MOVE_REACH + member.reach
    in_range = [e for e in living if math.dist(actor.position, e.position) <= reach]
    sealed = actor.has(EffectKind.JUTSU_SEAL, EffectMode.INFLICT)
    options: list[tuple[str, Move | None]] = [("attack", None)]
    if not sealed:
        for kind, move in (("ninjutsu", member.ninjutsu), ("secret", member.secret)):
            if move is not None and actor.chakra >= move.chakra:
                options.append((kind, move))

    # A heal is worth casting once the pool has taken a real beating.
    wounded = state.team.health < 0.5 * state.team.max_health
    for kind, move in options:
        if (
            move
            and (move.heal_flat or move.heal_percent)
            and wounded
            and not move.strikes
        ):
            amount = move.heal_flat + state.team.max_health * move.heal_percent / 100
            order = Order(
                fighter=member.key,
                jutsu=True,
                chakra_cost=move.chakra,
                heal=amount,
                grants=move.grants,
                label=move.name,
            )
            return order, f"uses {kind} {move.name} to heal the team"

    if not in_range:
        nearest = min(living, key=lambda e: math.dist(actor.position, e.position))
        spot = _approach(actor.position, nearest.position, member.reach)
        return (
            Order(fighter=member.key, move_to=spot),
            f"moves to {spot} toward {nearest.name} and stalls (out of reach)",
        )

    best: tuple[float, Order, str] | None = None
    for target in in_range:
        for kind, move in options:
            multiplier = move.multiplier if move else 1.0
            if multiplier <= 0:
                continue
            splash: list[Fighter] = []
            if move and move.targets > 1:
                others = sorted(
                    (e for e in living if e is not target),
                    key=lambda e: math.dist(e.position, target.position),
                )
                limit = move.targets - 1
                splash = [
                    e
                    for e in others
                    if move.targets >= 99
                    or math.dist(e.position, target.position) <= SPLASH
                ][:limit]
            value = 0.0
            for hit in [target, *splash]:
                dealt = _estimate(actor, hit, multiplier)
                value += min(dealt, hit.health) / max(1, hit.max_health)
                if dealt >= hit.health:
                    value += 1.0 + _priority(hit, bosses)
            value += 0.25 * _priority(target, bosses)
            # Chakra spent now is chakra not there for the boss.
            value -= 0.04 * (move.chakra if move else 0)
            if best is None or value > best[0]:
                spot = _approach(actor.position, target.position, member.reach * 0.9)
                order = Order(
                    fighter=member.key,
                    move_to=spot,
                    target=target.key,
                    multiplier=multiplier,
                    jutsu=move is not None,
                    chakra_cost=move.chakra if move else 0.0,
                    also=[e.key for e in splash],
                    inflicts=move.inflicts if move else [],
                    grants=move.grants if move else [],
                    label=move.name if move else "",
                )
                what = f"{kind} {move.name}" if move else "a normal attack"
                colour = damage_colour(actor.current_element, target.current_element)
                extra = f" (also hits {len(splash)} more)" if splash else ""
                best = (
                    value,
                    order,
                    f"moves to {spot} and uses {what} on {target.name}{extra} [{colour}]",
                )
    assert best is not None
    return best[1], best[2]


def _speed_order(front: list[Member]) -> list[Member]:
    return sorted(front, key=lambda m: -(m.stats.speed or m.unit.speed))


def play_stage(
    stage: Stage,
    front: list[Member],
    back: list[Member | None],
    rng: random.Random,
    *,
    record: bool = False,
    forced_sets: list[int] | None = None,
) -> Run:
    """One full attempt at the stage: every map in order, sharing one health pool."""
    team = build_team(front, back)
    state = BattleState(team=team)
    run = Run(
        won=False,
        turns=0,
        team_health=team.health,
        max_health=team.max_health,
        reached_map=0,
        sets_rolled=[],
    )
    if record:
        run.roster = {
            m.key: {
                "name": m.label,
                "element": m.unit.element,
                "level": m.level,
                "front": m in front,
            }
            for m in [*front, *(b for b in back if b)]
        }
    last_jutsu = False

    for number, battle_map in enumerate(stage.maps, start=1):
        run.reached_map = number
        weights = [s.weight for s in battle_map.sets] or [1.0]
        if forced_sets and len(forced_sets) >= number:
            chosen = forced_sets[number - 1]
        else:
            chosen = rng.choices(range(len(weights)), weights=weights)[0]
        run.sets_rolled.append(chosen)
        entries = battle_map.sets[chosen].enemies if battle_map.sets else []
        for key, spot in zip(team.on_field, _player_spots(battle_map, len(front))):
            team.member(key).position = spot

        waves = _waves(battle_map, entries)
        boss_rule = "boss" in (battle_map.clear or "").lower()
        for wave_number, wave in enumerate(waves, start=1):
            state.enemies = _spawn(battle_map, wave, f"m{number}w{wave_number}")
            bosses = _bosses(state.enemies, wave)
            if record:
                for e in state.enemies:
                    run.roster[e.key] = {
                        "name": e.name,
                        "element": e.element,
                        "max_health": e.max_health,
                        "boss": e.key in bosses,
                        "enemy": True,
                    }
            while True:
                for member in _speed_order(front):
                    if state.over or (boss_rule and bosses and _cleared(state, bosses)):
                        break
                    order, said = decide(state, member, bosses)
                    events = take_turn(state, order, rng)
                    last_jutsu = order.jutsu and any(e.kind == "defeat" for e in events)
                    run.ailments_taken += sum(
                        1
                        for e in events
                        if e.kind == "effect"
                        and (f := state.fighter(e.target)) is not None
                        and f.side is Side.PLAYER
                        and e.actor != e.target
                    )
                    if record:
                        run.frames.append(
                            _frame(state, number, wave_number, member, said, events)
                        )
                    if state.turn >= MAX_ACTIONS:
                        break
                if state.team.wiped or state.turn >= MAX_ACTIONS:
                    run.turns = state.turn
                    run.team_health = state.team.health
                    return run
                if state.cleared or (boss_rule and bosses and _cleared(state, bosses)):
                    break
            if boss_rule and bosses and _cleared(state, bosses):
                break
    run.won = True
    run.turns = state.turn
    run.team_health = state.team.health
    run.finished_by_jutsu = last_jutsu
    return run


def _cleared(state: BattleState, bosses: set[str]) -> bool:
    return all(e.defeated for e in state.enemies if e.key in bosses)


def _frame(
    state: BattleState,
    map_number: int,
    wave: int,
    member: Member,
    said: str,
    events: list[Event],
) -> Frame:
    fighters = [*state.team.fielded(), *state.enemies]
    return Frame(
        turn=state.turn,
        map=map_number,
        wave=wave,
        actor=member.key,
        instruction=f"{member.label} {said}",
        events=[e.model_dump(mode="json", exclude_defaults=True) for e in events],
        positions={f.key: f.position for f in fighters if not f.defeated},
        enemy_health={e.key: e.health for e in state.enemies},
        team_health=state.team.health,
    )
