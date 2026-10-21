"""The battle itself: who is standing where, and what one turn does to them."""

from __future__ import annotations

import math
import random
import re
from enum import StrEnum

from pydantic import BaseModel, Field

from nbsolver.ai import ActionKind, AiAction, AiScript, AiState, BranchKind
from nbsolver.combat import (
    ATTACK_BOOST_RANKS,
    ATTACK_WEAKENED_RANKS,
    COMBINATION_VALUE,
    CRITICAL_RATE_RANKS,
    DamageColour,
    critical_rate,
    damage,
    damage_colour,
    rank_value,
    slip_damage,
)
from nbsolver.effects import Effect, EffectKind, EffectMode, attack_multiplier
from nbsolver.enums import Element
from nbsolver.missions import EnemySkill, EnemyStats

# Blazing moves units freely inside a radius rather than between grid squares,
# so a position is a point and every distance below is in those same units.
Position = tuple[float, float]


class BattleRules(BaseModel):
    """Numbers the data does not publish, only some of which are confirmed."""

    # Confirmed by the player: one gauge each time a unit's turn comes round.
    chakra_per_turn: float = 1.0
    # Confirmed by the player: a combo past this many hits gives one extra bar,
    # on top of the normal refill.
    combo_hits_for_bonus: int = 15
    combo_chakra_bonus: float = 1.0
    knockback_distance: float = 1.0
    # How far an enemy closes in before it acts; 0 keeps enemies where they spawn.
    enemy_step: float = 0.0


UNVERIFIED_RULES = ("knockback_distance",)

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


class Technique(BaseModel):
    """One of an enemy's skills, as its AI script refers to it."""

    skill_id: int | None = None
    name: str = ""
    multiplier: float = 0.0
    heals: float = 0.0
    effects: list[Effect] = Field(default_factory=list)

    @property
    def strikes(self) -> bool:
        """A pure buff or heal has no attack multiplier to hit anyone with."""
        return self.multiplier > 0

    @property
    def inflicts(self) -> bool:
        return any(e.mode is EffectMode.INFLICT for e in self.effects)


