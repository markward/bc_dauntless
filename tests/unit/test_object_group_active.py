"""Unit tests for ObjectGroup.GetActiveObjectTuple (no-arg, walks all sets)
and single-arg ObjectGroup.SetEventFlag (group-level flag)."""
import App
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass


def _fresh_set_manager():
    App.g_kSetManager._sets.clear()


def test_get_active_object_tuple_empty_when_no_sets():
    _fresh_set_manager()
    g = ObjectGroup()
    g.AddName("anything")
    assert g.GetActiveObjectTuple() == ()


def test_get_active_object_tuple_finds_named_object_in_a_set():
    _fresh_set_manager()
    pSet = App.SetClass_Create()
    pSet.SetName("X")
    ship = ShipClass()
    pSet.AddObjectToSet(ship, "Bart")
    App.g_kSetManager._sets["X"] = pSet

    g = ObjectGroup()
    g.AddName("Bart")
    result = g.GetActiveObjectTuple()
    assert len(result) == 1
    assert result[0] is ship


def test_get_active_object_tuple_walks_multiple_sets():
    _fresh_set_manager()
    s1 = App.SetClass_Create(); s1.SetName("S1")
    s2 = App.SetClass_Create(); s2.SetName("S2")
    ship_a = ShipClass(); s1.AddObjectToSet(ship_a, "A")
    ship_b = ShipClass(); s2.AddObjectToSet(ship_b, "B")
    App.g_kSetManager._sets.update({"S1": s1, "S2": s2})

    g = ObjectGroup()
    g.AddName("A"); g.AddName("B")
    result = g.GetActiveObjectTuple()
    assert set(result) == {ship_a, ship_b}


def test_get_active_object_tuple_skips_missing_names():
    _fresh_set_manager()
    pSet = App.SetClass_Create(); pSet.SetName("X")
    ship = ShipClass(); pSet.AddObjectToSet(ship, "Bart")
    App.g_kSetManager._sets["X"] = pSet

    g = ObjectGroup()
    g.AddName("Bart"); g.AddName("Lisa")  # Lisa doesn't exist
    result = g.GetActiveObjectTuple()
    assert result == (ship,)


def test_set_event_flag_single_arg_marks_all_names():
    """Single-arg form sets the flag at the GROUP level — applies to all
    watched names. SDK conditions use this pattern."""
    g = ObjectGroup()
    g.AddName("A"); g.AddName("B")
    g.SetEventFlag(ObjectGroup.ENTERED_SET)
    # Both names should see the flag set.
    assert g.IsEventFlagSet("A", ObjectGroup.ENTERED_SET) == 1
    assert g.IsEventFlagSet("B", ObjectGroup.ENTERED_SET) == 1


def test_object_group_with_info_supports_getitem_for_per_name_info():
    """SDK SelectTarget rating reads pGroupWithInfo[sTarget]["Priority"].
    The __getitem__ accessor must return the per-name info dict, or
    empty dict for unknown names (so callers can still .get on it
    without crashing)."""
    from engine.appc.objects import ObjectGroupWithInfo
    g = ObjectGroupWithInfo()
    g.AddNameAndInfo("Bart", {"Priority": 5.0})
    assert g["Bart"] == {"Priority": 5.0}
    # Unknown name → empty dict (SDK callers do `.has_key("Priority")`).
    assert g["Unknown"] == {}
