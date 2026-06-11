# tests/unit/test_subsystem_emitters_anchor.py
from engine.appc import subsystem_emitters as se
from tests.unit.test_subsystem_emitters_registry import FakeSub, FakeShip
from tests.unit.test_subsystem_emitters_backend import FakeControllerBackend


def test_fixed_body_vector_nacelle_emits_aft():
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=999, r_cull=None)
    sub = FakeSub("WarpEngineSubsystem", pos=(3.0, 5.0, -1.0), state="damaged")
    m.update([FakeShip(subs=[sub])], None, 0.1)
    h = b.created[0]
    assert h.emit_dir == (0.0, -1.0, 0.0)            # aft body vector
    assert h.emit_pos_body == (3.0, 5.0, -1.0)       # body-frame, unmodified
    assert h.direction_mode == se.DirectionMode.FIXED_BODY_VECTOR


def test_spherical_warp_core_passes_no_direction():
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=999, r_cull=None)
    sub = FakeSub("PowerSubsystem", pos=(0.0, 1.0, 0.0), state="damaged")
    m.update([FakeShip(subs=[sub])], None, 0.1)
    h = b.created[0]
    assert h.emit_dir is None                         # omni
    assert h.direction_mode == se.DirectionMode.SPHERICAL


def test_body_position_not_world_transformed():
    # The manager must pass the body-frame hardpoint as-is; the backend (Spec A)
    # does the per-frame world resolution. A non-origin ship must NOT shift it.
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=999, r_cull=None)
    sub = FakeSub("WarpEngineSubsystem", pos=(2.0, -4.0, 0.0), state="damaged")
    ship = FakeShip(subs=[sub], loc=(1000.0, 1000.0, 1000.0))
    m.update([ship], None, 0.1)
    assert b.created[0].emit_pos_body == (2.0, -4.0, 0.0)  # body, not world