class Fighter(BaseModel):
    key: str
    name: str = ""
    side: Side
    element: Element
    attack: int = 0
    defense: int = 0
    # Abilities, field skills and a buddy skill all add to ATK before multipliers.
    flat_attack_boost: float = 0.0
    max_health: int = 0
    health: int = 0
    position: Position = (0.0, 0.0)
    chakra: float = 0.0
    barrier: float = 0.0
    # The number the game prints on an enemy portrait: turns until it attacks.
    countdown: int | None = None
    attack_interval: int | None = None
    # The published state machine, and where in it this enemy currently stands.
    ai: AiScript | None = None
    ai_state: int | None = None
    techniques: list[Technique] = Field(default_factory=list)
    skill_uses: dict[int, int] = Field(default_factory=dict)
    # What this fighter applies when it lands a hit.
    on_hit: list[Effect] = Field(default_factory=list)
    active: list[ActiveEffect] = Field(default_factory=list)
    defeated: bool = False
    # Attack range by name, and how close it must stand to join a combination.
    attack_range: str = ""
    reach: float = 0.0
    # How many times one of its attacks connects, which is what fills the combo count.
    hits: int = 1
    # Standing bonuses from abilities, field skills and buddy skills.
    damage_vs: dict[str, float] = Field(default_factory=dict)
    reduce_from: dict[str, float] = Field(default_factory=dict)
    inflict_boost: dict[str, float] = Field(default_factory=dict)
    combo_boost: float = 1.0
    counter_chance: float = 0.0
    regen: float = 0.0
    chakra_cut: float = 0.0
    ninjutsu_cut: tuple[float, float] | None = None
    secret_cut: tuple[float, float] | None = None
    chakra_on_hit: tuple[float, float] | None = None

    def technique(self, skill_id: int | None) -> Technique | None:
        if skill_id is None:
            return None
        return next((t for t in self.techniques if t.skill_id == skill_id), None)

    @property
    def health_fraction(self) -> float:
        return self.health / self.max_health if self.max_health else 1.0

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
    def attack_boost(self) -> float:
        """Repeat casts raise the rank rather than multiplying again."""
        ranks = [e.tier or 0 for e in self.of_kind(EffectKind.ATTACK_BOOST)]
        return rank_value(ATTACK_BOOST_RANKS, max(ranks, default=0))

    @property
    def attack_weakened(self) -> float:
        ranks = [e.tier or 0 for e in self.of_kind(EffectKind.ATTACK_REDUCTION)]
        return rank_value(ATTACK_WEAKENED_RANKS, max(ranks, default=0))

    @property
    def other_bonuses(self) -> float:
        """Ability percentages, which add among themselves before multiplying."""
        percent = sum(
            e.magnitude or 0.0
            for e in self.of_kind(EffectKind.ATTACK_BOOST)
            if e.tier is None
        )
        return 1 + percent / 100

    @property
    def critical_rate(self) -> float:
        boost = 1.0
        for effect in self.of_kind(EffectKind.CRITICAL_RATE_BOOST):
            boost *= (
                rank_value(CRITICAL_RATE_RANKS, effect.tier)
                if effect.tier
                else 1 + (effect.magnitude or 0.0) / 100
            )
        return critical_rate(boost)

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
    """Three pairs sharing one health pool: one of each pair is on the field."""

    members: list[Fighter] = Field(default_factory=list)
    # Each entry is the two halves of one slot, which swap with each other.
    pairs: list[tuple[str, str]] = Field(default_factory=list)
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

    def buddy(self, key: str) -> Fighter | None:
        for first, second in self.pairs:
            if key == first:
                return self.member(second)
            if key == second:
                return self.member(first)
        return None

    def switch(self, key: str) -> bool:
        """A unit can only trade places with its own buddy, and sealing stops it."""
        leaving, partner = self.member(key), self.buddy(key)
        if leaving is None or partner is None or key not in self.on_field:
            return False
        if leaving.has(EffectKind.SWITCH_SEAL, EffectMode.INFLICT):
            return False
        self.on_field[self.on_field.index(key)] = partner.key
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
    # How many times the attack connects, which is what builds the combo.
    hits: int = 1
    jutsu: bool = False
    chakra_cost: float = 0.0
    # Further enemies a multi-target jutsu also strikes, after `target`.
    also: list[str] = Field(default_factory=list)
    # What the technique itself inflicts on each target it hits.
    inflicts: list[Effect] = Field(default_factory=list)
    # What the technique grants its user once it has been used.
    grants: list[Effect] = Field(default_factory=list)
    # Health the technique restores to the shared pool.
    heal: float = 0.0
    # A share of each target's remaining health dealt outright, ignoring the formula.
    percent: float = 0.0
    # A share of the team's remaining health the technique costs its user.
    self_cost: float = 0.0
    # Chakra the technique hands straight back to its user.
    chakra_gain: float = 0.0
    # Ailments the technique lays on its own user, e.g. slip damage from a power-up.
    self_inflicts: list[Effect] = Field(default_factory=list)
    secret: bool = False
    label: str = ""


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


HEAL_RE = re.compile(r"restores\s+([\d,]+)\s*HP", re.IGNORECASE)


def _technique(skill: EnemySkill) -> Technique:
    healed = HEAL_RE.search(skill.description or "")
    return Technique(
        skill_id=skill.skill_id,
        name=skill.name,
        multiplier=attack_multiplier(skill.description) or 0.0,
        heals=float(healed.group(1).replace(",", "")) if healed else 0.0,
        effects=skill.effects.effects,
    )


def enemy_fighter(stats: EnemyStats, key: str, position: Position) -> Fighter:
    """Put one of the catalogue's enemies on the field, script and all."""
    return Fighter(
        key=key,
        name=stats.name,
        side=Side.ENEMY,
        element=stats.element,
        attack=stats.attack,
        defense=stats.defense,
        max_health=stats.hp,
        health=stats.hp,
        position=position,
        ai=stats.ai if stats.ai.states else None,
        techniques=[_technique(s) for s in stats.skills],
    )


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
            if kind == EffectKind.PERFECT_DODGE:
                _spend_perfect_dodge(target)
            return kind
    return None


def _spend_perfect_dodge(target: Fighter) -> None:
    """Perfect Dodge is a count of attacks, not a chance; each one used is gone."""
    for entry in target.active:
        effect = entry.effect
        if effect.kind == EffectKind.PERFECT_DODGE and effect.mode is EffectMode.GRANT:
            left = int(effect.magnitude or 1) - 1
            if left <= 0:
                target.active.remove(entry)
            else:
                entry.effect = effect.model_copy(update={"magnitude": float(left)})
            return


