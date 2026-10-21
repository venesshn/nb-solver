import pytest

from nbsolver.ai import ActionKind, BranchKind, parse_script, parse_state


def test_a_plain_state_names_its_jutsu_and_its_countdown():
    state = parse_state(
        'state 2: skill 301818 "KYUBI Beam" (countdown 1, Danger, target Current)'
        " -> state 1"
    )

    assert state is not None
    assert state.number == 2
    assert state.kind == ""
    action = state.actions[0]
    assert action.kind is ActionKind.SKILL
    assert action.skill_id == 301818
    assert action.name == "KYUBI Beam"
    assert action.countdown == 1
    assert action.target == "Current"
    assert action.is_dangerous
    assert not action.is_secret
    assert [(b.kind, b.state) for b in state.branches] == [(BranchKind.ALWAYS, 1)]


def test_a_jutsu_name_may_hold_the_punctuation_of_the_syntax():
    state = parse_state(
        'state 0 [Init]: skill 300517 "Impaling Headbutt (Me)" (countdown 2, Danger)'
        " -> state 3"
    )

    assert state is not None
    assert state.kind == "Init"
    assert state.actions[0].name == "Impaling Headbutt (Me)"
    assert state.actions[0].countdown == 2


def test_a_state_can_fire_two_jutsu_at_once():
    state = parse_state(
        'state 7: skill 300576 "Crushing Hammer" (countdown 2, Danger)'
        ' + skill 300577 "Fragmentation" (countdown 2, Secret) -> state 4'
    )

    assert state is not None
    first, second = state.actions
    assert (first.skill_id, first.is_dangerous) == (300576, True)
    assert (second.skill_id, second.is_secret) == (300577, True)


def test_a_use_limit_is_kept_because_it_decides_whether_a_heal_repeats():
    state = parse_state(
        'state 2: skill 300100 "Cellular Activation" (countdown 3, max 1 uses)'
        " -> state 1"
    )

    assert state is not None
    assert state.actions[0].max_uses == 1


def test_health_thresholds_are_read_in_the_order_they_are_checked():
    state = parse_state(
        "state 3 [Switch]: no action -> by HP: HP <= 100% -> state 0,"
        " HP <= 50% -> state 2"
    )

    assert state is not None
    assert state.actions[0].kind is ActionKind.NONE
    assert not state.acts
    assert [(b.health_at_most, b.state) for b in state.branches] == [
        (100.0, 0),
        (50.0, 2),
    ]


def test_chance_branches_keep_their_odds():
    state = parse_state(
        "state 2 [Switch]: no action -> then randomly: 25% state 4, 100% state 2"
    )

    assert state is not None
    assert [(b.kind, b.chance, b.state) for b in state.branches] == [
        (BranchKind.CHANCE, 25.0, 4),
        (BranchKind.CHANCE, 100.0, 2),
    ]


def test_turn_thresholds_are_read():
    state = parse_state(
        "state 10 [Switch]: no action -> by turn: from turn 8 -> state 7,"
        " from turn 14 -> state 13"
    )

    assert state is not None
    assert [(b.from_turn, b.state) for b in state.branches] == [(8, 7), (14, 13)]


def test_an_enemy_can_answer_a_normal_attack_differently_from_a_jutsu():
    state = parse_state(
        "state 3 [Switch]: no action -> reaction: when hit by normal attack by Heart"
        " / normal attack by Skill -> state 6, when hit by jutsu by Heart -> state 7"
    )

    assert state is not None
    normal, jutsu = state.branches
    assert normal.kind is BranchKind.REACTION
    assert normal.when_hit_by == ["normal attack by Heart", "normal attack by Skill"]
    assert normal.state == 6
    assert jutsu.when_hit_by == ["jutsu by Heart"]
    assert jutsu.state == 7


def test_a_truncated_branch_list_leaves_no_branches_rather_than_guessing():
    state = parse_state("state 0 [Init]: Attack (countdown 3) -> then randomly:")

    assert state is not None
    assert state.actions[0].kind is ActionKind.ATTACK
    assert state.branches == []


def test_a_line_that_is_not_a_state_is_refused():
    assert parse_state("Attack on countdown 2") is None


def test_equal_weights_are_an_even_split_not_an_unreachable_branch():
    state = parse_state(
        "state 6 [Switch]: no action -> then randomly: 100% state 4, 100% state 5"
    )

    assert state is not None
    assert state.odds == [(4, 0.5), (5, 0.5)]
    assert state.roll(0.0) == 4
    assert state.roll(0.49) == 4
    assert state.roll(0.5) == 5
    assert state.roll(0.99) == 5


def test_uneven_weights_are_shared_out_in_proportion():
    state = parse_state(
        "state 2 [Switch]: no action -> then randomly: 25% state 4, 100% state 2"
    )

    assert state is not None
    assert state.odds == [(4, 0.2), (2, 0.8)]


def test_a_truncated_branch_list_offers_no_odds():
    state = parse_state("state 0 [Init]: Attack (countdown 3) -> then randomly:")

    assert state is not None
    assert state.odds == []
    assert state.roll(0.5) is None


SCRIPT = [
    'state 0 [Init]: skill 300270 "Kusanagi" (countdown 2, Danger) -> state 1',
    "state 1 [Switch]: no action -> by HP: HP <= 100% -> state 0, HP <= 40% -> state 2",
    "state 2: Attack (countdown 1) -> state 1",
]


def test_a_script_starts_where_the_game_says_it_does():
    script = parse_script(SCRIPT)

    assert [s.number for s in script.states] == [0, 1, 2]
    assert script.start is not None
    assert script.start.number == 0
    assert script.state(2) is not None
    assert script.state(9) is None


@pytest.mark.parametrize(
    ("health", "expected"),
    [(1.0, 0), (0.5, 0), (0.41, 0), (0.4, 2), (0.1, 2)],
)
def test_a_wounded_enemy_takes_the_lowest_threshold_it_has_fallen_under(
    health: float, expected: int
):
    script = parse_script(SCRIPT)
    state = script.state(1)

    assert state is not None
    assert script.next_state(state, health_fraction=health) == expected


@pytest.mark.parametrize(("turn", "expected"), [(0, None), (8, 7), (13, 7), (14, 13)])
def test_a_turn_branch_waits_for_its_turn(turn: int, expected: int | None):
    by_turn = (
        "state 10 [Switch]: no action -> by turn: from turn 8 -> state 7,"
        " from turn 14 -> state 13"
    )
    script = parse_script([by_turn])
    state = script.state(10)

    assert state is not None
    assert script.next_state(state, turn=turn) == expected
