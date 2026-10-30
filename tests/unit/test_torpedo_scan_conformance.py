"""The incoming-torpedo table: one contract, both backends, and the answer of
the Python walk it replaced.

App.AIScriptAssist_GetIncomingTorpIDsInSet used to walk projectiles._active
in Python, calling _closing_time per torpedo -- over half of all AI time in a
64-ship fight. It now asks a table (engine/appc/torpedo_scan.py; native in the
host, pure Python headless). This file proves three things:

  * both backends obey the same contract (as the transform store's do);
  * the table's answer is the reference walk's, id for id and in order, over
    randomised fights -- including borderline thresholds, which is where a
    fused multiply-add in the native kernel would show;
  * projectiles keeps the table in step with every way the torpedo list and a
    torpedo's own velocity, source and set change.
"""
import random

import pytest

import App
from engine.appc import projectiles, torpedo_scan
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem
from engine.appc.transform_store import PythonTransformStore, get_store

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

_HAS_NATIVE = _h is not None and hasattr(_h, "torpedo_scan_add")

SET = 7


def _python_scan():
    store = PythonTransformStore()
    return torpedo_scan.PythonTorpedoScan(store), store


def _native_scan():
    from engine.appc.transform_store import NativeTransformStore
    scan = torpedo_scan.NativeTorpedoScan(_h)
    scan.clear()
    return scan, NativeTransformStore(_h)


BACKENDS = [
    pytest.param(_python_scan, id="python"),
    pytest.param(_native_scan, id="native", marks=pytest.mark.skipif(
        not _HAS_NATIVE, reason="native torpedo_scan bindings not built")),
]


@pytest.fixture(params=BACKENDS)
def backend(request):
    scan, store = request.param()
    handles = []

    def torp(tid, pos, vel, group=SET, source=None):
        h = store.alloc()
        handles.append(h)
        store.set_position(*h, *pos)
        scan.add(tid, h[0], h[1], *vel, source is not None,
                 source or 0, group)
        return h

    yield scan, store, torp
    scan.clear()
    for h in handles:
        try:
            store.free(*h)
        except Exception:
            pass


def _ask(scan, threshold, match=False, firing=0, offsets=((SET, 0, 0, 0),),
         obs=(0.0, 0.0, 0.0), obs_vel=(0.0, 0.0, 0.0)):
    return scan.incoming(obs, obs_vel, threshold, match, firing, list(offsets))


# ── The contract ─────────────────────────────────────────────────────────────

def test_lists_only_torpedoes_closing_within_the_threshold(backend):
    scan, _store, torp = backend
    torp(1, (0, 100, 0), (0, -50, 0))
    torp(2, (0, 100, 0), (0, 50, 0))
    torp(3, (0, 1000, 0), (0, -10, 0))
    assert _ask(scan, 18.0) == [1]


def test_a_group_with_no_offset_is_another_frame(backend):
    scan, _store, torp = backend
    torp(1, (0, 100, 0), (0, -50, 0), group=SET)
    torp(2, (0, 100, 0), (0, -50, 0), group=99)
    assert _ask(scan, 18.0) == [1]
    assert _ask(scan, 18.0, offsets=[(SET, 0, -1000, 0)]) == []


def test_the_source_filter(backend):
    scan, _store, torp = backend
    torp(1, (0, 100, 0), (0, -50, 0), source=40)
    torp(2, (0, 100, 0), (0, -50, 0), source=41)
    torp(3, (0, 100, 0), (0, -50, 0))
    assert _ask(scan, 18.0, match=True, firing=40) == [1]
    assert _ask(scan, 18.0) == [1, 2, 3]


def test_order_survives_removal(backend):
    scan, _store, torp = backend
    for i in range(1, 201):
        torp(i, (0, 100, 0), (0, -50, 0))
    for i in range(1, 201, 2):
        assert scan.remove(i) is True
    assert scan.remove(1) is False
    torp(500, (0, 100, 0), (0, -50, 0))
    assert _ask(scan, 18.0) == list(range(2, 201, 2)) + [500]
    assert scan.size() == 101


def test_updates_and_live_positions(backend):
    scan, store, torp = backend
    h = torp(1, (0, 1000, 0), (0, 50, 0))
    assert _ask(scan, 18.0) == []
    scan.set_velocity(1, 0, -50, 0)
    assert _ask(scan, 18.0) == []          # ETA 20 s
    store.set_position(*h, 0, 100, 0)
    assert _ask(scan, 18.0) == [1]
    scan.set_group(1, 99)
    assert _ask(scan, 18.0) == []
    scan.set_group(1, SET)
    scan.set_source(1, True, 40)
    assert _ask(scan, 18.0, match=True, firing=41) == []
    scan.set_velocity(5, 1, 1, 1)          # unknown id: ignored
    assert scan.size() == 1


# ── Agreement with the reference walk ───────────────────────────────────────

@pytest.fixture
def space():
    projectiles._active.clear()
    s = App.SetClass_Create()
    yield s
    projectiles._active.clear()


def _ship(space, x, y, z, vel=(0.0, 0.0, 0.0)):
    s = ShipClass()
    s._hull = HullSubsystem("H")
    s._hull.SetMaxCondition(1000.0)
    s.SetWorldLocation(TGPoint3(x, y, z))
    s.SetVelocity(TGPoint3(*vel))
    space.AddObjectToSet(s, "Ship%d" % id(s))
    return s