def _reduction(attacker: Fighter, target: Fighter) -> float:
    if _pierces(attacker, EffectKind.DAMAGE_REDUCTION):
        return 0.0
    element = attacker.current_element
    percent = sum(
        e.magnitude or 0.0
        for e in target.of_kind(EffectKind.DAMAGE_REDUCTION)
        if e.element is None or e.element == element
    )
    percent += target.reduce_from.get(str(element), 0.0)
    return min(percent, 100.0) / 100


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
    extra: list[Effect] | None = None,
) -> list[Event]:
    events: list[Event] = []
    for effect in [*attacker.on_hit, *(extra or [])]:
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
        if not _rolls(
            effect.chance + attacker.inflict_boost.get(str(effect.kind), 0.0), rng
        ) or _resists(target, effect.kind, rng):
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
    effects: list[Effect] | None = None,
    combination: bool = False,
    counter: bool = False,
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
    if combination:
        multiplier *= attacker.combo_boost
    favoured = 1 + attacker.damage_vs.get(str(target.current_element), 0.0) / 100
    landed = _take_damage(
        state,
        target,
        damage(
            attacker.attack,
            multiplier,
            attacker.current_element,
            target.current_element,
            flat_attack_boost=attacker.flat_attack_boost,
            attack_boost=attacker.attack_boost,
            attack_weakened=attacker.attack_weakened,
            other_bonuses=attacker.other_bonuses * favoured,
            critical=critical,
            nullify_reduction=attacker.has(
                EffectKind.NULLIFY_ELEMENT_REDUCTION, EffectMode.GRANT
            ),
            damage_reduction=_reduction(attacker, target),
            defense=target.defense,
        ),
    )

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
    events += _apply_on_hit(state, attacker, target, rng, effects)
    events += _after_hit(state, attacker, target, rng, jutsu=jutsu, counter=counter)
    return events


def _after_hit(
    state: BattleState,
    attacker: Fighter,
    target: Fighter,
    rng: random.Random,
    *,
    jutsu: bool,
    counter: bool,
) -> list[Event]:
    """Whatever being hit sets off: a counter, a chakra refund, a reaction."""
    events: list[Event] = []
    if target.side is Side.PLAYER and attacker.side is Side.ENEMY:
        if target.chakra_on_hit and _rolls(target.chakra_on_hit[0], rng):
            _give_chakra(state, target, target.chakra_on_hit[1])
        if (
            not counter
            and target.counter_chance
            and not attacker.defeated
            and target.can_act
            and _rolls(target.counter_chance, rng)
        ):
            for event in resolve_attack(
                state, target, attacker, 1.0, rng, counter=True
            ):
                if event.kind == "damage":
                    event.note = "counter" + (f", {event.note}" if event.note else "")
                events.append(event)
    elif target.side is Side.ENEMY and not target.defeated:
        _react(target, attacker, jutsu)
    return events


def _react(enemy: Fighter, attacker: Fighter, jutsu: bool) -> None:
    """A state waiting on a hit jumps when the right kind of hit arrives."""
    if enemy.ai is None or enemy.ai_state is None:
        return
    node = enemy.ai.state(enemy.ai_state)
    if node is None:
        return
    how = (
        f"{'jutsu' if jutsu else 'normal attack'} by {attacker.current_element}".lower()
    )
    for branch in node.branches:
        if branch.kind is BranchKind.REACTION and any(
            how == wanted.lower() for wanted in branch.when_hit_by
        ):
            _enter(enemy, branch.state)
            return


def tick_slip_damage(state: BattleState, rng: random.Random) -> list[Event]:
    """A share of what the victim has left, and nothing dodges it."""
    events: list[Event] = []
    for fighter in [*state.team.fielded(), *state.living_enemies]:
        for effect in fighter.of_kind(EffectKind.SLIP_DAMAGE, EffectMode.INFLICT):
            pool = state.team.health if fighter.side is Side.PLAYER else fighter.health
            landed = _take_damage(state, fighter, slip_damage(pool, effect.tier))
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


