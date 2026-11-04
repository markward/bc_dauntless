"""Objects that leave a set leave its manager list (ruling 6, native proximity
phase 1, Task 6; spec docs/superpowers/specs/2026-11-03-native-motion-and-
proximity-design.md s3).

Quick Battle UpdateObject's every ship into its set's ProximityManager at
spawn and nothing ever RemoveObject's it, so a ship that left the set (an
evicted hulk, a ship deleted at End Combat, a ship that warped away) stayed a
manager entry and AI nearby-object queries kept returning it: a ghost
(docs/reference/engine/native-motion/proximity-membership-map.md s2). Leaving
the set now also drops it from that set's manager list. Hulks still in the set
(up to ship_death.MAX_HULKS) are members and stay returned.
"""
import gc

import pytest

import App
from engine.appc import projectiles
from engine.appc import ship_death
from engine.appc.math import TGPoint3


@pytest.fixture(autouse=True)
def _clean():
    ship_death.reset()
    yield
    ship_death.reset()
    projectiles._active.clear()


def _qb_ship(pSet, name, xyz):
    """A ship as Quick Battle spawns one: in the set, then UpdateObject'd
    into the set's manager (engine/quickbattle/spawn.py)."""
    s = App.ShipClass_Create()
    pSet.AddObjectToSet(s, name)
    s.SetTranslateXYZ(*xyz)
    pSet.GetProximityManager().UpdateObject(s)
    return s


def _near(pm, xyz=(0.0, 0.0, 0.0), radius=1.0e5):
    return list(pm.GetNearObjects(TGPoint3(*xyz), radius))


def _held_by_manager(pm, obj):
    """Every place the manager can keep `obj`: its list and its cache."""
    in_list = any(o is obj for o in pm._objects)
    cand = pm._cand
    in_cand = cand is not None and any(o is obj for o in cand.objs)
    return in_list or in_cand


def _kill_to_hulk(ship):
    ship_death.begin(ship)
    ship_death.advance(ship_death.MAX_THROES_DURATION)


def _nine_hulks():
    pSet = App.SetClass_Create()
    pm = pSet.GetProximityManager()
    ships = [_qb_ship(pSet, "Hulk%d" % i, (100.0 * i, 0.0, 0.0))
             for i in range(ship_death.MAX_HULKS + 1)]
    for s in ships:
        _kill_to_hulk(s)
        _near(pm)                       # a cache is built between deaths
    return pSet, pm, ships


def test_evicted_hulk_is_not_returned():
    pSet, pm, ships = _nine_hulks()
    oldest = ships[0]
    assert pSet.GetObject("Hulk0") is None, "the ninth hulk evicts the oldest"
    assert _near(pm, (0.0, 0.0, 0.0), 1.0) == []
    assert not any(o is oldest for o in pm._objects)


def test_hulk_still_in_set_is_returned():
    pSet, pm, ships = _nine_hulks()
    assert _near(pm) == ships[1:]


def test_ship_deleted_at_end_combat_is_not_returned():
    pSet = App.SetClass_Create()
    pm = pSet.GetProximityManager()
    a = _qb_ship(pSet, "A", (0.0, 0.0, 0.0))
    b = _qb_ship(pSet, "B", (5.0, 0.0, 0.0))
    assert _near(pm) == [a, b]
    pSet.DeleteObjectFromSet("B")
    assert _near(pm) == [a]
    assert not any(o is b for o in pm._objects)


def test_ship_that_warped_out_is_not_returned():
    battle = App.SetClass_Create()
    warp_set = App.SetClass_Create()
    pm = battle.GetProximityManager()
    a = _qb_ship(battle, "A", (0.0, 0.0, 0.0))
    b = _qb_ship(battle, "B", (5.0, 0.0, 0.0))
    assert _near(pm) == [a, b]
    # As engine/appc/warp.py moves a ship between sets.
    battle.RemoveObjectFromSet("B")
    warp_set.AddObjectToSet(b, "B")
    assert _near(pm) == [a]
    assert not any(o is b for o in pm._objects), "the set move left an entry"
    assert _near(warp_set.GetProximityManager()) == [b]


def test_qb_ship_reentering_the_set_is_returned_once():
    pSet = App.SetClass_Create()
    pm = pSet.GetProximityManager()
    a = _qb_ship(pSet, "A", (0.0, 0.0, 0.0))
    b = _qb_ship(pSet, "B", (5.0, 0.0, 0.0))
    assert _near(pm) == [a, b]
    pSet.RemoveObjectFromSet("B")
    # As engine/quickbattle/sim_restore.py _return_home re-adds one.
    pSet.AddObjectToSet(b, "B")
    pm.UpdateObject(b)
    assert _near(pm) == [a, b]
    assert sum(1 for o in pm._objects if o is b) == 1


def test_object_still_in_set_under_another_name_stays_in_the_manager():
    pSet = App.SetClass_Create()
    pm = pSet.GetProximityManager()
    a = _qb_ship(pSet, "A", (0.0, 0.0, 0.0))
    pSet.AddObjectToSet(a, "A2")
    pSet.RemoveObjectFromSet("A")
    assert any(o is a for o in pm._objects), "A has not left the set"
    assert _near(pm) == [a]


def test_departed_object_no_longer_kept_alive_by_the_manager():
    """engine.core.ids holds every object strongly, so a weakref never dies
    here; pin the manager's side instead: once the object has left, nothing
    the manager owns refers to it -- not its list, not its cached
    candidates -- even if the manager is never queried again."""
    pSet = App.SetClass_Create()
    pm = pSet.GetProximityManager()
    _qb_ship(pSet, "A", (0.0, 0.0, 0.0))
    b = _qb_ship(pSet, "B", (5.0, 0.0, 0.0))
    _near(pm)                               # B is now in the cache too
    assert _held_by_manager(pm, b)
    pSet.RemoveObjectFromSet("B")
    assert not _held_by_manager(pm, b)
    gc.collect()
    owned = [pm._objects]
    if pm._cand is not None:
        owned += [getattr(pm._cand, f) for f in type(pm._cand).__slots__]
    referrers = gc.get_referrers(b)
    assert not any(r is o for r in referrers for o in owned)
