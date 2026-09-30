"""Drift and spin for rocks: the only motion a rock has.

Ships move through ship_motion's setpoint integrator, which a rock skips
(it has no AI and no engines). Missions give rocks motion with SetVelocity /
SetAngularVelocity (E1M2 CreateMovingAsteroids), which the shim only STORES,
so without this step a scripted rock never moves.

Spin honours the space it was set in: DIRECTION_MODEL_SPACE is a body-frame
axis (post-multiply, R.D), world space a world axis (pre-multiply, D.R).
"""
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.objects import PhysicsObjectClass


def step(rock, dt: float) -> None:
    if rock.IsImmobile():
        return
    v = rock._velocity
    if v.x or v.y or v.z:
        p = rock.GetTranslate()
        rock.SetTranslateXYZ(p.x + v.x * dt, p.y + v.y * dt, p.z + v.z * dt)
    w = rock._angular_velocity
    if w.x or w.y or w.z:
        rate = (w.x * w.x + w.y * w.y + w.z * w.z) ** 0.5
        axis = TGPoint3(w.x / rate, w.y / rate, w.z / rate)
        D = TGMatrix3()
        D.MakeRotation(rate * dt, axis)
        R = rock.GetWorldRotation()
        if getattr(rock, "_angular_space", PhysicsObjectClass.DIRECTION_WORLD_SPACE) \
                == PhysicsObjectClass.DIRECTION_MODEL_SPACE:
            R = R.MultMatrix(D)
        else:
            R = D.MultMatrix(R)
        rock.SetMatrixRotation(R)


def tick_all(dt: float) -> None:
    from engine.appc.ship_iter import iter_rocks
    for rock in iter_rocks():
        step(rock, dt)