def _act(
    state: BattleState, order: Order, rng: random.Random
) -> tuple[list[Event], int]:
    events: list[Event] = []
    actor = state.team.member(order.fighter)
    if actor is None or order.fighter not in state.team.on_field:
        return events, 0
    # An immobilised unit still burns its turn, which is what makes the effect bite.
    if not actor.can_act:
        return [Event(turn=state.turn, kind="immobilised", actor=actor.key)], 0

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
    supportive = order.jutsu and bool(order.heal or order.grants or order.chakra_gain)
    if not order.target and not supportive:
        events.append(Event(turn=state.turn, kind="stall", actor=actor.key))
        return events, 0
    if order.jutsu:
        if actor.has(EffectKind.JUTSU_SEAL, EffectMode.INFLICT):
            events.append(Event(turn=state.turn, kind="sealed", actor=actor.key))
            return events, 0
        cost = order.chakra_cost
        cut = actor.secret_cut if order.secret else actor.ninjutsu_cut
        if cut and _rolls(cut[0], rng):
            cost = min(cost, cut[1])
        cost = max(0.0, cost - actor.chakra_cut) * (1 - _chakra_discount(actor) / 100)
        if actor.chakra < cost:
            events.append(Event(turn=state.turn, kind="no-chakra", actor=actor.key))
            return events, 0
        actor.chakra -= cost
        if order.label:
            events.append(
                Event(turn=state.turn, kind="jutsu", actor=actor.key, note=order.label)
            )

    landed: list[Event] = []
    target = state.fighter(order.target) if order.target else None
    if target is not None and not target.defeated and order.percent:
        for victim in [target, *(state.fighter(k) for k in order.also)]:
            if (
                victim is not None
                and not victim.defeated
                and victim.side is not actor.side
            ):
                landed += _percent_hit(state, actor, victim, order.percent)
        combination_hits = 0
    elif target is not None and not target.defeated:
        landed = resolve_attack(
            state,
            actor,
            target,
            order.multiplier,
            rng,
            jutsu=order.jutsu,
            effects=order.inflicts or None,
        )
        for key in order.also:
            extra = state.fighter(key)
            if (
                extra is not None
                and not extra.defeated
                and extra.side is not actor.side
            ):
                landed += resolve_attack(
                    state,
                    actor,
                    extra,
                    order.multiplier,
                    rng,
                    jutsu=order.jutsu,
                    effects=order.inflicts or None,
                )
        if any(e.kind == "damage" for e in landed) and not target.defeated:
            joined = _combination(state, actor, target, rng)
            landed += joined
            combination_hits = sum(
                f.hits
                for e in joined
                if e.kind == "damage" and (f := state.fighter(e.actor)) is not None
            )
        else:
            combination_hits = 0
    elif not supportive:
        return events, 0
    else:
        combination_hits = 0
    events += landed
    if order.self_cost and state.team.health > 1:
        lost = min(
            state.team.health - 1, math.ceil(state.team.health * order.self_cost / 100)
        )
        state.team.health -= lost
        events.append(
            Event(
                turn=state.turn,
                kind="self-damage",
                target=actor.key,
                amount=lost,
                note="technique cost",
            )
        )
    if order.heal:
        events += _heal(state, actor, order.heal)
    if order.chakra_gain:
        _give_chakra(state, actor, order.chakra_gain)
    for effect in order.self_inflicts:
        actor.gain(effect)
        events.append(
            Event(
                turn=state.turn,
                kind="effect",
                actor=actor.key,
                target=actor.key,
                note=f"{effect.kind} (self)",
            )
        )
    for effect in order.grants:
        actor.gain(effect)
        events.append(
            Event(
                turn=state.turn,
                kind="effect",
                actor=actor.key,
                target=actor.key,
                note=effect.kind,
            )
        )
    combo = (
        order.hits + combination_hits if any(e.kind == "damage" for e in landed) else 0
    )
    return events, combo


def _combination(
    state: BattleState, actor: Fighter, target: Fighter, rng: random.Random
) -> list[Event]:
    """Allies already within their own range of the target join the attack."""
    events: list[Event] = []
    for ally in state.team.fielded():
        if ally is actor or not ally.can_act or not ally.reach or target.defeated:
            continue
        if math.dist(ally.position, target.position) > ally.reach:
            continue
        share = COMBINATION_VALUE.get(ally.attack_range, 0.0)
        if share <= 0:
            continue
        for event in resolve_attack(state, ally, target, share, rng, combination=True):
            if event.kind == "damage":
                event.note = "combination" + (f", {event.note}" if event.note else "")
            events.append(event)
    return events


