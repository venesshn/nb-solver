"""The battle itself: who is standing where, and what one turn does to them."""

from __future__ import annotations

import math
import random
from enum import StrEnum

from pydantic import BaseModel, Field

from nbsolver.combat import (
    BASE_CRITICAL_RATE,
    DamageColour,
    damage,
    damage_colour,
)
from nbsolver.effects import Effect, EffectKind, EffectMode
from nbsolver.enums import Element

# Blazing moves units freely inside a radius rather than between grid squares,
# so a position is a point and every distance below is in those same units.
Position = tuple[float, float]


class BattleRules(BaseModel):
    """Numbers no data source publishes. Every default here is a guess."""

    chakra_per_turn: float = 1.0
    slip_damage_by_tier: dict[int, int] = Field(
        default_factory=lambda: {1: 200, 2: 400, 3: 600, 4: 800}
    )
    slip_damage_default: int = 200
    knockback_distance: float = 1.0

    def slip_damage(self, tier: int | None) -> int:
        if tier is None:
            return self.slip_damage_default
        return self.slip_damage_by_tier.get(tier, self.slip_damage_default)


UNVERIFIED_RULES = (
    "chakra_per_turn",
    "slip_damage_by_tier",
    "slip_damage_default",
    "knockback_distance",
)

# An attack bypasses a defence when the attacker carries the matching pierce.
PIERCED_BY = {
    EffectKind.SUBSTITUTION: EffectKind.IGNORE_SUBSTITUTION,
    EffectKind.PERFECT_DODGE: EffectKind.IGNORE_PERFECT_DODGE,
    EffectKind.DODGE: EffectKind.IGNORE_PERFECT_DODGE,
    EffectKind.DAMAGE_REDUCTION: EffectKind.IGNORE_DAMAGE_REDUCTION,
}


class Side(StrEnum):
    PLAYER = "player"
    ENEMY = "enemy"


class ActiveEffect(BaseModel):
    """An effect currently on a fighter; `turns_left` of None lasts all battle."""

    effect: Effect
    turns_left: int | None = None

    @property
    def expired(self) -> bool:
        return self.turns_left is not None and self.turns_left <= 0

    def tick(self) -> None:
        if self.turns_left is not None:
            self.turns_left -= 1


class Fighter(BaseModel):
    key: str
    name: str = ""
    side: Side
    element: Element
    attack: int = 0
    max_health: int = 0
    health: int = 0
    position: Position = (0.0, 0.0)
    chakra: float = 0.0
    barrier: float = 0.0
    # The number the game prints on an enemy portrait: turns until it attacks.
    countdown: int | None = None
    attack_interval: int | None = None
    # What this fighter applies when it lands a hit.
    on_hit: list[Effect] = Field(default_factory=list)
    active: list[ActiveEffect] = Field(default_factory=list)
    defeated: bool = False

    def of_kind(self, kind: EffectKind, mode: EffectMode | None = None) -> list[Effect]:
        return [
            a.effect
            for a in self.active
            if a.effect.kind == kind and (mode is None or a.effect.mode == mode)
        ]

    def has(self, kind: EffectKind, mode: EffectMode | None = None) -> bool:
        return bool(self.of_kind(kind, mode))

    @property
    def current_element(self) -> Element:
        changes = self.of_kind(EffectKind.ELEMENT_CHANGE)
        return next((c.element for c in reversed(changes) if c.element), self.element)

    @property
    def attack_power(self) -> float:
        """Percentages are summed; the game's real stacking rule is unconfirmed."""
        percent = sum(e.magnitude or 0.0 for e in self.of_kind(EffectKind.ATTACK_BOOST))
        percent -= sum(
            e.magnitude or 0.0 for e in self.of_kind(EffectKind.ATTACK_REDUCTION)
        )
        return max(0.0, self.attack * (1 + percent / 100))

    @property
    def critical_rate(self) -> float:
        boosts = sum(
            e.magnitude or 0.0 for e in self.of_kind(EffectKind.CRITICAL_RATE_BOOST)
        )
        return BASE_CRITICAL_RATE + boosts

    @property
    def can_act(self) -> bool:
        return not self.defeated and not self.has(
            EffectKind.IMMOBILIZATION, EffectMode.INFLICT
        )

    def gain(self, effect: Effect) -> None:
        if effect.kind == EffectKind.BARRIER:
            self.barrier += effect.magnitude or 0.0
            return
        self.active.append(ActiveEffect(effect=effect, turns_left=effect.duration))

    def expire(self) -> None:
        for entry in self.active:
            entry.tick()
        self.active = [a for a in self.active if not a.expired]


