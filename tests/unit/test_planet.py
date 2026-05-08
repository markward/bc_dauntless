import App
from engine.appc.planet import (
    Planet, Sun,
    Planet_Create, Sun_Create, Planet_GetObject, Planet_Cast,
    ProximityManager,
)
from engine.appc.objects import ObjectClass
from engine.appc.sets import SetClass


# ── Planet basics ────────────────────────────────────────────────────────────

def test_planet_inherits_object_class():
    p = Planet_Create(200.0, "iceplanet.nif")
    assert isinstance(p, ObjectClass)


def test_planet_factory_records_radius_and_model():
    p = Planet_Create(180.5, "data/models/environment/IcePlanet.nif")
    assert p.GetRadius() == 180.5
    assert p.GetModelPath() == "data/models/environment/IcePlanet.nif"


def test_sun_inherits_planet():
    s = Sun_Create(800.0, 200.0, 100.0)
    assert isinstance(s, Planet)


def test_sun_factory_3_arg_form():
    """SDK pattern: pSun = App.Sun_Create(2000.0, 2000, 500)."""
    s = Sun_Create(2000.0, 2000, 500)
    assert s.GetRadius() == 2000.0
    assert s.GetAtmosphereRadius() == 2000.0
    assert s.GetEnvironmentalHullDamage() == 500.0


def test_sun_factory_5_arg_form_with_textures():
    """SDK pattern: pSun = App.Sun_Create(1500.0, 1500, 500, base_tex, flare_tex)."""
    s = Sun_Create(
        1500.0, 1500, 500,
        "data/Textures/SunYellow.tga",
        "data/Textures/Effects/SunFlaresYellow.tga",
    )
    assert s.GetModelPath() == "data/Textures/SunYellow.tga"
    assert s._flare_texture == "data/Textures/Effects/SunFlaresYellow.tga"


# ── Atmosphere ───────────────────────────────────────────────────────────────

def test_atmosphere_radius_round_trip():
    p = Planet_Create(100.0, "x.nif")
    p.SetAtmosphereRadius(150.0)
    assert p.GetAtmosphereRadius() == 150.0


def test_atmosphere_default_zero():
    p = Planet_Create(100.0, "x.nif")
    assert p.GetAtmosphereRadius() == 0.0


def test_environmental_damage_round_trip():
    p = Planet_Create(100.0, "x.nif")
    p.SetEnvironmentalShieldDamage(50.0)
    p.SetEnvironmentalHullDamage(25.0)
    assert p.GetEnvironmentalShieldDamage() == 50.0
    assert p.GetEnvironmentalHullDamage() == 25.0


# ── Hailable flag ────────────────────────────────────────────────────────────

def test_hailable_default_false():
    p = Planet_Create(100.0, "x.nif")
    assert p.IsHailable() == 0


def test_hailable_round_trip():
    """SDK pattern (E1M2.py:2346): pPlanet.SetHailable(TRUE) where TRUE = 1."""
    p = Planet_Create(100.0, "x.nif")
    p.SetHailable(1)
    assert p.IsHailable() == 1
    p.SetHailable(0)
    assert p.IsHailable() == 0


# ── Object attachment ────────────────────────────────────────────────────────

def test_attach_object_records():
    p = Planet_Create(100.0, "x.nif")
    moon = ObjectClass()
    p.AttachObject(moon)
    assert moon in p.GetAttachedObjects()


def test_attach_object_idempotent():
    p = Planet_Create(100.0, "x.nif")
    moon = ObjectClass()
    p.AttachObject(moon)
    p.AttachObject(moon)
    assert p.GetAttachedObjects().count(moon) == 1


def test_detach_object():
    p = Planet_Create(100.0, "x.nif")
    moon = ObjectClass()
    p.AttachObject(moon)
    p.DetachObject(moon)
    assert moon not in p.GetAttachedObjects()


# ── Planet_GetObject ─────────────────────────────────────────────────────────

def test_get_object_finds_planet_in_set():
    """SDK pattern: pPlanet = App.Planet_GetObject(pSet, "Tezle 1")."""
    pSet = SetClass()
    p = Planet_Create(200.0, "x.nif")
    pSet.AddObjectToSet(p, "Tezle 1")
    assert Planet_GetObject(pSet, "Tezle 1") is p


def test_get_object_returns_none_for_non_planet():
    pSet = SetClass()
    pSet.AddObjectToSet(ObjectClass(), "JustObject")
    assert Planet_GetObject(pSet, "JustObject") is None


def test_get_object_returns_none_for_missing_name():
    pSet = SetClass()
    assert Planet_GetObject(pSet, "NotThere") is None


def test_get_object_with_none_set_returns_none():
    assert Planet_GetObject(None, "Tezle 1") is None


def test_planet_cast():
    plain = ObjectClass()
    p = Planet()
    assert Planet_Cast(plain) is None
    assert Planet_Cast(p) is p


# ── ProximityManager ─────────────────────────────────────────────────────────

def test_proximity_manager_add_and_remove():
    pm = ProximityManager()
    obj = ObjectClass()
    pm.AddObject(obj)
    assert pm.GetNumObjects() == 1
    pm.RemoveObject(obj)
    assert pm.GetNumObjects() == 0


def test_proximity_manager_add_idempotent():
    pm = ProximityManager()
    obj = ObjectClass()
    pm.AddObject(obj)
    pm.AddObject(obj)
    assert pm.GetNumObjects() == 1


def test_proximity_manager_update_object_ensures_present():
    """SDK pattern (QuickBattle.py:2726): UpdateObject re-asserts membership
    after a position change; idempotent if already tracked."""
    pm = ProximityManager()
    obj = ObjectClass()
    pm.UpdateObject(obj)
    assert pm.GetNumObjects() == 1
    pm.UpdateObject(obj)
    assert pm.GetNumObjects() == 1


def test_set_class_get_proximity_manager_lazy_creates():
    """SDK pattern: pSet.GetProximityManager().AddObject(pProbe).
    Each set has one ProximityManager — repeat calls return the same instance."""
    pSet = SetClass()
    pm1 = pSet.GetProximityManager()
    pm2 = pSet.GetProximityManager()
    assert pm1 is pm2
    assert isinstance(pm1, ProximityManager)


def test_set_class_proximity_manager_accumulates():
    pSet = SetClass()
    obj = ObjectClass()
    pSet.GetProximityManager().AddObject(obj)
    assert pSet.GetProximityManager().GetNumObjects() == 1


# ── App namespace ────────────────────────────────────────────────────────────

def test_app_exposes_planet_factories():
    assert App.Planet_Create is Planet_Create
    assert App.Planet_GetObject is Planet_GetObject
    assert App.Sun_Create is Sun_Create
    assert App.Planet_Cast is Planet_Cast


def test_app_exposes_planet_classes():
    assert App.Planet is Planet
    assert App.Sun is Sun
    assert App.ProximityManager is ProximityManager
