"""GC freeze after every mission load, thaw on every teardown
(spec 2026-11-08-perf-tier1-design.md §2.5).

A gen-2 pass over the loaded heap is a 21-27 ms hitch every 30-80 s; a
collect + gc.freeze() after each load moves that heap out of the collector's
view. Every teardown must gc.unfreeze() FIRST, or the old mission's cyclic
garbage stays alive for good.

Every test that arms thaws and disarms in a finally: the suite itself must
never run frozen (docs/reference/architecture/test-suite-memory.md).
"""
from __future__ import annotations

import gc
import inspect
import types
import weakref

import pytest

from engine.core import gc_freeze


@pytest.fixture
def armed():
    gc_freeze.arm()
    try:
        yield
    finally:
        gc_freeze.thaw()
        gc_freeze.disarm()
        gc.unfreeze()


def _freeze_now():
    """A request is serviced at the SECOND service() after it: the first
    only marks it ready, so a whole frame's sweep and reconcile run first."""
    gc_freeze.request()
    assert gc_freeze.service() is False
    assert gc_freeze.service() is True
    assert gc.get_freeze_count() > 0


def test_disarmed_is_inert():
    try:
        assert gc_freeze.armed() is False
        gc_freeze.request()
        assert gc_freeze.service() is False
        assert gc_freeze.service() is False
        assert gc.get_freeze_count() == 0
    finally:
        gc_freeze.thaw()
        gc_freeze.disarm()
        gc.unfreeze()


def test_armed_request_service_freezes(armed):
    assert gc_freeze.armed() is True
    assert gc_freeze.service() is False          # nothing requested yet
    _freeze_now()
    assert gc_freeze.service() is False          # the request was consumed


def test_thaw_unfreezes_and_cancels_request(armed):
    _freeze_now()
    gc_freeze.request()
    assert gc_freeze.service() is False          # ready, one frame from due
    gc_freeze.thaw()
    assert gc.get_freeze_count() == 0
    assert gc_freeze.service() is False          # the pending request is gone
    assert gc_freeze.service() is False
    assert gc.get_freeze_count() == 0


def test_a_new_request_restarts_the_wait(armed):
    gc_freeze.request()
    assert gc_freeze.service() is False          # ready
    gc_freeze.request()                          # another load, this frame
    assert gc_freeze.service() is False          # ready again, not frozen
    assert gc.get_freeze_count() == 0
    assert gc_freeze.service() is True


def test_disarm_then_thaw_still_unfreezes():
    """The per-test reset runs disarm(); thaw(): a heap this module froze is
    thawed even after disarm, or a failing test would leave the run frozen."""
    gc_freeze.arm()
    try:
        _freeze_now()
        gc_freeze.disarm()
        gc_freeze.thaw()
        assert gc.get_freeze_count() == 0
    finally:
        gc_freeze.thaw()
        gc_freeze.disarm()
        gc.unfreeze()


# ── Teardown and load paths ─────────────────────────────────────────────────

def _stub_swap_controller(monkeypatch, *, load_raises=False, seen=None):
    """A stub HostController for _drain_pending_swap with every heavy
    dependency patched out. `seen` collects the freeze count at the first
    teardown step (pre-swap hooks), proving the thaw comes before it."""
    import engine.host_loop as hl
    monkeypatch.setattr(hl._native_combat, "clear_step", lambda: None)
    monkeypatch.setattr(hl._native_combat, "drain", lambda: None)
    monkeypatch.setattr(hl, "reset_mission_state", lambda *a, **k: None)
    monkeypatch.setattr(hl, "reset_sdk_globals", lambda *a, **k: None)
    monkeypatch.setattr(hl, "_warp_clear_turn", lambda: None)

    class _Loader:
        def load(self, name):
            if load_raises:
                raise RuntimeError("bad mission")
            return object()

    ctrl = types.SimpleNamespace(
        pending_swap="Some.Mission", session=None, renderer=None,
        panel_registry=None, loader=_Loader(), post_load_hook=None,
        pre_swap_hooks=[])
    if seen is not None:
        ctrl.pre_swap_hooks.append(
            lambda: seen.append(gc.get_freeze_count()))
    return hl, ctrl


