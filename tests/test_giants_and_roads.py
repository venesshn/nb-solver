import random

from nbsolver.battle import BattleState, Fighter, Order, Side, Team, take_turn
from nbsolver.enums import Element
from nbsolver.missions import BattleMap, EnemySet, EnemyStats, Stage
from nbsolver.models import StatLevel, Unit
from nbsolver.passives import parse_passive
from nbsolver.scrape.fandom import parse_ninja_road_boosts
from nbsolver.simulate import Member, _boss_plan, _spawn, play_road


def enemy(name: str, hp: int, role: str = "", attack: int = 10) -> EnemyStats:
    return EnemyStats(
        name=name,
        element=Element.SKILL,
        hp=hp,
        attack=attack,
        role=role,
        is_boss=bool(role),
    )


def test_explicit_boss_marking_wins_over_scripts():
    wave = [
        enemy("Sound Ninja", 3200),
        enemy("Sound Ninja", 3600),
        enemy("Orochimaru", 27500, "Boss"),
    ]
    wave[0].is_boss = True  # carries a script, which used to make it count as a boss
    _, _, keys = _spawn(BattleMap(number=1), wave, "x")
    bosses, parts = _boss_plan(wave, keys)
    assert bosses == set(keys[2]) and parts == {}


def test_giant_boss_head_is_the_first_part_and_takes_the_rest_down():
    wave = [
        enemy("Gamabunta", 50000, "Boss"),
        enemy("Gamabunta", 300000, "Boss"),
        enemy("Gamabunta", 300000, "Boss"),
    ]
    _, _, keys = _spawn(BattleMap(number=1), wave, "x")
    bosses, parts = _boss_plan(wave, keys)
    assert bosses == set(keys[0])
    assert parts == {keys[0][0]: [keys[1][0], keys[2][0]]}


def test_percentage_attack_stops_at_one_health():
    actor = Fighter(
        key="a",
        side=Side.PLAYER,
        element=Element.HEART,
        attack=1,
        max_health=10,
        health=10,
        chakra=9,
    )
    target = Fighter(
        key="e", side=Side.ENEMY, element=Element.HEART, max_health=100, health=2
    )
    team = Team(members=[actor], on_field=["a"])
    team.health = 10
    state = BattleState(team=team, enemies=[target])
    take_turn(
        state,
        Order(fighter="a", target="e", jutsu=True, chakra_cost=1, percent=90),
        random.Random(1),
    )
    assert target.health == 1 and not target.defeated


def test_map_movement_heal_is_not_regeneration():
    passive = parse_passive("Restores 300 health when moving to a new map.")
    assert passive.map_heal == 300 and passive.regen == 0


def unit(unit_id: int, health: int, attack: int) -> Unit:
    return Unit(
        unit_id=unit_id,
        name=f"Unit {unit_id}",
        element=Element.HEART,
        rarity=6,
        levels=[
            StatLevel(level=1, health=health, attack=attack),
            StatLevel(level=100, health=health, attack=attack),
        ],
    )


def test_road_carries_on_after_a_team_falls():
    """A team beaten on a map is out, but the others keep going (player's rule)."""
    weak = Member("t1p1", unit(1, health=10, attack=1), 100)
    strong = Member("t2p1", unit(2, health=10**6, attack=10**5), 100)
    brute = enemy("Brute", 50000, "Boss", attack=10**4)
    brute.ai_states = ["state 0 [Init]: Attack (countdown 1) -> state 0"]
    stage = Stage(
        name="Road",
        rank="C",
        stamina=1,
        maps=[
            BattleMap(
                number=1, clear="Defeat the boss", sets=[EnemySet(enemies=[brute])]
            )
        ],
    )
    # The weak team has more health share at the start only if equal; force order by matchup tie.
    run = play_road(stage, [([weak], [None]), ([strong], [None])], random.Random(3))
    assert run.won


def test_featured_units_parse_from_the_wiki_table():
    wikitext = """
=='''<u>Extra Effects</u>'''==
{| class="table"
|-
!width="15%"| Ninja Road #
!width="20%"| Character(s)
!width="65%"| Extra Effect
|-
|rowspan="2"| 21
|[[File:a.png|link=Pain (Ningendo) "Palm that Touches the Soul" (★5)]] [[File:b.png|link=Pain (Ningendo) "Palm that Touches the Soul" (★6)]]
|'''2x''' Health and '''1.5x''' Strength
|-
|[[File:c.png|link=Gaara "Sandstorm-Commanding Kage" (★6)]]
|rowspan="2"| '''3x''' Health and '''2x''' Strength<br />Receive 2x coins
|-
|22
|[[File:d.png|link=Hanabi Hyuga "Daughter of the Byakugan" (★6)]]
|}
"""
    boosts = parse_ninja_road_boosts(wikitext)
    assert [(b.name, b.health, b.attack) for b in boosts[21]] == [
        ("Pain (Ningendo)", 2.0, 1.5),
        ("Gaara", 3.0, 2.0),
    ]
    assert [(b.name, b.health, b.attack) for b in boosts[22]] == [
        ("Hanabi Hyuga", 3.0, 2.0)
    ]
