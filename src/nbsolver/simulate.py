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
from functools import cached_property

from nbsolver.battle import (
    BattleRules,
    BattleState,
    Event,
    Fighter,
    Order,
    Side,
    Team,
    enemy_fighter,
    take_turn,
)
from nbsolver.combat import COMBINATION_VALUE, damage, damage_colour, element_multiplier
from nbsolver.effects import Effect, EffectKind, EffectMode
from nbsolver.enums import AttackRange
from nbsolver.missions import BattleMap, ConditionKind, EnemyStats, Stage
from nbsolver.models import Jutsu, OwnedUnit, Unit
from nbsolver.passives import Passive, parse_passive

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
# How far an enemy closes in on its own turn.
ENEMY_STEP = 1.5
# Script-less enemies publish no rhythm; this is a guess at one.
PLAIN_INTERVAL = 3
# Hits per attack are not published; they decide when a combo passes 15. Results
# barely moved between 1 and 7 on the validation stage, so the cautious 1 stays.
ATTACK_HITS = 1
# "Perimeter Barrier" ships with no description; on record it is a 2.5x attack.
PERIMETER_BARRIER = 2.5
# Completing a map gives back half the health lost so far: measured on both map
# changes of the player's recorded e3003 clear (+378 of 756, +635 of 1270).
MAP_RESTORE = 0.5
# Long enough for any real clear; anything slower is treated as a loss.
MAX_ACTIONS = 400

