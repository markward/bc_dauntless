"""Every mutation that can change a ProximityManager candidate list bumps
proximity_cache's generation; no-op calls do not."""
import App
from engine.appc import proximity_cache
from engine.appc.ai import ProximityCheck
from engine.appc.planet import ProximityManager
from engine.appc.projectiles import Torpedo


class _Probe:
    def __enter__(self):
        self.start = proximity_cache.generation()
        return self

    def __exit__(self, *a):
        return False

    @property
    def bumped(self):
        return proximity_cache.generation() != self.start


def _ship():
    return App.ShipClass_Create()


def test_add_under_new_name_bumps():
    s = App.SetClass_Create()
    with _Probe() as p:
        s.AddObjectToSet(_ship(), "A")
    assert p.bumped


def test_readd_under_existing_name_bumps():
    s = App.SetClass_Create()
    s.AddObjectToSet(_ship(), "A")
    with _Probe() as p:
        s.AddObjectToSet(_ship(), "A")
    assert p.bumped


def test_torpedo_over_non_torpedo_bumps():
    s = App.SetClass_Create()
    s.AddObjectToSet(_ship(), "A")
    with _Probe() as p:
        s.AddObjectToSet(Torpedo(), "A")
    assert p.bumped


def test_non_torpedo_over_torpedo_bumps():
    s = App.SetClass_Create()
    s.AddObjectToSet(Torpedo(), "A")
    with _Probe() as p:
        s.AddObjectToSet(_ship(), "A")
    assert p.bumped


def test_remove_bumps_after_handlers():
    s = App.SetClass_Create()
    ship = _ship()
    s.AddObjectToSet(ship, "A")
    seen = []
    import engine.appc.sets as sets
    orig = sets.SetClass._broadcast_set_transition

    def spy(self, obj, **kw):
        seen.append(proximity_cache.generation())
        return orig(self, obj, **kw)
    sets.SetClass._broadcast_set_transition = spy
    try:
        start = proximity_cache.generation()
        s.RemoveObjectFromSet("A")
    finally:
        sets.SetClass._broadcast_set_transition = orig
    assert seen[0] == start
    assert proximity_cache.generation() != start


def test_delete_bumps():
    s = App.SetClass_Create()
    s.AddObjectToSet(_ship(), "A")
    with _Probe() as p:
        s.DeleteObjectFromSet("A")
    assert p.bumped


def test_torpedo_radius_transitions_bump():
    t = Torpedo()
    with _Probe() as p:
        t.SetRadius(0.5)
    assert p.bumped
    with _Probe() as p:
        t.SetRadius(0.0)
    assert p.bumped


def test_torpedo_radius_without_transition_does_not_bump():
    t = Torpedo()
    with _Probe() as p:
        t.SetRadius(0.0)
    assert not p.bumped
    t.SetRadius(0.5)
    with _Probe() as p:
        t.SetRadius(0.7)
    assert not p.bumped


def test_manager_add_update_remove_bump_only_on_change():
    s = App.SetClass_Create()
    m = ProximityManager(s)
    o = _ship()
    with _Probe() as p:
        m.AddObject(o)
    assert p.bumped
    with _Probe() as p:
        m.AddObject(o)
        m.UpdateObject(o)
    assert not p.bumped
    o2 = _ship()
    with _Probe() as p:
        m.UpdateObject(o2)
    assert p.bumped
    with _Probe() as p:
        m.RemoveObject(o2)
    assert p.bumped
    with _Probe() as p:
        m.RemoveObject(o2)
    assert not p.bumped


def test_manager_add_update_remove_of_a_check_does_not_bump():
    # Checks are never candidates (_Cand skips them in both sections), and
    # ConditionInRange re-registers its check on every retarget.
    m = ProximityManager(App.SetClass_Create())
    c = ProximityCheck(event_type=999)
    with _Probe() as p:
        m.AddObject(c)
        m.RemoveObject(c)
        m.UpdateObject(c)
        m.RemoveObject(c)
    assert not p.bumped
    assert c not in m._objects
    m.AddObject(c)
    assert c in m._objects                  # still registered for the evaluator


def test_class_swap_bumps():
    from engine.appc import native_combat
    with _Probe() as p:
        native_combat.reclassify(_ship())
    assert p.bumped


def test_torpedo_launch_into_fresh_key_does_not_bump():
    s = App.SetClass_Create()
    with _Probe() as p:
        s.AddObjectToSet(Torpedo(), "T1")
    assert not p.bumped


def test_torpedo_replacing_torpedo_key_does_not_bump():
    s = App.SetClass_Create()
    s.AddObjectToSet(Torpedo(), "T1")
    with _Probe() as p:
        s.AddObjectToSet(Torpedo(), "T1")
    assert not p.bumped


def test_torpedo_remove_and_delete_do_not_bump():
    s = App.SetClass_Create()
    s.AddObjectToSet(Torpedo(), "T1")
    s.AddObjectToSet(Torpedo(), "T2")
    with _Probe() as p:
        s.RemoveObjectFromSet("T1")
        s.DeleteObjectFromSet("T2")
    assert not p.bumped


def test_remove_and_delete_of_absent_name_do_not_bump():
    s = App.SetClass_Create()
    with _Probe() as p:
        s.RemoveObjectFromSet("nope")
        s.DeleteObjectFromSet("nope")
    assert not p.bumped
