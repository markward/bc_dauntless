import pytest
from engine.appc.properties import TGModelProperty


def test_name_storage():
    p = TGModelProperty("Hull")
    assert p.GetName() == "Hull"
    p.SetName("New Hull")
    assert p.GetName() == "New Hull"


def test_bool_is_true():
    p = TGModelProperty("X")
    assert bool(p) is True


def test_repr_contains_class_and_name():
    p = TGModelProperty("Hull")
    assert "TGModelProperty" in repr(p)
    assert "Hull" in repr(p)


def test_data_bag_single_arg():
    p = TGModelProperty("X")
    p.SetMaxCondition(5000)
    assert p.GetMaxCondition() == 5000


def test_data_bag_multi_arg():
    p = TGModelProperty("X")
    p.SetMaxShields(0, 4500.0)
    p.SetMaxShields(1, 3000.0)
    assert p.GetMaxShields(0) == 4500.0
    assert p.GetMaxShields(1) == 3000.0


def test_data_bag_unknown_returns_none():
    p = TGModelProperty("X")
    assert p.GetMaxCondition() is None
    assert p.GetMaxShields(0) is None


def test_unknown_attribute_raises():
    p = TGModelProperty("X")
    with pytest.raises(AttributeError):
        p.NotASetterOrGetter


from engine.appc.properties import (
    PositionOrientationProperty, EngineGlowProperty,
    SubsystemProperty, HullProperty, PowerProperty,
    WeaponProperty, EnergyWeaponProperty,
    PhaserProperty, PulseWeaponProperty, TractorBeamProperty,
    TorpedoTubeProperty,
    PoweredSubsystemProperty,
    ShieldProperty, SensorProperty, RepairSubsystemProperty,
    WeaponSystemProperty, TorpedoSystemProperty,
)


def test_subclass_isinstance_chain():
    p = PhaserProperty("X")
    assert isinstance(p, EnergyWeaponProperty)
    assert isinstance(p, WeaponProperty)
    assert isinstance(p, SubsystemProperty)
    assert isinstance(p, TGModelProperty)


def test_shield_property_inherits_powered_subsystem():
    p = ShieldProperty("X")
    assert isinstance(p, PoweredSubsystemProperty)
    assert isinstance(p, SubsystemProperty)


def test_torpedo_system_inherits_weapon_system():
    p = TorpedoSystemProperty("X")
    assert isinstance(p, WeaponSystemProperty)
    assert isinstance(p, PoweredSubsystemProperty)


def test_shield_face_constants():
    assert ShieldProperty.FRONT_SHIELDS == 0
    assert ShieldProperty.REAR_SHIELDS == 1
    assert ShieldProperty.TOP_SHIELDS == 2
    assert ShieldProperty.BOTTOM_SHIELDS == 3
    assert ShieldProperty.LEFT_SHIELDS == 4
    assert ShieldProperty.RIGHT_SHIELDS == 5
    assert ShieldProperty.NUM_SHIELDS == 6


def test_weapon_system_type_constants():
    assert WeaponSystemProperty.WST_UNKNOWN == 0
    assert WeaponSystemProperty.WST_PHASER == 1
    assert WeaponSystemProperty.WST_TORPEDO == 2
    assert WeaponSystemProperty.WST_PULSE == 3
    assert WeaponSystemProperty.WST_TRACTOR == 4


def test_data_bag_works_on_subclasses():
    p = ShieldProperty("Shield Generator")
    p.SetMaxShields(ShieldProperty.FRONT_SHIELDS, 4500.0)
    assert p.GetMaxShields(ShieldProperty.FRONT_SHIELDS) == 4500.0


from engine.appc.properties import (
    PositionOrientationProperty_Create,
    HullProperty_Create, PowerProperty_Create,
    PhaserProperty_Create, PulseWeaponProperty_Create,
    TractorBeamProperty_Create, TorpedoTubeProperty_Create,
    ShieldProperty_Create, SensorProperty_Create,
    RepairSubsystemProperty_Create, TorpedoSystemProperty_Create,
)


