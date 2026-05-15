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


def test_directional_direction_tracks_placement_rotation():
    """A light created via LightPlacement re-reads the placement's forward
    each call to direction_world(), so animation controllers (or scripts
    that call AlignToVectors a second time) flow through to the renderer."""
    import App
    from engine.appc.math import TGPoint3
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "TestSet")
    p = App.LightPlacement_Create("Directional Light", "TestSet", None)
    forward1 = TGPoint3(); forward1.SetXYZ(0.0, 1.0, 0.0)
    up1      = TGPoint3(); up1.SetXYZ(0.0, 0.0, 1.0)
    p.AlignToVectors(forward1, up1)
    p.ConfigDirectionalLight(1.0, 1.0, 1.0, 1.0)

    light = pSet.GetLight("Directional Light")
    assert light.direction_world() == pytest.approx((0.0, 1.0, 0.0), abs=1e-6)

    # Re-align the placement after Config — direction_world() must reflect this.
    forward2 = TGPoint3(); forward2.SetXYZ(1.0, 0.0, 0.0)
    up2      = TGPoint3(); up2.SetXYZ(0.0, 0.0, 1.0)
    p.AlignToVectors(forward2, up2)

    assert light.direction_world() == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)
    App.g_kSetManager.DeleteSet("TestSet")


def test_directional_without_placement_uses_static_direction():
    """Lights created via the 8-arg pSet.CreateDirectionalLight path have
    no placement; direction_world() returns the static _direction_world."""
    import App
    pSet = App.SetClass_Create()
    light = pSet.CreateDirectionalLight(1, 1, 1, 1, 0.5, 0.0, 0.5, "d")
    assert light.direction_world() == (0.5, 0.0, 0.5)


def test_config_directional_light_captures_forward_direction():
    import App
    from engine.appc.lights import Light
    from engine.appc.math import TGPoint3
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "TestSet")
    p = App.LightPlacement_Create("Directional Light", "TestSet", None)
    # Match the unit-length fixture from sdk/.../Systems/Biranu/Biranu2.py.
    # AlignToVectors normalizes its inputs, so non-unit forwards get rescaled
    # and won't round-trip exactly.
    forward = TGPoint3(); forward.SetXYZ(-0.099571, -0.962789, 0.251243)
    up      = TGPoint3(); up.SetXYZ(0.019077, 0.250604, 0.967902)
    p.AlignToVectors(forward, up)
    p.ConfigDirectionalLight(0.9, 0.8, 0.6, 0.45)

    light = pSet.GetLight("Directional Light")
    assert light._kind == Light.KIND_DIRECTIONAL
    assert light._color == (0.9, 0.8, 0.6)
    assert light._dimmer == 0.45
    # direction_world() (not the static _direction_world) is the public
    # accessor: for placement-backed lights it queries the placement's
    # rotation each call.
    dx, dy, dz = light.direction_world()
    assert dx == pytest.approx(-0.099571, abs=1e-5)
    assert dy == pytest.approx(-0.962789, abs=1e-5)
    assert dz == pytest.approx(0.251243, abs=1e-5)
    App.g_kSetManager.DeleteSet("TestSet")


def test_resolve_bridge_set_returns_set_named_bridge():
    """Locate the bridge SetClass by the conventional name 'bridge'."""
    import App
    from engine.appc.lights import _resolve_bridge_set
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "bridge")
    try:
        assert _resolve_bridge_set() is pSet
    finally:
        App.g_kSetManager.DeleteSet("bridge")


def test_resolve_bridge_set_returns_none_when_no_bridge():
    """No 'bridge' set registered → resolver returns None."""
    import App
    from engine.appc.lights import _resolve_bridge_set
    if App.g_kSetManager.GetSet("bridge") is not None:
        App.g_kSetManager.DeleteSet("bridge")
    assert _resolve_bridge_set() is None


def test_aggregate_bridge_for_renderer_uses_bridge_set_ambient():
    """aggregate_bridge_for_renderer reads the bridge set's
    CreateAmbientLight, NOT the space scene's lighting."""
    import App
    from engine.appc.lights import aggregate_bridge_for_renderer
    if App.g_kSetManager.GetSet("bridge") is not None:
        App.g_kSetManager.DeleteSet("bridge")
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "bridge")
    try:
        pSet.CreateAmbientLight(1.0, 0.5, 0.25, 0.8, "ambientlight1")
        default_ambient = (0.01, 0.01, 0.01)
        ambient, directionals = aggregate_bridge_for_renderer(
            default_ambient, [])
        assert ambient == pytest.approx((0.8, 0.4, 0.2))
        assert directionals == []
    finally:
        App.g_kSetManager.DeleteSet("bridge")


def test_aggregate_bridge_for_renderer_returns_defaults_when_no_bridge():
    """No 'bridge' set → defaults flow through."""
    import App
    from engine.appc.lights import aggregate_bridge_for_renderer
    if App.g_kSetManager.GetSet("bridge") is not None:
        App.g_kSetManager.DeleteSet("bridge")
    default_ambient = (0.7, 0.7, 0.7)
    default_directionals = []
    ambient, directionals = aggregate_bridge_for_renderer(
        default_ambient, default_directionals)
    assert ambient == default_ambient
    assert directionals == default_directionals
