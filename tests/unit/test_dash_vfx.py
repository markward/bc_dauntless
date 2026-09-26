"""engine.dash_vfx — the player's dash screen flash / dust-streak / nacelle-
glow clock (in-system-warp spec §4, Task 6).

Pure math, mirroring tests/unit/test_warp_vfx.py's style for the tunnel's own
WarpVFX. Exact values at 0, 0.2, 0.4, 0.5 s pin the envelopes named in the
task brief.
"""
import pytest

from engine.dash_vfx import DashVFX


def test_idle_by_default():
    d = DashVFX()
    assert d.dash_intensity() == 0.0
    assert d.flash_intensity() == 0.0
    assert d.engine_glow() == (0.0, 0.0)


def test_dash_intensity_ramps_up_over_half_a_second_after_engage():
    d = DashVFX()
    d.engage(0.0)
    d.tick(0.0);  assert d.dash_intensity() == 0.0
    d.tick(0.2);  assert d.dash_intensity() == 0.4
    d.tick(0.4);  assert abs(d.dash_intensity() - 0.8) < 1e-9
    d.tick(0.5);  assert d.dash_intensity() == 1.0


def test_dash_intensity_holds_at_one_while_dashing():
    d = DashVFX()
    d.engage(0.0)
    d.tick(0.5); assert d.dash_intensity() == 1.0
    d.tick(9.0); assert d.dash_intensity() == 1.0   # still holding, no drop-out yet


def test_dash_intensity_ramps_down_over_half_a_second_after_drop_out():
    d = DashVFX()
    d.engage(0.0)
    d.tick(9.0)
    d.drop_out(9.0)
    d.tick(9.0);   assert d.dash_intensity() == 1.0
    d.tick(9.2);   assert abs(d.dash_intensity() - 0.6) < 1e-9
    d.tick(9.4);   assert abs(d.dash_intensity() - 0.2) < 1e-9
    d.tick(9.5);   assert d.dash_intensity() == 0.0
    d.tick(10.0);  assert d.dash_intensity() == 0.0


def test_flash_decays_from_one_to_zero_over_04s_after_engage():
    d = DashVFX()
    d.engage(0.0)
    d.tick(0.0); assert d.flash_intensity() == 1.0
    d.tick(0.2); assert abs(d.flash_intensity() - 0.5) < 1e-9
    d.tick(0.4); assert d.flash_intensity() == 0.0
    d.tick(0.5); assert d.flash_intensity() == 0.0


def test_flash_decays_from_one_to_zero_over_04s_after_drop_out_too():
    d = DashVFX()
    d.engage(0.0)
    d.tick(5.0)
    d.drop_out(5.0)
    d.tick(5.0); assert d.flash_intensity() == 1.0
    d.tick(5.2); assert abs(d.flash_intensity() - 0.5) < 1e-9
    d.tick(5.4); assert d.flash_intensity() == 0.0
    d.tick(5.5); assert d.flash_intensity() == 0.0


def test_engine_glow_drive_tracks_dash_intensity_burst_always_zero():
    d = DashVFX()
    d.engage(0.0)
    d.tick(0.2); assert d.engine_glow() == (0.4, 0.0)
    d.tick(1.0); assert d.engine_glow() == (1.0, 0.0)
    d.drop_out(1.0)
    d.tick(1.2); assert abs(d.engine_glow()[0] - 0.6) < 1e-9
    assert d.engine_glow()[1] == 0.0


def test_a_second_engage_resets_the_clock():
    d = DashVFX()
    d.engage(0.0)
    d.tick(9.0)
    d.drop_out(9.0)
    d.tick(9.5)
    assert d.dash_intensity() == 0.0
    d.engage(20.0)
    d.tick(20.0); assert d.dash_intensity() == 0.0
    d.tick(20.5); assert d.dash_intensity() == 1.0


def test_module_singleton_get_returns_same_instance():
    from engine import dash_vfx
    assert dash_vfx.get() is dash_vfx.get()


# ── host_loop wiring ─────────────────────────────────────────────────────

