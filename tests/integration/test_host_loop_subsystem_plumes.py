# tests/integration/test_host_loop_subsystem_plumes.py
from engine.appc import subsystem_emitters as se
from tests.unit.test_subsystem_emitters_registry import FakeSub, FakeShip
from tests.unit.test_subsystem_emitters_backend import FakeControllerBackend


def test_pump_drives_the_singleton_manager():
    se.reset_registry()
    se.reset_manager()
    b = FakeControllerBackend()
    se.set_backend(b)
    sub = FakeSub("WarpEngineSubsystem", state="disabled")
    ship = FakeShip(subs=[sub])
    se.pump([ship], camera_pos=None, dt=0.1)
    assert se.get_manager().active_count() == 1
    assert b.created[0].params["fSize"] == 1.4


def test_default_backend_is_null_safe_noop():
    se.reset_registry()
    se.reset_manager()  # no set_backend -> NullBackend
    sub = FakeSub("WarpEngineSubsystem", state="disabled")
    se.pump([FakeShip(subs=[sub])], camera_pos=None, dt=0.1)
    # Manager ran its full state machine without error; NullBackend rendered nothing.
    assert se.get_manager().active_count() == 1  # tracked, but inert handle


def test_reset_manager_drops_tracked_emitters():
    se.reset_registry()
    se.reset_manager()
    b = FakeControllerBackend()
    se.set_backend(b)
    sub = FakeSub("WarpEngineSubsystem", state="disabled")
    se.pump([FakeShip(subs=[sub])], camera_pos=None, dt=0.1)
    assert se.get_manager().active_count() == 1
    # Simulate a mission swap: reset_manager() must drop all tracked emitters.
    se.reset_manager()
    assert se.get_manager().active_count() == 0