class Team(BaseModel):
    """Six units sharing one health pool, three on the field and three on the bench."""

    members: list[Fighter] = Field(default_factory=list)
    on_field: list[str] = Field(default_factory=list)
    health: int = 0

    @property
    def max_health(self) -> int:
        return sum(m.max_health for m in self.members)

    @property
    def wiped(self) -> bool:
        return self.health <= 0

    def member(self, key: str) -> Fighter | None:
        return next((m for m in self.members if m.key == key), None)

    def fielded(self) -> list[Fighter]:
        return [m for m in self.members if m.key in self.on_field]

    def switch(self, out_key: str, in_key: str) -> bool:
        """Blocked while the unit leaving is switch sealed."""
        leaving = self.member(out_key)
        if leaving is None or self.member(in_key) is None:
            return False
        if out_key not in self.on_field or in_key in self.on_field:
            return False
        if leaving.has(EffectKind.SWITCH_SEAL, EffectMode.INFLICT):
            return False
        self.on_field[self.on_field.index(out_key)] = in_key
        return True


class Event(BaseModel):
    """One thing the player would see happen, ready to be replayed on the grid."""

    turn: int
    kind: str
    actor: str = ""
    target: str = ""
    amount: float = 0.0
    colour: DamageColour | None = None
    note: str = ""


class Order(BaseModel):
    """What one unit is told to do this turn; no target means it is stalling."""

    fighter: str
    move_to: Position | None = None
    target: str = ""
    multiplier: float = 1.0
    jutsu: bool = False
    chakra_cost: float = 0.0


class BattleState(BaseModel):
    team: Team
    enemies: list[Fighter] = Field(default_factory=list)
    turn: int = 0
    rules: BattleRules = Field(default_factory=BattleRules)

    def fighter(self, key: str) -> Fighter | None:
        found = self.team.member(key)
        if found is not None:
            return found
        return next((e for e in self.enemies if e.key == key), None)

    @property
    def living_enemies(self) -> list[Fighter]:
        return [e for e in self.enemies if not e.defeated]

    @property
    def cleared(self) -> bool:
        return not self.living_enemies

    @property
    def over(self) -> bool:
        return self.cleared or self.team.wiped


def _rolls(chance: float, rng: random.Random) -> bool:
    return chance >= 100.0 or rng.uniform(0, 100) < chance


def _resists(target: Fighter, kind: EffectKind, rng: random.Random) -> bool:
    return any(_rolls(e.chance, rng) for e in target.of_kind(kind, EffectMode.RESIST))


def _pierces(attacker: Fighter, defence: EffectKind) -> bool:
    pierce = PIERCED_BY.get(defence)
    return pierce is not None and attacker.has(pierce, EffectMode.PIERCE)


def _avoids(
    attacker: Fighter, target: Fighter, rng: random.Random
) -> EffectKind | None:
    for kind in (EffectKind.PERFECT_DODGE, EffectKind.SUBSTITUTION, EffectKind.DODGE):
        if _pierces(attacker, kind):
            continue
        if any(_rolls(e.chance, rng) for e in target.of_kind(kind, EffectMode.GRANT)):
            return kind
    return None


def _reduction(attacker: Fighter, target: Fighter) -> float:
    if _pierces(attacker, EffectKind.DAMAGE_REDUCTION):
        return 0.0
    percent = sum(
        e.magnitude or 0.0 for e in target.of_kind(EffectKind.DAMAGE_REDUCTION)
    )
    return min(percent, 100.0)


def _push(target: Fighter, away_from: Position, distance: float) -> None:
    dx, dy = target.position[0] - away_from[0], target.position[1] - away_from[1]
    span = math.hypot(dx, dy)
    if span == 0:
        return
    target.position = (
        target.position[0] + dx / span * distance,
        target.position[1] + dy / span * distance,
    )


