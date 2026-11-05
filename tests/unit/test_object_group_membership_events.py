"""ObjectGroup ENTERED_SET / EXITED_SET events — spec #4.

ObjectGroup.SetEventFlag stored the flag and nothing ever posted the event:
13 SDK files subscribe, 21 SetEventFlag call sites. ConditionAllInSameSet
(25 mission AIs) and AnyInSameSet were frozen at their construction value."""
import pytest

import App
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_app_state()
    yield
    _reset_app_state()


class _Recorder:
    def __init__(self): self.events = []
    def Entered(self, evt): self.events.append(("in", evt.GetObjPtr(), evt.GetDestination()))
    def Exited(self, evt): self.events.append(("out", evt.GetObjPtr(), evt.GetDestination()))


def _subscribe(group):
    rec = _Recorder()
    w = App.TGPythonInstanceWrapper(); w.SetPyWrapper(rec)
    group.SetEventFlag(App.ObjectGroup.ENTERED_SET)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(App.ET_OBJECT_GROUP_OBJECT_ENTERED_SET, w, "Entered", group)
    group.SetEventFlag(App.ObjectGroup.EXITED_SET)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(App.ET_OBJECT_GROUP_OBJECT_EXITED_SET, w, "Exited", group)
    rec._w = w
    return rec


def _ship():
    s = ShipClass(); s._hull = HullSubsystem("H"); s._hull.SetMaxCondition(1000.0)
    return s


def test_add_to_set_posts_entered_to_the_watching_group():
    grp = ObjectGroup(); grp.AddName("Bart")
    rec = _subscribe(grp)
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = _ship(); pSet.AddObjectToSet(ship, "Bart")
    assert rec.events == [("in", ship, grp)]
    # The consumer reads the containing set off the object: it must be set by now.
    assert ship.GetContainingSet() is pSet


def test_remove_from_set_posts_exited():
    grp = ObjectGroup(); grp.AddName("Bart")
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = _ship(); pSet.AddObjectToSet(ship, "Bart")
    rec = _subscribe(grp)
    pSet.RemoveObjectFromSet("Bart")
    assert rec.events == [("out", ship, grp)]


def test_group_without_the_flag_or_the_name_is_silent():
    watching = ObjectGroup(); watching.AddName("Lisa")      # wrong name
    unflagged = ObjectGroup(); unflagged.AddName("Bart")    # right name, no flag
    rec_w = _subscribe(watching)
    rec_u = _Recorder(); w = App.TGPythonInstanceWrapper(); w.SetPyWrapper(rec_u)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(App.ET_OBJECT_GROUP_OBJECT_ENTERED_SET, w, "Entered", unflagged)
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    pSet.AddObjectToSet(_ship(), "Bart")
    assert rec_w.events == [] and rec_u.events == []


def test_non_ship_objects_also_post():
    from engine.appc.planet import Planet
    grp = ObjectGroup(); grp.AddName("Vulcan")
    rec = _subscribe(grp)
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    planet = Planet(); pSet.AddObjectToSet(planet, "Vulcan")
    assert [e[0] for e in rec.events] == ["in"]


def _raising_handler(pGroup, evt):
    raise RuntimeError("boom")


def test_throwing_group_handler_does_not_unwind_the_set_add(capfd):
    """A group's own instance handler -- registered via
    AddPythonFuncHandlerForInstance with a dotted function name, the way
    AddFleetCommandHandlers wires HelmMenuHandlers.FriendlyEnteredSet -- is
    reached through TGEventManager.AddEvent's UNguarded destination dispatch
    (dest.ProcessEvent(event)). If it raises, that must not unwind
    SetClass.AddObjectToSet: a set add is engine state and must never be
    undone by a downstream SDK handler failing, the same ruling as Task 12's
    DeleteObjectFromSet broadcast. A second, well-behaved group must still
    receive its event."""
    throwing = ObjectGroup()
    throwing.AddName("Bart")
    throwing.SetEventFlag(App.ObjectGroup.ENTERED_SET)
    throwing.AddPythonFuncHandlerForInstance(
        App.ET_OBJECT_GROUP_OBJECT_ENTERED_SET,
        "%s._raising_handler" % __name__,
    )

    healthy = ObjectGroup()
    healthy.AddName("Bart")
    rec = _subscribe(healthy)

    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = _ship()

    pSet.AddObjectToSet(ship, "Bart")  # must not raise

    assert pSet.GetObject("Bart") is ship
    assert ship.GetContainingSet() is pSet
    assert rec.events == [("in", ship, healthy)]

    out, err = capfd.readouterr()
    assert "[events] broadcast handler" in err


def test_set_event_flag_single_arg_applies_to_names_added_later():
    """Defensive, not traced: BC's single-arg SetEventFlag(flag) form has no
    documented "does it cover names added later" story, and the real SDK
    caller (ConditionExists.SetTarget) always calls RemoveAllNames()/AddName()
    BEFORE re-arming the flag, so this ordering is never actually exercised
    by ConditionExists. _default_flags exists so a caller that DOES arm the
    flag first still gets correct behaviour for names added afterward,
    rather than silently going deaf."""
    grp = ObjectGroup()
    grp.SetEventFlag(App.ObjectGroup.ENTERED_SET)  # called before any name exists
    grp.RemoveAllNames()
    grp.AddName("Homer")
    rec = _Recorder()
    w = App.TGPythonInstanceWrapper(); w.SetPyWrapper(rec)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(App.ET_OBJECT_GROUP_OBJECT_ENTERED_SET, w, "Entered", grp)
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = _ship(); pSet.AddObjectToSet(ship, "Homer")
    assert rec.events == [("in", ship, grp)]