def _percent_hit(
    state: BattleState, actor: Fighter, target: Fighter, percent: float
) -> list[Event]:
    """A share of what the target has left; element plays no part, and it can't
    finish anyone off: it stops at 1 HP."""
    share = min(math.ceil(target.health * percent / 100), target.health - 1)
    landed = _take_damage(state, target, max(0, share))
    events = [
        Event(
            turn=state.turn,
            kind="damage",
            actor=actor.key,
            target=target.key,
            amount=landed,
            colour=DamageColour.NEUTRAL,
            note=f"{percent:g}% of remaining health",
        )
    ]
    if target.defeated:
        events.append(Event(turn=state.turn, kind="defeat", target=target.key))
    return events


def _chakra_discount(fighter: Fighter) -> float:
    return sum(
        e.magnitude or 0.0 for e in fighter.of_kind(EffectKind.CHAKRA_COST_REDUCTION)
    )


# A chain of Switch states that never settles would otherwise spin forever.
MAX_SWITCHES = 16


def _branch(state: BattleState, enemy: Fighter, node: AiState) -> int | None:
    """Where this state sends the enemy next, once it has played out."""
    if enemy.ai is None:
        return None
    return enemy.ai.next_state(
        node, health_fraction=enemy.health_fraction, turn=state.turn
    )


def _enter(enemy: Fighter, number: int) -> None:
    enemy.ai_state = number
    node = enemy.ai.state(number) if enemy.ai else None
    enemy.countdown = node.countdown if node else None


def _settle(state: BattleState, enemy: Fighter, rng: random.Random) -> AiState | None:
    """Switch states choose and hand straight on; they do not cost a turn."""
    for _ in range(MAX_SWITCHES):
        if enemy.ai is None or enemy.ai_state is None:
            return None
        node = enemy.ai.state(enemy.ai_state)
        if node is None or node.acts:
            return node
        chosen = node.roll(rng.random()) if node.odds else _branch(state, enemy, node)
        # A truncated or purely reactive branch list leaves it stuck here.
        if chosen is None or chosen == enemy.ai_state:
            return node
        _enter(enemy, chosen)
    return enemy.ai.state(enemy.ai_state) if enemy.ai else None


def _ai_target(state: BattleState, enemy: Fighter, action: AiAction) -> Fighter | None:
    fielded = [m for m in state.team.fielded() if not m.defeated]
    if not fielded:
        return None

    def distance(member: Fighter) -> float:
        return math.dist(member.position, enemy.position)

    target = action.target
    if target.startswith(("FarTarget", "MaxRange")):
        return max(fielded, key=distance)
    if found := re.search(r"\((\w+) ninja first\)", target):
        wanted = found.group(1).lower()
        matching = [m for m in fielded if m.current_element.lower() == wanted]
        if matching:
            return min(matching, key=distance)
    return min(fielded, key=distance)


def _self_cast(state: BattleState, enemy: Fighter, technique: Technique) -> list[Event]:
    events: list[Event] = []
    if technique.heals:
        events += _heal(state, enemy, technique.heals)
    for effect in technique.effects:
        if effect.mode is EffectMode.GRANT:
            enemy.gain(effect)
            events.append(
                Event(
                    turn=state.turn,
                    kind="effect",
                    actor=enemy.key,
                    target=enemy.key,
                    note=effect.kind,
                )
            )
    return events


def _fire(
    state: BattleState, enemy: Fighter, node: AiState, rng: random.Random
) -> list[Event]:
    events: list[Event] = []
    for action in node.actions:
        if not action.acts:
            continue
        technique = enemy.technique(action.skill_id)
        if action.skill_id is not None and action.max_uses is not None:
            spent = enemy.skill_uses.get(action.skill_id, 0)
            if spent >= action.max_uses:
                continue
            enemy.skill_uses[action.skill_id] = spent + 1

        if technique is not None and not technique.strikes:
            # No multiplier, so it either lands an ailment or buffs the caster.
            if technique.inflicts:
                victim = _ai_target(state, enemy, action)
                if victim is not None:
                    events += _apply_on_hit(
                        state, enemy, victim, rng, technique.effects
                    )
            else:
                events += _self_cast(state, enemy, technique)
            continue

        target = _ai_target(state, enemy, action)
        if target is None:
            break
        multiplier = technique.multiplier if technique else 1.0
        events += resolve_attack(
            state,
            enemy,
            target,
            multiplier,
            rng,
            jutsu=action.kind is ActionKind.SKILL,
            effects=technique.effects if technique else None,
        )
        if state.over:
            break
    return events


