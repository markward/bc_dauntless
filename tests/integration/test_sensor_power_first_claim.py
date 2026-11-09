"""The sensor array has first claim on a starved plant's conduits.

#26 paced the plant's interval budget across the interval, so a shortfall
reaches the consumers as a steady share each tick, in draw order. With a big
shortfall that order decided whether the player could see: the Galaxy's
torpedoes and phasers attach ahead of its sensor array, so at 81% short
(main conduit 250/s against about 1,314/s wanted, e.g. a badly damaged
core) the sensors got a steady 0 and the player could not hold a target.

What the original does (stbc-oracle, measured by jmanyc for PR #26: Galaxy,
`power_core` and `batteries_flat` runs): sensors and torpedoes are served at
the budget reset, shields and impulse five frames later, phasers every
frame, so its sensors are always served while there is any power. The pump
(native/src/combat/src/subsystem_step.cc power_flow) now serves the ship's
sensor array first and every other consumer in attach order after it; on
the Galaxy, torpedoes already come next.
"""
import App

from engine.appc.sensor_detection import (clear_undetectable_player_lock,
                                          effective_sensor_range)
from engine.core.loop import GameLoop, TICK_DELTA
from tests.helpers import headless_mission
from tests.integration.test_sensor_power_blink import (_facility,
                                                       _over_asked_player,
                                                       _step)

SEVERE_MAIN_CONDUIT = 250.0     # ~81% short of the over-asked Galaxy's demand


def _severely_short_player():
    player, plant = _over_asked_player()
    plant.GetProperty().SetMainConduitCapacity(SEVERE_MAIN_CONDUIT)
    return player, plant


def test_a_severe_shortfall_still_gives_the_sensor_array_its_whole_share():
    player, plant = _severely_short_player()
    sensors = player.GetSensorSubsystem()
    loop = GameLoop()
    _step(loop, player, int(1.0 / TICK_DELTA))      # past the first interval
    short = []

    def look():
        if sensors.GetPowerWanted() > 0.0 and \
                sensors.GetPowerReceived() < sensors.GetPowerWanted():
            short.append((round(App.g_kUtopiaModule.GetGameTime(), 3),
                          sensors.GetPowerReceived(), sensors.GetPowerWanted()))
    _step(loop, player, int(5.0 / TICK_DELTA), look)
    assert short == [], "sensors short on %d ticks; first (time, got, wanted): %s" % (
        len(short), short[:3])
    assert effective_sensor_range(player) > 0.0


def test_a_severe_shortfall_still_lets_the_player_hold_its_target():
    player, plant = _severely_short_player()
    facility = _facility(player)
    loop = GameLoop()
    _step(loop, player, int(1.0 / TICK_DELTA))
    player.SetTarget(facility)
    drops = []

    def host_rule():
        clear_undetectable_player_lock(player)       # host_loop runs this every frame
        if player.GetTarget() is None:
            drops.append(round(App.g_kUtopiaModule.GetGameTime(), 3))
            player.SetTarget(facility)
    _step(loop, player, int(5.0 / TICK_DELTA), host_rule)
    assert drops == [], "the target was dropped %d times, first at %s" % (
        len(drops), drops[:5])


def test_the_shortfall_still_falls_on_the_consumers_last_in_attach_order():
    """Only the sensor array moves: the rest keep first-registered-first, so
    the plant still runs short on someone, and it is not the sensors."""
    player, plant = _severely_short_player()
    loop = GameLoop()
    _step(loop, player, int(1.0 / TICK_DELTA))
    starved = set()

    def look():
        for getter in ("GetShields", "GetImpulseEngineSubsystem",
                       "GetPhaserSystem", "GetTorpedoSystem"):
            sub = getattr(player, getter)()
            if sub.GetPowerWanted() > 0.0 and \
                    sub.GetPowerReceived() < sub.GetPowerWanted():
                starved.add(getter)
    _step(loop, player, int(5.0 / TICK_DELTA), look)
    assert starved, "a plant 81% short must starve some consumer"