def test_set_event_flag_re_registers_a_group_dropped_from_live():
    """host_loop.reset_sdk_globals clears ObjectGroup._live on every mission
    swap (Important 3, 2026-09-19 NPC AI contract review fix wave) -- there
    is no Game-level player group surviving a swap to justify keeping a
    prior mission's groups registered. A group that re-arms its flags after
    that reset (the SDK's own AddFleetCommandHandlers pattern: set flags when
    you register handlers) must be live again, or every group built before a
    swap goes permanently deaf even though it is still holding handlers."""
    grp = ObjectGroup(); grp.AddName("Bart")
    rec = _subscribe(grp)          # arms ENTERED_SET/EXITED_SET via SetEventFlag
    assert grp in ObjectGroup._live

    ObjectGroup._live.clear()      # simulate reset_sdk_globals on a mission swap
    assert grp not in ObjectGroup._live

    grp.SetEventFlag(App.ObjectGroup.ENTERED_SET)   # re-arm, as a re-registering caller would
    assert grp in ObjectGroup._live

    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = _ship(); pSet.AddObjectToSet(ship, "Bart")
    assert ("in", ship, grp) in rec.events


# ── The name index (phase 6 A3): broadcast_membership finds the groups
# watching a name through ObjectGroup._by_name, kept on AddName / RemoveName /
# RemoveAllNames and weak, so it never scans every live group for a name no
# group holds (every expiring torpedo's). When some group may match it runs
# the full scan over `_live`, so the delivery order is today's.

class _CountingLive(type(ObjectGroup._live)):
    """ObjectGroup._live that counts full iterations (the scan)."""
    iterations = 0

    def __iter__(self):
        type(self).iterations += 1
        return super().__iter__()


@pytest.fixture
def counting_live(monkeypatch):
    live = _CountingLive()
    for g in list(ObjectGroup._live):
        live.add(g)
    _CountingLive.iterations = 0
    monkeypatch.setattr(ObjectGroup, "_live", live)
    return _CountingLive


def _set(name="S"):
    pSet = App.SetClass_Create(); pSet.SetName(name)
    App.g_kSetManager._sets[name] = pSet
    return pSet


def test_a_name_no_group_holds_scans_no_group(counting_live):
    grps = [ObjectGroup() for _ in range(5)]
    for i, g in enumerate(grps):
        g.AddName("Ship %d" % i)
        _subscribe(g)
    pSet = _set()
    pSet.AddObjectToSet(_ship(), "Torpedo 1")
    pSet.RemoveObjectFromSet("Torpedo 1")
    assert counting_live.iterations == 0


def test_a_watched_name_still_reaches_its_group(counting_live):
    grp = ObjectGroup(); grp.AddName("Bart")
    rec = _subscribe(grp)
    ship = _ship(); _set().AddObjectToSet(ship, "Bart")
    assert rec.events == [("in", ship, grp)]


def test_removed_names_are_not_delivered_and_re_added_ones_are():
    grp = ObjectGroup(); grp.AddName("Bart"); grp.AddName("Lisa")
    rec = _subscribe(grp)
    pSet = _set()
    grp.RemoveName("Bart")
    pSet.AddObjectToSet(_ship(), "Bart")
    grp.RemoveAllNames()
    pSet.AddObjectToSet(_ship(), "Lisa")
    assert rec.events == []
    grp.AddName("Maggie")
    ship = _ship(); pSet.AddObjectToSet(ship, "Maggie")
    assert rec.events == [("in", ship, grp)]


def test_a_dead_group_leaves_the_index():
    import gc
    from engine.core import ids
    grp = ObjectGroup(); grp.AddName("Unique Name 7")
    assert grp in ObjectGroup._by_name["Unique Name 7"]
    ids.unregister(grp.GetObjID())     # the id registry holds it strongly
    del grp
    gc.collect()
    assert not ObjectGroup._by_name.get("Unique Name 7")


def test_a_group_dropped_from_live_is_not_delivered_until_re_armed():
    grp = ObjectGroup(); grp.AddName("Bart")
    rec = _subscribe(grp)
    ObjectGroup._live.clear()
    pSet = _set()
    pSet.AddObjectToSet(_ship(), "Bart")
    assert rec.events == []
    pSet.RemoveObjectFromSet("Bart")
    grp.SetEventFlag(App.ObjectGroup.ENTERED_SET)
    ship = _ship(); pSet.AddObjectToSet(ship, "Bart")
    assert rec.events == [("in", ship, grp)]


def test_several_watching_groups_hear_it_in_live_order():
    grps = [ObjectGroup() for _ in range(6)]
    seen = []
    for g in grps:
        g.AddName("Bart")
        g.SetEventFlag(App.ObjectGroup.ENTERED_SET)
    order = [g for g in list(ObjectGroup._live) if g in grps]
    for g in grps:
        rec = _Recorder()
        rec.Entered = lambda evt, _g=g: seen.append(_g)
        w = App.TGPythonInstanceWrapper(); w.SetPyWrapper(rec)
        App.g_kEventManager.AddBroadcastPythonMethodHandler(
            App.ET_OBJECT_GROUP_OBJECT_ENTERED_SET, w, "Entered", g)
        g._keep = w
    _set().AddObjectToSet(_ship(), "Bart")
    assert seen == order
