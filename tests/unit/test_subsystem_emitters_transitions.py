# tests/unit/test_subsystem_emitters_transitions.py
from engine.appc import subsystem_emitters as se
from tests.unit.test_subsystem_emitters_registry import FakeSub, FakeShip
from tests.unit.test_subsystem_emitters_backend import FakeControllerBackend


def _mgr(backend):
    # Large cap + cull disabled isolates transition behaviour from the budget.
    return se.PlumeManager(backend, n_per_ship=999, r_cull=None)


def test_none_to_damaged_spawns():
    se.reset_registry()
    b = FakeControllerBackend()
    m = _mgr(b)
    sub = FakeSub("WarpEngineSubsystem", state="damaged")
    ship = FakeShip(subs=[sub])
    m.update([ship], camera_pos=None, dt=0.1)
    assert len(b.created) == 1
    assert b.created[0].factory == "CreateSmokeHigh"


def test_damaged_to_disabled_swaps_controller():
    se.reset_registry()
    b = FakeControllerBackend()
    m = _mgr(b)
    sub = FakeSub("WarpEngineSubsystem", state="damaged")
    ship = FakeShip(subs=[sub])
    m.update([ship], None, 0.1)
    first = b.created[0]
    sub._state = "disabled"
    m.update([ship], None, 0.1)
    assert first.emitting is False           # old controller told to stop
    assert len(b.created) == 2               # new tier spawned
    assert b.created[1].params["fSize"] == 1.4  # DISABLED size, not DAMAGED


def test_repaired_fades_not_hard_killed():
    se.reset_registry()
    b = FakeControllerBackend()
    m = _mgr(b)
    sub = FakeSub("WarpEngineSubsystem", state="damaged")
    ship = FakeShip(subs=[sub])
    m.update([ship], None, 0.1)
    h = b.created[0]
    sub._state = "ok"
    m.update([ship], None, 0.1)
    assert h.emitting is False               # stopped emitting (fade)
    assert h.has_live_particles() is True    # but still lingering, not torn down
    # one-shot death puff must NOT fire on a repair
    assert b.one_shots == []


def test_destroyed_fires_puff_and_no_sustained():
    se.reset_registry()
    b = FakeControllerBackend()
    m = _mgr(b)
    sub = FakeSub("WarpEngineSubsystem", state="damaged")
    ship = FakeShip(subs=[sub])
    m.update([ship], None, 0.1)
    h = b.created[0]
    sub._state = "destroyed"
    m.update([ship], None, 0.1)
    assert h.emitting is False               # sustained plume faded
    assert len(b.one_shots) == 1             # death puff fired once
    assert b.one_shots[0][0] == "CreateExplosionPlumeHigh"


def test_destroyed_does_not_reemit_next_tick():
    se.reset_registry()
    b = FakeControllerBackend()
    m = _mgr(b)
    sub = FakeSub("WarpEngineSubsystem", state="destroyed")
    ship = FakeShip(subs=[sub])
    m.update([ship], None, 0.1)  # first time we ever see it: destroyed
    m.update([ship], None, 0.1)
    m.update([ship], None, 0.1)
    assert b.created == []                    # never a sustained plume
    assert len(b.one_shots) == 1             # puff fires exactly once (on first sight)


def test_faded_handle_dropped_when_particles_die():
    se.reset_registry()
    b = FakeControllerBackend()
    m = _mgr(b)
    sub = FakeSub("WarpEngineSubsystem", state="damaged")
    ship = FakeShip(subs=[sub])
    m.update([ship], None, 0.1)
    sub._state = "ok"
    # Pump until the lingering particles expire; handle should be released.
    for _ in range(5):
        m.update([ship], None, 0.1)
    assert m.active_count() == 0