def _stub_mission_change(monkeypatch, *, load_raises=False, seen=None):
    from engine.core import game as game_mod
    from engine.core import mission_change as mc

    class _Mission:
        _module_name = "Old.Mission"

    class _Episode:
        _module_name = "Old.Episode"

        def GetCurrentMission(self):
            return _Mission()

        def _load_mission_raw(self, name, evt):
            if load_raises:
                raise RuntimeError("bad mission")

    ep = _Episode()
    game = types.SimpleNamespace(GetCurrentEpisode=lambda: ep)
    monkeypatch.setattr(game_mod, "Game_GetCurrentGame", lambda: game)
    monkeypatch.setattr(
        mc, "_terminate",
        lambda obj: seen.append(gc.get_freeze_count())
        if seen is not None else None)
    monkeypatch.setattr(mc, "_clear_for_next_mission", lambda *a: None)
    monkeypatch.setattr(mc, "_on_changed", None)
    return mc


def _stub_qb_end(monkeypatch, seen):
    import App
    from engine.quickbattle import battle_end, late_arrivals, spawn
    monkeypatch.setattr(late_arrivals, "cancel_all", lambda: None)
    monkeypatch.setattr(battle_end, "reset", lambda: None)
    qb = types.SimpleNamespace(
        g_idTimer=App.NULL_ID,
        EndSimulation=lambda *a: seen.append(gc.get_freeze_count()))
    assert spawn.install_end_simulation_hook(qb) is True
    return qb


def test_every_teardown_path_thaws(armed, monkeypatch):
    seen: list = []

    _freeze_now()
    hl, ctrl = _stub_swap_controller(monkeypatch, seen=seen)
    hl.HostController._drain_pending_swap(ctrl)
    assert seen[-1] == 0, "dev swap tore down before thawing"
    assert gc.get_freeze_count() == 0

    _freeze_now()
    mc = _stub_mission_change(monkeypatch, seen=seen)
    assert mc.change(mission="New.Mission") is True
    assert seen[-1] == 0, "mission_change terminated before thawing"

    _freeze_now()
    qb = _stub_qb_end(monkeypatch, seen)
    qb.EndSimulation()
    assert seen[-1] == 0, "Quick Battle End ran before thawing"
    assert gc.get_freeze_count() == 0


def test_every_load_path_requests(armed, monkeypatch):
    # Dev swap: success requests, a failed load does not.
    hl, ctrl = _stub_swap_controller(monkeypatch)
    hl.HostController._drain_pending_swap(ctrl)
    assert gc_freeze._due is True
    gc_freeze.thaw()
    hl, ctrl = _stub_swap_controller(monkeypatch, load_raises=True)
    hl.HostController._drain_pending_swap(ctrl)
    assert gc_freeze._due is False

    # mission_change: success requests; refused and failed do not.
    mc = _stub_mission_change(monkeypatch)
    assert mc.change(mission="New.Mission") is True
    assert gc_freeze._due is True
    gc_freeze.thaw()
    assert mc.change(mission="Old.Mission") is False       # refused
    assert gc_freeze._due is False
    mc = _stub_mission_change(monkeypatch, load_raises=True)
    assert mc.change(mission="New.Mission") is False       # failed
    assert gc_freeze._due is False

    # Quick Battle start: the GenerateShips wrapper requests.
    from engine.quickbattle import spawn
    monkeypatch.setattr(spawn, "current_plan", lambda: None)
    monkeypatch.setattr(spawn, "_begin_battle", lambda qb, plan: None)
    qb = types.SimpleNamespace(GenerateShips=lambda: None)
    assert spawn.install_generate_ships_hook(qb) is True
    qb.GenerateShips()
    assert gc_freeze._due is True
    gc_freeze.thaw()

    # Quick Battle End: sim_restore requests once the rebuild is done.
    from engine.quickbattle import sim_restore
    sim_restore.reset()
    sim_restore._restore_after_end(types.SimpleNamespace())
    assert gc_freeze._due is True


