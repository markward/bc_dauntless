from engine.host_loop import _reticle_visible


def _v(**kw):
    base = dict(is_exterior=True, has_player=True, reticle_hidden=False)
    base.update(kw)
    return _reticle_visible(**base)


def test_exterior_with_player_shows_reticle():
    assert _v() is True


def test_bridge_view_hides_reticle():
    assert _v(is_exterior=False) is False


def test_no_player_hides_reticle():
    assert _v(has_player=False) is False


def test_cutscene_bhidereticle_hides_reticle():
    # StartCutscene(..., bHideReticle=1) — reticle_hidden() is True.
    assert _v(reticle_hidden=True) is False


def test_cutscene_without_bhidereticle_keeps_reticle():
    # E1M2's bHideReticle=FALSE cutscenes deliberately KEEP the reticle;
    # reticle_hidden() is False there and the predicate must not hide it.
    assert _v(reticle_hidden=False) is True


def test_cinematic_mode_hides_reticle():
    """BC's cinematic mode (F9) is a clean camera view — the reticle and its
    captions must hide. It is NOT a cutscene (no letterbox), so
    reticle_hidden() stays False and cinematic_active carries the gate."""
    assert _v(cinematic_active=True) is False


def test_cinematic_default_is_off():
    # cinematic_active defaults False so future callers are safe.
    assert _reticle_visible(is_exterior=True, has_player=True,
                            reticle_hidden=False) is True
