"""SpeedDisplay panel snapshot + payload tests.

The panel reads two pieces of state:
  - current_speed (GU/s, BC's internal unit) and _warp_boost from the
    injected _PlayerControl-shaped object
  - max_speed (GU/s) from player.GetImpulseEngineSubsystem().GetMaxSpeed()

Reference numbers anchor on Galaxy class: SetMaxSpeed(6.3) GU/s →
3969 kph in stock BC's helm tooltip (see
sdk/Build/scripts/BridgeHandlers.py:1389). Conversion factor lives in
engine.units (GUPS_TO_KPH = 630).

These tests use a stub player_control + a real ShipClass with a
populated ImpulseEngineSubsystem.
"""
import json

import App
from engine.appc.ships import ShipClass
from engine.appc.subsystems import ImpulseEngineSubsystem


class _FakePlayerControl:
    """Minimal stand-in for _PlayerControl with the fields SpeedDisplay
    reads. Keeps the test independent of host_loop's full integrator."""

    def __init__(self, current_speed=0.0, warp_boost=False):
        self._current_speed = float(current_speed)
        self._warp_boost = bool(warp_boost)


def _setup_game(max_speed_gups=6.3):
    from engine.core.game import Game, Episode, Mission, _set_current_game
    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)
    player = ShipClass(); player.SetName("Player")
    # Attach a populated ImpulseEngineSubsystem so GetMaxSpeed returns
    # something meaningful — by default ShipClass has no subsystems.
    # Default 6.3 GU/s = Galaxy's SetMaxSpeed → 3969 kph.
    ies = ImpulseEngineSubsystem("ImpulseEngines")
    ies.SetMaxSpeed(max_speed_gups)
    player.SetImpulseEngineSubsystem(ies)
    game.SetPlayer(player)
    _set_current_game(game)
    return game, player


def _teardown_game():
    from engine.core.game import _set_current_game
    _set_current_game(None)


def _decode(script):
    """Strip the JS call wrapper and return the inner dict."""
    assert script.startswith("setSpeedDisplay(")
    return json.loads(script[len("setSpeedDisplay("):-2])


def test_payload_emits_kph_rounded_from_gups():
    from engine.ui.speed_display import SpeedDisplay

    # Galaxy max speed: 6.3 GU/s → 3969 kph (matches BC helm tooltip).
    _setup_game(max_speed_gups=6.3)
    try:
        # 4.2 GU/s ≈ impulse 6 on Galaxy → 2646 kph.
        pc = _FakePlayerControl(current_speed=4.2, warp_boost=False)
        panel = SpeedDisplay(player_control=pc)
        state = _decode(panel.render_payload())
        assert state["visible"] is True
        assert state["current_kph"] == 2646  # 4.2 * 630 = 2646.0
        assert state["max_kph"] == 3969      # 6.3 * 630 = 3969.0
        assert state["warp"] is False
    finally:
        _teardown_game()


def test_payload_emits_warp_flag_when_boost_active():
    from engine.ui.speed_display import SpeedDisplay

    _setup_game()
    try:
        pc = _FakePlayerControl(current_speed=0.0, warp_boost=True)
        panel = SpeedDisplay(player_control=pc)
        state = _decode(panel.render_payload())
        assert state["warp"] is True
    finally:
        _teardown_game()


def test_payload_is_idempotent_until_state_changes():
    """render_payload returns None if the snapshot hasn't changed; this
    is the same idempotency contract every other Panel honours so the
    host loop can call render_all() each tick without churning the DOM."""
    from engine.ui.speed_display import SpeedDisplay

    _setup_game(max_speed_gups=6.3)
    try:
        pc = _FakePlayerControl(current_speed=4.2)  # 4.2 GU/s → 2646 kph
        panel = SpeedDisplay(player_control=pc)
        first = panel.render_payload()
        assert first is not None
        # No state change → no re-emit.
        assert panel.render_payload() is None
        # Sub-km/h jitter rounds to the same KPH bucket → still no emit.
        # +0.0005 GU/s = +0.315 km/h, rounds back to 2646 → no diff
        pc._current_speed = 4.2005
        assert panel.render_payload() is None
        # A real change crosses the rounding boundary → re-emit.
        pc._current_speed = 4.21  # 2652.3 → rounds to 2652
        second = panel.render_payload()
        assert second is not None
        assert _decode(second)["current_kph"] == 2652
    finally:
        _teardown_game()


def test_payload_handles_no_player_gracefully():
    """Between mission swaps the game can briefly have no player; the
    panel should emit a sane zero-value payload, not crash."""
    from engine.ui.speed_display import SpeedDisplay
    from engine.core.game import Game, _set_current_game

    game = Game()
    _set_current_game(game)
    try:
        pc = _FakePlayerControl(current_speed=42.0)
        panel = SpeedDisplay(player_control=pc)
        state = _decode(panel.render_payload())
        assert state["visible"] is True
        assert state["current_kph"] == 0
        assert state["max_kph"] == 0
        assert state["warp"] is False
    finally:
        _set_current_game(None)


def test_payload_hidden_when_visible_false():
    """When visible is flipped off (e.g. bridge view) the panel emits
    a hidden payload so the JS hides the DOM element."""
    from engine.ui.speed_display import SpeedDisplay

    _setup_game()
    try:
        pc = _FakePlayerControl(current_speed=100.0)
        panel = SpeedDisplay(player_control=pc)
        panel.visible = False
        state = _decode(panel.render_payload())
        assert state["visible"] is False
    finally:
        _teardown_game()


def test_panel_name_is_speed():
    """The PanelRegistry dispatches events by `panel.name` prefix."""
    from engine.ui.speed_display import SpeedDisplay

    pc = _FakePlayerControl()
    panel = SpeedDisplay(player_control=pc)
    assert panel.name == "speed"


def test_dispatch_event_is_a_noop():
    """Speed is read-only — dispatch_event always returns False."""
    from engine.ui.speed_display import SpeedDisplay

    pc = _FakePlayerControl()
    panel = SpeedDisplay(player_control=pc)
    assert panel.dispatch_event("anything") is False
