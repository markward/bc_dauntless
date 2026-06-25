"""PulseWeaponSystem dispatch — SingleFire round-robin vs multi-fire all.

Mirrors PhaserSystem's _dispatch_one_or_all behaviour, but the emitters are
pulse cannons that fire discrete projectile bolts (no beam, no global range
gate). SingleFire(0) fires every eligible cannon together; SingleFire(1)
round-robins one eligible cannon per trigger. Held-fire is driven per-frame
by retry_held_fire (host_loop._advance_combat). See
sdk/Build/scripts/ships/Hardpoints/birdofprey.py (SetSingleFire(0)) and
warbird.py (SetSingleFire(1)).
"""
from unittest.mock import patch

import App  # noqa: F401  (installs the SDK import finder via conftest)
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import PulseWeapon, PulseWeaponSystem
from engine.appc.properties import PulseWeaponProperty, WeaponSystemProperty
from engine.appc.projectiles import _active

_MODULE = "Tactical.Projectiles.PulseDisruptor"


class _Target:
    """A live target at a fixed world location."""
    def __init__(self, pos):
        self._pos = pos
    def GetWorldLocation(self):  return self._pos
    def IsDead(self):            return 0


# BoP StarCannon arc: a ±25° (±0.436 rad) forward cone — see
# sdk/Build/scripts/ships/Hardpoints/birdofprey.py SetArcWidthAngles.
_ARC = 0.436332


def _make_cannon(name):
    cannon = PulseWeapon(name)
    prop = PulseWeaponProperty(name)
    # Charge model with a REACHABLE refire threshold: the energy-weapon
    # re-arm hysteresis needs MinFiringCharge + 0.20*MaxCharge <= MaxCharge,
    # so MinFiringCharge must sit well below MaxCharge for a cannon to fire
    # more than once. (The stock BoP 3.6/3.8 values never re-arm — a latent
    # prerequisite quirk, out of scope here; we pick rechargeable values so
    # the retry path is deterministically exercisable.)
    prop.SetMaxCharge(10.0)
    prop.SetMinFiringCharge(2.0)
    prop.SetRechargeRate(5.0)
    prop.SetNormalDischargeRate(1.0)
    prop.SetCooldownTime(0.2)
    prop.SetMaxDamage(200.0)
    prop.SetModuleName(_MODULE)
    # Real ±25° forward cone so an aft target falls outside the arc.
    prop.SetArcWidthAngles(-_ARC, _ARC)
    prop.SetArcHeightAngles(-_ARC, _ARC)
    cannon.SetProperty(prop)
    # Pass-4 copies property values onto runtime fields; do it explicitly.
    cannon._max_charge = 10.0
    cannon._min_firing_charge = 2.0
    cannon._recharge_rate = 5.0
    cannon._normal_discharge_rate = 1.0
    cannon._cooldown_time = 0.2
    cannon._charge_level = 10.0  # MaxCharge -> CanFire true
    cannon._armed = True
    return cannon


def _build(single_fire):
    """Ship with a PulseWeaponSystem parent owning two charged cannons,
    both pointing +Y (forward, default direction) so an ahead target is
    in-arc. Returns (ship, parent_system)."""
    ship = ShipClass_Create("Test")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))

    parent = PulseWeaponSystem("Disruptor Cannons")
    parent.TurnOn()
    parent_prop = WeaponSystemProperty("Disruptor Cannons")
    parent.SetProperty(parent_prop)
    parent.SetSingleFire(single_fire)
    parent._parent_ship = ship
    ship._pulse_weapon_system = parent

    parent.AddChildSubsystem(_make_cannon("Port Cannon"))
    parent.AddChildSubsystem(_make_cannon("Star Cannon"))
    return ship, parent


def _target_ahead():
    return _Target(TGPoint3(0.0, 100.0, 0.0))


def _target_behind():
    return _Target(TGPoint3(0.0, -100.0, 0.0))


# ── SingleFire round-trip ───────────────────────────────────────────────────

def test_single_fire_round_trips_on_system():
    parent = PulseWeaponSystem("Pulse")
    assert parent.GetSingleFire() == 0
    parent.SetSingleFire(1)
    assert parent.GetSingleFire() == 1
    parent.SetSingleFire(0)
    assert parent.GetSingleFire() == 0


# ── SingleFire(0): every eligible cannon fires together ─────────────────────

def test_multi_fire_engages_both_cannons():
    _active.clear()
    ship, parent = _build(single_fire=0)
    target = _target_ahead()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, "hit")
    assert len(_active) == 2, f"SingleFire(0) should fire both cannons, got {len(_active)}"
    _active.clear()


# ── SingleFire(1): one cannon per trigger, cursor advances ──────────────────

def test_single_fire_round_robins_one_cannon_per_trigger():
    _active.clear()
    ship, parent = _build(single_fire=1)
    target = _target_ahead()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, "hit")
        assert len(_active) == 1, f"first trigger should fire 1 cannon, got {len(_active)}"
        first_cursor = parent._next_emitter_index
        # Both cannons are charged, so the only gate on the SECOND trigger
        # is the round-robin cursor — it must advance to the OTHER cannon.
        parent.StartFiring(target, "hit")
    assert len(_active) == 2, f"second trigger should fire the other cannon, got {len(_active)}"
    assert parent._next_emitter_index != first_cursor or first_cursor == 0
    _active.clear()


# ── retry_held_fire: gated by cooldown, re-fires after recharge ─────────────

def test_retry_held_fire_blocked_during_cooldown_then_refires():
    _active.clear()
    ship, parent = _build(single_fire=0)
    target = _target_ahead()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, "hit")
        assert len(_active) == 2
        # Both cannons drained + on cooldown. retry while on cooldown -> nothing.
        parent.retry_held_fire()
    assert len(_active) == 2, "retry during cooldown must not spawn new bolts"

    # Step enough simulated dt to clear cooldown AND recharge past the
    # refire threshold so the cannons re-arm.
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        for _ in range(200):
            for i in range(parent.GetNumWeapons()):
                parent.GetWeapon(i).UpdateCharge(0.1)
        parent.retry_held_fire()
    assert len(_active) == 4, f"retry after recharge should re-fire both, got {len(_active)}"
    _active.clear()


# ── StopFiring clears held state ────────────────────────────────────────────

def test_stop_firing_clears_held_state():
    _active.clear()
    ship, parent = _build(single_fire=0)
    target = _target_ahead()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, "hit")
        assert len(_active) == 2
        parent.StopFiring()
        assert parent._fire_held is False
        # Recharge then retry — nothing fires because the trigger is released.
        for _ in range(200):
            for i in range(parent.GetNumWeapons()):
                parent.GetWeapon(i).UpdateCharge(0.1)
        parent.retry_held_fire()
    assert len(_active) == 2, "retry after StopFiring must not fire"
    _active.clear()


# ── Out-of-arc target ───────────────────────────────────────────────────────

def test_out_of_arc_target_does_not_fire():
    _active.clear()
    ship, parent = _build(single_fire=0)
    target = _target_behind()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, "hit")
    assert len(_active) == 0, "aft target must not fire forward cannons"
    _active.clear()
