"""Deferred mirror frees and queued off-main pushes (kernels off the lock,
spec 2026-11-03 §2 goal 2, §4, ruling R2).

Before a kernel may compute with the GIL released, nothing may mutate the
mirror tables while it computes. So:

- every mirror-row and transform-slot free (a finalizer, `_drop`, a replaced
  Profile row) is RECORDED, and applied only at a drain point: the start of
  a kernel session (when no other session is open), the tick boundary, and
  the GameLoop's own end-of-tick. A pending row stays valid and its handle
  is not reused until then;
- a mirror push made on a thread other than the main one is QUEUED and
  applied at the next drain. Main-thread pushes keep their direct path.
- Frees drain before pushes, each in recorded order. `nc.reset()` and a
  mission swap drain; `forget_rows()` (after a test's combat_clear rebuilt
  the mirror) applies none of the stale row frees.
"""
import gc
import sys
import threading
import types

import pytest
from tests.helpers import host_frame_source

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_register"),
    reason="native combat bindings not built")

from engine.appc import native_combat as nc  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
_INDEX_MASK = 0xFFFFFFFF


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    gc.collect()
    nc.drain()
    yield
    nc.reset()


def _live(h):
    try:
        _h.combat_dump(h)
    except ValueError:
        return False
    return True


def _object():
    from engine.appc.objects import ObjectClass
    return ObjectClass()


def _forget(obj):
    """Drop the id registry's strong reference: once the caller drops its
    own, gc.collect() runs the object's finalizer (on this, the main,
    thread)."""
    from engine.core import ids
    ids.unregister(obj.GetObjID())


class _Spy:
    """Stands in for the bindings module and logs the mirror calls a drain
    makes, in order."""

    def __init__(self, log):
        self._log = log

    def __getattr__(self, name):
        fn = getattr(_h, name)
        if name == "combat_unregister":
            def unregister(h):
                self._log.append(("free", h))
                return fn(h)
            return unregister
        if name == "combat_push_scalar":
            def push(h, fid, code, value):
                self._log.append(("push", h, fid))
                return fn(h, fid, code, value)
            return push
        return fn


def _in_thread(fn):
    t = threading.Thread(target=fn)
    t.start()
    t.join()


# ── Review Focus 1: a pending row stays valid; its handle is not reused ──────

def test_a_finalized_row_stays_valid_until_the_drain():
    obj = _object()
    h = obj.__dict__["_nslot"]
    _forget(obj)
    del obj
    gc.collect()
    assert _live(h)                         # recorded, not freed
    assert h in [e[0] for e in nc.pending_frees()]
    nc.drain()
    assert not _live(h)
    assert nc.pending_frees() == []


def test_a_pending_handle_is_not_reused_before_the_drain():
    obj = _object()
    h = obj.__dict__["_nslot"]
    _forget(obj)
    del obj
    gc.collect()
    early = _object()
    assert early.__dict__["_nslot"] & _INDEX_MASK != h & _INDEX_MASK
    nc.drain()
    # The freed index is reused at once after the drain (the free list), so
    # the check above is not vacuous.
    late = _object()
    assert late.__dict__["_nslot"] & _INDEX_MASK == h & _INDEX_MASK
    assert late.__dict__["_nslot"] != h


def test_no_drain_while_a_kernel_session_is_open():
    nc.configure(ON)
    obj = _object()
    h = obj.__dict__["_nslot"]
    t, use_memo, drift = nc._k1_clocks()
    _h.combat_k1_begin_pump([], 1.0 / 60.0, t, use_memo, drift)
    try:
        assert _h.combat_k1_depth() == 1
        _forget(obj)
        del obj
        gc.collect()
        nc.drain()                          # a nested session's start
        assert _live(h)
    finally:
        _h.combat_k1_abandon()
    nc.drain()
    assert not _live(h)


def test_a_main_thread_drop_frees_at_once():
    """A live object's row dropped mid-walk is the kernels' "row gone"
    protocol (test_native_k1_dispatch): never deferred on the main
    thread."""
    nc.configure(ON)
    obj = _object()
    h = obj.__dict__["_nslot"]
    nc._drop(obj)
    assert "_nslot" not in obj.__dict__
    assert not _live(h)
    assert nc.pending_frees() == []


def test_an_off_main_drop_is_queued_whole():
    """Off the main thread the drop itself waits for the drain: it frees
    the row and re-pushes its referrers, both mirror writes."""
    nc.configure(ON)
    obj = _object()
    h = obj.__dict__["_nslot"]
    _in_thread(lambda: nc._drop(obj))
    assert obj.__dict__["_nslot"] == h and _live(h)
    assert [(o is obj, n) for o, n in nc.pending_pushes()] == [
        (True, "_drop")]
    nc.drain()
    assert "_nslot" not in obj.__dict__
    assert not _live(h)


