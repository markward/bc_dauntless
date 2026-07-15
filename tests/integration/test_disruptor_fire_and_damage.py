"""Held-trigger pulse weapons (disruptors) driven through _advance_combat.

Two behaviours pinned here:

1. End-to-end: a held-fire disruptor cannon spawns a bolt that flies to a
   target ahead and routes damage through combat.apply_hit (mirrors the
   torpedo run smoke + phaser apply_hit test) — the target's hull condition
   drops.

2. Continuity via the hook: after a single StartFiring, _advance_combat's
   per-frame weapon tick (_pump_held_weapons) keeps re-firing cannons as they recharge
   past the refire threshold while the trigger stays held — WITHOUT any
   further StartFiring call. More than one bolt is spawned over time.

Pulse bolts are spawned into projectiles._active by PulseWeapon.Fire and the
existing torpedo hit loop in _advance_combat routes their damage; this step
adds only the per-frame tick driver. See
tests/integration/test_pulse_singlefire_modes.py for the ship/cannon build,
tests/integration/test_phaser_damage_applied_through_apply_hit.py for the
apply_hit damage assertion, and test_torpedo_run_smoke.py for the
step-until-impact loop.
"""
from unittest.mock import patch

from engine.appc import projectiles
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import HullSubsystem, PulseWeapon, PulseWeaponSystem
from engine.appc.properties import PulseWeaponProperty, WeaponSystemProperty
from engine.host_loop import _advance_combat, _advance_weapons

_MODULE = "Tactical.Projectiles.PulseDisruptor"

# BoP StarCannon arc: a ±25° forward cone — see test_pulse_singlefire_modes.
_ARC = 0.436332


def _make_cannon(name):
    """Charged pulse cannon with rechargeable values so the refire
    hysteresis can re-arm (mirrors test_pulse_singlefire_modes._make_cannon)."""
    cannon = PulseWeapon(name)
    prop = PulseWeaponProperty(name)
    prop.SetMaxCharge(10.0)
    prop.SetMinFiringCharge(2.0)
    prop.SetRechargeRate(5.0)
    prop.SetNormalDischargeRate(1.0)
    prop.SetCooldownTime(0.2)
    prop.SetMaxDamage(200.0)
    prop.SetModuleName(_MODULE)
    prop.SetArcWidthAngles(-_ARC, _ARC)
    prop.SetArcHeightAngles(-_ARC, _ARC)
    cannon.SetProperty(prop)
    cannon._max_charge = 10.0
    cannon._min_firing_charge = 2.0
    cannon._recharge_rate = 5.0
    cannon._normal_discharge_rate = 1.0
    cannon._cooldown_time = 0.2
    cannon._charge_level = 10.0
    cannon._armed = True
    return cannon


def _build_ship(num_cannons=1):
    """Ship at origin facing +Y with a PulseWeaponSystem owning charged
    forward cannons (SingleFire(0) so every eligible cannon fires)."""
    ship = ShipClass_Create("Attacker")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))

    parent = PulseWeaponSystem("Disruptor Cannons")
    parent.TurnOn()
    parent.SetProperty(WeaponSystemProperty("Disruptor Cannons"))
    parent.SetSingleFire(0)
    parent._parent_ship = ship
    ship._pulse_weapon_system = parent

    for i in range(num_cannons):
        parent.AddChildSubsystem(_make_cannon("Cannon %d" % i))
    return ship, parent


def _build_target(at_y=40.0, hull_max=100000.0, radius=20.0):
    """Hull-only target directly ahead (no shields, so damage lands on hull)."""
    tgt = ShipClass_Create("Target")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(hull_max)
    tgt._hull = hull
    tgt.SetWorldLocation(TGPoint3(0.0, at_y, 0.0))
    tgt._radius = radius
    return tgt


def test_held_disruptor_fire_damages_target_through_apply_hit():
    """One StartFiring + stepping the loop flies a bolt into the target
    ahead; its hull condition drops (damage routed via apply_hit)."""
    projectiles._active.clear()
    ship, parent = _build_ship(num_cannons=1)
    target = _build_target(at_y=40.0)
    ship.SetTarget(target)

    hull_before = target._hull.GetCondition()

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, "hit")
        # 55 GU/s over 40 GU ≈ 0.73 s; step well past impact.
        for _ in range(40):
            _advance_weapons([ship, target], 0.05)
            _advance_combat([ship, target], dt=0.05, ship_instances=None)

    hull_after = target._hull.GetCondition()
    assert hull_after < hull_before, (
        "disruptor bolt should damage target hull; "
        "before=%s after=%s" % (hull_before, hull_after)
    )
    projectiles._active.clear()


def test_held_trigger_refires_via_advance_combat_hook():
    """After a single StartFiring, _advance_combat's weapon tick
    keeps re-firing the cannon as it recharges — MORE than one bolt spawns
    over time WITHOUT calling StartFiring again. Bolts impact/expire and
    leave _active, so we count cumulative register() calls, not len(_active)."""
    projectiles._active.clear()
    ship, parent = _build_ship(num_cannons=1)
    target = _build_target(at_y=40.0)
    ship.SetTarget(target)

    spawn_count = {"n": 0}
    real_register = projectiles.register

    def counting_register(torp):
        spawn_count["n"] += 1
        return real_register(torp)

    with patch("engine.audio.tg_sound.TGSoundManager.instance"), \
         patch.object(projectiles, "register", counting_register):
        parent.StartFiring(target, "hit")
        bolts_after_start = spawn_count["n"]
        # One trigger fires exactly one bolt.
        assert bolts_after_start == 1, (
            "StartFiring should fire one bolt, got %d" % bolts_after_start
        )
        # Step long enough for the cannon to clear cooldown + recharge past
        # the refire threshold several times. The weapon tick (inside
        # _advance_combat) is the ONLY thing that can re-fire it.
        for _ in range(80):
            _advance_weapons([ship, target], 0.1)
            _advance_combat([ship, target], dt=0.1, ship_instances=None)

    assert spawn_count["n"] > 1, (
        "held trigger should re-fire over time via the _advance_combat hook; "
        "total bolts spawned=%d (expected > 1)" % spawn_count["n"]
    )
    projectiles._active.clear()
