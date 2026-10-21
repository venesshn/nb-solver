"""Read the enemy AI scripts blazingonline extracted from the original game.

Published guides say enemy behaviour is unknowable. It isn't: every enemy
carries a state machine giving its exact countdown, which jutsu it reaches for,
the health thresholds that change its mind and the odds on each branch. A line
reads like this:

    state 2 [Switch]: skill 300271 "Kusanagi Blade" (countdown 1, Danger,
    target Current) -> by HP: HP <= 100% -> state 1, HP <= 50% -> state 3
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field

HEAD_RE = re.compile(r"^state (\d+)(?: \[(\w+)\])?:\s*(.*)$")
SKILL_RE = re.compile(r'^skill (\d+)\s*"(.*)"\s*(?:\((.*)\))?$')
ATTACK_RE = re.compile(r"^Attack\s*(?:\((.*)\))?$", re.IGNORECASE)
STOP_RE = re.compile(r"^Stop\b\s*(?:\((.*)\))?", re.IGNORECASE)
COUNTDOWN_RE = re.compile(r"^countdown (\d+)$", re.IGNORECASE)
USES_RE = re.compile(r"^max (\d+) uses?$", re.IGNORECASE)
TARGET_RE = re.compile(r"^target (.+)$", re.IGNORECASE)
CHANCE_RE = re.compile(r"(\d+)%\s*state (\d+)")
HEALTH_RE = re.compile(r"HP <= (\d+)%\s*->\s*state (\d+)")
TURN_RE = re.compile(r"from turn (\d+)\s*->\s*state (\d+)")
REACTION_RE = re.compile(r"when hit by (.+?)\s*->\s*state (\d+)")
# The transition is the first arrow that introduces one of these words; arrows
# inside a branch list are part of the transition, not separate from it.
SPLIT_RE = re.compile(
    r"->\s*(?:state \d+\s*$|then randomly:|by HP:|by turn:|reaction:)", re.IGNORECASE
)


class ActionKind(StrEnum):
    NONE = "none"
    ATTACK = "attack"
    SKILL = "skill"
    STOP = "stop"


class BranchKind(StrEnum):
    ALWAYS = "always"
    CHANCE = "chance"
    HEALTH = "health"
    TURN = "turn"
    REACTION = "reaction"


class AiAction(BaseModel):
    kind: ActionKind = ActionKind.NONE
    skill_id: int | None = None
    name: str = ""
    # Turns the enemy waits before this lands; 0 means it acts immediately.
    countdown: int = 0
    target: str = ""
    max_uses: int | None = None
    tags: list[str] = Field(default_factory=list)

    @property
    def is_secret(self) -> bool:
        return "Secret" in self.tags

    @property
    def is_dangerous(self) -> bool:
        """The game's own warning flag, shown to the player before it lands."""
        return "Danger" in self.tags

    @property
    def acts(self) -> bool:
        return self.kind in (ActionKind.ATTACK, ActionKind.SKILL)


class Branch(BaseModel):
    kind: BranchKind = BranchKind.ALWAYS
    state: int = 0
    # A relative weight, not an independent roll: see `AiState.odds`.
    chance: float = 100.0
    health_at_most: float | None = None
    from_turn: int | None = None
    # What the enemy must be hit by for a reaction branch to fire.
    when_hit_by: list[str] = Field(default_factory=list)


class AiState(BaseModel):
    number: int
    kind: str = ""
    actions: list[AiAction] = Field(default_factory=list)
    branches: list[Branch] = Field(default_factory=list)
    text: str = ""

    @property
    def countdown(self) -> int:
        return max((a.countdown for a in self.actions), default=0)

    @property
    def acts(self) -> bool:
        return any(a.acts for a in self.actions)

    @property
    def odds(self) -> list[tuple[int, float]]:
        """Chance branches as real probabilities.

        The published percentages are relative weights rather than independent
        rolls. Read as rolls, "100% state 4, 100% state 5" could never reach
        state 5, yet the game plainly does; and lists adding up to 90% or 125%
        are common. As weights both make sense, and that even split is what
        Orochimaru is observed to do.
        """
        weights = [b for b in self.branches if b.kind is BranchKind.CHANCE]
        total = sum(b.chance for b in weights)
        if not total:
            return []
        return [(b.state, b.chance / total) for b in weights]

    def roll(self, value: float) -> int | None:
        """Pick a chance branch from a roll in [0, 1)."""
        running = 0.0
        for state, share in self.odds:
            running += share
            if value < running:
                return state
        return None


