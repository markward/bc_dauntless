"""The K3 torpedo kernel's Python bindings (native combat phase 3, Task 4;
native/src/combat/include/dauntless/combat/k3_projectiles.h).

Real ships and torpedoes with native combat on, driven through
combat_k3_begin / next / answer / end by hand: the record layouts Task 5's
driver consumes, the answers each ASK takes, the store and row writes made
at DONE, and the reasons begin hands a whole step to Python. The kernel's
walk itself is pinned by native/tests/combat/k3_projectiles_test.cc; the
native-vs-Python differential is Task 5's. Floats compare by .hex().
"""
import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_k3_begin"),
    reason="native K3 bindings not built")

import engine.host_loop as host_loop  # noqa: E402,F401  (K2's class snapshot)
from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import projectiles  # noqa: E402
from engine.appc.math import TGPoint3  # noqa: E402
from engine.appc.projectiles import Torpedo  # noqa: E402
from engine.appc.sets import SetClass  # noqa: E402
from engine.appc.ships import ShipClass  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
DT = 1.0 / 60.0
SET = "K3BindSet"
SET2 = "K3BindSet2"


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    nc.configure(ON)
    assert nc.enabled()
    nc.torpedo_table_rebuild(projectiles._active)
    if _h.combat_k3_open():
        _h.combat_k3_abandon()
    _h.combat_k3_reset_counts()
    yield
    if _h.combat_k3_open():
        _h.combat_k3_abandon()
    for t in list(projectiles._active):
        projectiles.expire(t)
    App.g_kSetManager._sets.pop(SET, None)
    nc.reset()


class World:
    pass


def _ship(pSet, name, at, radius=2.0):
    s = ShipClass()
    s.SetName(name)
    s.SetTranslateXYZ(*at)
    s.SetRadius(radius)
    pSet.AddObjectToSet(s, name)
    return s


@pytest.fixture
def world():
    w = World()
    w.set = SetClass()
    w.set.SetName(SET)
    App.g_kSetManager._sets[SET] = w.set
    w.x = _ship(w.set, "K3BindX", (0.0, 50.0, 0.0))
    w.src = _ship(w.set, "K3BindSrc", (500.0, 0.0, 0.0))
    w.ships = [w.x, w.src]
    return w


def _fire(w, at, vel, target=None):
    t = Torpedo()
    t._source_ship = w.src
    t.SetTranslateXYZ(*at)
    t._velocity = TGPoint3(*vel)
    if target is not None:
        t._target_ship = target
    projectiles.register(t)          # joins the source's set; a table row
    assert "_k3_row" in t.__dict__
    return t


def _row(t):
    return t.__dict__["_k3_row"]


def _slot(obj):
    return obj.__dict__["_nslot"]


def _hx(xyz):
    return tuple(float(c).hex() for c in xyz)


def _begin(n_active=None, use_memo=False):
    if n_active is None:
        n_active = len(projectiles._active)
    return _h.combat_k3_begin(DT, (0.0, 0.0), use_memo,
                              {"n_active": n_active})


def test_done_layout_writes_and_expiry_order(world):
    w = world
    kinds = _h.combat_k3_kinds()
    assert kinds == {"DONE": 0, "ASK": 1}
    hit = _fire(w, (0.0, 40.0, 0.0), (0.0, 600.0, 0.0))
    ttl = _fire(w, (0.0, -500.0, 0.0), (0.0, 600.0, 0.0))
    ttl._age = 59.99
    st = nc.step_scan(w.ships)
    assert st.ok, st.reason
    assert _begin() is None
    rec = _h.combat_k3_next()
    assert rec[0] == kinds["DONE"] and len(rec) == 4
    _, writes, expired, hits = rec
    # TTL expiries first, then hits.
    assert expired == [_row(ttl), _row(hit)]
    assert hits == [(_row(hit), _slot(w.x), (0.0, 50.0, 0.0), "fallback",
                     None, None, False)]
    by = {wr[0]: wr for wr in writes}
    assert [wr[0] for wr in writes] == [_row(hit), _row(ttl)]
    assert by[_row(hit)][1].hex() == (0.0 + DT).hex()
    assert by[_row(ttl)][1].hex() == (59.99 + DT).hex()
    assert by[_row(hit)][2:] == (None,) * 4   # not guided, no attribution
    # The kernel wrote the store at DONE: Python reads it back.
    p = hit.GetTranslate()
    assert _hx((p.x, p.y, p.z)) == _hx((0.0, 50.0, 0.0))
    q = ttl.GetTranslate()
    assert _hx((q.x, q.y, q.z)) == _hx((0.0, -500.0 + 600.0 * DT, 0.0))
    # ... and the row (Python copies the log without pushing).
    assert float(_h.combat_torp_dump(_row(ttl))["age"]).hex() == \
        (59.99 + DT).hex()
    _h.combat_k3_end()
    c = _h.combat_k3_counts()
    assert c["k3_runs"] == 1 and c["k3_python_steps"] == 0
    assert set(c["k3_asks"]) == {"frame", "steer_point", "guide",
                                 "shields_block", "bubble", "resolve_hit"}
    assert set(c["k3_python_reasons"]) == {
        "scan", "table", "unrepresentable", "stale_ref", "torpedo_xform",
        "ship_cache"}