def _take_damage(state: BattleState, target: Fighter, dealt: float) -> float:
    """Barriers soak first; player damage comes off the shared pool, not the unit."""
    if target.barrier > 0:
        soaked = min(target.barrier, dealt)
        target.barrier -= soaked
        dealt -= soaked
    landed = round(dealt)
    if target.side is Side.PLAYER:
        state.team.health = max(0, state.team.health - landed)
    else:
        target.health = max(0, target.health - landed)
        target.defeated = target.health <= 0
    return landed


def _heal(state: BattleState, fighter: Fighter, amount: float) -> list[Event]:
    """A healed unit under heal-to-damage takes the number instead of gaining it."""
    if fighter.has(EffectKind.HEALTH_RECOVERY_SEAL, EffectMode.INFLICT):
        return []
    if fighter.has(EffectKind.HEAL_TO_DAMAGE, EffectMode.INFLICT):
        landed = _take_damage(state, fighter, amount)
        return [
            Event(
                turn=state.turn,
                kind="damage",
                target=fighter.key,
                amount=landed,
                colour=DamageColour.NEUTRAL,
                note="healing turned to damage",
            )
        ]
    gained = round(amount)
    if fighter.side is Side.PLAYER:
        state.team.health = min(state.team.max_health, state.team.health + gained)
    else:
        fighter.health = min(fighter.max_health, fighter.health + gained)
    return [
        Event(
            turn=state.turn,
            kind="heal",
            target=fighter.key,
            amount=gained,
            colour=DamageColour.HEALING,
        )
    ]


def _apply_on_hit(
    state: BattleState,
    attacker: Fighter,
    target: Fighter,
    rng: random.Random,
) -> list[Event]:
    events: list[Event] = []
    for effect in attacker.on_hit:
        if effect.mode is not EffectMode.INFLICT:
            continue
        if effect.kind == EffectKind.REMOVE_BARRIER:
            target.barrier = 0.0
            events.append(
                Event(
                    turn=state.turn,
                    kind="effect",
                    actor=attacker.key,
                    target=target.key,
                    note="barrier removed",
                )
            )
            continue
        if effect.kind in (EffectKind.KNOCKBACK, EffectKind.PULL):
            if _resists(target, effect.kind, rng) or not _rolls(effect.chance, rng):
                continue
            distance = effect.magnitude or state.rules.knockback_distance
            _push(
                target,
                attacker.position,
                distance if effect.kind == EffectKind.KNOCKBACK else -distance,
            )
            events.append(
                Event(
                    turn=state.turn,
                    kind="move",
                    actor=attacker.key,
                    target=target.key,
                    note=effect.kind,
                )
            )
            continue
        if effect.kind == EffectKind.CHAKRA_DRAIN:
            target.chakra = max(0.0, target.chakra - (effect.magnitude or 1.0))
            continue
        if not _rolls(effect.chance, rng) or _resists(target, effect.kind, rng):
            continue
        target.gain(effect)
        events.append(
            Event(
                turn=state.turn,
                kind="effect",
                actor=attacker.key,
                target=target.key,
                note=effect.kind,
            )
        )
    return events


def resolve_attack(
    state: BattleState,
    attacker: Fighter,
    target: Fighter,
    multiplier: float,
    rng: random.Random,
    *,
    jutsu: bool = False,
) -> list[Event]:
    avoided = _avoids(attacker, target, rng)
    if avoided is not None:
        return [
            Event(
                turn=state.turn,
                kind="avoided",
                actor=attacker.key,
                target=target.key,
                note=avoided,
            )
        ]
    if jutsu and target.has(EffectKind.NULLIFY_JUTSU_DAMAGE, EffectMode.GRANT):
        return [
            Event(
                turn=state.turn,
                kind="avoided",
                actor=attacker.key,
                target=target.key,
                note="ninjutsu nullified",
            )
        ]

    critical = _rolls(attacker.critical_rate, rng)
    raw = damage(
        round(attacker.attack_power),
        multiplier,
        attacker.current_element,
        target.current_element,
        critical=critical,
        nullify_reduction=attacker.has(
            EffectKind.NULLIFY_ELEMENT_REDUCTION, EffectMode.GRANT
        ),
    )
    raw *= 1 - _reduction(attacker, target) / 100
    landed = _take_damage(state, target, raw)

    events = [
        Event(
            turn=state.turn,
            kind="damage",
            actor=attacker.key,
            target=target.key,
            amount=landed,
            colour=damage_colour(attacker.current_element, target.current_element),
            note="critical" if critical else "",
        )
    ]
    if target.defeated:
        events.append(Event(turn=state.turn, kind="defeat", target=target.key))

    for steal in attacker.of_kind(EffectKind.LIFESTEAL, EffectMode.GRANT):
        events += _heal(state, attacker, landed * (steal.magnitude or 0.0) / 100)
    events += _apply_on_hit(state, attacker, target, rng)
    return events


