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

# Units can move anywhere on the map before acting (player-confirmed).
MOVE_REACH = 99.0
# How close it must then be to hit something, by its attack range.
ATTACK_REACH = {
    AttackRange.SHORT: 1.5,
    AttackRange.MID: 2.5,
    AttackRange.LONG: 3.5,
    AttackRange.VAST: 5.0,
}
# Enemies can move anywhere (player-confirmed); their range is what limits them.
ENEMY_STEP = 99.0
# Script-less enemies publish no rhythm; this is a guess at one.
PLAIN_INTERVAL = 3
# Hits per attack are not published; they decide when a combo passes 15 for the
# extra chakra bar. The player says a combination "sometimes" passes 15; these
# make a full three-unit combination pass it, about one attack in five.
ATTACK_HITS = 6
JUTSU_HITS = 10
# "Perimeter Barrier" ships with no description; on record it is a 2.5x attack.
PERIMETER_BARRIER = 2.5
# Completing a map gives back half the health lost so far: measured on both map
# changes of the player's recorded e3003 clear (+378 of 756, +635 of 1270).
MAP_RESTORE = 0.5
# Script-less enemies use their striking skill on every Nth attack (0: never).
PLAIN_SKILL_EVERY = 2
# How much further than its own range an ally can be and still join a combination.
COMBO_REACH_BONUS = 0.0
# How far around an attacking enemy your other units get caught too, as a share of
# its reach. Unpublished, and the setting results hinge on most. Calibrated on the
# player's e3003 [B] Body-only clear ("almost every time"): at 1.0 the simulated
# Body team wins 10-20% of runs, at 0.75 or less 65-80%; Heart stays 100%
# throughout. 0.75 is the largest area consistent with that clear.
ENEMY_AREA = 0.75


# A support comes in on its pair's turn when its best move beats the front unit's by
# this much; how much a power-up is worth against a hit when comparing the two.
SWITCH_MARGIN = 0.05
POWER_UP_VALUE = 0.6
# Where a unit stands to attack: this many spots tried around the target, and how
# far apart a player keeps units so one enemy attack can't catch them all.
SPOT_ANGLES = 12
_ANGLES = tuple(
    (math.cos(2 * math.pi * k / SPOT_ANGLES), math.sin(2 * math.pi * k / SPOT_ANGLES))
    for k in range(SPOT_ANGLES)
)
# Targets weighed in full per decision, after a cheap first sort.
TARGETS_WEIGHED = 4
# What one bar of chakra is worth when deciding to spend it, on ordinary enemies and
# on a boss: saving it for the boss is how real clears are made.
CHAKRA_ON_TRASH = 0.04
CHAKRA_ON_BOSS = 0.005


@dataclass(frozen=True)
class Style:
    """How the simulated player plays. Players clear hard stages by changing how
    they play, not only who they bring, so the solver tries several of these."""

    name: str = "balanced"
    label: str = "Balanced: save chakra for the boss, heal below half health"
    chakra_on_trash: float = CHAKRA_ON_TRASH
    chakra_on_boss: float = CHAKRA_ON_BOSS
    # Team health share below which a heal is cast.
    heal_below: float = 0.5
    # How far apart units keep, so one enemy attack can't catch them all.
    spread: float = 2.5
    # How strongly the boss (and an enemy about to strike) pulls attacks toward it.
    focus: float = 0.25


STYLES = (
    Style(),
    Style(
        name="burst",
        label="All-out: spend chakra on techniques as soon as it is there",
        chakra_on_trash=0.0,
        chakra_on_boss=0.0,
    ),
    Style(
        name="careful",
        label="Careful: keep units well apart and heal early",
        heal_below=0.7,
        spread=3.5,
    ),
    Style(
        name="boss",
        label="Boss rush: hoard chakra and pour everything into the boss",
        chakra_on_trash=0.08,
        chakra_on_boss=0.0,
        focus=1.0,
    ),
)
STYLE = STYLES[0]


def battle_rules() -> BattleRules:
    """The unpublished rules as currently estimated, read at call time."""
    return BattleRules(
        enemy_step=ENEMY_STEP,
        plain_skill_every=PLAIN_SKILL_EVERY,
        combo_reach_bonus=COMBO_REACH_BONUS,
        enemy_area=ENEMY_AREA,
    )


# Long enough for any real clear; anything slower is treated as a loss.
MAX_ACTIONS = 400

