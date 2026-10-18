from nbsolver.effects import EffectKind, EffectMode
from nbsolver.missions import EnemySkill, EnemyStats
from nbsolver.models import Jutsu


def test_jutsu_exposes_parsed_effects_alongside_its_multiplier():
    jutsu = Jutsu(
        name="8 Trigrams 64 Palms",
        description=(
            "Ignores Substitution for 1 enemy(s) in range with 4.2x attack toward"
            " them and a 60% chance of jutsu sealing for 3 turn(s)."
        ),
    )

    assert jutsu.multiplier == 4.2
    assert {e.kind for e in jutsu.effects.effects} == {
        EffectKind.IGNORE_SUBSTITUTION,
        EffectKind.JUTSU_SEAL,
    }


def test_enemy_threats_gather_skills_and_field_skill_but_drop_its_own_buffs():
    enemy = EnemyStats(
        name="Zabuza",
        element="Body",
        hp=10000,
        attack=900,
        skills=[
            EnemySkill(
                name="Water Prison",
                description="3x attack, 50% chance of immobilization for 2 turn(s)",
            ),
            EnemySkill(
                name="Guard", description="Reduce Damage Reduces damage by 20%."
            ),
        ],
        field_skill="Boosts attack. 30% chance of slip damage (tier 2)",
    )
    kinds = {e.kind for e in enemy.threats}

    assert kinds == {EffectKind.IMMOBILIZATION, EffectKind.SLIP_DAMAGE}
    assert all(e.mode is not EffectMode.GRANT for e in enemy.threats)