def tick_slip_damage(state: BattleState, rng: random.Random) -> list[Event]:
    """Slip damage lands on its own, outside anyone's attack."""
    events: list[Event] = []
    for fighter in [*state.team.fielded(), *state.living_enemies]:
        for effect in fighter.of_kind(EffectKind.SLIP_DAMAGE, EffectMode.INFLICT):
            landed = _take_damage(state, fighter, state.rules.slip_damage(effect.tier))
            events.append(
                Event(
                    turn=state.turn,
                    kind="slip",
                    target=fighter.key,
                    amount=landed,
                    colour=DamageColour.SLIP,
                )
            )
            if fighter.defeated:
                events.append(Event(turn=state.turn, kind="defeat", target=fighter.key))
                break
    return events


def _player_phase(
    state: BattleState, orders: list[Order], rng: random.Random
) -> list[Event]:
    events: list[Event] = []
    for order in orders:
        actor = state.team.member(order.fighter)
        if (
            actor is None
            or not actor.can_act
            or order.fighter not in state.team.on_field
        ):
            continue
        if order.move_to is not None and not actor.has(
            EffectKind.MOVEMENT_RESTRICTION, EffectMode.INFLICT
        ):
            actor.position = order.move_to
            events.append(
                Event(
                    turn=state.turn,
                    kind="move",
                    actor=actor.key,
                    note=f"{order.move_to}",
                )
            )
        if not order.target:
            events.append(Event(turn=state.turn, kind="stall", actor=actor.key))
            continue
        if order.jutsu:
            if actor.has(EffectKind.JUTSU_SEAL, EffectMode.INFLICT):
                events.append(Event(turn=state.turn, kind="sealed", actor=actor.key))
                continue
            cost = order.chakra_cost * (1 - _chakra_discount(actor) / 100)
            if actor.chakra < cost:
                events.append(Event(turn=state.turn, kind="no-chakra", actor=actor.key))
                continue
            actor.chakra -= cost
        target = state.fighter(order.target)
        if target is None or target.defeated:
            continue
        events += resolve_attack(
            state, actor, target, order.multiplier, rng, jutsu=order.jutsu
        )
        if state.over:
            break
    return events


def _chakra_discount(fighter: Fighter) -> float:
    return sum(
        e.magnitude or 0.0 for e in fighter.of_kind(EffectKind.CHAKRA_COST_REDUCTION)
    )


def _enemy_phase(state: BattleState, rng: random.Random) -> list[Event]:
    """Enemies strike when their printed countdown runs out, then it resets."""
    events: list[Event] = []
    for enemy in state.living_enemies:
        if enemy.countdown is None or not enemy.can_act:
            continue
        enemy.countdown -= 1
        if enemy.countdown > 0:
            continue
        enemy.countdown = enemy.attack_interval
        fielded = [m for m in state.team.fielded() if not m.defeated]
        if not fielded:
            continue
        target = min(fielded, key=lambda m: math.dist(m.position, enemy.position))
        events += resolve_attack(state, enemy, target, 1.0, rng)
        if state.over:
            break
    return events


def take_turn(
    state: BattleState,
    orders: list[Order],
    rng: random.Random | None = None,
) -> list[Event]:
    """One full round: the player acts, the enemies answer, then everything decays."""
    rng = rng or random.Random()
    state.turn += 1
    events = _player_phase(state, orders, rng)
    if not state.over:
        events += _enemy_phase(state, rng)
    if not state.over:
        events += tick_slip_damage(state, rng)

    for fighter in [*state.team.members, *state.enemies]:
        fighter.expire()
        if fighter.side is Side.PLAYER and not fighter.has(
            EffectKind.CHAKRA_RECOVERY_SEAL, EffectMode.INFLICT
        ):
            fighter.chakra += state.rules.chakra_per_turn
    return events