# ── With their row: the launch module, the part caches, the transform slot ───

def test_the_launch_module_is_released_with_its_row():
    obj = _object()
    h = obj.__dict__["_nslot"]
    mod = types.ModuleType("_t_launch")
    _h.combat_set_launch_module(h, mod)
    held = sys.getrefcount(mod)
    _forget(obj)
    del obj
    gc.collect()
    assert sys.getrefcount(mod) == held
    nc.drain()
    assert sys.getrefcount(mod) == held - 1


def test_the_part_caches_are_forgotten_with_their_row():
    obj = _object()
    h = obj.__dict__["_nslot"]
    nc._slot_names[h] = "part"
    _forget(obj)
    del obj
    gc.collect()
    assert nc._slot_names.get(h) == "part"
    nc.drain()
    assert h not in nc._slot_names


def test_the_transform_slot_is_freed_with_its_row():
    from engine.appc.transform_store import StaleHandleError, get_store
    store = get_store()
    obj = _object()
    xform = obj._xform
    before = store.live_count()
    _forget(obj)
    del obj
    gc.collect()
    assert store.live_count() == before
    store.get_position(*xform)              # still valid
    nc.drain()
    assert store.live_count() == before - 1
    with pytest.raises(StaleHandleError):
        store.get_position(*xform)


# ── Off-main pushes are queued; main-thread pushes are direct (Focus 2) ─────

def test_an_off_main_push_lands_at_the_next_drain_in_order():
    nc.configure(ON)
    obj = _object()
    h = obj.__dict__["_nslot"]

    def write():
        obj._radius = 3.5
        obj._scale = 2.25
    _in_thread(write)
    assert obj.__dict__["_radius"] == 3.5          # Python at once
    assert _h.combat_dump(h)["_radius"] == 0.0     # the mirror not yet
    assert [(o is obj, n) for o, n in nc.pending_pushes()] == [
        (True, "_radius"), (True, "_scale")]
    log = []
    real = nc._h
    nc._h = _Spy(log)
    try:
        nc.drain()
    finally:
        nc._h = real
    assert [e[2] for e in log] == [nc._fid("_radius"), nc._fid("_scale")]
    row = _h.combat_dump(h)
    assert (row["_radius"], row["_scale"]) == (3.5, 2.25)
    assert nc.pending_pushes() == []


def test_a_queued_push_applies_the_current_value():
    """A main-thread write after a queued off-main one must not be undone by
    the drain: the drain pushes what the object holds then."""
    nc.configure(ON)
    obj = _object()
    h = obj.__dict__["_nslot"]
    _in_thread(lambda: setattr(obj, "_radius", 3.5))
    obj._radius = 7.0                               # direct
    assert _h.combat_dump(h)["_radius"] == 7.0
    nc.drain()
    assert _h.combat_dump(h)["_radius"] == 7.0


def test_an_off_main_condition_watch_push_is_queued():
    nc.configure(ON)
    from engine.appc.subsystems import SensorSubsystem
    sub = SensorSubsystem("Watched")
    h = sub.__dict__["_nslot"]
    w = sub.GetConditionWatcher()
    assert _h.combat_dump(h)["cond_watch_checks"] == 0
    _in_thread(lambda: w.AddRangeCheck(0.5, w.FRW_BOTH, None))
    assert _h.combat_dump(h)["cond_watch_checks"] == 0
    nc.drain()
    assert _h.combat_dump(h)["cond_watch_checks"] == 1


def test_a_queued_push_for_a_collected_object_is_skipped():
    nc.configure(ON)
    obj = _object()
    _in_thread(lambda: setattr(obj, "_radius", 3.5))
    _forget(obj)
    del obj
    gc.collect()
    nc.drain()                                      # must not raise
    assert nc.pending_pushes() == []


def test_a_drain_off_the_main_thread_applies_nothing():
    obj = _object()
    h = obj.__dict__["_nslot"]
    _forget(obj)
    del obj
    gc.collect()
    _in_thread(nc.drain)
    assert _live(h)
    nc.drain()
    assert not _live(h)


def test_a_main_thread_push_is_direct():
    nc.configure(ON)
    obj = _object()
    h = obj.__dict__["_nslot"]
    obj._radius = 4.0
    assert _h.combat_dump(h)["_radius"] == 4.0
    assert nc.pending_pushes() == []


def test_a_main_thread_del_push_is_direct():
    """An SDK __del__ (ConditionPulseReady's RemoveRangeCheck, LM §2.2)
    collected on the main thread pushes at once, as today."""
    nc.configure(ON)
    obj = _object()
    h = obj.__dict__["_nslot"]

    class _Pusher:
        def __del__(self):
            obj._radius = 9.0
    p = _Pusher()
    p.cycle = p
    del p
    gc.collect()
    assert _h.combat_dump(h)["_radius"] == 9.0
    assert nc.pending_pushes() == []


