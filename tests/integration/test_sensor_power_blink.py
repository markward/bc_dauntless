"""A ship asking for more power than its conduits carry must degrade steadily:
its sensors never blink to zero, and the player never loses its target.

Live report (2026-11-06, a long Quick Battle at every slider 125%): once the
Sovereign's backup battery ran dry, the player's target vanished for 0.117 s
every second and came back. The cause is the plant's interval budget
(native/src/combat/src/subsystem_step.cc power_flow): it is refilled once per
POWER_INTERVAL and every consumer draws its share from it each tick, in
attach order, so when the wanted total is above main conduit + backup conduit
the budget ran dry before the interval ended and EVERY consumer, the sensor
array included, received nothing for the rest of it. A sensor array with no
power read GetNormalPowerPercentage() == 0, so effective_sensor_range was 0,
and host_loop's clear_undetectable_player_lock dropped the player's target;
attempt_persistent_restore put it back after the refill. (0.2.1's Python
power stage did the same.)

The plant now paces the interval's budget across the interval (power_flow's
allowance), so a shortfall reaches the consumers as a steady reduced share
each tick, in draw order, as the power design's graceful-degradation rule
asks. These tests were strict xfails before that change.

What the original does (stbc-oracle, Galaxy, batteries empty, core 100%,
every slider 125%, demand about 1313 against 1000): power is handed out 3
times a second, each system gets its full share or nothing, the biggest
consumers are cut first, and the sensors and torpedoes are always served.
So the original's sensors never go dark from an over-asked plant at full
core either.

Scenario: E1M2's player Galaxy, every consumer wanted at 125%, the main
conduit set to 250/s so the idle ship's wanted total (about 314/s) is above
the budget once the backup battery is empty.
"""
import App
import pytest

from engine.appc.sensor_detection import (clear_undetectable_player_lock,
                                          effective_sensor_range)
from engine.core.loop import GameLoop, TICK_DELTA
from tests.helpers import headless_mission

E1M2 = "Maelstrom.Episode1.E1M2.E1M2"


def _consumers(ship):
    out = []
    for getter in ("GetSensorSubsystem", "GetImpulseEngineSubsystem",
                   "GetWarpEngineSubsystem", "GetTorpedoSystem",
                   "GetPhaserSystem", "GetShields", "GetRepairSubsystem"):
        sub = getattr(ship, getter)()
        if sub is not None:
            out.append(sub)
    return out


def _hold_sliders(player, level):
    """Every consumer at `level`, held there the way a player holds the
    controls: E1M2's tutorial resets the sliders on its own timer, so each
    consumer's setter is replaced on the instance after the set."""
    for sub in _consumers(player):
        sub.SetPowerPercentageWanted(level)
        sub.SetPowerPercentageWanted = lambda _pct: None


def _over_asked_player(backup=0.0):
    headless_mission.load(E1M2)
    player = App.Game_GetCurrentPlayer()
    # Red alert: shields up and weapons powered, so every conduit consumer draws.
    player.SetAlertLevel(App.ShipClass.RED_ALERT)
    _hold_sliders(player, 1.25)
    plant = player.GetPowerSubsystem()
    plant.GetProperty().SetMainConduitCapacity(1150.0)
    # The main battery below its limit, as in the live fight (73k of 200k):
    # the core's recharge then goes to the main battery and none spills into
    # the backup, so an empty backup stays empty.
    plant.SetMainBatteryPower(100000.0)
    plant.SetBackupBatteryPower(backup)
    return player, plant


def _facility(player):
    for obj in player.GetContainingSet().GetClassObjectList(App.CT_SHIP):
        if obj.GetName() == "Facility":
            return obj
    raise AssertionError("E1M2's Facility is not in the player's set")


def _step(loop, player, ticks, each=None):
    for _ in range(ticks):
        headless_mission._sim_tick(loop, player)
        if each is not None:
            each()