def _torp(space, pos, vel, source=None):
    t = projectiles.Torpedo()
    t.SetTranslateXYZ(*pos)
    t._velocity = TGPoint3(*vel)
    t._source_ship = source
    projectiles.register(t)
    if t.GetContainingSet() is None:
        space.AddObjectToSet(t, "Torp%d" % t._id)
    return t


def _reference(observer, threshold, firing, match):
    return [t.GetObjID() for t in projectiles._active
            if projectiles.is_incoming(observer, t, threshold, firing, match)]


@pytest.mark.parametrize("seed", range(12))
def test_the_table_answers_what_the_walk_answered(space, seed):
    rng = random.Random(seed)
    ships = [_ship(space, *(rng.uniform(-300, 300) for _ in range(3)),
                   vel=tuple(rng.uniform(-10, 10) for _ in range(3)))
             for _ in range(6)]
    for _ in range(300):
        _torp(space, tuple(rng.uniform(-400, 400) for _ in range(3)),
              tuple(rng.uniform(-60, 60) for _ in range(3)),
              source=rng.choice(ships + [None]))
    for observer in ships:
        for threshold in (0.5, 3.0, 18.0, 3600.0):
            for firing, match in ((App.NULL_ID, False),
                                  (ships[0].GetObjID(), True)):
                got = projectiles.incoming_ids(observer, threshold, firing, match)
                assert got == _reference(observer, threshold, firing, match)


def test_borderline_thresholds_agree_to_the_bit(space):
    # Every torpedo's own ETA, taken as the threshold: the compare sits
    # exactly on the boundary, so any rounding difference between the kernel
    # and _closing_time flips the answer.
    rng = random.Random(99)
    observer = _ship(space, 1.5, -2.25, 3.0, vel=(0.3, -0.7, 1.1))
    torps = [_torp(space, tuple(rng.uniform(-400, 400) for _ in range(3)),
                   tuple(rng.uniform(-60, 60) for _ in range(3)))
             for _ in range(400)]
    for t in torps:
        eta = projectiles._closing_time(observer, t)
        if eta is None:
            continue
        for threshold in (eta, eta * (1 - 1e-16), eta * (1 + 1e-16)):
            got = projectiles.incoming_ids(observer, threshold, App.NULL_ID, False)
            assert got == _reference(observer, threshold, App.NULL_ID, False)


# ── projectiles keeps the table in step ─────────────────────────────────────

def _ids(observer):
    return projectiles.incoming_ids(observer, 18.0, App.NULL_ID, False)


def test_a_velocity_change_after_launch_is_seen(space):
    ship = _ship(space, 0, 0, 0)
    t = _torp(space, (0, 100, 0), (0, 50, 0))
    assert _ids(ship) == []
    t._velocity = TGPoint3(0, -50, 0)
    assert _ids(ship) == [t.GetObjID()]


def test_a_source_change_after_launch_is_seen(space):
    ship = _ship(space, 0, 0, 0)
    shooter = _ship(space, 0, 500, 0)
    t = _torp(space, (0, 100, 0), (0, -50, 0))
    assert projectiles.incoming_ids(ship, 18.0, shooter.GetObjID(), True) == []
    t._source_ship = shooter
    assert projectiles.incoming_ids(
        ship, 18.0, shooter.GetObjID(), True) == [t.GetObjID()]


def test_leaving_the_set_is_seen(space):
    ship = _ship(space, 0, 0, 0)
    t = _torp(space, (0, 100, 0), (0, -50, 0))
    assert _ids(ship) == [t.GetObjID()]
    space.RemoveObjectFromSet(t.GetName())
    assert _ids(ship) == []
    space.AddObjectToSet(t, "Torp back")
    assert _ids(ship) == [t.GetObjID()]


def test_expire_and_every_list_mutation_are_seen(space):
    ship = _ship(space, 0, 0, 0)
    a = _torp(space, (0, 100, 0), (0, -50, 0))
    b = _torp(space, (0, 100, 0), (0, -50, 0))
    projectiles.expire(a)
    assert _ids(ship) == [b.GetObjID()]
    projectiles._active.clear()
    assert _ids(ship) == []
    space.AddObjectToSet(a, "Torp a again")   # expire took it out of the set
    # Fixtures put torpedoes on the list by hand, without register().
    projectiles._active.append(b)
    assert _ids(ship) == [b.GetObjID()]
    projectiles._active.insert(0, a)
    assert _ids(ship) == [a.GetObjID(), b.GetObjID()]
    projectiles._active.remove(a)
    assert _ids(ship) == [b.GetObjID()]
    projectiles._active[:] = [a, b]
    assert _ids(ship) == [a.GetObjID(), b.GetObjID()]
    del projectiles._active[0]
    assert _ids(ship) == [b.GetObjID()]
    assert projectiles._active.pop() is b
    assert _ids(ship) == []


def test_a_replaced_list_falls_back_to_the_walk(space, monkeypatch):
    ship = _ship(space, 0, 0, 0)
    t = projectiles.Torpedo()
    t.SetTranslateXYZ(0, 100, 0)
    t._velocity = TGPoint3(0, -50, 0)
    space.AddObjectToSet(t, "Loose")
    monkeypatch.setattr(projectiles, "_active", [t])
    assert _ids(ship) == [t.GetObjID()]


def test_the_backend_follows_the_transform_store():
    # Rows hold transform handles, so the table must index the same store
    # every ObjectClass allocates from.
    scan = torpedo_scan.get_scan()
    if isinstance(get_store(), PythonTransformStore):
        assert isinstance(scan, torpedo_scan.PythonTorpedoScan)
    else:
        assert isinstance(scan, torpedo_scan.NativeTorpedoScan)
