from nbsolver.enums import Element
from nbsolver.missions import BattleMap, EnemySet, EnemyStats, Mission, Rank, Stage
from nbsolver.scrape.hideoutgacha import (
    ATTRIBUTION,
    merge_mission,
    mission_id,
    parse_mission,
)

# Trimmed to the shape of a real page: hashed CSS-module classes, an SVG
# battlefield, enemy rows and the reinforcement lines between them.
PAGE = """
<div class="stage_panels__a1">
  <article class="stage_panel__b2">
    <h2 class="stage_pTitle__c3"><span class="stage_pNo__d4">Mission 1 of 2</span>The Evil Snake Shows its Fangs [C]</h2>
    <ul class="stage_facts__e5">
      <li class="stage_fact__f6">Stamina 10</li>
      <li class="stage_fact__f6">EXP 1,500</li>
    </ul>
    <section class="stage_maps__g7">
      <details class="stage_map__h8">
        <div class="stage_mapBody__i9">
          <div class="stage_grid__j0">
            <svg aria-label="Battlefield: your three front-row characters start on the blue tiles." viewBox="0 0 58 58">
              <g><rect class="fill-v2-raised" x="0" y="0" width="18" height="18"/></g>
              <g><rect class="fill-state-info" x="20" y="20" width="18" height="18"/></g>
              <g>
                <rect class="fill-primary" x="40" y="0" width="18" height="18"/>
                <text x="49" y="13">1</text>
              </g>
              <g>
                <rect class="fill-primary" x="40" y="40" width="18" height="18"/>
                <text x="49" y="53">2</text>
              </g>
            </svg>
          </div>
          <div class="stage_waves__k1">
            <h4 class="stage_waveHead__l2">Wave 1<span>2 enemies</span></h4>
            <ol class="stage_rows__m3">
              <li class="stage_row__n4">
                <span class="stage_who__o5">
                  <span class="stage_whoLine__p6">
                    <span class="stage_whoName__q7">Kabuto Yakushi</span>
                    <span class="stage_role__r8">Mid-boss</span>
                    <span><img src="/images/naruto-blazing/elements/2.webp"/>Skill</span>
                    <span class="stage_grp__s9" title="Spawn group 1: enters on the red tile 1 of the map">Group 1</span>
                  </span>
                  <span class="stage_whoSub__t0"><b>Field Skill:</b> First Aid</span>
                  <span class="jutsu_jutsu__u1"><b class="jutsu_label__v2">Jutsu:</b><span class="jutsu_chip__w3">Cellular Activation</span></span>
                </span>
                <span class="stage_stats__x4">
                  <span><small>HP</small><b>17,500</b></span>
                  <span><small>ATK</small><b>320</b></span>
                  <span><small>DEF</small><b>150</b></span>
                </span>
              </li>
              <li class="stage_cmd__y5">
                <span class="stage_no__z6">#2</span>
                <span>Group 1: its next enemy waits 2 turns before it enters, or enters at once if no enemy is left.</span>
              </li>
              <li class="stage_row__n4">
                <span class="stage_who__o5">
                  <span class="stage_whoLine__p6">
                    <span class="stage_whoName__q7">Sound Ninja</span>
                    <span>&times; 4</span>
                    <span><img src="/images/naruto-blazing/elements/2.webp"/>Skill</span>
                    <span class="stage_grp__s9" title="Spawn group 2">Group 2</span>
                  </span>
                </span>
                <span class="stage_stats__x4">
                  <span><small>HP</small><b>3,200</b></span>
                  <span><small>ATK</small><b>240</b></span>
                  <span><small>DEF</small><b>0</b></span>
                </span>
              </li>
            </ol>
          </div>
        </div>
      </details>
    </section>
  </article>
</div>
"""


def test_the_mission_number_is_stripped_off_the_heading():
    (stage,) = parse_mission(PAGE)

    assert stage.name == "The Evil Snake Shows its Fangs [C]"
    assert stage.stamina == 10


