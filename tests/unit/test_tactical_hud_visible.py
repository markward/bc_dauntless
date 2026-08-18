from engine.host_loop import _tactical_hud_visible


def _v(**kw):
    base = dict(is_exterior=False, spv_open=False,
                cutscene_active=False, bridge_tactical_active=False)
    base.update(kw)
    return _tactical_hud_visible(**base)


def test_exterior_shows_hud():
    assert _v(is_exterior=True) is True


def test_plain_bridge_hides_hud():
    assert _v(is_exterior=False) is False


def test_bridge_tactical_shows_hud_on_bridge():
    # F2 on the bridge with the Tactical menu open.
    assert _v(is_exterior=False, bridge_tactical_active=True) is True


def test_spv_hides_hud_even_in_bridge_tactical():
    assert _v(bridge_tactical_active=True, spv_open=True) is False


def test_cutscene_hides_hud_even_in_bridge_tactical():
    assert _v(bridge_tactical_active=True, cutscene_active=True) is False


def test_hud_hidden_in_cinematic_mode():
    """BC's cinematic mode is a clean camera view — no tactical HUD. It is NOT
    a cutscene, so the letterbox stays off; only the HUD goes."""
    from engine.host_loop import _tactical_hud_visible
    assert _tactical_hud_visible(
        is_exterior=True, spv_open=False, cutscene_active=False,
        cinematic_active=True) is False


def test_hud_visible_outside_cinematic_mode():
    from engine.host_loop import _tactical_hud_visible
    assert _tactical_hud_visible(
        is_exterior=True, spv_open=False, cutscene_active=False,
        cinematic_active=False) is True