@pytest.mark.parametrize("factory,cls", [
    (PositionOrientationProperty_Create, PositionOrientationProperty),
    (HullProperty_Create, HullProperty),
    (PowerProperty_Create, PowerProperty),
    (PhaserProperty_Create, PhaserProperty),
    (PulseWeaponProperty_Create, PulseWeaponProperty),
    (TractorBeamProperty_Create, TractorBeamProperty),
    (TorpedoTubeProperty_Create, TorpedoTubeProperty),
    (ShieldProperty_Create, ShieldProperty),
    (SensorProperty_Create, SensorProperty),
    (RepairSubsystemProperty_Create, RepairSubsystemProperty),
    (TorpedoSystemProperty_Create, TorpedoSystemProperty),
])
def test_factory_returns_correct_subclass(factory, cls):
    p = factory("Test Name")
    assert isinstance(p, cls)
    assert p.GetName() == "Test Name"


from engine.appc.properties import TGModelPropertyManager


@pytest.fixture
def mgr():
    return TGModelPropertyManager()


def test_scope_constants():
    assert TGModelPropertyManager.LOCAL_TEMPLATES == 0
    assert TGModelPropertyManager.GLOBAL_TEMPLATES == 1


def test_register_local_then_find(mgr):
    p = HullProperty("Hull")
    mgr.RegisterLocalTemplate(p)
    assert mgr.FindByName("Hull", TGModelPropertyManager.LOCAL_TEMPLATES) is p


def test_register_global_then_find(mgr):
    p = HullProperty("Hull")
    mgr.RegisterGlobalTemplate(p)
    assert mgr.FindByName("Hull", TGModelPropertyManager.GLOBAL_TEMPLATES) is p


def test_find_by_name_unknown_returns_none(mgr):
    assert mgr.FindByName("Missing", TGModelPropertyManager.LOCAL_TEMPLATES) is None
    assert mgr.FindByName("Missing", TGModelPropertyManager.GLOBAL_TEMPLATES) is None


def test_local_and_global_scopes_are_independent(mgr):
    local_hull = HullProperty("Hull")
    global_hull = HullProperty("Hull")
    mgr.RegisterLocalTemplate(local_hull)
    mgr.RegisterGlobalTemplate(global_hull)
    assert mgr.FindByName("Hull", TGModelPropertyManager.LOCAL_TEMPLATES) is local_hull
    assert mgr.FindByName("Hull", TGModelPropertyManager.GLOBAL_TEMPLATES) is global_hull


def test_clear_local_does_not_affect_global(mgr):
    mgr.RegisterLocalTemplate(HullProperty("L"))
    mgr.RegisterGlobalTemplate(HullProperty("G"))
    mgr.ClearLocalTemplates()
    assert mgr.FindByName("L", TGModelPropertyManager.LOCAL_TEMPLATES) is None
    assert mgr.FindByName("G", TGModelPropertyManager.GLOBAL_TEMPLATES) is not None


def test_clear_global_does_not_affect_local(mgr):
    mgr.RegisterLocalTemplate(HullProperty("L"))
    mgr.RegisterGlobalTemplate(HullProperty("G"))
    mgr.ClearGlobalTemplates()
    assert mgr.FindByName("L", TGModelPropertyManager.LOCAL_TEMPLATES) is not None
    assert mgr.FindByName("G", TGModelPropertyManager.GLOBAL_TEMPLATES) is None


def test_find_by_name_and_type_match(mgr):
    p = ShieldProperty("Shields")
    mgr.RegisterLocalTemplate(p)
    found = mgr.FindByNameAndType("Shields", ShieldProperty, TGModelPropertyManager.LOCAL_TEMPLATES)
    assert found is p


def test_find_by_name_and_type_mismatch(mgr):
    p = ShieldProperty("Shields")
    mgr.RegisterLocalTemplate(p)
    found = mgr.FindByNameAndType("Shields", HullProperty, TGModelPropertyManager.LOCAL_TEMPLATES)
    assert found is None