UNVERIFIED = (
    (
        "Your units and enemies can move anywhere (player-confirmed); attack"
        " distances themselves are estimates."
    ),
    (
        "An enemy's attack hits its target and every other unit of yours within"
        " three-quarters of its reach. The game says 'every unit in range'"
        " (player-confirmed) but not how big that is; three-quarters is calibrated"
        " on a clear the player makes almost every time."
    ),
    (
        "Enemies with no published script (most ordinary enemies) attack every 3"
        " turns, alternating with their skill."
    ),
    (
        "Hits per attack are not published: 6 per attack and 10 per jutsu, so a full"
        " combination passes 15 hits about one attack in five, as the player reports."
    ),
    (
        "A normal attack, and a technique 'toward all enemies in range', lands on"
        " every enemy within the unit's own attack range; technique shapes vary."
    ),
    "Jutsu that heal by a share of the damage dealt are not modelled yet.",
    (
        "Field skills use the weakest end of their range, as if allies stood at the"
        " edge of the circle."
    ),
    (
        "Abilities count only as far as your box says they are unlocked; a friend's"
        " helper is assumed to have none. A copy of your own unit in the helper slot"
        " has your levels and abilities and adds nothing to the team cost"
        " (player-confirmed)."
    ),
    (
        "Combination attacks join when an ally stands within its own attack range"
        " of the target; the game's exact joining rule is not published."
    ),
    (
        "A support switches in on its pair's turn and still acts that turn"
        " (player-confirmed); it does so when its best move beats the front unit's."
    ),
    (
        "The simulated player tries four play styles (balanced, all-out, careful,"
        " boss rush) and the plan uses whichever cleared most; a real player may"
        " find better moves still."
    ),
)