def test_a_powered_undamaged_sensor_array_never_reads_zero_range():
    player, plant = _over_asked_player()
    loop = GameLoop()
    _step(loop, player, int(1.0 / TICK_DELTA))      # past the first interval
    zero = []

    def look():
        if plant.GetMainBatteryPower() > 0.0 and effective_sensor_range(player) == 0.0:
            zero.append(App.g_kUtopiaModule.GetGameTime())
    _step(loop, player, int(5.0 / TICK_DELTA), look)
    assert zero == [], "sensor range 0 on %d ticks with %.0f in the main battery (first %s)" % (
        len(zero), plant.GetMainBatteryPower(), [round(t, 3) for t in zero[:5]])


def test_the_player_keeps_a_target_its_sensors_can_still_reach():
    player, plant = _over_asked_player()
    facility = _facility(player)
    loop = GameLoop()
    _step(loop, player, int(1.0 / TICK_DELTA))
    player.SetTarget(facility)
    drops = []

    def host_rule():
        clear_undetectable_player_lock(player)       # host_loop runs this every frame
        if player.GetTarget() is None:
            drops.append(App.g_kUtopiaModule.GetGameTime())
            player.SetTarget(facility)               # the persistent restore's part
    _step(loop, player, int(5.0 / TICK_DELTA), host_rule)
    assert drops == [], "the target was dropped %d times, first at %s" % (
        len(drops), [round(t, 3) for t in drops[:5]])


def test_a_long_fight_that_drains_the_backup_battery_never_blinks_the_target():
    """The live sequence: fine while the backup battery covers the excess,
    blinking from the moment it runs dry."""
    player, plant = _over_asked_player(backup=300.0)
    facility = _facility(player)
    loop = GameLoop()
    _step(loop, player, int(1.0 / TICK_DELTA))
    player.SetTarget(facility)
    drops = []

    def host_rule():
        clear_undetectable_player_lock(player)
        if player.GetTarget() is None:
            drops.append((round(App.g_kUtopiaModule.GetGameTime(), 3),
                          round(plant.GetBackupBatteryPower(), 1)))
            player.SetTarget(facility)
    _step(loop, player, int(20.0 / TICK_DELTA), host_rule)
    assert drops == [], "%d drops; first (time, backup battery): %s" % (len(drops), drops[:3])


# The conduit consumers of the over-asked Galaxy (the cloak draws from the
# backup reserve, not the conduits, so the pacing never touches it).
_CONDUIT_CONSUMERS = ("GetSensorSubsystem", "GetShields", "GetImpulseEngineSubsystem",
                      "GetPhaserSystem", "GetTorpedoSystem")


@pytest.mark.parametrize("getter", _CONDUIT_CONSUMERS)
def test_a_long_over_asked_fight_never_cuts_a_consumer_to_zero(getter):
    """Inside every interval the budget is spread over its ticks, so a
    consumer wanting power never reads efficiency 0 while the interval still
    has budget; it reads a steady reduced share instead."""
    player, plant = _over_asked_player()
    sub = getattr(player, getter)()
    loop = GameLoop()
    _step(loop, player, int(1.0 / TICK_DELTA))
    lows = []

    def look():
        if sub.GetPowerWanted() > 0.0:
            lows.append(sub.GetPowerPercentage())
    _step(loop, player, int(20.0 / TICK_DELTA), look)
    assert lows, "%s never wanted power" % getter
    assert min(lows) > 0.0, "%s: efficiency hit 0 on %d of %d ticks" % (
        getter, sum(1 for e in lows if e <= 0.0), len(lows))


def test_a_plant_that_covers_its_demand_hands_out_full_power_every_tick():
    """No shortfall, no change: every consumer gets everything it asks for."""
    headless_mission.load(E1M2)
    player = App.Game_GetCurrentPlayer()
    plant = player.GetPowerSubsystem()
    plant.SetMainBatteryPower(100000.0)
    loop = GameLoop()
    _step_plain = int(1.0 / TICK_DELTA)
    for _ in range(_step_plain):
        headless_mission._sim_tick(loop, player)
    short = []
    for _ in range(int(5.0 / TICK_DELTA)):
        headless_mission._sim_tick(loop, player)
        for sub in _consumers(player):
            if sub.GetPowerWanted() > 0.0 and sub.GetPowerPercentage() != 1.0:
                short.append((sub.GetName(), sub.GetPowerPercentage()))
    assert short == []
