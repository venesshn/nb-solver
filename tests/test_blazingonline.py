from nbsolver.missions import ConditionKind
from nbsolver.models import AttackRange, Element
from nbsolver.scrape.blazingonline import parse_mission

RAW = {
    "id": "e3013",
    "mode": "emergency",
    "title": "The Mist Demon",
    "wiki": {"url": "https://naruto-blazing.fandom.com/wiki/The_Mist_Demon"},
    "foes": {
        "30020213": {
            "n": "Zabuza Momochi",
            "el": "Wisdom",
            "hp": 22000,
            "atk": 383,
            "range": "Mid mid (width 189)",
            "boss": "Boss",
            "field": {"n": "Critical Rate Boost", "d": "critical rate reduced"},
            "sk": [
                {
                    "slot": "ai",
                    "n": "Water Style: Giant Vortex Jutsu",
                    "d": "2.5x attack, 30% chance of jutsu sealing",
                    "rng": "rectangle: left : long",
                    "tgt": "all targets in range",
                }
            ],
            "ai": ["First acts after 1 turn"],
            "raw": {
                "aiStates": ["state 0 [Init]: skill 300251 (countdown 1) -> state 1"]
            },
        },
        "30020211": {"n": "Gozu", "el": "Wisdom", "hp": 6666, "atk": 220},
    },
    "tabs": [
        {
            "name": "Missions",
            "missions": [
                {
                    "name": "The Mist Demon [B]",
                    "server": {
                        "id": 301302,
                        "name": "The Mist Demon [B]",
                        "rank": "B",
                        "stamina": 20,
                        "clear": "Defeat the boss",
                        "conds": [
                            {
                                "t": "Wisdom elementals only",
                                "r": [{"c": "pearl", "q": 3}],
                            },
                            {
                                "t": "Character cost 28 or lower only",
                                "r": [{"c": "pearl", "q": 5}],
                            },
                        ],
                        "maps": [
                            {
                                "no": 1,
                                "clear": "Defeat every enemy",
                                "sets": [
                                    {
                                        "w": 100.0,
                                        "e": [
                                            {
                                                "n": "Gozu",
                                                "el": "Wisdom",
                                                "lv": 1,
                                                "hp": 6666,
                                                "atk": 220,
                                                "k": "30020211",
                                            }
                                        ],
                                        "waves": [
                                            {"n": 1, "t": "battle start", "rows": 3},
                                            {"n": 2, "t": "after a wait", "rows": 1},
                                        ],
                                    }
                                ],
                            },
                            {
                                "no": 2,
                                "clear": "Defeat the boss",
                                "sets": [
                                    {
                                        "w": 40.0,
                                        "e": [
                                            {
                                                "n": "Zabuza Momochi",
                                                "el": "Wisdom",
                                                "hp": 22000,
                                                "atk": 383,
                                                "boss": "Boss",
                                                "k": "30020213",
                                            }
                                        ],
                                    },
                                    {
                                        "w": 60.0,
                                        "e": [
                                            {
                                                "n": "Zabuza Momochi",
                                                "el": "Wisdom",
                                                "hp": 40000,
                                                "atk": 686,
                                                "boss": "Boss",
                                                "k": "30020213",
                                            }
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                }
            ],
        }
    ],
}


def mission():
    return parse_mission(RAW)


def test_mission_header():
    parsed = mission()

    assert (parsed.slug, parsed.name, parsed.mode) == (
        "e3013",
        "The Mist Demon",
        "emergency",
    )
    assert any("CC BY-SA" in source for source in parsed.sources)


def test_stage_and_conditions():
    stage = mission().stages[0]

    assert (stage.stage_id, stage.stamina, stage.clear) == (
        301302,
        20,
        "Defeat the boss",
    )
    assert [c.kind for c in stage.conditions] == [
        ConditionKind.ELEMENT_ONLY,
        ConditionKind.COST_CAP,
    ]
    assert stage.conditions[0].element is Element.WISDOM
    assert stage.conditions[1].max_cost == 28


def test_waves_are_kept():
    first_map = mission().stages[0].maps[0]

    assert [w.number for w in first_map.sets[0].waves] == [1, 2]
    assert first_map.sets[0].waves[0].trigger == "battle start"
    assert not first_map.is_random


def test_weighted_sets_are_flagged_as_random():
    stage = mission().stages[0]

    assert stage.has_random_sets
    assert [s.weight for s in stage.maps[1].sets] == [40.0, 60.0]


def test_boss_detail_is_merged_from_foes():
    stage = mission().stages[0]
    boss = stage.maps[1].sets[0].enemies[0]

    assert boss.is_boss
    assert boss.range is AttackRange.MID
    assert boss.field_skill == "Critical Rate Boost"
    assert boss.ai_states and boss.skills[0].description.startswith("2.5x attack")
    assert stage.boss_name == "Zabuza Momochi"
    assert stage.boss_element is Element.WISDOM


def test_per_map_stats_override_the_shared_foe_entry():
    stage = mission().stages[0]

    assert [s.enemies[0].hp for s in stage.maps[1].sets] == [22000, 40000]