class AiScript(BaseModel):
    states: list[AiState] = Field(default_factory=list)

    def state(self, number: int) -> AiState | None:
        return next((s for s in self.states if s.number == number), None)

    @property
    def start(self) -> AiState | None:
        initial = next((s for s in self.states if s.kind == "Init"), None)
        return initial or next(iter(self.states), None)

    def next_state(
        self, state: AiState, *, health_fraction: float = 1.0, turn: int = 0
    ) -> int | None:
        """Where the enemy goes once this state has played out.

        Thresholds are listed loosest first, so the last one still satisfied is
        the tier the enemy is actually in. Chance branches need a roll and are
        left to the caller, which should read `state.branches` itself.
        """
        chosen: int | None = None
        for branch in state.branches:
            if branch.kind is BranchKind.ALWAYS:
                return branch.state
            if (
                branch.kind is BranchKind.HEALTH
                and branch.health_at_most is not None
                and health_fraction * 100 <= branch.health_at_most
            ) or (
                branch.kind is BranchKind.TURN
                and branch.from_turn is not None
                and turn >= branch.from_turn
            ):
                chosen = branch.state
        return chosen


def _mask_quotes(text: str) -> str:
    """Blank out skill names so their punctuation cannot be mistaken for syntax."""
    out, quoted = [], False
    for char in text:
        if char == '"':
            quoted = not quoted
            out.append('"')
        else:
            out.append(" " if quoted else char)
    return "".join(out)


def _split_top(text: str, separator: str) -> list[str]:
    parts, depth, quoted, current = [], 0, False, ""
    for char in text:
        if char == '"':
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
        if char == separator and depth == 0 and not quoted:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return [p.strip() for p in parts if p.strip()]


def _tags(raw: str | None) -> list[str]:
    return _split_top(raw, ",") if raw else []


def _action(text: str) -> AiAction:
    skill = SKILL_RE.match(text)
    attack = ATTACK_RE.match(text)
    stop = STOP_RE.match(text)

    if skill:
        kind, name, raw = ActionKind.SKILL, skill.group(2), skill.group(3)
        skill_id = int(skill.group(1))
    elif attack:
        kind, name, raw, skill_id = ActionKind.ATTACK, "", attack.group(1), None
    elif stop:
        kind, name, raw, skill_id = ActionKind.STOP, "", stop.group(1), None
    else:
        return AiAction(kind=ActionKind.NONE, tags=[])

    action = AiAction(kind=kind, skill_id=skill_id, name=name, tags=_tags(raw))
    for tag in action.tags:
        if found := COUNTDOWN_RE.match(tag):
            action.countdown = int(found.group(1))
        elif found := USES_RE.match(tag):
            action.max_uses = int(found.group(1))
        elif found := TARGET_RE.match(tag):
            action.target = found.group(1)
    return action


def _branches(text: str) -> list[Branch]:
    body = text.lstrip("-> ").strip()
    lowered = body.lower()

    if lowered.startswith("then randomly:"):
        return [
            Branch(kind=BranchKind.CHANCE, chance=float(pct), state=int(state))
            for pct, state in CHANCE_RE.findall(body)
        ]
    if lowered.startswith("by hp:"):
        return [
            Branch(kind=BranchKind.HEALTH, health_at_most=float(pct), state=int(state))
            for pct, state in HEALTH_RE.findall(body)
        ]
    if lowered.startswith("by turn:"):
        return [
            Branch(kind=BranchKind.TURN, from_turn=int(turn), state=int(state))
            for turn, state in TURN_RE.findall(body)
        ]
    if lowered.startswith("reaction:"):
        return [
            Branch(
                kind=BranchKind.REACTION,
                state=int(state),
                when_hit_by=[part.strip() for part in when.split("/")],
            )
            for when, state in REACTION_RE.findall(body)
        ]
    if found := re.match(r"state (\d+)$", body, re.IGNORECASE):
        return [Branch(kind=BranchKind.ALWAYS, state=int(found.group(1)))]
    return []


def parse_state(line: str) -> AiState | None:
    head = HEAD_RE.match(line.strip())
    if not head:
        return None

    body = head.group(3)
    split = SPLIT_RE.search(_mask_quotes(body))
    actions, transition = (body, "") if not split else _cut(body, split.start())

    return AiState(
        number=int(head.group(1)),
        kind=head.group(2) or "",
        actions=[_action(part) for part in _split_top(actions, "+")],
        branches=_branches(transition),
        text=line.strip(),
    )


def _cut(body: str, at: int) -> tuple[str, str]:
    return body[:at].strip(), body[at:].strip()


def parse_script(lines: list[str]) -> AiScript:
    states = [state for line in lines if (state := parse_state(line))]
    return AiScript(states=states)


__all__ = [
    "ActionKind",
    "AiAction",
    "AiScript",
    "AiState",
    "Branch",
    "BranchKind",
    "parse_script",
    "parse_state",
]
