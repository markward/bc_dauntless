"""BlinkingLightProperty + the EffectEmitter family (running-lights spec §4.1).

Before this, App.BlinkingLightProperty_Create fell through to a _NamedStub whose
GetName() is itself a stub hashed by identity, so RegisterLocalTemplate keyed
each light under a key nobody could find and every mod running light was
silently dropped by FindByName.
"""
import importlib
import sys
from pathlib import Path

import pytest

import App
import tools.mission_harness as mh
from engine import mods
from engine.appc.math import TGPoint3
from engine.appc.properties import (
    BlinkingLightProperty, EffectEmitterProperty, ExplodeEmitterProperty,
    PositionOrientationProperty, SmokeEmitterProperty, SparkEmitterProperty,
    TGModelPropertySet,
)


def test_defaults_match_the_binary_constructor():
    # FUN_0067B590: Radius 0.1, Period 3.0, Duration 1.0, no texture.
    p = App.BlinkingLightProperty_Create("Strobe")
    assert isinstance(p, BlinkingLightProperty)
    assert p.GetName() == "Strobe"
    assert p.GetRadius() == pytest.approx(0.1)
    assert p.GetPeriod() == pytest.approx(3.0)
    assert p.GetDuration() == pytest.approx(1.0)
    assert p.GetTextureName() is None
    c = p.GetColor()
    assert (c.r, c.g, c.b, c.a) == (1.0, 1.0, 1.0, 1.0)


def test_setters_round_trip_like_a_mod_hardpoint():
    p = App.BlinkingLightProperty_Create("Bridge Blinker")
    pos = TGPoint3(); pos.SetXYZ(-0.000447, 0.578326, 0.280537)
    p.SetPosition(pos)
    fwd = TGPoint3(); fwd.SetXYZ(0, 1, 0)
    up = TGPoint3(); up.SetXYZ(0, 0, 1)
    right = TGPoint3(); right.SetXYZ(1, 0, 0)
    p.SetOrientation(fwd, up, right)
    col = App.TGColorA(); col.SetRGBA(1.0, 1.0, 0.501961, 1.0)
    p.SetColor(col)
    p.SetRadius(1.5); p.SetPeriod(3.0); p.SetDuration(1.0)
    p.SetTextureName("scripts/Custom/NanoFXv2/SpecialFX/Gfx/Blinker/Blank.tga")

    got = p.GetPosition()
    assert (round(got.x, 6), round(got.y, 6), round(got.z, 6)) == (-0.000447, 0.578326, 0.280537)
    c = p.GetColor()
    assert (c.r, c.g, round(c.b, 6), c.a) == (1.0, 1.0, 0.501961, 1.0)
    assert (p.GetRadius(), p.GetPeriod(), p.GetDuration()) == (1.5, 3.0, 1.0)
    assert p.GetTextureName().endswith("Blank.tga")
    # Mutating the caller's colour after SetColor must not change the property.
    col.SetRGBA(0, 0, 0, 0)
    assert p.GetColor().r == 1.0


def test_get_color_returns_a_copy():
    p = App.BlinkingLightProperty_Create("x")
    p.GetColor().SetRGBA(0, 0, 0, 0)
    assert p.GetColor().r == 1.0


def test_effect_emitter_family_is_placement_only():
    for create, cls in (
        (App.SmokeEmitterProperty_Create, SmokeEmitterProperty),
        (App.SparkEmitterProperty_Create, SparkEmitterProperty),
        (App.ExplodeEmitterProperty_Create, ExplodeEmitterProperty),
        (App.EffectEmitterProperty_Create, EffectEmitterProperty),
    ):
        p = create("SmokeEmitter2")
        assert isinstance(p, cls)
        assert isinstance(p, EffectEmitterProperty)
        assert isinstance(p, PositionOrientationProperty)
        pos = TGPoint3(); pos.SetXYZ(204.452, 179.076, 113.168)
        p.SetPosition(pos)
        assert p.GetPosition().x == pytest.approx(204.452)


def test_blinking_light_is_an_effect_emitter():
    assert issubclass(BlinkingLightProperty, EffectEmitterProperty)


def test_cast_accepts_own_class_and_rejects_others():
    light = App.BlinkingLightProperty_Create("a")
    smoke = App.SmokeEmitterProperty_Create("b")
    assert App.BlinkingLightProperty_Cast(light) is light
    assert App.BlinkingLightProperty_Cast(smoke) is None
    assert App.BlinkingLightProperty_Cast(None) is None
    assert App.EffectEmitterProperty_Cast(light) is light
    assert App.SmokeEmitterProperty_Cast(smoke) is smoke
    assert App.SparkEmitterProperty_Cast(smoke) is None
    assert App.ExplodeEmitterProperty_Cast(smoke) is None


def test_get_properties_by_type_finds_lights_by_ct_tag():
    pset = TGModelPropertySet()
    light = App.BlinkingLightProperty_Create("a")
    smoke = App.SmokeEmitterProperty_Create("b")
    pset.AddToSet("Scene Root", light)
    pset.AddToSet("Scene Root", smoke)
    assert list(pset.GetPropertiesByType(App.CT_BLINKING_LIGHT_PROPERTY)) == [light]
    assert list(pset.GetPropertiesByType(App.CT_SMOKE_EMITTER_PROPERTY)) == [smoke]
    assert list(pset.GetPropertiesByType(App.CT_SPARK_EMITTER_PROPERTY)) == []
    assert list(pset.GetPropertiesByType(App.CT_EXPLODE_EMITTER_PROPERTY)) == []
    assert set(pset.GetPropertiesByType(App.CT_EFFECT_EMITTER_PROPERTY)) == {light, smoke}


def test_named_template_survives_find_by_name():
    App.g_kModelPropertyManager.ClearLocalTemplates()
    light = App.BlinkingLightProperty_Create("Bridge Blinker")
    App.g_kModelPropertyManager.RegisterLocalTemplate(light)
    found = App.g_kModelPropertyManager.FindByName(
        "Bridge Blinker", App.TGModelPropertyManager.LOCAL_TEMPLATES)
    assert found is light
    App.g_kModelPropertyManager.ClearLocalTemplates()


_LC_HP = "LC Intrepid Pack/scripts/ships/Hardpoints/LCintrepidHP.py"


def test_real_lc_intrepid_hardpoint_puts_19_lights_on_the_ship():
    """The regression: 0 before this change (FindByName returned None)."""
    root = Path(mods.mods_root(argv=[], env={}))
    if not (root / _LC_HP).is_file():
        pytest.skip("LC Intrepid Pack not installed under the mods root")
    mods.configure(mods.build_index(root))
    mh.setup_sdk()
    App.g_kModelPropertyManager.ClearLocalTemplates()
    sys.modules.pop("ships.Hardpoints.LCintrepidHP", None)
    hp = importlib.import_module("ships.Hardpoints.LCintrepidHP")
    assert hp.__spec__.origin.endswith("LCintrepidHP.py")
    pset = TGModelPropertySet()
    hp.LoadPropertySet(pset)
    lights = list(pset.GetPropertiesByType(App.CT_BLINKING_LIGHT_PROPERTY))
    assert len(lights) == 19
    statics = [l for l in lights if l.GetDuration() == 0.0]
    blinkers = [l for l in lights if l.GetDuration() == 1.0]
    assert len(statics) + len(blinkers) == 19
    assert all(l.GetPeriod() == 3.0 for l in lights)
    App.g_kModelPropertyManager.ClearLocalTemplates()
