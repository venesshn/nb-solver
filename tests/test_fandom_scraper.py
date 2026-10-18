from nbsolver.missions import ClearCondition, ConditionKind, Rank
from nbsolver.models import Element
from nbsolver.scrape.fandom import parse_mission

PAGE_HTML = """
<table>
  <tr><th>Rank</th><th>Stamina</th><th>Boss</th><th>Element</th></tr>
  <tr><td>Stage 1: The Evil Snake Shows its Fangs [C]</td></tr>
  <tr>
    <td><img alt="Mission difficulty icon c"></td><td>10</td>
    <td><img alt="Card-0171"></td><td><img alt="Skill icon"></td>
  </tr>
  <tr><td>Stage 2: The Evil Snake Shows its Fangs [B]</td></tr>
  <tr>
    <td><img alt="Mission difficulty icon b"></td><td>20</td>
    <td><img alt="Card-0171"></td><td><img alt="Skill icon"></td>
  </tr>
</table>
<table>
  <tr><th>Special Reward Condition</th></tr>
  <tr><th>Rank</th><th>#</th><th>Condition</th><th>Reward</th></tr>
  <tr><td><img alt="Mission difficulty icon c"></td><td>1</td><td>Heart elementals only</td><td>x1</td></tr>
  <tr><td>2</td><td>Skill elementals only</td><td>x3</td></tr>
  <tr><td><img alt="Mission difficulty icon b"></td><td>1</td><td>Body elementals only</td><td>x5</td></tr>
</table>
"""


def test_parses_both_stages():
    mission = parse_mission("Shadow_of_the_Vile_Serpent", PAGE_HTML)

    assert [s.rank for s in mission.stages] == [Rank.C, Rank.B]
    assert [s.stamina for s in mission.stages] == [10, 20]
    assert all(s.boss_element is Element.SKILL for s in mission.stages)


def test_conditions_attach_to_matching_rank():
    mission = parse_mission("Shadow_of_the_Vile_Serpent", PAGE_HTML)

    stage_c = mission.stage("The Evil Snake Shows its Fangs [C]")
    stage_b = mission.stage("The Evil Snake Shows its Fangs [B]")

    assert [c.element for c in stage_c.conditions] == [Element.HEART, Element.SKILL]
    assert [c.pearls for c in stage_c.conditions] == [1, 3]
    assert [c.element for c in stage_b.conditions] == [Element.BODY]


def test_attribution_is_recorded():
    assert "CC BY-SA" in parse_mission("X", PAGE_HTML).sources[0]


def test_parses_cost_cap_condition():
    condition = ClearCondition.parse("Character cost 28 or lower only", pearls=5)

    assert condition.kind is ConditionKind.COST_CAP
    assert condition.max_cost == 28


def test_parses_turn_limit_condition():
    condition = ClearCondition.parse("Complete within 20 turns", pearls=3)

    assert condition.kind is ConditionKind.TURN_LIMIT
    assert condition.max_turns == 20


def test_parses_affiliation_condition():
    condition = ClearCondition.parse("Use only Hidden Leaf characters")

    assert condition.kind is ConditionKind.AFFILIATION_ONLY
    assert condition.affiliation == "Hidden Leaf"


def test_parses_required_unit_condition():
    condition = ClearCondition.parse("Have 3+ Naruto Uzumaki characters on your team")

    assert condition.kind is ConditionKind.REQUIRE_UNITS
    assert (condition.required_count, condition.required_unit) == (3, "Naruto Uzumaki")


def test_unknown_condition_falls_back():
    assert ClearCondition.parse("Dance the tango").kind is ConditionKind.OTHER