def test_combined_flash_intensity_is_the_brighter_of_the_two():
    from engine.host_loop import _combined_flash_intensity
    assert _combined_flash_intensity(0.3, 0.7) == 0.7
    assert _combined_flash_intensity(0.9, 0.1) == 0.9
    assert _combined_flash_intensity(0.0, 0.0) == 0.0


def test_warp_glow_envelope_returns_dash_glow_while_player_dashes(
        monkeypatch):
    import App
    from engine import dash_vfx, host_loop

    class _Ship:
        pass

    ship = _Ship()
    # The dash branch is player-only (warp._is_current_player).
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: ship)
    d = dash_vfx.get()
    try:
        d.engage(0.0)
        d.tick(1.0)                            # fully ramped: dash_intensity 1.0
        ship.__dict__["_dash"] = object()       # dash.is_dashing() reads this
        assert host_loop._warp_glow_envelope(ship) == (1.0, 0.0)
    finally:
        del ship.__dict__["_dash"]
        d.__init__()                            # reset the module singleton


def test_warp_glow_envelope_ignores_dash_for_a_non_dashing_ship():
    from engine import dash_vfx, host_loop
    from engine.appc import warp_state

    class _Ship:
        pass

    ship = _Ship()
    d = dash_vfx.get()
    try:
        d.engage(0.0)
        d.tick(1.0)
        # No "_dash" on __dict__, and no warp flythrough registered either.
        assert host_loop._warp_glow_envelope(ship) is None
    finally:
        d.__init__()
        warp_state.reset()


# ── engine.appc.dash's engage/drop-out fx hooks (ruling R3) ────────────────

class _Ship:
    pass


@pytest.fixture(autouse=True)
def _reset_dash_vfx_singleton():
    from engine import dash_vfx
    yield
    dash_vfx.get().__init__()


def test_on_engage_fx_starts_the_clock_and_plays_enter_warp(monkeypatch):
    import App
    from engine import dash_vfx
    from engine.appc import dash, warp

    monkeypatch.setattr(warp, "_is_current_player", lambda ship: True)
    monkeypatch.setattr(App.g_kUtopiaModule, "GetGameTime", lambda: 42.0)
    played = []
    monkeypatch.setattr(App.g_kSoundManager, "PlaySound",
                        lambda name, *a, **k: played.append(name))

    dash._on_engage_fx(_Ship())

    assert played == ["Enter Warp"]
    d = dash_vfx.get()
    d.tick(42.0)
    assert d.dash_intensity() == 0.0     # just engaged: ramp starts at 0
    assert d.flash_intensity() == 1.0    # the engage flash fires immediately


def test_on_drop_out_fx_ends_the_clock_and_plays_exit_warp(monkeypatch):
    import App
    from engine import dash_vfx
    from engine.appc import dash, warp

    monkeypatch.setattr(warp, "_is_current_player", lambda ship: True)
    monkeypatch.setattr(App.g_kUtopiaModule, "GetGameTime", lambda: 50.0)
    played = []
    monkeypatch.setattr(App.g_kSoundManager, "PlaySound",
                        lambda name, *a, **k: played.append(name))

    dash_vfx.get().engage(40.0)
    dash._on_drop_out_fx(_Ship())

    assert played == ["Exit Warp"]
    d = dash_vfx.get()
    d.tick(50.0)
    assert d.dash_intensity() == 1.0     # just dropped out: ramp starts at 1
    assert d.flash_intensity() == 1.0    # the drop-out flash fires immediately


def test_fx_hooks_are_gated_on_is_current_player(monkeypatch):
    """A dash hook fired for a non-player ship (should never happen -- only
    the player dashes today -- but the gate matches the rest of warp.py's
    player-scene effects) touches neither the clock nor the sound manager."""
    import App
    from engine import dash_vfx
    from engine.appc import dash, warp

    monkeypatch.setattr(warp, "_is_current_player", lambda ship: False)
    played = []
    monkeypatch.setattr(App.g_kSoundManager, "PlaySound",
                        lambda name, *a, **k: played.append(name))

    dash._on_engage_fx(_Ship())
    dash._on_drop_out_fx(_Ship())

    assert played == []
    assert dash_vfx.get().dash_intensity() == 0.0