UNVERIFIED = (
    "Movement and attack distances are estimates, not published values.",
    "Enemies close in 1.5 tiles on their own turn; the game's step is not published.",
    "Enemies with no published script attack every 3 turns, alternating with their skill.",
    "Multi-target jutsu catch enemies near the main target; real shapes vary.",
    (
        "Field skills use the weakest end of their range, as if allies stood at the"
        " edge of the circle."
    ),
    (
        "Abilities count only as far as your box says they are unlocked; a friend's"
        " helper is assumed to have none."
    ),
    (
        "Combination attacks join when an ally stands within its own attack range"
        " of the target; the game's exact joining rule is not published."
    ),
    "A support switches in only when the unit in front of it is immobilised.",
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
PERCENT_HIT_RE = re.compile(
    r"deals?\s+(\d+(?:\.\d+)?)%\s+of\s+(?:the\s+)?(?:targeted\s+)?(?:enemy's|target's|their)\s+remaining health",
    re.IGNORECASE,
)
SELF_COST_RE = re.compile(
    r"depletes? your remaining health by (\d+(?:\.\d+)?)%", re.IGNORECASE
)
CHAKRA_GAIN_RE = re.compile(r"restores (?:your )?chakra gauge by (\d+)", re.IGNORECASE)
SELF_AILMENT_RE = re.compile(
    r"(?:gives|inflicts) you(?: with)? ([a-z ]+?)(?: \(tier (\d)\))? for (\d+) turn",
    re.IGNORECASE,
)
SELF_AILMENTS = {
    "slip damage": EffectKind.SLIP_DAMAGE,
    "immobiliz": EffectKind.IMMOBILIZATION,
    "jutsu seal": EffectKind.JUTSU_SEAL,
    "attack reduc": EffectKind.ATTACK_REDUCTION,
}


def _self_ailments(text: str) -> list[Effect]:
    found = []
    for words, tier, turns in SELF_AILMENT_RE.findall(text):
        for key, kind in SELF_AILMENTS.items():
            if key in words.lower():
                found.append(
                    Effect(
                        kind=kind,
                        mode=EffectMode.INFLICT,
                        duration=int(turns),
                        tier=int(tier) if tier else 1,
                        targets_caster=True,
                        source=text,
                    )
                )
    return found


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
    percent: float = 0.0
    self_cost: float = 0.0
    secret: bool = False
    chakra_gain: float = 0.0
    self_inflicts: list[Effect] = field(default_factory=list)

    @property
    def strikes(self) -> bool:
        return self.multiplier > 0 or self.percent > 0

    @property
    def boost(self) -> float:
        """Attack boost percentage it gives its user, if any."""
        return max(
            (
                e.magnitude or 0.0
                for e in self.grants
                if e.kind == EffectKind.ATTACK_BOOST
            ),
            default=0.0,
        )


def parse_move(jutsu: Jutsu | None, *, secret: bool = False) -> Move | None:
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
    share = PERCENT_HIT_RE.search(text)
    cost = SELF_COST_RE.search(text)
    gain = CHAKRA_GAIN_RE.search(text)
    return Move(
        name=jutsu.name,
        chakra=jutsu.chakra,
        multiplier=jutsu.multiplier or 0.0,
        targets=max(1, targets),
        inflicts=[
            e for e in effects if e.mode is EffectMode.INFLICT and not e.targets_caster
        ],
        grants=grants,
        heal_flat=float(flat.group(1).replace(",", "")) if flat else 0.0,
        heal_percent=float(percent.group(1)) if percent else 0.0,
        percent=float(share.group(1)) if share else 0.0,
        self_cost=float(cost.group(1)) if cost else 0.0,
        secret=secret,
        chakra_gain=float(gain.group(1)) if gain else 0.0,
        self_inflicts=_self_ailments(text),
    )


@dataclass
class Member:
    """One unit on the player's team at the level the player actually has it."""

    key: str
    unit: Unit
    level: int
    helper: bool = False
    copy: int | None = None
    abilities: int = 0
    health_x: float = 1.0
    attack_x: float = 1.0

    @cached_property
    def stats(self):
        return self.unit.stats_at(self.level)

    @cached_property
    def ninjutsu(self) -> Move | None:
        return parse_move(self.unit.ninjutsu)

    @cached_property
    def secret(self) -> Move | None:
        return parse_move(self.unit.secret_technique, secret=True)

    @property
    def reach(self) -> float:
        return ATTACK_REACH.get(self.unit.range or AttackRange.SHORT, 1.5)

    @property
    def label(self) -> str:
        tag = " (helper)" if self.helper else ""
        return f"{self.unit.name} '{self.unit.title}'{tag}"

    @cached_property
    def own_passive(self) -> Passive:
        total = Passive()
        for ability in self.unit.abilities[: self.abilities]:
            total.merge(parse_passive(ability.description))
        return total

    @cached_property
    def field_passive(self) -> Passive:
        skill = self.unit.field_skill
        return parse_passive(skill.description) if skill else Passive()

    @cached_property
    def buddy_passive(self) -> Passive:
        skill = self.unit.buddy_skill
        return parse_passive(skill.description) if skill else Passive()

    def speed(self) -> float:
        return (self.stats.speed or self.unit.speed) + self.own_passive.speed


def member_for(
    owned: OwnedUnit, unit: Unit, key: str, copy: int | None = None
) -> Member:
    return Member(
        key=key,
        unit=unit,
        level=owned.level,
        copy=copy,
        abilities=owned.unlocked_count(unit),
    )


def helper_member(unit: Unit, key: str = "helper") -> Member:
    """Friends' units are assumed at their normal maximum level, unbroken."""
    return Member(key=key, unit=unit, level=unit.max_level, helper=True)


def _apply(fighter: Fighter, passive: Passive, *, element_bonus: bool = True) -> None:
    fighter.flat_attack_boost += passive.flat_attack
    if element_bonus:
        fighter.flat_attack_boost += passive.element_attack.get(
            str(fighter.element), 0.0
        )
    fighter.regen += passive.regen
    fighter.counter_chance = min(100.0, fighter.counter_chance + passive.counter)
    fighter.combo_boost *= passive.combo_boost
    fighter.chakra_cut += passive.chakra_cut
    fighter.ninjutsu_cut = passive.ninjutsu_cut or fighter.ninjutsu_cut
    fighter.secret_cut = passive.secret_cut or fighter.secret_cut
    fighter.chakra_on_hit = passive.chakra_on_hit or fighter.chakra_on_hit
    for name in ("damage_vs", "reduce_from", "inflict_boost"):
        mine = getattr(fighter, name)
        for key, value in getattr(passive, name).items():
            mine[key] = mine.get(key, 0.0) + value
    for effect in passive.effects:
        fighter.gain(effect.model_copy(update={"duration": None}))


def _fighter(member: Member) -> Fighter:
    stats = member.stats
    ninjutsu = member.ninjutsu
    own = member.own_passive
    health = round(stats.health * member.health_x) + int(own.flat_health)
    fighter = Fighter(
        key=member.key,
        name=member.label,
        side=Side.PLAYER,
        element=member.unit.element,
        attack=round(stats.attack * member.attack_x),
        max_health=health,
        health=health,
        # Every unit enters a battle one bar short of its ninjutsu.
        chakra=max(0, (ninjutsu.chakra if ninjutsu else 1) - 1),
        attack_range=str(member.unit.range or AttackRange.SHORT),
        reach=member.reach,
        hits=ATTACK_HITS,
    )
    _apply(fighter, own, element_bonus=False)
    return fighter


def build_team(front: list[Member], back: list[Member | None]) -> Team:
    fighters = [_fighter(m) for m in front]
    pairs = []
    supports = []
    for index, partner in enumerate(back):
        if partner is None or index >= len(front):
            continue
        support = _fighter(partner)
        supports.append(support)
        pairs.append((front[index].key, partner.key))
        _apply(fighters[index], partner.buddy_passive)
    # Every front unit's field skill covers the whole front line.
    for member in front:
        passive = member.field_passive
        for fighter in fighters:
            _apply(fighter, passive)
    team = Team(
        members=[*fighters, *supports], pairs=pairs, on_field=[m.key for m in front]
    )
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


def _spawn(
    battle_map: BattleMap, wave: list[EnemyStats], prefix: str
) -> tuple[list[Fighter], set[str], list[list[str]]]:
    """The wave's enemies on their spawn tiles, which of them carry drops, and
    which fighters each line of the wave became."""
    grid = battle_map.grid
    columns = grid.columns if grid and grid.columns else 7
    used: dict[int, int] = {}
    fighters = []
    carriers = set()
    keys_by_entry: list[list[str]] = []
    for stats in wave:
        keys_by_entry.append([])
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
            for technique in fighter.techniques:
                if technique.name == "Perimeter Barrier" and not technique.multiplier:
                    technique.multiplier = PERIMETER_BARRIER
            fighter.attack_interval = PLAIN_INTERVAL
            fighter.countdown = PLAIN_INTERVAL if fighter.ai is None else None
            fighters.append(fighter)
            keys_by_entry[-1].append(key)
            if stats.carries:
                carriers.add(key)
    return fighters, carriers, keys_by_entry


def _boss_plan(
    wave: list[EnemyStats], keys_by_entry: list[list[str]]
) -> tuple[set[str], dict[str, list[str]]]:
    """Who must fall to clear a boss map, and the parts each giant's head takes down.

    The map data marks bosses explicitly; only when it marks none does any enemy
    with a script count. A giant boss is listed as several same-named boss lines,
    one per part, each acting on its own; the first is its head, and beating the
    head finishes the whole giant (confirmed by the player).
    """
    marked = [i for i, s in enumerate(wave) if s.role == "Boss"]
    if not marked:
        marked = [i for i, s in enumerate(wave) if s.is_boss]
    by_name: dict[str, list[int]] = {}
    for i in marked:
        by_name.setdefault(wave[i].name, []).append(i)
    bosses: set[str] = set()
    parts: dict[str, list[str]] = {}
    for lines in by_name.values():
        head = keys_by_entry[lines[0]]
        bosses.update(head)
        if len(lines) > 1 and all(wave[i].count <= 1 for i in lines):
            parts[head[0]] = [k for i in lines[1:] for k in keys_by_entry[i]]
        else:
            for i in lines[1:]:
                bosses.update(keys_by_entry[i])
    return bosses, parts


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
    finished_by_combination: bool = False
    ailments_taken: int = 0
    drops_seen: int = 0
    drops_taken: int = 0
    # Which team fought each map, when several teams share the road.
    squad_maps: list[int] = field(default_factory=list)
    frames: list[Frame] = field(default_factory=list)
    roster: dict[str, dict] = field(default_factory=dict)

    @property
    def all_drops(self) -> bool:
        return self.drops_taken >= self.drops_seen


def _estimate(attacker: Fighter, target: Fighter, multiplier: float) -> int:
    reduction = sum(
        e.magnitude or 0.0
        for e in target.of_kind(EffectKind.DAMAGE_REDUCTION)
        if e.element is None or e.element == attacker.current_element
    )
    reduction += target.reduce_from.get(str(attacker.current_element), 0.0)
    favoured = 1 + attacker.damage_vs.get(str(target.current_element), 0.0) / 100
    return damage(
        attacker.attack,
        multiplier,
        attacker.current_element,
        target.current_element,
        flat_attack_boost=attacker.flat_attack_boost,
        attack_boost=attacker.attack_boost,
        attack_weakened=attacker.attack_weakened,
        other_bonuses=attacker.other_bonuses * favoured,
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


def describe_move(start: Position, end: Position) -> str:
    """How a player would say it: rows grow downward, as on the phone screen."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    span = math.hypot(dx, dy)
    if span < 0.3:
        return "stays put"
    vertical = "up" if dy < -0.3 else "down" if dy > 0.3 else ""
    horizontal = "left" if dx < -0.3 else "right" if dx > 0.3 else ""
    way = "-".join(p for p in (vertical, horizontal) if p)
    tiles = "1 tile" if round(span) <= 1 else f"{round(span)} tiles"
    return f"moves {tiles} {way}"


def _dealt(actor: Fighter, target: Fighter, move: Move | None) -> int:
    if move is not None and move.percent:
        # A percentage attack stops at 1 HP, so it never finishes anyone.
        return max(
            0, min(math.ceil(target.health * move.percent / 100), target.health - 1)
        )
    return _estimate(actor, target, move.multiplier if move else 1.0)


def decide(
    state: BattleState,
    member: Member,
    bosses: set[str],
    hold: set[str] | None = None,
) -> tuple[Order, str]:
    """Pick the best affordable action, and say it the way a player would.

    `hold` lists enemies not to finish off yet, e.g. a boss whose defeat would
    end the map before every drop has been collected.
    """
    actor = state.team.member(member.key)
    living = state.living_enemies
    if actor is None or not living:
        return Order(fighter=member.key), "waits"
    hold = hold or set()

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
                secret=move.secret,
                chakra_cost=move.chakra,
                heal=amount,
                grants=move.grants,
                label=move.name,
            )
            return order, f"uses {kind} {move.name} to heal the team"

    # A power-up pays for itself when there is plenty left to hit and none is running.
    boosted = actor.has(EffectKind.ATTACK_BOOST, EffectMode.GRANT)
    remaining = sum(e.health for e in living)
    for kind, move in options:
        if (
            move
            and not move.strikes
            and move.boost >= 50
            and not boosted
            and remaining > 3 * _estimate(actor, living[0], 1.0)
        ):
            order = Order(
                fighter=member.key,
                jutsu=True,
                secret=move.secret,
                chakra_cost=move.chakra,
                grants=move.grants,
                chakra_gain=move.chakra_gain,
                self_inflicts=move.self_inflicts,
                label=move.name,
            )
            return (
                order,
                f"uses {kind} {move.name} to power up (+{move.boost:g}% attack)",
            )

    if not in_range:
        nearest = min(living, key=lambda e: math.dist(actor.position, e.position))
        spot = _approach(actor.position, nearest.position, member.reach)
        said = f"{describe_move(actor.position, spot)} toward {nearest.name} and stalls"
        return Order(fighter=member.key, move_to=spot), f"{said} (nothing in reach yet)"

    best: tuple[float, Order, str] | None = None
    for target in in_range:
        for kind, move in options:
            if move is not None and not move.strikes:
                continue
            splash: list[Fighter] = []
            if move and move.targets > 1:
                others = sorted(
                    (e for e in living if e is not target),
                    key=lambda e: math.dist(e.position, target.position),
                )
                splash = [
                    e
                    for e in others
                    if move.targets >= 99
                    or math.dist(e.position, target.position) <= SPLASH
                ][: move.targets - 1]
            value = 0.0
            spoils = False
            for hit in [target, *splash]:
                dealt = _dealt(actor, hit, move)
                value += min(dealt, hit.health) / max(1, hit.max_health)
                if dealt >= hit.health:
                    if hit.key in hold:
                        spoils = True
                    value += 1.0 + _priority(hit, bosses)
            if spoils:
                continue
            # Allies already in reach of this target will join in.
            joiners = [
                ally
                for ally in state.team.fielded()
                if ally is not actor
                and ally.can_act
                and ally.reach
                and math.dist(ally.position, target.position) <= ally.reach
            ]
            for ally in joiners:
                share = COMBINATION_VALUE.get(ally.attack_range, 0.0) * ally.combo_boost
                value += min(_estimate(ally, target, share), target.health) / max(
                    1, target.max_health
                )
            if ATTACK_HITS * (1 + len(joiners)) > state.rules.combo_hits_for_bonus:
                value += 0.3
            value += 0.25 * _priority(target, bosses)
            # Chakra spent now is chakra not there for the boss.
            value -= 0.04 * (move.chakra if move else 0)
            if move and move.self_cost:
                value -= (
                    move.self_cost
                    / 100
                    * state.team.health
                    / max(1, state.team.max_health)
                )
            if best is None or value > best[0]:
                spot = _approach(actor.position, target.position, member.reach * 0.9)
                order = Order(
                    fighter=member.key,
                    move_to=spot,
                    target=target.key,
                    hits=ATTACK_HITS,
                    multiplier=move.multiplier if move else 1.0,
                    percent=move.percent if move else 0.0,
                    self_cost=move.self_cost if move else 0.0,
                    jutsu=move is not None,
                    secret=bool(move and move.secret),
                    chakra_cost=move.chakra if move else 0.0,
                    also=[e.key for e in splash],
                    inflicts=move.inflicts if move else [],
                    grants=move.grants if move else [],
                    chakra_gain=move.chakra_gain if move else 0.0,
                    self_inflicts=move.self_inflicts if move else [],
                    label=move.name if move else "",
                )
                what = f"{kind} {move.name}" if move else "a normal attack"
                colour = damage_colour(actor.current_element, target.current_element)
                extra = f" (also hits {len(splash)} more)" if splash else ""
                advantage = {"red": "advantage", "blue": "disadvantage"}.get(
                    colour, "neutral"
                )
                said = f"{describe_move(actor.position, spot)} and uses {what} on"
                best = (value, order, f"{said} {target.name}{extra} ({advantage})")
    if best is None:
        nearest = min(living, key=lambda e: math.dist(actor.position, e.position))
        return Order(
            fighter=member.key
        ), f"holds back to keep {nearest.name}'s drop in play"
    return best[1], best[2]


def _swap_in(state: BattleState, key: str) -> str | None:
    """Send the support in when the unit in front can't act anyway."""
    fighter = state.team.member(key)
    partner = state.team.buddy(key)
    if fighter is None or partner is None or fighter.can_act or not partner.can_act:
        return None
    return partner.key if state.team.switch(key) else None


@dataclass
class Squad:
    """One team and the battle state it carries from map to map."""

    front: list[Member]
    back: list[Member | None]
    state: BattleState
    members: dict[str, Member]
    label: str = ""

    @property
    def health_share(self) -> float:
        team = self.state.team
        return team.health / team.max_health if team.max_health else 0.0

    def matchup(self, battle_map: BattleMap) -> float:
        """How well this team's front line hits the map's enemies, by element."""
        enemies = [e for s in battle_map.sets[:1] for e in s.enemies]
        total = sum(e.hp * max(1, e.count) for e in enemies) or 1
        return (
            sum(
                e.hp
                * max(1, e.count)
                * sum(element_multiplier(m.unit.element, e.element) for m in self.front)
                / max(1, len(self.front))
                for e in enemies
            )
            / total
        )


def make_squad(
    front: list[Member], back: list[Member | None], label: str = ""
) -> Squad:
    team = build_team(front, back)
    state = BattleState(team=team, rules=BattleRules(enemy_step=ENEMY_STEP))
    members = {m.key: m for m in [*front, *(b for b in back if b)]}
    return Squad(front=front, back=back, state=state, members=members, label=label)


def _new_run(squads: list[Squad], record: bool) -> Run:
    run = Run(
        won=False,
        turns=0,
        team_health=sum(s.state.team.health for s in squads),
        max_health=sum(s.state.team.max_health for s in squads),
        reached_map=0,
        sets_rolled=[],
    )
    if record:
        for squad in squads:
            for m in squad.members.values():
                run.roster[m.key] = {
                    "name": m.label,
                    "element": m.unit.element,
                    "level": m.level,
                    "front": m in squad.front,
                    "team": squad.label,
                }
    return run


def _play_map(
    squad: Squad,
    battle_map: BattleMap,
    number: int,
    run: Run,
    rng: random.Random,
    *,
    record: bool,
    forced_sets: list[int] | None,
    objective: ConditionKind | None,
    fresh: bool,
) -> bool:
    """Fight one map with one squad; False if the squad falls or runs out of time."""
    state, team, members = squad.state, squad.state.team, squad.members
    weights = [s.weight for s in battle_map.sets] or [1.0]
    if forced_sets and len(forced_sets) >= number:
        chosen = forced_sets[number - 1]
    else:
        chosen = rng.choices(range(len(weights)), weights=weights)[0]
    run.sets_rolled.append(chosen)
    entries = battle_map.sets[chosen].enemies if battle_map.sets else []
    for key, spot in zip(team.on_field, _player_spots(battle_map, len(team.on_field))):
        team.member(key).position = spot
    if not fresh:
        for key, member in members.items():
            bonus = member.own_passive.map_chakra
            if bonus:
                team.member(key).chakra += bonus

    waves = _waves(battle_map, entries)
    boss_rule = "boss" in (battle_map.clear or "").lower()
    for wave_number, wave in enumerate(waves, start=1):
        state.enemies, carriers, keys_by_entry = _spawn(
            battle_map, wave, f"m{number}w{wave_number}"
        )
        run.drops_seen += len(carriers)
        bosses, parts = _boss_plan(wave, keys_by_entry)
        if record:
            for e in state.enemies:
                run.roster[e.key] = {
                    "name": e.name,
                    "element": e.element,
                    "max_health": e.max_health,
                    "boss": e.key in bosses,
                    "drop": e.key in carriers,
                    "enemy": True,
                }
        while True:
            order_now = sorted(team.on_field, key=lambda k: -members[k].speed())
            for key in order_now:
                if state.over or (boss_rule and bosses and _cleared(state, bosses)):
                    break
                if key not in team.on_field:
                    continue
                swapped = _swap_in(state, key)
                if swapped is not None:
                    key = swapped
                member = members[key]
                hold = set()
                collecting = objective is ConditionKind.DROP_COMPLETE and boss_rule
                if collecting and any(not state.fighter(c).defeated for c in carriers):
                    hold = set(bosses)
                order, said = decide(state, member, bosses, hold)
                if swapped is not None:
                    said = f"switches in for its partner, then {said}"
                events = take_turn(state, order, rng)
                defeated = {e.target for e in events if e.kind == "defeat"}
                for head in defeated & parts.keys():
                    for key in parts[head]:
                        part = state.fighter(key)
                        if part is not None and not part.defeated:
                            part.health, part.defeated = 0, True
                            events.append(
                                Event(
                                    turn=state.turn,
                                    kind="defeat",
                                    target=key,
                                    note="head defeated",
                                )
                            )
                run.finished_by_jutsu = order.jutsu and bool(defeated)
                if defeated & bosses:
                    hitters = {
                        e.actor
                        for e in events
                        if e.kind == "damage" and e.target in bosses
                    }
                    run.finished_by_combination = len(hitters) >= 3
                run.ailments_taken += sum(
                    1
                    for e in events
                    if e.kind == "effect"
                    and (f := state.fighter(e.target)) is not None
                    and f.side is Side.PLAYER
                    and e.actor != e.target
                )
                if record:
                    frame = _frame(state, number, wave_number, member, said, events)
                    if squad.label:
                        frame.instruction = f"{squad.label} · {frame.instruction}"
                    run.frames.append(frame)
                if state.turn >= MAX_ACTIONS:
                    break
            if state.team.wiped or state.turn >= MAX_ACTIONS:
                return False
            if state.cleared or (boss_rule and bosses and _cleared(state, bosses)):
                break
        run.drops_taken += sum(1 for c in carriers if state.fighter(c).defeated)
        if boss_rule and bosses and _cleared(state, bosses):
            break
    return True


def play_stage(
    stage: Stage,
    front: list[Member],
    back: list[Member | None],
    rng: random.Random,
    *,
    record: bool = False,
    forced_sets: list[int] | None = None,
    objective: ConditionKind | None = None,
) -> Run:
    """One full attempt at the stage: every map in order, sharing one health pool."""
    return play_road(
        stage,
        [(front, back)],
        rng,
        record=record,
        forced_sets=forced_sets,
        objective=objective,
    )


def play_road(
    stage: Stage,
    teams: list[tuple[list[Member], list[Member | None]]],
    rng: random.Random,
    *,
    record: bool = False,
    forced_sets: list[int] | None = None,
    objective: ConditionKind | None = None,
) -> Run:
    """Every map in order. With several teams (Ninja Road), each keeps its own health
    bar, and each map is fought by the team with the most health left."""
    labels = [f"Team {i + 1}" if len(teams) > 1 else "" for i in range(len(teams))]
    squads = [
        make_squad(front, back, label) for (front, back), label in zip(teams, labels)
    ]
    run = _new_run(squads, record)
    used: set[int] = set()
    for number, battle_map in enumerate(stage.maps, start=1):
        run.reached_map = number
        while True:
            standing = [i for i, s in enumerate(squads) if not s.state.team.wiped]
            if not standing:
                _close(run, squads)
                return run
            # The team with health to spare and the better element matchup goes in.
            pick = max(
                standing,
                key=lambda i: (
                    squads[i].health_share * squads[i].matchup(battle_map) ** 2
                ),
            )
            run.squad_maps.append(pick)
            cleared = _play_map(
                squads[pick],
                battle_map,
                number,
                run,
                rng,
                record=record,
                forced_sets=forced_sets,
                objective=objective,
                fresh=pick not in used,
            )
            used.add(pick)
            if cleared:
                _restore(squads[pick])
                break
            # A beaten team is out; the next one takes the map from the start.
            if not squads[pick].state.team.wiped:
                _close(run, squads)
                return run
    run.won = True
    _close(run, squads)
    return run


def _restore(squad: Squad) -> None:
    """Completing a map gives back half the health lost, plus any ability bonus."""
    team = squad.state.team
    if team.wiped:
        return
    gain = (team.max_health - team.health) * MAP_RESTORE + sum(
        m.own_passive.map_heal for m in squad.members.values()
    )
    team.health = min(team.max_health, team.health + round(gain))


def _close(run: Run, squads: list[Squad]) -> None:
    run.turns = sum(s.state.turn for s in squads)
    run.team_health = sum(s.state.team.health for s in squads)


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