def _scripted_turn(
    state: BattleState, enemy: Fighter, rng: random.Random
) -> list[Event]:
    node = _settle(state, enemy, rng)
    if node is None:
        return []
    if enemy.countdown is None:
        enemy.countdown = node.countdown
    if enemy.countdown > 0:
        enemy.countdown -= 1
    if enemy.countdown > 0:
        return []

    _close_in(state, enemy)
    events = _fire(state, enemy, node, rng)
    chosen = node.roll(rng.random()) if node.odds else _branch(state, enemy, node)
    _enter(enemy, chosen if chosen is not None else enemy.ai_state or 0)
    return events


def _plain_turn(state: BattleState, enemy: Fighter, rng: random.Random) -> list[Event]:
    """Fallback for enemies whose script was never published."""
    if enemy.countdown is None:
        return []
    enemy.countdown -= 1
    if enemy.countdown > 0:
        return []
    enemy.countdown = enemy.attack_interval
    _close_in(state, enemy)
    fielded = [m for m in state.team.fielded() if not m.defeated]
    if not fielded:
        return []
    target = min(fielded, key=lambda m: math.dist(m.position, enemy.position))
    # With no script to say otherwise, a striking skill alternates with normal attacks.
    skill = next((t for t in enemy.techniques if t.strikes), None)
    attacks = enemy.skill_uses.get(-1, 0)
    enemy.skill_uses[-1] = attacks + 1
    if skill is not None and attacks % 2 == 1:
        return resolve_attack(
            state,
            enemy,
            target,
            skill.multiplier,
            rng,
            jutsu=True,
            effects=skill.effects,
        )
    return resolve_attack(state, enemy, target, 1.0, rng)


def _close_in(state: BattleState, enemy: Fighter) -> None:
    """Walk toward the nearest player unit, stopping just short of it."""
    step = state.rules.enemy_step
    if step <= 0 or enemy.has(EffectKind.MOVEMENT_RESTRICTION, EffectMode.INFLICT):
        return
    fielded = [m for m in state.team.fielded() if not m.defeated]
    if not fielded:
        return
    target = min(fielded, key=lambda m: math.dist(m.position, enemy.position))
    span = math.dist(enemy.position, target.position)
    travel = min(step, max(0.0, span - 1.0))
    if span and travel:
        ratio = travel / span
        enemy.position = (
            round(
                enemy.position[0] + (target.position[0] - enemy.position[0]) * ratio, 2
            ),
            round(
                enemy.position[1] + (target.position[1] - enemy.position[1]) * ratio, 2
            ),
        )


def _enemy_phase(state: BattleState, rng: random.Random) -> list[Event]:
    """Each enemy follows its own script, or its printed countdown if it has none."""
    events: list[Event] = []
    for enemy in state.living_enemies:
        if not enemy.can_act:
            continue
        if enemy.ai is not None and enemy.ai.states:
            if enemy.ai_state is None:
                start = enemy.ai.start
                _enter(enemy, start.number if start else 0)
            events += _scripted_turn(state, enemy, rng)
        else:
            events += _plain_turn(state, enemy, rng)
        if state.over:
            break
    return events


def _give_chakra(state: BattleState, fighter: Fighter, amount: float) -> None:
    if fighter.has(EffectKind.CHAKRA_RECOVERY_SEAL, EffectMode.INFLICT):
        return
    fighter.chakra += amount


def take_turn(
    state: BattleState,
    order: Order,
    rng: random.Random | None = None,
) -> list[Event]:
    """One character's action, which is exactly what the game counts as a turn."""
    rng = rng or random.Random()
    state.turn += 1
    events, combo = _act(state, order, rng)
    if not state.over:
        events += _enemy_phase(state, rng)
    if not state.over:
        events += tick_slip_damage(state, rng)

    # Only the unit that acted refills, and its buddy charges alongside it.
    actor = state.team.member(order.fighter)
    if actor is not None:
        if actor.regen and not state.over:
            events += _heal(state, actor, actor.regen)
        _give_chakra(state, actor, state.rules.chakra_per_turn)
        if (partner := state.team.buddy(actor.key)) is not None:
            _give_chakra(state, partner, state.rules.chakra_per_turn)

    if combo > state.rules.combo_hits_for_bonus:
        for fighter in state.team.members:
            _give_chakra(state, fighter, state.rules.combo_chakra_bonus)
        events.append(
            Event(turn=state.turn, kind="combo", amount=combo, note="chakra bonus")
        )

    # Effects decay last so a stated duration covers that many whole turns.
    for fighter in [*state.team.members, *state.enemies]:
        fighter.expire()
    return events
