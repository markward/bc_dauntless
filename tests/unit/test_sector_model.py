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


def test_quickbattle_region_resolves_to_deep_space():
    """QuickBattle builds its own set (Systems/QuickBattle/QuickBattleRegion),
    which is not a charted system, so the stripped-digits fallback produced
    "quickbattleregion" and matched nothing. On the map that arena is Deep
    Space.

    This is not cosmetic: an unresolved set makes the star map anchor its
    orbit on the sector centroid AND omit the "you are here" reticle — by
    design, since a misplaced one is worse than none. Every QuickBattle
    session hit that path.
    """
    import engine.appc.sector_model as sm

    assert sm.system_id_for_set("QuickBattleRegion") == "deepspace"
    assert sm.system_id_for_set("quickbattleregion") == "deepspace"
    # deepspace must actually exist in the model, or the mapping just moves
    # the miss somewhere less obvious.
    ids = {s["id"] for s in sm.load_sector_model()["systems"]}
    assert "deepspace" in ids


def test_tau_ceti_members_resolve_from_their_sdk_menu_labels():
    """The SDK's CreateSystemMenu labels are "Dry Dock" and "Starbase 12" —
    with a space. The map's existing "drydock"/"starbase12" keys never matched
    those, and "starbase 12" fell through to the strip-trailing-digits branch
    and became "starbase " (trailing space included).

    Consequence: Tau Ceti baked with no destinations, so the E1M1 objective
    "head to Starbase 12" had nowhere to set course to.
    """
    import engine.appc.sector_model as sm

    assert sm.system_id_for_set("Dry Dock") == "tauceti"
    assert sm.system_id_for_set("Starbase 12") == "tauceti"
    # The id forms must keep working too.
    assert sm.system_id_for_set("DryDock") == "tauceti"
    assert sm.system_id_for_set("Starbase12") == "tauceti"


def test_starbase_12_is_a_reachable_course_destination():
    """The end of E1M1 sends the player to Starbase 12. It is charted under
    Tau Ceti, and must be selectable there — with a real set module, not a
    label alone."""
    import engine.appc.sector_model as sm

    wps = sm.warp_points_for("tauceti")
    by_label = {w["label"]: w for w in wps}
    assert "Starbase 12" in by_label, sorted(by_label)
    assert "Dry Dock" in by_label, sorted(by_label)
    assert by_label["Starbase 12"]["module"] == "Systems.Starbase12.Starbase12"
    assert by_label["Dry Dock"]["module"] == "Systems.DryDock.DryDock"
