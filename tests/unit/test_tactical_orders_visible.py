from engine.host_loop import _tactical_orders_visible


def _v(**kw):
    base = dict(tactical_menu_open=True, spv_open=False,
                cutscene_active=False)
    base.update(kw)
    return _tactical_orders_visible(**base)


def test_tactical_menu_open_shows_orders_panel():
    # Shown whenever the Tactical crew menu is open, in EITHER view
    # (SetupBridgeTactical + SetupTacticalTactical).
    assert _v() is True


def test_no_tactical_menu_hides_orders_panel():
    assert _v(tactical_menu_open=False) is False


def test_spv_hides_orders_panel():
    assert _v(spv_open=True) is False


def test_cutscene_hides_orders_panel():
    assert _v(cutscene_active=True) is False


def test_cinematic_mode_hides_orders_panel():
    """BC's cinematic mode (F9) is a clean camera view. The Orders/Tactics/
    Maneuvers panel must hide if the Tactical menu was open when the user
    pressed F9 — the live-reported leak."""
    assert _v(cinematic_active=True) is False


def test_cinematic_default_is_off():
    # cinematic_active defaults False so existing callers are unaffected.
    assert _tactical_orders_visible(
        tactical_menu_open=True, spv_open=False,
        cutscene_active=False) is True
