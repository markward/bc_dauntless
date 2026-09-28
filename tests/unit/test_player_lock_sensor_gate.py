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

from engine.appc.placement import PlacementObject
from engine.appc.sensor_detection import clear_undetectable_player_lock
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import CloakingSubsystem, SensorSubsystem
from tests.helpers.cloak_geometry import assert_outside
from tests.helpers.fresh_world import _fresh_world
from tests.helpers.mapped_regions import load_region


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
    # Still passes unchanged under ENHANCED_SENSOR_CONTEST: the cloak bubble is
    # a flat floor plus a fraction of range, and this fixture's 1000 GU base
    # range leaves an enemy 50 GU away comfortably outside it. Pinned rather
    # than assumed. See tests/unit/test_cloak_detection_contest.py.
    assert_outside(50.0, 1000.0)
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


def test_lock_survives_orbiting_a_distant_planet():
    """Mark's live regression, 2026-09-28: orbiting a planet no longer locks
    the camera on. Bridge/HelmMenuHandlers.py's OrbitPlanet sets the player's
    target to the planet the instant Orbit is chosen -- before the
    AI.Player.OrbitPlanet AI has flown the ship anywhere near it. On this
    branch engine.systems.apply_map places a mapped region's real "Player
    Start" placement about ~6,000 GU from Ona 1 (radius 1,800 GU), well past
    a Galaxy's 2,000 GU sensor range, so the very next
    clear_undetectable_player_lock() call dropped the target before the ship
    could ever close the distance. A planet can't hide or leave sensor range
    the way a ship can, so it must never be dropped by this rule.
    """
    _fresh_world()
    pSet = load_region("Ona", "Ona1")
    planet = pSet.GetObject("Ona 1")
    assert planet is not None

    player = ShipClass_Create("Galaxy")
    player.SetName("Player")
    pSet.AddObjectToSet(player, "Player")
    player.PlaceObjectByName("Player Start")
    sensors = SensorSubsystem("Sensor Array")
    sensors.SetBaseSensorRange(2000.0)
    player.SetSensorSubsystem(sensors)

    p_loc, t_loc = player.GetWorldLocation(), planet.GetWorldLocation()
    dx, dy, dz = t_loc.x - p_loc.x, t_loc.y - p_loc.y, t_loc.z - p_loc.z
    separation = (dx * dx + dy * dy + dz * dz) ** 0.5
    assert separation > 2000.0, "fixture no longer reproduces the out-of-range gap"

    player.SetTarget(planet)
    clear_undetectable_player_lock(player)
    assert player.GetTarget() is planet


def test_lock_survives_a_nav_point_beyond_sensor_range():
    # A waypoint/placement is a nav marker, not a ship -- it has no sensors
    # to lose and cannot "leave range" of anything. Mirrors the planet case.
    player, _, sensors = _scene()
    sensors._power_factor = 1.0
    nav = PlacementObject()
    nav.SetName("Nav Point")
    nav.SetTranslateXYZ(0, 50000.0, 0)   # far past the 1000 GU base range
    player.SetTarget(nav)
    clear_undetectable_player_lock(player)
    assert player.GetTarget() is nav
