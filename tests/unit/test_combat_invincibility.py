"""combat.apply_hit must honour BC's invincibility surface — real gameplay,
NOT a dev cheat, so these apply with dev mode OFF:

* ShipClass.SetHurtable(0) makes the WHOLE ship immune (E7M2's JonKa and
  Chairo "not hurtable", E3M1's "player can't be hurt"). Immune = takes no
  hull/shield/subsystem damage, but hit feedback still fires (the shot
  visually connects).
* ShipClass.SetInvincible(1) does NOT make it immune: damage lands and only
  the death is stopped (native-damage ruling M1; the death side is pinned in
  test_damage_immunity_semantics.py).
* ShipSubsystem.SetInvincible protects one subsystem (MissionLib.
  MakeSubsystemsInvincible — e.g. a capture-mission warp core that must
  survive) while the rest of the ship takes damage normally.

Before this surface existed, all four methods fell through to the truthy
TGObject _Stub and combat.apply_hit had no immunity gate at all, so an
"invincible" mission ship could be destroyed."""
from unittest.mock import patch

import pytest

from engine.appc.math import TGPoint3
from engine.appc.combat import apply_hit
from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem, SensorSubsystem
from engine.appc import effect_queue


def _ship(name, hull_max=2000.0, face_max=1000.0):
    ship = ShipClass_Create(name)
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(hull_max)
    ship._hull = hull
    ss = ShieldSubsystem("Shield Generator")
    ss.SetMaxCondition(100.0)
    ss.SetDisabledPercentage(0.25)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, face_max)
    ship.SetShieldSubsystem(ss)
    ship._radius = 20.0
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT)
    return ship


# ── ship-level: SetInvincible ──────────────────────────────────────────────
def test_invincible_ship_takes_damage_and_feedback_fires():
    ship = _ship("Vorcha")
    ship.SetInvincible(1)
    ship.GetShields().SetCurrentShields(0, 0.0)   # drained: hit would reach hull
    with patch("engine.appc.hit_feedback.dispatch") as mock_dispatch:
        apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)
        effect_queue.boundary()             # the tick boundary
    assert ship.GetHull().GetCondition() == 1500.0   # damage lands (M1)
    assert mock_dispatch.called


def test_invincible_cleared_restores_damage():
    ship = _ship("Vorcha")
    ship.SetInvincible(1)
    ship.SetInvincible(0)
    ship.GetShields().SetCurrentShields(0, 0.0)
    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)
    assert ship.GetHull().GetCondition() == 1500.0


# ── ship-level: SetHurtable ────────────────────────────────────────────────
def test_unhurtable_ship_takes_no_damage_but_feedback_fires():
    ship = _ship("Player")
    ship.SetHurtable(0)
    ship.GetShields().SetCurrentShields(0, 0.0)
    with patch("engine.appc.hit_feedback.dispatch") as mock_dispatch:
        apply_hit(ship, 5000.0, TGPoint3(0, 10, 0), source=None)
        effect_queue.boundary()             # the tick boundary
    assert ship.GetHull().GetCondition() == 2000.0   # no damage
    assert mock_dispatch.called                       # but the shot connects


def test_hurtable_restored_takes_damage():
    ship = _ship("Player")
    ship.SetHurtable(0)
    ship.SetHurtable(1)   # E3M1 restores at the end of the scripted window
    ship.GetShields().SetCurrentShields(0, 0.0)
    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)
    assert ship.GetHull().GetCondition() == 1500.0


def test_default_ship_is_hurtable_and_not_invincible():
    ship = _ship("NPC")
    assert ship.IsInvincible() == 0
    assert ship.IsHurtable() == 1
    ship.GetShields().SetCurrentShields(0, 0.0)
    apply_hit(ship, 500.0, TGPoint3(0, 10, 0), source=None)
    assert ship.GetHull().GetCondition() == 1500.0


# ── subsystem-level: MakeSubsystemsInvincible ──────────────────────────────
def _ship_with_sensor(name):
    ship = _ship(name)
    sensor = SensorSubsystem("Sensor Array")
    sensor.SetMaxCondition(400.0)
    sensor.SetCondition(400.0)
    sensor.SetRadius(5.0)
    sensor._position = TGPoint3(0.0, 10.0, 0.0)   # at the hit point
    ship.SetSensorSubsystem(sensor)
    return ship, sensor


def test_invincible_subsystem_spared_while_hull_damaged():
    ship, sensor = _ship_with_sensor("Keldon")
    sensor.SetInvincible(1)
    # bypass_shields routes full damage to hull + subsystems; hit lands on the
    # sensor's world position so it is inside the splash sphere.
    apply_hit(ship, 300.0, TGPoint3(0, 10, 0), source=None,
              splash_radius=5.0, bypass_shields=True)
    assert sensor.GetCondition() == 400.0            # protected subsystem intact
    assert ship.GetHull().GetCondition() < 2000.0    # rest of the ship still hurt


def test_non_invincible_subsystem_takes_damage():
    ship, sensor = _ship_with_sensor("Keldon")
    assert sensor.IsInvincible() == 0                # default
    apply_hit(ship, 300.0, TGPoint3(0, 10, 0), source=None,
              splash_radius=5.0, bypass_shields=True)
    assert sensor.GetCondition() < 400.0             # unprotected: takes its share
