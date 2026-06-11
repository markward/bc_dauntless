# tests/unit/test_subsystem_emitters_persistence.py
from engine.appc import subsystem_emitters as se
from tests.unit.test_subsystem_emitters_registry import FakeSub, FakeShip
from tests.unit.test_subsystem_emitters_backend import FakeControllerBackend


def test_fresh_manager_redrives_disabled_plume_on_first_tick():
    # Simulates a load: a brand-new manager sees an already-disabled subsystem
    # and must re-derive the steady-state heavy plume immediately.
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=3, r_cull=None)
    sub = FakeSub("WarpEngineSubsystem", state="disabled")
    m.update([FakeShip(subs=[sub])], None, 0.1)
    assert m.active_count() == 1
    assert b.created[0].params["fSize"] == 1.4  # DISABLED tier


def test_fresh_manager_pre_destroyed_emits_nothing_and_no_puff():
    # A subsystem that was destroyed before save loads back destroyed. A load is
    # not a live transition, so: no sustained plume AND no death-puff replay.
    se.reset_registry()
    b = FakeControllerBackend()
    m = se.PlumeManager(b, n_per_ship=3, r_cull=None)
    sub = FakeSub("WarpEngineSubsystem", state="destroyed")
    m.update([FakeShip(subs=[sub])], None, 0.1)
    assert m.active_count() == 0
    assert b.one_shots == []
