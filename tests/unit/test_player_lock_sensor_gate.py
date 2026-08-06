"""The player's weapon lock must drop when the target stops being detectable.

The host loop already dropped the lock when a target finished CLOAKING, with
the right reasoning in its comment: "AI ships re-select via SelectTarget; the
player has no such preprocessor, so the lock would otherwise persist." But it
gated on ``is_hidden_by_cloak`` — one specific way to lose a contact — instead
of ``can_detect``, the engine's authoritative detection predicate already used
at the firing chokepoint (host_loop.py:716), the AI candidate gate, projectiles
and weapon_subsystems.

So cutting sensor power to 0% emptied the target list (whose gate DOES consult
the sensors) while the lock survived: locked onto a ship you cannot see or fire
on. Live-reported by Mark 2026-08-06.

Sensors at 0% power reach this through ``effective_sensor_range``, which
multiplies by GetNormalPowerPercentage() — so range collapses to 0.0 and
can_detect fails on ``r <= 0.0``, whether or not the subsystem also reports
_is_offline.
"""
import App

from engine.appc.sensor_detection import clear_undetectable_player_lock
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import CloakingSubsystem, SensorSubsystem


def _scene(separation_gu=50.0):
    """A player with working sensors holding a lock on a nearby enemy."""
    App.g_kSetManager._sets.clear()
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    player = ShipClass_Create("Galaxy")
    player.SetName("Player")
    player.SetTranslateXYZ(0, 0, 0)
    sensors = SensorSubsystem("Sensor Array")
    sensors.SetBaseSensorRange(1000.0)
    player.SetSensorSubsystem(sensors)
    pSet.AddObjectToSet(player, "Player")

    enemy = ShipClass_Create("Warbird")
    enemy.SetName("Enemy")
    enemy.SetTranslateXYZ(0, separation_gu, 0)
    pSet.AddObjectToSet(enemy, "Enemy")

    player.SetTarget(enemy)
    assert player.GetTarget() is enemy
    return player, enemy, sensors


def test_lock_survives_a_detectable_target():
    player, enemy, _ = _scene()
    clear_undetectable_player_lock(player)
    assert player.GetTarget() is enemy


def test_lock_drops_when_sensors_lose_all_power():
    # Mark's repro: drag sensor power to 0% and the target list empties, but
    # the lock used to survive.
    player, _, sensors = _scene()
    sensors._power_factor = 0.0
    clear_undetectable_player_lock(player)
    assert player.GetTarget() is None


def test_lock_survives_partial_sensor_power():
    # Degraded, not blind: range shrinks but the target is still well inside it.
    player, enemy, sensors = _scene()
    sensors._power_factor = 0.5
    clear_undetectable_player_lock(player)
    assert player.GetTarget() is enemy


def test_lock_drops_when_sensors_are_destroyed():
    player, _, sensors = _scene()
    sensors.SetDestroyed(1)
    clear_undetectable_player_lock(player)
    assert player.GetTarget() is None


def test_lock_drops_when_the_target_cloaks():
    # Behaviour the host loop already had; it must survive the swap from
    # is_hidden_by_cloak to can_detect (whose first gate is the same test).
    player, enemy, _ = _scene()
    enemy.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    clear_undetectable_player_lock(player)
    assert player.GetTarget() is enemy          # decloaked → lock holds
    enemy.GetCloakingSubsystem().InstantCloak()
    clear_undetectable_player_lock(player)
    assert player.GetTarget() is None


def test_lock_drops_when_the_target_leaves_sensor_range():
    # can_detect is range-aware, so the lock now agrees with the firing
    # chokepoint, which already stops firing at can_detect == False.
    player, _, _ = _scene(separation_gu=5000.0)   # base range is 1000 GU
    clear_undetectable_player_lock(player)
    assert player.GetTarget() is None


def test_no_target_is_a_no_op():
    player, _, _ = _scene()
    player.SetTarget(None)
    clear_undetectable_player_lock(player)       # must not raise
    assert player.GetTarget() is None


def test_no_player_is_a_no_op():
    clear_undetectable_player_lock(None)          # host loop calls this before
    # a player exists during boot; must be silent rather than raise.
