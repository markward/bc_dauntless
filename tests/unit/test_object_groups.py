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


# ── ObjectClass module-level helpers ─────────────────────────────────────────
from engine.appc.objects import (
    ObjectClass_Cast, ObjectClass_GetObject, ObjectClass_GetObjectByID,
    IsNull,
)
from engine.appc.objects import ObjectClass


def test_object_class_cast_returns_object_for_object():
    obj = ObjectClass()
    assert ObjectClass_Cast(obj) is obj


def test_object_class_cast_returns_object_for_subclass():
    """ShipClass and CharacterClass are subclasses; cast should accept them."""
    from engine.appc.ships import ShipClass
    ship = ShipClass()
    assert ObjectClass_Cast(ship) is ship


def test_object_class_cast_returns_none_for_non_object():
    assert ObjectClass_Cast(None) is None
    assert ObjectClass_Cast("string") is None
    assert ObjectClass_Cast(42) is None


def test_object_class_get_object_finds_by_name():
    pSet = SetClass()
    obj = ObjectClass()
    pSet.AddObjectToSet(obj, "alpha")
    assert ObjectClass_GetObject(pSet, "alpha") is obj


def test_object_class_get_object_returns_none_for_missing():
    pSet = SetClass()
    assert ObjectClass_GetObject(pSet, "nope") is None


def test_object_class_get_object_with_none_set_returns_none():
    assert ObjectClass_GetObject(None, "alpha") is None


def test_object_class_get_object_by_id_finds_by_id():
    obj = ObjectClass()
    found = ObjectClass_GetObjectByID(None, obj.GetObjID())
    assert found is obj


def test_object_class_get_object_by_id_unknown_returns_none():
    assert ObjectClass_GetObjectByID(None, 9999999) is None


# ── IsNull ───────────────────────────────────────────────────────────────────

def test_is_null_for_none():
    assert IsNull(None) == 1


def test_is_null_for_normal_object_returns_zero():
    assert IsNull(ObjectClass()) == 0
    assert IsNull("string") == 0
    assert IsNull(42) == 0


def test_is_null_for_character_class_create_null_sentinel():
    """CharacterClass_CreateNull returns a sentinel that must register as null
    so the SDK iteration loop pattern (HideCharacters) exits cleanly."""
    null_char = App.CharacterClass_CreateNull()
    assert IsNull(null_char) == 1


def test_is_null_for_normal_character_returns_zero():
    real_char = App.CharacterClass_Create()
    assert IsNull(real_char) == 0


def test_is_null_for_named_stub_returns_one():
    """SDK iteration loops call GetFirstObject() / GetNextObject() — both
    unimplemented in Phase 1, so they fall through to NamedStub.  IsNull
    must treat NamedStub as null so the loop exits immediately rather than
    spinning forever."""
    stub = App.SomeUnknownThing  # falls through to _NamedStub
    assert type(stub).__name__ == "_NamedStub"
    assert IsNull(stub) == 1


def test_is_null_for_stub_returns_one():
    from engine.core.ids import _Stub
    assert IsNull(_Stub()) == 1


def test_app_exposes_object_class_helpers():
    assert App.ObjectClass_Cast is ObjectClass_Cast
    assert App.ObjectClass_GetObject is ObjectClass_GetObject
    assert App.ObjectClass_GetObjectByID is ObjectClass_GetObjectByID
    assert App.IsNull is IsNull
