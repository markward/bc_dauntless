from engine.appc import sector_model as sm


def test_load_has_systems():
    model = sm.load_sector_model()
    assert isinstance(model.get("systems"), list)
    assert len(model["systems"]) >= 30


def test_system_id_for_set_normalizes():
    assert sm.system_id_for_set("Vesuvi6") == "vesuvi"
    assert sm.system_id_for_set("Starbase12") == "tauceti"  # member -> parent


def test_display_label_overrides_and_titlecase():
    assert sm.display_label("vesuvi") == "Vesuvi"
    assert sm.display_label("xientrades") == "Xi Entrades"
    assert sm.display_label("omegadraconis") == "Omega Draconis"


def test_is_real_system_excludes_multi():
    assert sm.is_real_system("vesuvi") is True
    assert sm.is_real_system("multi1") is False


def test_warp_points_for_absent_is_empty():
    # A system id with no baked warp_points yields [].
    assert sm.warp_points_for("does-not-exist") == []


def test_sky_projection_reexports_still_work():
    from engine.appc import sky_projection as sp
    assert sp.load_sector_model() is sm.load_sector_model()
    assert sp.system_id_for_set("Vesuvi6") == "vesuvi"


def test_warp_points_carry_module():
    from engine.appc import sector_model as sm
    wps = sm.warp_points_for("vesuvi")
    assert any(w.get("module") == "Systems.Vesuvi.Vesuvi4" for w in wps)


def test_system_module_for_riha():
    from engine.appc import sector_model as sm
    assert sm.system_module("riha") == "Systems.Riha.Riha1"
