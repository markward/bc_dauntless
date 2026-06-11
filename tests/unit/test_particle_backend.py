from engine.appc import particles as P
from engine.appc import subsystem_emitters as se
from engine.appc.particles import ParticleBackend


def test_create_registers_controller_and_returns_handle():
    P.reset()
    b = ParticleBackend()
    ship = object()
    h = b.create("CreateSmokeHigh", {"fVelocity": 2.0, "fLife": 1.2, "fSize": 0.6},
                 emit_pos_body=(1.0, -2.0, 0.0), emit_dir=(0.0, -1.0, 0.0),
                 direction_mode=se.DirectionMode.FIXED_BODY_VECTOR, ship=ship)
    assert P.active_count() == 1
    assert h.has_live_particles() is True
    h.stop_emitting()
    ctrl = P._active[0]
    assert ctrl._stop_age is not None


def test_create_spherical_widens_angle_variance():
    P.reset()
    b = ParticleBackend()
    h = b.create("CreateSmokeHigh", {"fVelocity": 1.0, "fLife": 2.0, "fSize": 1.0},
                 emit_pos_body=(0.0, 1.0, 0.0), emit_dir=None,
                 direction_mode=se.DirectionMode.SPHERICAL, ship=object())
    ctrl = P._active[0]
    assert ctrl._angle_variance >= 120.0


def test_fire_one_shot_registers_short_lived_controller():
    P.reset()
    b = ParticleBackend()
    b.fire_one_shot("CreateSmokeHigh", emit_pos_body=(0.0, 0.0, 0.0),
                    emit_dir=(0.0, -1.0, 0.0), ship=object())
    assert P.active_count() == 1
    assert P._active[0]._effect_life_time <= 2.0
