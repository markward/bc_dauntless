import App


def _make_nebula():
    n = App.MetaNebula_Create(
        155.0 / 255.0, 90.0 / 255.0, 185.0 / 255.0,
        145.0, 10.5,
        "data/Backgrounds/nebulaoverlay.tga",
        "data/Backgrounds/nebulaexternal.tga",
    )
    n.SetupDamage(150.0, 20.0)
    n.AddNebulaSphere(0.0, 1500.0, 0.0, 1500.0)
    return n


def test_metanebula_getters_return_constructor_values():
    n = _make_nebula()
    r, g, b = n.GetTintRGB()
    assert abs(r - 155.0 / 255.0) < 1e-6
    assert abs(g - 90.0 / 255.0) < 1e-6
    assert abs(b - 185.0 / 255.0) < 1e-6
    assert n.GetVisibility() == 145.0
    assert n.GetSensorDensity() == 10.5
    assert n.GetInternalTexture() == "data/Backgrounds/nebulaoverlay.tga"
    assert n.GetExternalTexture() == "data/Backgrounds/nebulaexternal.tga"
    assert n.GetDamage() == (150.0, 20.0)


def test_metanebula_cast_accepts_nebula_rejects_other():
    n = _make_nebula()
    assert App.MetaNebula_Cast(n) is n
    assert App.MetaNebula_Cast(object()) is None
    assert App.MetaNebula_Cast(None) is None