TARGETS_RE = re.compile(r"(\d+)\s*enem", re.IGNORECASE)
ALL_RE = re.compile(r"\ball enemies\b", re.IGNORECASE)
HEAL_FLAT_RE = re.compile(
    r"(?:restores?|recovers?)[^.]*?([\d,]{3,})\s*(?:of (?:own|your) )?(?:HP|health)",
    re.IGNORECASE,
)
# "Puts up a barrier that protects you from 2500 damage worth of attacks", "puts up
# a barrier blocking 1000 damage", "allow you to block up to 1000 damage".
BARRIER_GIVE_RE = re.compile(
    r"(?:barrier (?:that protects you from|blocking)|block up to) ([\d,]+) damage",
    re.IGNORECASE,
)
# How many allies a heal reaches: "for 1 ally(s) in range", "all allies in range".
HEAL_ALLIES_RE = re.compile(r"(\d+)\s*all(?:y|ies)", re.IGNORECASE)
HEAL_ALL_RE = re.compile(r"\ball allies\b", re.IGNORECASE)
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
    # How many allies the heal reaches; each one reached adds the amount again
    # to the shared pool (player-confirmed: 1280 x 3 allies = 3,840).
    heal_allies: int = 1
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

    @property
    def barrier(self) -> float:
        """Damage the barrier it puts up on its user soaks, if any."""
        return sum(
            e.magnitude or 0.0 for e in self.grants if e.kind == EffectKind.BARRIER
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
    if wall := BARRIER_GIVE_RE.search(text):
        grants.append(
            Effect(
                kind=EffectKind.BARRIER,
                mode=EffectMode.GRANT,
                magnitude=float(wall.group(1).replace(",", "")),
                source=text,
            )
        )
    targets = 99 if ALL_RE.search(text) else 1
    if found := TARGETS_RE.search(text):
        targets = int(found.group(1))
    flat = HEAL_FLAT_RE.search(text)
    percent = HEAL_PERCENT_RE.search(text)
    allies = HEAL_ALLIES_RE.search(text)
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
        heal_allies=(
            99 if HEAL_ALL_RE.search(text) else int(allies.group(1)) if allies else 1
        ),
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
        chakra_max=2 * ninjutsu.chakra if ninjutsu else 0.0,
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
            fighter.reach = ATTACK_REACH.get(
                stats.range, ATTACK_REACH[AttackRange.SHORT]
            )
            fighters.append(fighter)
            keys_by_entry[-1].append(key)
            if stats.carries:
                carriers.add(key)
    return fighters, carriers, keys_by_entry


def _boss_plan(
    wave: list[EnemyStats],
    keys_by_entry: list[list[str]],
    map_marks_boss: bool = False,
) -> tuple[set[str], dict[str, list[str]]]:
    """Who must fall to clear a boss map, and the parts each giant's head takes down.

    The map data marks bosses explicitly. When the map marks one anywhere, a wave
    without it holds no boss and must simply be cleared; only a map that marks
    none falls back to any enemy with a script. A giant boss is listed as several
    same-named boss lines, one per part, each acting on its own; the first is its
    head, and beating the head finishes the whole giant (confirmed by the player).
    """
    marked = [i for i, s in enumerate(wave) if s.role == "Boss"]
    if not marked and not map_marks_boss:
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
    # On a loss: the share of the deciding enemies' health still standing (the boss
    # on a boss map, everyone otherwise), to show how close the attempt came.
    enemy_left: float = 1.0
    maps: int = 0

    @property
    def progress(self) -> float:
        """How far through the stage the attempt got: 1 for a clear, otherwise maps
        cleared plus the share of the deciding enemies' health taken off."""
        if self.won:
            return 1.0
        if not self.maps:
            return 0.0
        return (self.reached_map - 1 + (1 - self.enemy_left)) / self.maps

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


def _heal_spot(
    state: BattleState, actor: Fighter, reach: float, allies: int
) -> tuple[Position, int]:
    """Where a healer stands to reach the most allies (itself included), and how
    many that is, up to what the technique allows."""
    if allies <= 1:
        return actor.position, 1
    others = [m.position for m in state.team.fielded() if m is not actor]
    candidates = [actor.position, *others]
    if others:
        xs = [actor.position[0], *(p[0] for p in others)]
        ys = [actor.position[1], *(p[1] for p in others)]
        candidates.append((round(sum(xs) / len(xs), 2), round(sum(ys) / len(ys), 2)))
    best = max(
        candidates,
        key=lambda spot: sum(1 for p in others if math.dist(spot, p) <= reach),
    )
    reached = 1 + sum(1 for p in others if math.dist(best, p) <= reach)
    return best, min(reached, allies)


def _attack_spot(
    state: BattleState,
    actor: Fighter,
    target: Fighter,
    reach: float,
    catches: bool = False,
    spread: float = STYLE.spread,
) -> Position:
    """Where a player would stand to hit `target`: inside its own reach, as few enemy
    ranges as possible, and apart from allies, since an enemy's attack catches every
    unit inside its range. An attack that lands on everything in range (`catches`)
    also wants as many other enemies inside its reach as it can get.
    """
    if math.dist(actor.position, target.position) > MOVE_REACH + reach:
        return _approach(actor.position, target.position, reach)
    ax, ay = actor.position
    tx, ty = target.position
    allies = [m.position for m in state.team.fielded() if m is not actor]
    enemies = [
        (e.position[0], e.position[1], max(1.0, e.reach))
        for e in state.living_enemies
        if e is not target
    ]
    reach_sq = reach * reach
    best: tuple[float, Position] | None = None
    for radius in (reach, reach * 0.5) if catches else (reach,):
        for cos, sin in _ANGLES:
            sx, sy = round(tx + radius * cos, 2), round(ty + radius * sin, 2)
            travel = math.hypot(sx - ax, sy - ay)
            if travel > MOVE_REACH:
                continue
            score = 0.01 * travel
            for px, py in allies:
                gap = math.hypot(sx - px, sy - py)
                if gap < spread:
                    score += spread - gap
            for ex, ey, er in enemies:
                dx, dy = sx - ex, sy - ey
                gap_sq = dx * dx + dy * dy
                if gap_sq <= er * er:
                    score += 0.5
                if catches and gap_sq <= reach_sq:
                    score -= 1.5
            if best is None or score < best[0]:
                best = (score, (sx, sy))
    return best[1] if best else _approach(actor.position, target.position, reach)


def _caught(
    state: BattleState, spot: Position, target: Fighter, reach: float, count: int
) -> list[Fighter]:
    """The other enemies an attack from `spot` lands on: every one inside the
    attacker's reach, nearest first, up to what the technique allows."""
    near = sorted(
        (
            e
            for e in state.living_enemies
            if e is not target and math.dist(spot, e.position) <= reach
        ),
        key=lambda e: math.dist(spot, e.position),
    )
    return near[: max(0, count - 1)]


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
    _, order, said = _choose(state, member, bosses, hold)
    return order, said


def _choose(
    state: BattleState,
    member: Member,
    bosses: set[str],
    hold: set[str] | None = None,
    style: Style = STYLE,
) -> tuple[float, Order, str]:
    """`decide`, with how much the chosen action is worth, so pairs can compare."""
    actor = state.team.member(member.key)
    living = state.living_enemies
    if actor is None or not living:
        return 0.0, Order(fighter=member.key), "waits"
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
    wounded = state.team.health < style.heal_below * state.team.max_health
    for kind, move in options:
        if (
            move
            and (move.heal_flat or move.heal_percent)
            and wounded
            and not move.strikes
        ):
            amount = move.heal_flat + state.team.max_health * move.heal_percent / 100
            spot, reached = _heal_spot(state, actor, member.reach, move.heal_allies)
            amount *= reached
            order = Order(
                fighter=member.key,
                move_to=spot,
                jutsu=True,
                secret=move.secret,
                chakra_cost=move.chakra,
                heal=amount,
                grants=move.grants,
                label=move.name,
            )
            missing = state.team.max_health - state.team.health
            worth = 1.0 + min(amount, missing) / max(1, state.team.max_health)
            whom = f" ({reached} allies in range)" if reached > 1 else ""
            return worth, order, f"uses {kind} {move.name} to heal the team{whom}"

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
                POWER_UP_VALUE,
                order,
                f"uses {kind} {move.name} to power up (+{move.boost:g}% attack)",
            )

    # A barrier is worth raising when none is up; it soaks hits on its user.
    for kind, move in options:
        if move and not move.strikes and move.barrier and actor.barrier <= 0:
            order = Order(
                fighter=member.key,
                jutsu=True,
                secret=move.secret,
                chakra_cost=move.chakra,
                grants=move.grants,
                label=move.name,
            )
            worth = (
                2
                * min(move.barrier, state.team.max_health)
                / max(1, state.team.max_health)
            )
            return (
                worth,
                order,
                f"uses {kind} {move.name} to raise a {move.barrier:g} barrier",
            )

    if not in_range:
        nearest = min(living, key=lambda e: math.dist(actor.position, e.position))
        spot = _approach(actor.position, nearest.position, member.reach)
        said = f"{describe_move(actor.position, spot)} toward {nearest.name} and stalls"
        return (
            0.0,
            Order(fighter=member.key, move_to=spot),
            f"{said} (nothing in reach yet)",
        )

    best: tuple[float, Order, str] | None = None
    spots: dict[tuple[str, bool], Position] = {}
    # Weigh in full only the likeliest targets: the boss or a striker about to act,
    # anything a normal hit would finish, then the nearest.
    if len(in_range) > TARGETS_WEIGHED:
        plain = member.reach

        def appeal(e: Fighter) -> float:
            finish = 1.0 if _estimate(actor, e, 1.0) >= e.health else 0.0
            near = 1.0 / (1.0 + max(0.0, math.dist(actor.position, e.position) - plain))
            return _priority(e, bosses) + finish + near

        in_range = sorted(in_range, key=appeal, reverse=True)[:TARGETS_WEIGHED]
    for target in in_range:
        for kind, move in options:
            if move is not None and not move.strikes:
                continue
            # A normal attack lands on every enemy in range (hideoutgacha's battle
            # guide); a technique on as many as it says, within the same reach.
            count = move.targets if move else 99
            where = (target.key, count > 1)
            if where not in spots:
                spots[where] = _attack_spot(
                    state,
                    actor,
                    target,
                    member.reach * 0.9,
                    catches=count > 1,
                    spread=style.spread,
                )
            spot = spots[where]
            splash = _caught(state, spot, target, member.reach, count)
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
            own_hits = JUTSU_HITS if move else ATTACK_HITS
            if own_hits + ATTACK_HITS * len(joiners) > state.rules.combo_hits_for_bonus:
                value += 0.3
            value += style.focus * _priority(target, bosses)
            # Chakra spent now is chakra not there for the boss - unless the gauge is
            # full and the next bar would be wasted, or the boss is what it's spent on.
            if move:
                full = actor.chakra_max and actor.chakra + 1 > actor.chakra_max
                on_boss = any(h.key in bosses for h in [target, *splash])
                rate = (
                    0.0
                    if full
                    else style.chakra_on_boss
                    if on_boss
                    else style.chakra_on_trash
                )
                value -= rate * move.chakra
            if move and move.self_cost:
                value -= (
                    move.self_cost
                    / 100
                    * state.team.health
                    / max(1, state.team.max_health)
                )
            if best is None or value > best[0]:
                order = Order(
                    fighter=member.key,
                    move_to=spot,
                    target=target.key,
                    hits=JUTSU_HITS if move else ATTACK_HITS,
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
        return (
            0.0,
            Order(fighter=member.key),
            f"holds back to keep {nearest.name}'s drop in play",
        )
    return best


def _swap_in(state: BattleState, key: str) -> str | None:
    """Send the support in when the unit in front can't act anyway."""
    fighter = state.team.member(key)
    partner = state.team.buddy(key)
    if fighter is None or partner is None or fighter.can_act or not partner.can_act:
        return None
    return partner.key if state.team.switch(key) else None


def _switch_if_better(
    state: BattleState,
    members: dict[str, Member],
    key: str,
    staying: float,
    bosses: set[str],
    hold: set[str],
    style: Style = STYLE,
) -> tuple[str, tuple[float, Order, str]] | None:
    """On its pair's turn the support may come in (player-confirmed); it does when
    its own best move is clearly worth more than the front unit's."""
    team = state.team
    partner = team.buddy(key)
    if partner is None or not partner.can_act or partner.key not in members:
        return None
    # Only worth weighing when the support could fire a technique, hits clearly
    # harder, or the unit in front has nothing useful to do.
    ninjutsu = members[partner.key].ninjutsu
    ready = ninjutsu is not None and partner.chakra >= ninjutsu.chakra
    front = team.member(key)
    stronger = front is not None and (
        partner.attack + partner.flat_attack_boost
        > 1.2 * (front.attack + front.flat_attack_boost)
    )
    if not ready and not stronger and staying > SWITCH_MARGIN:
        return None
    before, spot = list(team.on_field), partner.position
    if not team.switch(key):
        return None
    choice = _choose(state, members[partner.key], bosses, hold, style)
    if choice[0] > staying + SWITCH_MARGIN:
        return partner.key, choice
    team.on_field, partner.position = before, spot
    return None


@dataclass
class Squad:
    """One team and the battle state it carries from map to map."""

    front: list[Member]
    back: list[Member | None]
    state: BattleState
    members: dict[str, Member]
    label: str = ""
    style: Style = STYLE

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
    front: list[Member],
    back: list[Member | None],
    label: str = "",
    style: Style = STYLE,
) -> Squad:
    team = build_team(front, back)
    state = BattleState(team=team, rules=battle_rules())
    members = {m.key: m for m in [*front, *(b for b in back if b)]}
    return Squad(
        front=front, back=back, state=state, members=members, label=label, style=style
    )


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
                fighter = team.member(key)
                fighter.chakra += bonus
                if fighter.chakra_max:
                    fighter.chakra = min(fighter.chakra, fighter.chakra_max)

    waves = _waves(battle_map, entries)
    boss_rule = "boss" in (battle_map.clear or "").lower()
    marks_boss = any(e.role == "Boss" for e in entries)
    for wave_number, wave in enumerate(waves, start=1):
        state.enemies, carriers, keys_by_entry = _spawn(
            battle_map, wave, f"m{number}w{wave_number}"
        )
        run.drops_seen += len(carriers)
        bosses, parts = _boss_plan(wave, keys_by_entry, marks_boss)
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
            # Missions take turns in a fixed order, pair 1, 2, then 3 (the helper's);
            # Speed only matters in the Ninja World battles (player-confirmed).
            for slot in range(len(team.on_field)):
                key = team.on_field[slot]
                if state.over or (boss_rule and bosses and _cleared(state, bosses)):
                    break
                swapped = _swap_in(state, key)
                if swapped is not None:
                    key = swapped
                member = members[key]
                hold = set()
                collecting = objective is ConditionKind.DROP_COMPLETE and boss_rule
                if collecting and any(not state.fighter(c).defeated for c in carriers):
                    hold = set(bosses)
                value, order, said = _choose(state, member, bosses, hold, squad.style)
                if swapped is None:
                    better = _switch_if_better(
                        state, members, key, value, bosses, hold, squad.style
                    )
                    if better is not None:
                        swapped, (value, order, said) = better
                        key, member = swapped, members[swapped]
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
                deciding = [
                    e
                    for e in state.enemies
                    if not (boss_rule and bosses) or e.key in bosses
                ]
                total = sum(e.max_health for e in deciding)
                run.enemy_left = (
                    sum(max(0, e.health) for e in deciding) / total if total else 1.0
                )
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
    style: Style = STYLE,
) -> Run:
    """One full attempt at the stage: every map in order, sharing one health pool."""
    return play_road(
        stage,
        [(front, back)],
        rng,
        record=record,
        forced_sets=forced_sets,
        objective=objective,
        style=style,
    )


def play_road(
    stage: Stage,
    teams: list[tuple[list[Member], list[Member | None]]],
    rng: random.Random,
    *,
    record: bool = False,
    forced_sets: list[int] | None = None,
    objective: ConditionKind | None = None,
    style: Style = STYLE,
) -> Run:
    """Every map in order. With several teams (Ninja Road), each keeps its own health
    bar, and each map is fought by the team with the most health left."""
    labels = [f"Team {i + 1}" if len(teams) > 1 else "" for i in range(len(teams))]
    squads = [
        make_squad(front, back, label, style)
        for (front, back), label in zip(teams, labels)
    ]
    run = _new_run(squads, record)
    run.maps = len(stage.maps)
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