def test_the_battlefield_is_read_off_the_drawn_grid():
    grid = parse_mission(PAGE)[0].maps[0].grid

    assert grid is not None
    assert (grid.columns, grid.rows) == (3, 3)
    assert [(t.column, t.row) for t in grid.player_starts] == [(1, 1)]
    assert [(t.column, t.row) for t in grid.tiles_for(1)] == [(2, 0)]
    assert [(t.column, t.row) for t in grid.tiles_for(2)] == [(2, 2)]


def test_an_enemy_carries_its_defense_role_and_spawn_group():
    kabuto = parse_mission(PAGE)[0].maps[0].enemies[0]

    assert kabuto.name == "Kabuto Yakushi"
    assert kabuto.element is Element.SKILL
    assert (kabuto.hp, kabuto.attack, kabuto.defense) == (17500, 320, 150)
    assert kabuto.role == "Mid-boss"
    assert kabuto.is_boss
    assert kabuto.spawn_group == 1
    assert kabuto.field_skill == "First Aid"
    assert [s.name for s in kabuto.skills] == ["Cellular Activation"]


def test_a_row_standing_for_several_enemies_keeps_the_count():
    ninja = parse_mission(PAGE)[0].maps[0].enemies[1]

    assert ninja.count == 4
    assert ninja.spawn_group == 2
    assert not ninja.is_boss


def test_reinforcement_lines_are_kept_in_place():
    detail = parse_mission(PAGE)[0].maps[0]

    assert [w.number for w in detail.waves] == [1]
    assert len(detail.spawn_rules) == 1
    assert detail.spawn_rules[0].index == 2
    assert "waits 2 turns" in detail.spawn_rules[0].text


def test_our_slug_maps_onto_the_sites_mission_id():
    assert mission_id("e3003") == "3003"
    assert mission_id("3003") == "3003"


def _mission(*groups: list[tuple[str, int, int, int]]) -> Mission:
    sets = [
        EnemySet(
            enemies=[
                EnemyStats(name=n, element=Element.SKILL, hp=hp, attack=atk, count=x)
                for n, hp, atk, x in lineup
            ]
        )
        for lineup in groups
    ]
    return Mission(
        slug="e3003",
        name="Shadow of the Vile Serpent",
        stages=[
            Stage(
                name="The Evil Snake Shows its Fangs [B]",
                rank=Rank.B,
                stamina=20,
                maps=[BattleMap(number=1, sets=sets)],
            )
        ],
    )


def test_merging_adds_the_detail_blazingonline_leaves_out():
    mission = _mission(
        [("Kabuto Yakushi", 17500, 320, 1), ("Sound Ninja", 3200, 240, 4)]
    )

    assert merge_mission(mission, parse_mission(PAGE)) == 1

    battle_map = mission.stages[0].maps[0]
    kabuto, ninja = battle_map.sets[0].enemies
    assert battle_map.grid is not None
    assert kabuto.defense == 150
    assert kabuto.role == "Mid-boss"
    assert kabuto.spawn_group == 1
    assert ninja.spawn_group == 2
    assert len(battle_map.sets[0].spawn_rules) == 1
    assert ATTRIBUTION in mission.sources


def test_a_map_that_picks_at_random_has_its_variants_listed_end_to_end():
    mission = _mission(
        [("Kabuto Yakushi", 17500, 320, 1)], [("Sound Ninja", 3200, 240, 4)]
    )

    assert merge_mission(mission, parse_mission(PAGE)) == 1

    first, second = mission.stages[0].maps[0].sets
    assert first.enemies[0].defense == 150
    assert second.enemies[0].spawn_group == 2
    # The rule sits below the first variant's only enemy, so it belongs to it.
    assert [r.after for r in first.spawn_rules] == [1]
    assert [r.after for r in second.spawn_rules] == [0]


def test_a_line_up_that_has_shifted_is_left_alone():
    mission = _mission(
        [("Kabuto Yakushi", 17500, 320, 1), ("Sound Ninja", 3200, 240, 3)]
    )

    assert merge_mission(mission, parse_mission(PAGE)) == 0

    battle_map = mission.stages[0].maps[0]
    assert battle_map.grid is None
    assert battle_map.sets[0].enemies[0].defense == 0
    assert mission.sources == []
