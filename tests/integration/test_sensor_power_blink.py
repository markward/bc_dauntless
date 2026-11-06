"""A ship asking for more power than its conduits carry blinks its sensors to
zero at the end of every power interval, and the player loses its target.

Live report (2026-11-06, a long Quick Battle at every slider 125%): once the
Sovereign's backup battery ran dry, the player's target vanished for 0.117 s
every second and came back. The cause is the plant's interval budget
(native/src/combat/src/subsystem_step.cc power_flow): it is refilled once per
POWER_INTERVAL and every consumer draws its share from it each tick, in
attach order, so when the wanted total is above main conduit + backup conduit
the budget runs dry before the interval ends and EVERY consumer, the sensor
array included, receives nothing for the rest of it. A sensor array with no
power reads GetNormalPowerPercentage() == 0, so effective_sensor_range is 0,
and host_loop's clear_undetectable_player_lock drops the player's target;
attempt_persistent_restore puts it back after the refill.

The same happens on 0.2.1's Python power stage, so this is not new.

What the original does (stbc-oracle, Galaxy, batteries empty, core 100%,
every slider 125%, demand about 1313 against 1000): power is handed out 3
times a second, each system gets its full share or nothing, the biggest
consumers are cut first, and the sensors and torpedoes are always served.
So the original's sensors never go dark from an over-asked plant at full
core. Which fix is right is a maintainer decision (power is a deliberate
departure area), so these are strict xfails: each flips to a pass when the
blink is fixed, and the strictness makes that impossible to miss.

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
_PENDING = pytest.mark.xfail(
    strict=True,
    reason="power interval budget starves every consumer once it runs dry "
           "(subsystem_step.cc power_flow); the fix is a maintainer decision")


def _consumers(ship):
    out = []
    for getter in ("GetSensorSubsystem", "GetImpulseEngineSubsystem",
                   "GetWarpEngineSubsystem", "GetTorpedoSystem",
                   "GetPhaserSystem", "GetShields", "GetRepairSubsystem"):
        sub = getattr(ship, getter)()
        if sub is not None:
            out.append(sub)
    return out


def _over_asked_player(backup=0.0):
    headless_mission.load(E1M2)
    player = App.Game_GetCurrentPlayer()
    for sub in _consumers(player):
        sub.SetPowerPercentageWanted(1.25)
    plant = player.GetPowerSubsystem()
    plant.GetProperty().SetMainConduitCapacity(250.0)
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
        for sub in _consumers(player):
            if sub.GetPowerPercentageWanted() != 1.25:   # the mission resets sliders
                sub.SetPowerPercentageWanted(1.25)
        headless_mission._sim_tick(loop, player)
        if each is not None:
            each()


@_PENDING
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


@_PENDING
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


@_PENDING
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