def test_frees_drain_before_pushes():
    nc.configure(ON)
    live = _object()
    gone = _object()
    lh, gh = live.__dict__["_nslot"], gone.__dict__["_nslot"]
    _in_thread(lambda: setattr(live, "_radius", 1.5))   # recorded first
    _forget(gone)
    del gone
    gc.collect()
    log = []
    real = nc._h
    nc._h = _Spy(log)
    try:
        nc.drain()
    finally:
        nc._h = real
    assert [e[:2] for e in log] == [("free", gh), ("push", lh)]


# ── The drain points ────────────────────────────────────────────────────────

def test_a_kernel_session_start_drains():
    nc.configure(ON)
    obj = _object()
    h = obj.__dict__["_nslot"]
    _forget(obj)
    del obj
    gc.collect()
    nc.k1_pump([], 1.0 / 60.0)
    assert not _live(h)


def test_the_host_tick_boundary_drains():
    from engine import host_loop
    obj = _object()
    h = obj.__dict__["_nslot"]
    _forget(obj)
    del obj
    gc.collect()
    host_loop._combat_tick_boundary()
    assert not _live(h)


def test_the_game_loop_end_of_tick_drains():
    from engine.core.loop import GameLoop
    loop = GameLoop()
    obj = _object()
    h = obj.__dict__["_nslot"]
    _forget(obj)
    del obj
    gc.collect()
    loop.tick()
    assert not _live(h)


# ── Review Focus 4: reset, rebuilt mirror, mission swap ──────────────────────

def test_reset_drains_the_pending_lists():
    nc.configure(ON)
    obj = _object()
    h = obj.__dict__["_nslot"]
    keep = _object()
    _in_thread(lambda: setattr(keep, "_radius", 2.0))
    _forget(obj)
    del obj
    gc.collect()
    nc.reset()
    assert not _live(h)
    assert nc.pending_frees() == [] and nc.pending_pushes() == []


def test_forget_rows_applies_no_stale_row_free_to_a_rebuilt_mirror():
    from engine.appc.transform_store import get_store
    store = get_store()
    nc.configure(ON)
    obj = _object()
    keep = _object()
    _in_thread(lambda: setattr(keep, "_radius", 2.0))
    _forget(obj)
    del obj
    gc.collect()
    before = store.live_count()
    _h.combat_clear()
    log = []
    real = nc._h
    nc._h = _Spy(log)
    try:
        nc.forget_rows()
    finally:
        nc._h = real
    assert log == []                        # no row free, no push
    assert nc.pending_frees() == [] and nc.pending_pushes() == []
    assert store.live_count() == before - 1  # the transform slot is freed


def _dev_swap():
    from engine.host_loop import HostController, MissionSession

    class _StubLoader:
        def load(self, name):
            return MissionSession(mission_name=name)

    class _FakeRenderer:
        def destroy_instance(self, iid):
            pass

    h = HostController()
    h.renderer = _FakeRenderer()
    h.loader = _StubLoader()
    h.session = MissionSession(mission_name="prev")
    h.swap_mission("Next.Mission")
    h._drain_pending_swap()


def test_the_dev_mission_swap_drains():
    obj = _object()
    h = obj.__dict__["_nslot"]
    _forget(obj)
    del obj
    gc.collect()
    _dev_swap()
    assert not _live(h)
    assert nc.pending_frees() == []


def test_a_mission_change_drains():
    from engine.core import mission_change
    from tests.helpers.mission_change_fixtures import (
        _forget_world, _install, _world)
    try:
        _world()
        _install("_t.Old", Terminate=lambda m: None)
        _install("_t.New", Initialize=lambda m: None)
        obj = _object()
        h = obj.__dict__["_nslot"]
        _forget(obj)
        del obj
        gc.collect()
        assert mission_change.change(mission="_t.New") is True
        assert not _live(h)
        assert nc.pending_frees() == []
    finally:
        _forget_world()


# ── Final review: a raising push, the audit, a pending probe, stalls ────────

def test_a_queued_push_that_raises_is_logged_once_and_the_drain_carries_on(
        capsys):
    """M2: before the queue, an off-main push that raised did so inside a
    __del__, where Python reports it and carries on. A drain does the same:
    the push is logged (once per site), the rest is applied."""
    nc.configure(ON)
    obj = _object()
    h = obj.__dict__["_nslot"]

    def boom(o, arg):
        raise RuntimeError("boom %d" % arg)
    nc._queue_push(obj, boom, 1, "boom")
    _in_thread(lambda: setattr(obj, "_radius", 3.5))
    nc._queue_push(obj, boom, 2, "boom")
    nc.drain()
    assert _h.combat_dump(h)["_radius"] == 3.5
    assert nc.pending_pushes() == []
    err = capsys.readouterr().err
    assert err.count("[native-combat]") == 1, err
    assert "boom" in err and "RuntimeError" in err
    nc._queue_push(obj, boom, 3, "boom")             # the same site again
    nc.drain()
    assert "[native-combat]" not in capsys.readouterr().err