def test_is_local_and_is_global(mgr):
    local_p = HullProperty("L")
    global_p = HullProperty("G")
    mgr.RegisterLocalTemplate(local_p)
    mgr.RegisterGlobalTemplate(global_p)
    assert mgr.IsLocalTemplate(local_p) is True
    assert mgr.IsLocalTemplate(global_p) is False
    assert mgr.IsGlobalTemplate(global_p) is True
    assert mgr.IsGlobalTemplate(local_p) is False


def test_remove_template(mgr):
    p = HullProperty("Hull")
    mgr.RegisterLocalTemplate(p)
    mgr.RemoveTemplate(p)
    assert mgr.FindByName("Hull", TGModelPropertyManager.LOCAL_TEMPLATES) is None
    assert mgr.IsLocalTemplate(p) is False


from engine.appc.properties import TGModelPropertySet


def test_property_set_starts_empty():
    s = TGModelPropertySet()
    items = list(s.GetPropertyList())
    assert items == []


def test_property_set_add_to_set_appends():
    s = TGModelPropertySet()
    hull = HullProperty("Hull")
    shield = ShieldProperty("Shield Generator")
    s.AddToSet("Scene Root", hull)
    s.AddToSet("Scene Root", shield)
    items = list(s.GetPropertyList())
    assert items == [hull, shield]


def test_property_set_get_properties_by_type():
    s = TGModelPropertySet()
    hull = HullProperty("Hull")
    shield = ShieldProperty("Shield Generator")
    phaser = PhaserProperty("Forward Phaser")
    s.AddToSet("Scene Root", hull)
    s.AddToSet("Scene Root", shield)
    s.AddToSet("Scene Root", phaser)
    weapons = list(s.GetPropertiesByType(WeaponProperty))
    assert weapons == [phaser]
    subsystems = list(s.GetPropertiesByType(SubsystemProperty))
    assert subsystems == [hull, shield, phaser]


def test_property_list_sdk_iteration_protocol():
    s = TGModelPropertySet()
    hull = HullProperty("Hull")
    shield = ShieldProperty("Shield Generator")
    s.AddToSet("Scene Root", hull)
    s.AddToSet("Scene Root", shield)
    lst = s.GetPropertyList()
    lst.TGBeginIteration()
    assert lst.TGGetNumItems() == 2
    first = lst.TGGetNext()
    assert first.GetProperty() is hull
    second = lst.TGGetNext()
    assert second.GetProperty() is shield
    lst.TGDoneIterating()
    lst.TGDestroy()


def test_property_list_iter_round_trip_after_sdk_protocol():
    s = TGModelPropertySet()
    hull = HullProperty("Hull")
    s.AddToSet("Scene Root", hull)
    lst = s.GetPropertyList()
    lst.TGBeginIteration()
    lst.TGGetNext()
    lst.TGDoneIterating()
    # After iteration, list(lst) should still yield all items via __iter__
    assert list(lst) == [hull]


# ── ShipProperty / EngineProperty / WeaponSystemProperty (Phase 1) ────────────
from engine.appc.properties import (
    ShipProperty, ShipProperty_Create,
    EngineProperty, EngineProperty_Create,
    ImpulseEngineProperty, ImpulseEngineProperty_Create,
    WarpEngineProperty, WarpEngineProperty_Create,
    WeaponSystemProperty_Create,
    CloakingSubsystemProperty, CloakingSubsystemProperty_Create,
)


def test_ship_property_inherits_tg_model_property():
    p = ShipProperty("ambassador")
    assert isinstance(p, TGModelProperty)
    assert p.GetName() == "ambassador"


def test_ship_property_factory():
    p = ShipProperty_Create("ambassador")
    assert isinstance(p, ShipProperty)
    assert p.GetName() == "ambassador"


def test_ship_property_data_bag_round_trip():
    p = ShipProperty_Create("nebula")
    p.SetGenus(2)
    p.SetSpecies(7)
    p.SetMass(50000.0)
    p.SetShipName("Nebula Class")
    p.SetModelFilename("ships/nebula.nif")
    p.SetDamageResolution(8)
    p.SetAffiliation(1)
    assert p.GetGenus() == 2
    assert p.GetSpecies() == 7
    assert p.GetMass() == 50000.0
    assert p.GetShipName() == "Nebula Class"
    assert p.GetModelFilename() == "ships/nebula.nif"
    assert p.GetDamageResolution() == 8
    assert p.GetAffiliation() == 1


