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


# ---- ALONG_SUBSYSTEM_AXIS direction mode -----------------------------------

class _DirectedFakeSub(FakeSub):
    """FakeSub subclass with GetDirection() so the ALONG_SUBSYSTEM_AXIS branch fires."""
    def __init__(self, kind_class_name, axis, **kwargs):
        super().__init__(kind_class_name, **kwargs)
        # axis stored before __class__ reassignment (the reassigned class inherits
        # _get_dir via MRO, but the value lives on the instance, so that's fine).
        self._axis = axis

    def GetDirection(self):
        from engine.appc.math import TGPoint3
        return TGPoint3(*self._axis)


def test_along_subsystem_axis_uses_get_direction():
    # When the descriptor is ALONG_SUBSYSTEM_AXIS and the sub has GetDirection(),
    # _emit_frame must pass that axis as emit_dir (not the descriptor's fallback).
    se.reset_registry()
    axis = (0.5, 0.5, 0.0)
    fallback = (0.0, -1.0, 0.0)
    desc = se.PlumeDescriptor(
        factory="CreateSmokeHigh",
        params={"fSize": 1.0},
        direction_mode=se.DirectionMode.ALONG_SUBSYSTEM_AXIS,
        direction_vec=fallback,
    )
    se.register("warp_engine", se.TIER_DAMAGED, desc)
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=999, r_cull=None)
    sub = _DirectedFakeSub("WarpEngineSubsystem", axis=axis,
                           pos=(1.0, 0.0, 0.0), state="damaged")
    m.update([FakeShip(subs=[sub])], None, 0.1)
    assert len(b.created) == 1
    assert b.created[0].emit_dir == axis        # subsystem axis, not the fallback


def test_along_subsystem_axis_falls_back_without_get_direction():
    # When the descriptor is ALONG_SUBSYSTEM_AXIS but the sub lacks GetDirection,
    # _emit_frame must fall through to descriptor.direction_vec.
    se.reset_registry()
    fallback = (1.0, 0.0, 0.0)
    desc = se.PlumeDescriptor(
        factory="CreateSmokeHigh",
        params={"fSize": 1.0},
        direction_mode=se.DirectionMode.ALONG_SUBSYSTEM_AXIS,
        direction_vec=fallback,
    )
    se.register("warp_engine", se.TIER_DAMAGED, desc)
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=999, r_cull=None)
    # Plain FakeSub — no GetDirection method
    sub = FakeSub("WarpEngineSubsystem", pos=(1.0, 0.0, 0.0), state="damaged")
    m.update([FakeShip(subs=[sub])], None, 0.1)
    assert len(b.created) == 1
    assert b.created[0].emit_dir == fallback    # descriptor fallback vector
