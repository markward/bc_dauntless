"""Unit tests for ObjectGroup and ShipClass."""
import pytest
import App
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass, ShipClass_Create, ShipClass_GetObject, ShipClass_Cast


# ── ObjectGroup ────────────────────────────────────────────────────────────────

def test_object_group_add_and_query():
    g = ObjectGroup()
    g.AddName("USS Enterprise")
    assert g.IsNameInGroup("USS Enterprise")
    assert not g.IsNameInGroup("IKS Rotarran")


def test_object_group_remove():
    g = ObjectGroup()
    g.AddName("ship1")
    g.AddName("ship2")
    g.RemoveName("ship1")
    assert not g.IsNameInGroup("ship1")
    assert g.IsNameInGroup("ship2")


def test_object_group_remove_all():
    g = ObjectGroup()
    g.AddName("a")
    g.AddName("b")
    g.RemoveAllNames()
    assert g.GetNumActiveObjects() == 0


def test_object_group_count():
    g = ObjectGroup()
    g.AddName("a")
    g.AddName("b")
    assert g.GetNumActiveObjects() == 2


def test_object_group_duplicate_add_ignored():
    g = ObjectGroup()
    g.AddName("x")
    g.AddName("x")
    assert g.GetNumActiveObjects() == 1


def test_object_group_has_event_handler_api():
    g = ObjectGroup()
    assert hasattr(g, "AddPythonFuncHandlerForInstance")


# ── ShipClass ──────────────────────────────────────────────────────────────────

def test_ship_class_create_returns_ship():
    ship = ShipClass_Create("Galaxy")
    assert isinstance(ship, ShipClass)


def test_ship_class_has_obj_id():
    ship = ShipClass_Create("Galaxy")
    assert isinstance(ship.GetObjID(), int)
    assert ship.GetObjID() > 0


def test_ship_class_set_get_name():
    ship = ShipClass_Create("Galaxy")
    ship.SetName("USS Enterprise")
    assert ship.GetName() == "USS Enterprise"


def test_ship_class_set_get_script():
    ship = ShipClass_Create("Galaxy")
    ship.SetScript("ships.Galaxy")
    assert ship.GetScript() == "ships.Galaxy"


def test_ship_class_set_ai():
    ship = ShipClass_Create("Galaxy")
    ai_stub = object()
    ship.SetAI(ai_stub)
    assert ship.GetAI() is ai_stub


def test_ship_class_cast_returns_self():
    ship = ShipClass_Create("Galaxy")
    assert ShipClass_Cast(ship) is ship


def test_ship_class_cast_non_ship_returns_none():
    assert ShipClass_Cast(object()) is None


def test_ship_class_get_object_from_set():
    from engine.appc.sets import SetClass
    pSet = SetClass()
    ship = ShipClass_Create("Galaxy")
    pSet.AddObjectToSet(ship, "Galaxy 1")
    result = ShipClass_GetObject(pSet, "Galaxy 1")
    assert result is ship


def test_ship_class_get_object_missing_returns_none():
    from engine.appc.sets import SetClass
    pSet = SetClass()
    assert ShipClass_GetObject(pSet, "no such ship") is None


def test_ship_class_get_object_none_set_returns_none():
    assert ShipClass_GetObject(None, "ship") is None


def test_ship_class_unknown_attr_returns_stub():
    ship = ShipClass_Create("Galaxy")
    result = ship.GetHull()
    # Should not raise; returns a stub-like value
    assert result is not None


def test_app_ship_class_constants_accessible():
    assert App.ShipClass.GREEN_ALERT == 0
    assert App.ShipClass.YELLOW_ALERT == 1
    assert App.ShipClass.RED_ALERT == 2
