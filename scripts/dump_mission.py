from nbsolver.scrape.blazingonline import BlazingOnline

with BlazingOnline() as api:
    mission = api.mission("e3013")

print(f"{mission.name}  [{mission.mode}]  slug={mission.slug}")
for source in mission.sources:
    print("  source:", source)

for stage in mission.stages:
    print(f"\n--- {stage.name} (rank {stage.rank}, {stage.stamina} stamina, id {stage.stage_id})")
    print(f"    clear: {stage.clear} | random sets: {stage.has_random_sets}")
    for condition in stage.conditions:
        print(
            f"    cond: {condition.kind.value:<13} {condition.description:<33}"
            f" pearls={condition.pearls} el={condition.element} cap={condition.max_cost}"
        )
    for battle in stage.maps:
        print(f"    MAP {battle.number}: {battle.clear}  ({len(battle.sets)} set(s))")
        for group in battle.sets:
            print(f"      weight {group.weight}%")
            for wave in group.waves:
                print(f"        wave {wave.number}: {wave.trigger} (rows {wave.rows})")
            for enemy in group.enemies:
                flag = " BOSS" if enemy.is_boss else ""
                print(f"        {enemy.name:<16} {enemy.element:<8} hp={enemy.hp:<6} atk={enemy.attack:<5}{flag}")
                for state in enemy.ai_states:
                    print(f"            ai: {state}")
                for skill in enemy.skills:
                    if skill.description:
                        print(f"            sk: {skill.name} -> {skill.description} [{skill.range}]")
