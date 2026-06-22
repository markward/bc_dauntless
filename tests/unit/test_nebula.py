import App
from engine.appc.sets import SetClass_Create


def _obj_at(x, y, z):
    o = App.ShipClass_Create(); o.SetName("o")
    o.SetTranslateXYZ(x, y, z); o.Update(0)
    return o


def test_point_in_sphere_membership():
    neb = App.MetaNebula_Create(0.5, 0.5, 0.5, 100.0, 1.0, "i.tga", "e.tga")
    neb.AddNebulaSphere(0.0, 0.0, 0.0, 100.0)
    assert neb.IsObjectInNebula(_obj_at(10.0, 0.0, 0.0))   # inside
    assert not neb.IsObjectInNebula(_obj_at(200.0, 0.0, 0.0))  # outside


def test_multi_sphere():
    neb = App.MetaNebula_Create(0.5, 0.5, 0.5, 100.0, 1.0, "i.tga", "e.tga")
    neb.AddNebulaSphere(0.0, 0.0, 0.0, 50.0)
    neb.AddNebulaSphere(500.0, 0.0, 0.0, 50.0)
    assert neb.IsObjectInNebula(_obj_at(490.0, 0.0, 0.0))   # inside 2nd
    assert not neb.IsObjectInNebula(_obj_at(250.0, 0.0, 0.0))  # between


def test_get_nebula_and_class_list():
    App.g_kSetManager._sets.clear()
    s = SetClass_Create(); App.g_kSetManager.AddSet(s, "N")
    neb = App.MetaNebula_Create(0.5, 0.5, 0.5, 100.0, 1.0, "i.tga", "e.tga")
    s.AddObjectToSet(neb, "neb")
    assert s.GetNebula() is neb
    assert neb in s.GetClassObjectList(App.CT_NEBULA)
