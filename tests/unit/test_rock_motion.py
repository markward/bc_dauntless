import math
import App
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from tests.unit.test_rock_class import _make


def test_rock_drifts_by_velocity():
    from engine.rocks import motion
    rock = _make(App.GENUS_ASTEROID)
    rock.SetTranslateXYZ(0.0, 0.0, 0.0)
    rock.SetVelocity(TGPoint3(5.0, 0.0, 0.0))
    for _ in range(60):
        motion.step(rock, 1.0 / 60.0)
    assert abs(rock.GetTranslate().x - 5.0) < 1e-6


def test_static_rock_never_moves():
    from engine.rocks import motion
    rock = _make(App.GENUS_ASTEROID)
    rock.SetStatic(1)
    rock.SetVelocity(TGPoint3(5.0, 0.0, 0.0))
    motion.step(rock, 1.0)
    assert rock.GetTranslate().x == 0.0


def test_model_space_spin_is_about_body_axis():
    from engine.rocks import motion
    rock = _make(App.GENUS_ASTEROID)
    # Pitch the rock 90 deg about world X, so body-Z points along world -Y.
    R = App.TGMatrix3(); R.MakeRotation(math.pi / 2, TGPoint3(1, 0, 0))
    rock.SetMatrixRotation(R)
    rock.SetAngularVelocity(TGPoint3(0.0, 0.0, 1.0),
                            PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    motion.step(rock, 0.5)
    # Spinning about BODY Z leaves body Z (the column) unchanged.
    z = rock.GetWorldRotation().GetCol(2)
    assert abs(z.y - R.GetCol(2).y) < 1e-6
    assert abs(z.z - R.GetCol(2).z) < 1e-6


def test_world_space_spin_is_about_world_axis():
    from engine.rocks import motion
    rock = _make(App.GENUS_ASTEROID)
    R = App.TGMatrix3(); R.MakeRotation(math.pi / 2, TGPoint3(1, 0, 0))
    rock.SetMatrixRotation(R)
    rock.SetAngularVelocity(TGPoint3(0.0, 0.0, 1.0))   # default world space
    motion.step(rock, 0.5)
    # Spinning about WORLD Z moves body-Y (which pointed along world +Z) nowhere.
    y = rock.GetWorldRotation().GetCol(1)
    assert abs(y.z - R.GetCol(1).z) < 1e-6