def test_the_audit_runs_after_the_drain():
    """M3: DAUNTLESS_NATIVE_AUDIT audits the mirror once a GameLoop tick. An
    off-main push queued since the last drain is not a mirror bypass: the
    audit drains first, so it does not read as Python != mirror."""
    from engine.core.loop import GameLoop
    loop = GameLoop(owns_boundary=False)    # a host's: its boundary is later
    nc.configure({"DAUNTLESS_NATIVE_AUDIT": "1"})   # (GameLoop configures)
    assert nc.audit_enabled()
    obj = _object()
    _in_thread(lambda: setattr(obj, "_radius", 3.5))
    loop.tick()
    assert ("ObjectClass", "_radius") not in nc.audit_failures(), \
        nc.audit_failures()


def test_an_unregistered_object_id_is_not_found_by_the_mirror():
    """M5: Python's probe walk (SensorSubsystem.probes) skips an id that no
    longer resolves (ids.unregister); native can_detect's _live_probes finds
    its probes by obj_id in the mirror, where a collected object's row waits
    for the drain. So the row stops being findable at the unregister, and is
    findable again at ids.register: the two walks agree."""
    from engine.core import ids
    nc.configure(ON)
    obj = _object()
    h, oid = obj.__dict__["_nslot"], obj.GetObjID()
    assert _h.combat_find_by_obj_id(oid) == h
    ids.unregister(oid)
    assert ids.get_object_by_id(oid) is None
    assert _h.combat_find_by_obj_id(oid) == -1
    assert _live(h)
    ids.register(obj)
    assert _h.combat_find_by_obj_id(oid) == h
    # Off the main thread: queued like a push, applied at the drain.
    _in_thread(lambda: ids.unregister(oid))
    assert _h.combat_find_by_obj_id(oid) == h
    nc.drain()
    assert _h.combat_find_by_obj_id(oid) == -1
    del obj
    gc.collect()
    nc.drain()
    assert not _live(h)


def test_a_long_pending_free_list_is_logged_once(monkeypatch, capsys):
    """M9: nothing drains while no tick runs (a menu, a pre-boot screen):
    the frees pile up. Past the bound, one line on stderr."""
    monkeypatch.setattr(nc, "PENDING_FREES_WARN", 3)
    for _ in range(3):
        nc.defer_free()
    assert "[native-combat]" not in capsys.readouterr().err
    for _ in range(5):
        nc.defer_free()
    err = capsys.readouterr().err
    assert err.count("[native-combat]") == 1, err
    assert "pending" in err
    nc.drain()
    assert nc.pending_frees() == []


def test_a_drain_skipped_at_the_tick_boundary_by_an_open_session_is_logged(
        capsys):
    """M9: a K1 session leaked open (K1 nests, so the next begin does not
    throw) stops every drain. At a tick boundary no session should be open:
    a drain skipped there says so, once."""
    from engine import host_loop
    nc.configure(ON)
    obj = _object()
    h = obj.__dict__["_nslot"]
    t, use_memo, drift = nc._k1_clocks()
    _h.combat_k1_begin_pump([], 1.0 / 60.0, t, use_memo, drift)
    try:
        _forget(obj)
        del obj
        gc.collect()
        host_loop._combat_tick_boundary()
        host_loop._combat_tick_boundary()
        assert _live(h)
        err = capsys.readouterr().err
        assert err.count("[native-combat]") == 1, err
        assert "session" in err
        nc.drain()                          # mid-tick: an open session is
        assert "[native-combat]" not in capsys.readouterr().err   # normal
    finally:
        _h.combat_k1_abandon()
    host_loop._combat_tick_boundary()
    assert not _live(h)


def test_a_paused_frame_drains():
    """M9: a paused frame runs no tick, so no tick boundary drains. run()'s
    paused-frame branch (`if pause.sim_frozen:`) drains instead.
    STRUCTURAL, like tests/unit/test_spv_anchor_pose.py's: run() has no seam
    to execute one frame from a test."""
    import ast
    from engine import host_loop
    tree = ast.parse(host_frame_source.run_source())
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.If)
                and isinstance(node.test, ast.Attribute)
                and node.test.attr == "sim_frozen"):
            continue
        for stmt in node.body:
            for inner in ast.walk(stmt):
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == "drain"
                        and isinstance(inner.func.value, ast.Name)
                        and inner.func.value.id == "_native_combat"):
                    found.append(inner)
    assert len(found) == 1, found