def test_native_attribution_rides_on_done(world):
    """An unattributed mount the kernel can attribute itself (round trips,
    Task 4): no ASK; DONE's write carries (target, offset, sub) -- here no
    mount claims the offset, sub -1 -- and the row holds the key; the next
    tick attributes nothing."""
    w = world
    t = _fire(w, (0.0, -100.0, 0.0), (0.0, 60.0, 0.0), target=w.x)
    t.SetTargetOffset(TGPoint3(1.0, 0.25, -0.5))
    assert nc.step_scan(w.ships).ok
    assert _begin() is None
    rec = _h.combat_k3_next()
    assert rec[0] == 0
    (wr,) = rec[1]
    assert len(wr) == 6 and wr[5] == (_slot(w.x), (1.0, 0.25, -0.5), -1)
    _h.combat_k3_end()
    row = _h.combat_torp_dump(_row(t))
    assert (row["mount_attributed"], row["mount_sub"],
            tuple(row["mount_offset"])) == (1, -1, (1.0, 0.25, -0.5))
    assert nc.step_scan(w.ships).ok
    assert _begin() is None
    assert _h.combat_k3_next()[1][0][5] is None
    _h.combat_k3_end()
    c = _h.combat_k3_counts()
    assert c["k3_native_attributions"] == 1
    assert c["k3_asks"]["steer_point"] == 0


def test_steer_point_ask_round_trip(world):
    """A steer point the kernel cannot decide (here: the target's mount
    order opens with an entry the mirror cannot name, so it cannot
    attribute the offset -- unattributed): ASK steer_point(torp, target,
    off); Python's _steer_point writes `_mount_key` (pushed) and answers
    the point, and DONE logs no `_mount_key` of its own."""
    w = world
    t = _fire(w, (0.0, -100.0, 0.0), (0.0, 60.0, 0.0), target=w.x)
    t.SetTargetOffset(TGPoint3(1.0, 0.0, 0.0))
    order = _h.combat_dump(_slot(w.x))["mount_order"]
    _h.combat_set_mount_order(_slot(w.x), [-2] + list(order))
    assert nc.step_scan(w.ships).ok
    assert _begin() is None
    rec = _h.combat_k3_next()
    assert rec[:2] == (_h.combat_k3_kinds()["ASK"], "steer_point")
    torp, target, off = rec[2:]
    assert (torp, target, off) == (_row(t), _slot(w.x), (0.0, 0.0, 0.0))
    p = projectiles._steer_point(t, w.x, off)
    assert t._mount_key is not None
    _h.combat_k3_answer((p.x, p.y, p.z))
    rec = _h.combat_k3_next()
    assert rec[0] == 0
    (wr,) = rec[1]
    assert wr[0] == _row(t)
    assert wr[2] == (p.x, p.y, p.z)            # last_seen is the point
    assert wr[3] is not None and wr[4] is not None
    assert wr[5] is None                       # Python wrote the key
    _h.combat_k3_end()
    # Next tick: attributed, so no ASK.
    assert nc.step_scan(w.ships).ok
    assert _begin() is None
    assert _h.combat_k3_next()[0] == 0
    _h.combat_k3_end()
    assert _h.combat_k3_counts()["k3_asks"]["steer_point"] == 1


@pytest.fixture
def two_sets(world):
    """A target in a SECOND set: the guide's offset_between must resolve
    both sets' frames (one set short-circuits to zeros, frames unread)."""
    w = world
    w.other = SetClass()
    w.other.SetName(SET2)
    App.g_kSetManager._sets[SET2] = w.other
    w.y = _ship(w.other, "K3BindY", (0.0, 100.0, 0.0))
    w.ships = [w.x, w.src, w.y]
    yield w
    App.g_kSetManager._sets.pop(SET2, None)


