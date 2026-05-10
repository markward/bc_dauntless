"""Phase-1 light shim: Light objects, LightPlacement materialisation."""
import pytest


def test_light_holds_color_and_dimmer():
    from engine.appc.lights import Light
    light = Light(Light.KIND_AMBIENT, "ambient1", 0.5, 0.6, 0.7, 0.8)
    assert light._kind == Light.KIND_AMBIENT
    assert light._color == (0.5, 0.6, 0.7)
    assert light._dimmer == 0.8
    assert light.GetName() == "ambient1"
    # Default direction (overwritten by LightPlacement for directionals)
    assert light._direction_world == (0.0, 1.0, 0.0)


def test_light_add_illuminated_object_is_noop():
    from engine.appc.lights import Light
    light = Light(Light.KIND_DIRECTIONAL, "d", 1, 1, 1, 1)
    assert light.AddIlluminatedObject(object()) is None  # SDK no-op


def test_light_placement_create_registers_in_set():
    import App
    from engine.appc.lights import LightPlacement
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "TestSet")
    p = App.LightPlacement_Create("Ambient Light", "TestSet", None)
    assert isinstance(p, LightPlacement)
    assert p.GetName() == "Ambient Light"
    # Placement is in the set's object dict (added via AddObjectToSet).
    assert pSet.GetObject("Ambient Light") is p
    App.g_kSetManager.DeleteSet("TestSet")


def test_config_ambient_light_appends_to_set_lights():
    import App
    from engine.appc.lights import Light
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "TestSet")
    p = App.LightPlacement_Create("Ambient Light", "TestSet", None)
    p.ConfigAmbientLight(0.8, 0.9, 1.0, 0.1)

    assert len(pSet._lights) == 1
    light = pSet._lights[0]
    assert light._kind == Light.KIND_AMBIENT
    assert light._color == (0.8, 0.9, 1.0)
    assert light._dimmer == 0.1
    assert pSet.GetLight("Ambient Light") is light
    App.g_kSetManager.DeleteSet("TestSet")


def test_config_directional_light_captures_forward_direction():
    import App
    from engine.appc.lights import Light
    from engine.appc.math import TGPoint3
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "TestSet")
    p = App.LightPlacement_Create("Directional Light", "TestSet", None)
    forward = TGPoint3(); forward.SetXYZ(-0.1, -0.96, 0.25)
    up      = TGPoint3(); up.SetXYZ(0.02, 0.25, 0.97)
    p.AlignToVectors(forward, up)
    p.ConfigDirectionalLight(0.9, 0.8, 0.6, 0.45)

    light = pSet.GetLight("Directional Light")
    assert light._kind == Light.KIND_DIRECTIONAL
    assert light._color == (0.9, 0.8, 0.6)
    assert light._dimmer == 0.45
    dx, dy, dz = light._direction_world
    assert dx == pytest.approx(-0.1, abs=1e-5)
    assert dy == pytest.approx(-0.96, abs=1e-5)
    assert dz == pytest.approx(0.25, abs=1e-5)
    App.g_kSetManager.DeleteSet("TestSet")
