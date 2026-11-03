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
    nc.k1_pump([], 1.0 / 60.0, lambda ship, getter: None)
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