def test_frame_ask_answered_from_the_step_keys(two_sets):
    """A set with no frame-table entry asks `frame`; the answer is
    (key_id, ax, ay, az) interned in the step's key table. Two plain sets
    are two frames, so the shot goes ballistic (no guide write)."""
    w = two_sets
    t = _fire(w, (0.0, -100.0, 0.0), (0.0, 60.0, 0.0), target=w.y)
    st = nc.step_scan(w.ships)
    assert st.ok
    _h.combat_step_frames([])        # drop the table: every compare asks
    assert _begin() is None
    asked = []
    for _ in range(10):
        rec = _h.combat_k3_next()
        if rec[0] == 0:
            break
        assert rec[1] == "frame"
        asked.append(rec[2])
        (entry,) = nc._step_frames([rec[2]], st.keys)
        _h.combat_k3_answer(entry[1:])
    # torpedo set first (offset_between looks `a` up first), then the
    # target's; each installed once, so the broadphase asks nothing.
    assert asked == [_slot(w.set), _slot(w.other)]
    (wr,) = rec[1]
    assert wr[0] == _row(t) and wr[2:] == (None,) * 4
    _h.combat_k3_end()
    assert _h.combat_k3_counts()["k3_asks"]["frame"] == 2


def test_frame_ask_answered_none(two_sets):
    """frame_of None (key -1): no frame, so the shot is ballistic."""
    w = two_sets
    _fire(w, (0.0, -100.0, 0.0), (0.0, 60.0, 0.0), target=w.y)
    assert nc.step_scan(w.ships).ok
    _h.combat_step_frames([])
    assert _begin() is None
    rec = _h.combat_k3_next()
    assert rec[1] == "frame"
    while rec[0] != 0:
        _h.combat_k3_answer(None)
        rec = _h.combat_k3_next()
    assert rec[1][0][2:] == (None,) * 4
    _h.combat_k3_end()


def test_whole_step_reasons(world):
    w = world
    _fire(w, (0.0, -100.0, 0.0), (0.0, 60.0, 0.0))
    _h.combat_step_reset()           # no representable scan this step
    assert _begin() == "scan"
    assert not _h.combat_k3_open()
    assert nc.step_scan(w.ships).ok
    assert _begin(n_active=len(projectiles._active) + 1) == "table"
    c = _h.combat_k3_counts()
    assert c["k3_python_steps"] == 2
    assert c["k3_python_reasons"]["scan"] == 1
    assert c["k3_python_reasons"]["table"] == 1
    with pytest.raises(ValueError):
        _h.combat_k3_begin(DT, (0.0, 0.0), False, {})   # no n_active


def test_protocol_errors_raise(world):
    w = world
    _fire(w, (0.0, -100.0, 0.0), (0.0, 60.0, 0.0), target=w.x)
    with pytest.raises(RuntimeError):
        _h.combat_k3_next()          # no session
    assert nc.step_scan(w.ships).ok
    assert _begin() is None
    with pytest.raises(RuntimeError):
        _begin()                     # a session is open
    with pytest.raises(RuntimeError):
        _h.combat_k3_end()           # not DONE
    _h.combat_k3_abandon()
    assert not _h.combat_k3_open()


def test_resolve_hit_answer_shape_is_checked(world):
    """A resolve_hit answer that is not ((x, y, z), normal or None, tier)
    raises ValueError naming the shape, as the frame answer does (not a
    bare IndexError from the tuple)."""
    w = world
    _fire(w, (0.0, 40.0, 0.0), (0.0, 600.0, 0.0))
    assert nc.step_scan(w.ships).ok
    # The target has an instance but its set no view offset: Python's
    # _resolve_hit_point answers.
    assert _h.combat_k3_begin(
        DT, (0.0, 0.0), False,
        {"n_active": len(projectiles._active), "iids": {_slot(w.x): 1},
         "view_offsets": {}}) is None
    rec = _h.combat_k3_next()
    assert rec[1] == "resolve_hit"
    for bad in (((0.0, 50.0, 0.0), None),
                ((0.0, 50.0, 0.0), None, "mesh", 1)):
        with pytest.raises(ValueError, match=r"resolve_hit answer is"):
            _h.combat_k3_answer(bad)
    _h.combat_k3_answer(((0.0, 50.0, 0.0), None, "fallback"))
    assert _h.combat_k3_next()[0] == 0
    _h.combat_k3_end()
