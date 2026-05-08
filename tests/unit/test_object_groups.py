import App
from engine.appc.objects import (
    ObjectGroup, ObjectGroupWithInfo,
    ObjectGroup_ForceToGroup, ObjectGroup_FromModule,
    ObjectGroupWithInfo_Cast,
)
from engine.appc.sets import SetClass


# ── ObjectGroup additions ─────────────────────────────────────────────────────

def test_get_name_tuple_returns_tuple_of_names():
    g = ObjectGroup()
    g.AddName("Enterprise")
    g.AddName("Defiant")
    assert g.GetNameTuple() == ("Enterprise", "Defiant")


def test_get_active_object_tuple_in_set_returns_live_objects():
    pSet = SetClass()
    from engine.appc.ships import ShipClass
    s1 = ShipClass()
    s2 = ShipClass()
    pSet.AddObjectToSet(s1, "Enterprise")
    pSet.AddObjectToSet(s2, "Defiant")
    g = ObjectGroup()
    g.AddName("Enterprise")
    g.AddName("Romulan-1")  # not in set
    g.AddName("Defiant")
    objs = g.GetActiveObjectTupleInSet(pSet)
    assert objs == (s1, s2)


def test_get_active_object_tuple_with_none_set_returns_empty():
    g = ObjectGroup()
    g.AddName("X")
    assert g.GetActiveObjectTupleInSet(None) == ()


def test_event_flags_round_trip():
    g = ObjectGroup()
    g.AddName("X")
    assert g.IsEventFlagSet("X", 1) == 0
    g.SetEventFlag("X", 1)
    assert g.IsEventFlagSet("X", 1) == 1
    g.ClearEventFlag("X", 1)
    assert g.IsEventFlagSet("X", 1) == 0


def test_remove_name_clears_event_flags():
    g = ObjectGroup()
    g.AddName("X")
    g.SetEventFlag("X", 5)
    g.RemoveName("X")
    assert g.IsEventFlagSet("X", 5) == 0


# ── ObjectGroupWithInfo ───────────────────────────────────────────────────────

def test_object_group_with_info_inherits_object_group():
    g = ObjectGroupWithInfo()
    assert isinstance(g, ObjectGroup)


def test_add_name_and_info_round_trip():
    g = ObjectGroupWithInfo()
    g.AddNameAndInfo("Enterprise", {"hull": 100})
    assert g.IsNameInGroup("Enterprise") == 1
    assert g.GetInfo("Enterprise") == {"hull": 100}


def test_dict_syntax_aliases():
    """FixApp.py wires __getitem__/__setitem__ — we expose them directly."""
    g = ObjectGroupWithInfo()
    g["Enterprise"] = "Federation"
    assert g["Enterprise"] == "Federation"
    del g["Enterprise"]
    assert g["Enterprise"] is None
    assert g.IsNameInGroup("Enterprise") == 0


def test_object_group_with_info_cast():
    plain = ObjectGroup()
    info = ObjectGroupWithInfo()
    assert ObjectGroupWithInfo_Cast(plain) is None
    assert ObjectGroupWithInfo_Cast(info) is info


# ── ObjectGroup_ForceToGroup ──────────────────────────────────────────────────

def test_force_to_group_passes_through_existing_group():
    g = ObjectGroup()
    g.AddName("X")
    out = ObjectGroup_ForceToGroup(g)
    assert out is g


def test_force_to_group_from_list_creates_new_group_with_names():
    out = ObjectGroup_ForceToGroup(["A", "B", "C"])
    assert out.GetNameTuple() == ("A", "B", "C")


def test_force_to_group_from_single_name_string():
    out = ObjectGroup_ForceToGroup("Enterprise")
    assert out.GetNameTuple() == ("Enterprise",)


def test_force_to_group_from_none_returns_empty_group():
    out = ObjectGroup_ForceToGroup(None)
    assert out.GetNumActiveObjects() == 0


# ── ObjectGroup_FromModule ────────────────────────────────────────────────────

def test_from_module_returns_named_attribute_as_group(tmp_path, monkeypatch):
    """Build a synthetic module with a list attribute and re-fetch it."""
    import sys
    import types
    mod = types.ModuleType("synthetic_test_mod")
    mod.pEnemies = ["Galor", "Keldon"]
    sys.modules["synthetic_test_mod"] = mod
    try:
        out = ObjectGroup_FromModule("synthetic_test_mod", "pEnemies")
        assert out.GetNameTuple() == ("Galor", "Keldon")
    finally:
        sys.modules.pop("synthetic_test_mod", None)


def test_from_module_unknown_module_returns_empty_group():
    out = ObjectGroup_FromModule("definitely.not.a.real.module", "x")
    assert out.GetNumActiveObjects() == 0


def test_from_module_unknown_attr_returns_empty_group():
    import sys, types
    mod = types.ModuleType("synth_no_attr_mod")
    sys.modules["synth_no_attr_mod"] = mod
    try:
        out = ObjectGroup_FromModule("synth_no_attr_mod", "missing")
        assert out.GetNumActiveObjects() == 0
    finally:
        sys.modules.pop("synth_no_attr_mod", None)


# ── App namespace ────────────────────────────────────────────────────────────

def test_app_exposes_helpers():
    assert App.ObjectGroup_ForceToGroup is ObjectGroup_ForceToGroup
    assert App.ObjectGroup_FromModule is ObjectGroup_FromModule
    assert App.ObjectGroupWithInfo is ObjectGroupWithInfo
