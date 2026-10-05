"""Target panel honours the SDK's IsObjectKnown gate; radar affiliation
colours are real NiColorA objects, not stubs. See sensor-tiers spec §5."""
import App

from engine.appc.ships import ShipClass
from engine.appc.subsystems import SensorSubsystem
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.ui.ship_display_panel import ROLE_TARGET, _resolve_ship_for_role


def test_radar_colours_are_real_and_unknown_is_mid_grey():
    for name in ("g_kRadarFriendlyColor", "g_kRadarEnemyColor",
                 "g_kRadarNeutralColor", "g_kRadarUnknownColor"):
        assert isinstance(getattr(App, name), App.NiColorA), name
    c = App.g_kRadarUnknownColor
    assert abs(c.r - 127.5 / 255.0) < 1e-6
    assert abs(c.g - 127.5 / 255.0) < 1e-6
    assert abs(c.b - 127.5 / 255.0) < 1e-6


def _setup():
    mission = Mission()
    episode = Episode(); episode.SetCurrentMission(mission)
    game = Game(); game.SetCurrentEpisode(episode)

    player = ShipClass(); player.SetName("Player")
    sensors = SensorSubsystem("Sensors")
    player.SetSensorSubsystem(sensors)
    game.SetPlayer(player)
    _set_current_game(game)

    target = ShipClass(); target.SetName("Target")
    player.SetTarget(target)
    return game, player, target, sensors


def teardown_function(_):
    _set_current_game(None)


def test_unknown_target_blanks_the_target_panel():
    _, player, target, sensors = _setup()
    # Unidentified: the SDK gate blanks the target-role panel.
    assert _resolve_ship_for_role(ROLE_TARGET) is None
    # Identified via the contact manager: the gate opens.
    sensors.AddKnownObject(target)
    assert _resolve_ship_for_role(ROLE_TARGET) is target
