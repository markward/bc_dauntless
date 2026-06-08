from engine.appc import damage_decals as dd


def test_phaser_maps_to_heat_glow():
    assert dd.weapon_class_for("phaser") == dd.WEAPON_CLASS_HEAT_GLOW


def test_torpedo_maps_to_scorch():
    assert dd.weapon_class_for("torpedo") == dd.WEAPON_CLASS_SCORCH


def test_unknown_and_none_default_to_scorch():
    assert dd.weapon_class_for(None) == dd.WEAPON_CLASS_SCORCH
    assert dd.weapon_class_for("disruptor") == dd.WEAPON_CLASS_SCORCH


def test_intensity_is_monotonic_and_clamped():
    assert dd.decal_intensity(0.0) == 0.0
    assert dd.decal_intensity(-5.0) == 0.0          # negative clamps to 0
    low = dd.decal_intensity(1.0)
    high = dd.decal_intensity(50.0)
    assert 0.0 < low <= high <= 1.0
    assert dd.decal_intensity(1e9) == 1.0           # saturates


def test_current_game_time_is_float_and_safe_without_app(monkeypatch):
    # With no usable App clock, returns 0.0 rather than raising.
    monkeypatch.setattr(dd, "_game_time_source", lambda: (_ for _ in ()).throw(RuntimeError()))
    assert dd.current_game_time() == 0.0
