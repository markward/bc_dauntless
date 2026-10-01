"""Rock death burst (rock-class spec §2): a crack flash, a dust-and-grit
burst, a short light. No fireball. World-anchored: the rock leaves its set
0.5 s later, taking its renderer instance with it, so the burst carries no
instance id and hit_vfx_pass draws spark kind 2 at its world position."""
from engine.appc.math import TGPoint3

kDustSparkCount = 40
kFlashLightLife = 0.4          # seconds
kFlashLightSizeFraction = 0.5  # light size as a fraction of the rock radius


def pump() -> None:
    from engine.appc import explosion_lights, hit_vfx
    from engine.appc.hit_feedback import SPARK_KIND_ROCK
    from engine.rocks import death
    for spec in death.drain_death_vfx():
        pos = TGPoint3(*spec.loc)
        hit_vfx.spawn(pos, severity=hit_vfx.Severity.CRITICAL,
                      instance_id=None, weapon_kind=SPARK_KIND_ROCK,
                      spark_count=kDustSparkCount, pSet=spec.pSet)
        explosion_lights.register_at(
            pos, spec.pSet,
            size_gu=kFlashLightSizeFraction * spec.radius_gu,
            life_s=kFlashLightLife)