def test_swapped_out_ship_is_collected(armed):
    fired = []

    class _Ship:
        pass

    ship = _Ship()
    ship.self_ref = ship                      # a reference cycle
    weakref.finalize(ship, fired.append, True)
    _freeze_now()
    del ship
    gc.collect()
    assert fired == [], "a frozen cycle must not be collected"
    gc_freeze.thaw()
    gc.collect()
    assert fired == [True]


def test_doomed_battle_is_not_frozen_before_its_sweep(armed, monkeypatch):
    """Quick Battle End runs mid-frame (CEF pump inside r.frame(), or a timer
    in the sim ticks): BC flags the battle SetDeleteMe and sim_restore
    requests while the ships are still in their set. The NEXT frame's
    session_sync sweep takes them out of the set, but session.ship_instances
    still holds them until that frame's sim.reconcile. A freeze in between
    would keep the battle's cycles alive to the next teardown."""
    import App
    import engine.host_loop as hl
    from engine.appc import objects as objects_mod
    monkeypatch.setattr(objects_mod, "broadcast_object_deleted",
                        lambda obj: None)

    class _Ship:
        pass

    class _Set:
        def __init__(self):
            self._objects = {}

        def RemoveObjectFromSet(self, name):
            self._objects.pop(name, None)

    fired = []
    ship = _Ship()
    ship.self_ref = ship                          # a reference cycle
    weakref.finalize(ship, fired.append, True)
    pset = _Set()
    pset._objects["Enemy 1"] = ship
    ship_instances = {ship: 7}                    # session.ship_instances
    monkeypatch.setitem(App.g_kSetManager._sets, "QBDoomed", pset)
    del ship

    # Mid-frame End: flag, then sim_restore's request.
    pset._objects["Enemy 1"].__dict__["_delete_me"] = True
    gc_freeze.request()

    def reconcile():                              # _reconcile_runtime_instances
        live = {id(o) for s in App.g_kSetManager._sets.values()
                for o in getattr(s, "_objects", {}).values()}
        for s_ in [k for k in ship_instances if id(k) not in live]:
            ship_instances.pop(s_)

    for _ in range(3):                            # next frames, host order
        hl._process_object_deletions()            # sim.session_sync: sweep
        gc_freeze.service()                       # ... then service
        reconcile()                               # sim.reconcile, later
    assert gc.get_freeze_count() > 0, "the battle load was never frozen"
    gc.collect()
    assert fired == [True], "the swept battle ship was frozen alive"


def test_service_sits_after_the_sweep_in_session_sync():
    import engine.host_loop as hl
    src = inspect.getsource(hl._run_frame_sim)
    sync = src.index('frame_profiler.scope("sim.session_sync")')
    sweep = src.index("_process_object_deletions()", sync)
    svc = src.index("gc_freeze.service()", sync)
    assert sweep < svc < src.index("frame_profiler.scope(", sync + 1)
    assert src.count("gc_freeze.service()") == 1
    assert "gc_freeze.service()" not in inspect.getsource(hl.run)


def test_run_arms_only_outside_pytest():
    import engine.host_loop as hl
    src = inspect.getsource(hl.run)
    assert '"pytest" not in sys.modules' in src
    guard = src.index('"pytest" not in sys.modules')
    assert "gc_freeze.arm()" in src[guard:guard + 200]
    assert "gc_freeze.request()" in src
    # run()'s outer finally opens by unhooking mission_change.
    tail = src[src.index("_mission_change.configure(on_changed=None)") - 300:]
    assert "gc_freeze.thaw()" in tail
    assert gc_freeze.armed() is False