def test_engine_property_inherits_subsystem_property():
    p = EngineProperty("Port Warp")
    assert isinstance(p, SubsystemProperty)
    assert isinstance(p, TGModelProperty)


def test_engine_property_type_constants():
    assert hasattr(EngineProperty, "EP_IMPULSE")
    assert hasattr(EngineProperty, "EP_WARP")
    assert EngineProperty.EP_IMPULSE != EngineProperty.EP_WARP


def test_engine_property_factory_and_set_engine_type():
    p = EngineProperty_Create("Port Warp")
    assert isinstance(p, EngineProperty)
    p.SetEngineType(EngineProperty.EP_WARP)
    assert p.GetEngineType() == EngineProperty.EP_WARP


def test_impulse_engine_property_inherits_powered_subsystem():
    p = ImpulseEngineProperty("Impulse Engines")
    assert isinstance(p, PoweredSubsystemProperty)
    assert isinstance(p, SubsystemProperty)


def test_impulse_engine_factory_and_setters():
    p = ImpulseEngineProperty_Create("Impulse Engines")
    assert isinstance(p, ImpulseEngineProperty)
    p.SetMaxSpeed(120.0)
    p.SetMaxAccel(25.0)
    p.SetMaxAngularVelocity(0.5)
    p.SetMaxAngularAccel(0.25)
    assert p.GetMaxSpeed() == 120.0
    assert p.GetMaxAccel() == 25.0
    assert p.GetMaxAngularVelocity() == 0.5
    assert p.GetMaxAngularAccel() == 0.25


def test_warp_engine_property_inherits_powered_subsystem():
    p = WarpEngineProperty("Warp Engines")
    assert isinstance(p, PoweredSubsystemProperty)
    assert isinstance(p, SubsystemProperty)


def test_warp_engine_factory():
    p = WarpEngineProperty_Create("Warp Engines")
    assert isinstance(p, WarpEngineProperty)
    assert p.GetName() == "Warp Engines"


def test_weapon_system_property_factory():
    p = WeaponSystemProperty_Create("Phaser System")
    assert isinstance(p, WeaponSystemProperty)
    assert p.GetName() == "Phaser System"
    p.SetWeaponSystemType(WeaponSystemProperty.WST_PHASER)
    p.SetAimedWeapon(1)
    p.SetFiringChainString("ABAB")
    assert p.GetWeaponSystemType() == WeaponSystemProperty.WST_PHASER
    assert p.GetAimedWeapon() == 1
    assert p.GetFiringChainString() == "ABAB"


def test_cloaking_subsystem_inherits_powered_subsystem():
    p = CloakingSubsystemProperty("Cloaking Device")
    assert isinstance(p, PoweredSubsystemProperty)
    assert isinstance(p, SubsystemProperty)


def test_cloaking_subsystem_factory_and_setters():
    p = CloakingSubsystemProperty_Create("Cloaking Device")
    assert isinstance(p, CloakingSubsystemProperty)
    p.SetCloakStrength(0.85)
    p.SetCritical(1)
    p.SetMaxCondition(800.0)
    assert p.GetCloakStrength() == 0.85
    assert p.GetCritical() == 1
    assert p.GetMaxCondition() == 800.0


def test_subsystem_property_inherited_setters_via_data_bag():
    """All Subsystem* setters used by hardpoints should round-trip via data bag."""
    p = ImpulseEngineProperty_Create("Impulse Engines")
    p.SetCritical(1)
    p.SetMaxCondition(1000.0)
    p.SetDisabledPercentage(0.25)
    p.SetRadius(50.0)
    p.SetPrimary(1)
    p.SetTargetable(1)
    p.SetRepairComplexity(3)
    assert p.GetCritical() == 1
    assert p.GetMaxCondition() == 1000.0
    assert p.GetDisabledPercentage() == 0.25
    assert p.GetRadius() == 50.0
    assert p.GetPrimary() == 1
    assert p.GetTargetable() == 1
    assert p.GetRepairComplexity() == 3
