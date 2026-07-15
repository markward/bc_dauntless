"""Tractor toggle = a persistent ON/OFF *intent*, independent of IsFiring().

Bug fixed here (found live): the panel/menu toggle reflected IsFiring() (the
instantaneous beam state).  It now reflects IsEngaged() — the sticky intent that
stays ON while the player wants the tractor engaged, re-acquiring the beam each
frame via update_weapons.  Crucially IsEngaged stays 1 even when the beam can't
currently grip (target's shields up / out of range), so the button doesn't flip
back to Off.  Firing/grip semantics (range + shields-down) are unchanged.

Construction mirrors tests/integration/test_tractor_effect.py.
"""
from unittest.mock import patch

import App  # noqa: F401  (installs the SDK import finder via conftest)
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import (
    ShieldSubsystem,
    TractorBeam,
    TractorBeamSystem,
)
from engine.appc.properties import TractorBeamProperty, WeaponSystemProperty
from engine.appc.tractor import advance_tractors

_DT = 1.0 / 60.0


def _make_emitter(name):
    emitter = TractorBeam(name)
    prop = TractorBeamProperty(name)
    prop.SetMaxCharge(5.0)
    prop.SetMinFiringCharge(3.0)
    prop.SetRechargeRate(0.5)
    prop.SetNormalDischargeRate(1.0)
    emitter.SetProperty(prop)
    emitter._max_charge = 5.0
    emitter._min_firing_charge = 3.0
    emitter._recharge_rate = 0.5
    emitter._normal_discharge_rate = 1.0
    emitter._charge_level = 5.0
    emitter._armed = True
    return emitter


def _source_with_tractor(mass=100.0):
    ship = ShipClass_Create("Source")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    ship.SetMass(mass)
    parent = TractorBeamSystem("Tractors")
    parent.TurnOn()
    parent.SetProperty(WeaponSystemProperty("Tractors"))
    parent.SetSingleFire(1)
    parent._parent_ship = ship
    ship._tractor_beam_system = parent
    parent.AddChildSubsystem(_make_emitter("Aft Tractor"))
    return ship, parent


def _target(pos, mass=100.0, *, shields_up=False):
    t = ShipClass_Create("Target")
    t.SetWorldLocation(TGPoint3(*pos))
    t.SetMass(mass)
    if shields_up:
        shields = ShieldSubsystem("Shields")
        shields.TurnOn()
        for f in range(ShieldSubsystem.NUM_SHIELDS):
            shields.SetMaxShields(f, 1000.0)   # seeds current to max
        t.SetShieldSubsystem(shields)
    return t


def _engage(parent, target, mode=TractorBeamSystem.TBS_PULL):
    parent.SetMode(mode)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, None)


def _dist(a, b):
    pa, pb = a.GetWorldLocation(), b.GetWorldLocation()
    dx, dy, dz = pa.x - pb.x, pa.y - pb.y, pa.z - pb.z
    return (dx*dx + dy*dy + dz*dz) ** 0.5


# ── IsEngaged: persistent intent, independent of IsFiring ────────────────────

def test_is_engaged_zero_before_engage():
    _ship, parent = _source_with_tractor()
    assert parent.IsEngaged() == 0


def test_is_engaged_one_after_start_even_with_shields_up():
    _ship, parent = _source_with_tractor()
    target = _target((0, 50, 0), shields_up=True)
    _engage(parent, target)
    assert parent.IsEngaged() == 1


def test_is_engaged_back_to_zero_after_stop():
    _ship, parent = _source_with_tractor()
    target = _target((0, 50, 0), shields_up=True)
    _engage(parent, target)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StopFiring()
    assert parent.IsEngaged() == 0


# ── Shields still deflect the pull (unchanged grip semantics) ────────────────

def test_advance_moves_target_when_shields_down():
    ship, parent = _source_with_tractor()
    target = _target((0, 50, 0), shields_up=False)
    _engage(parent, target)
    start = _dist(ship, target)
    for _ in range(120):
        advance_tractors([ship, target], _DT)
    assert _dist(ship, target) < start - 1.0
