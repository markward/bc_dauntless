"""Tractor-beam EFFECT — per-mode physics applied to the locked target.

Engages a tractor on a target a fixed distance away, steps the effect, and
asserts the target (and, where reciprocal, the source) moves in the
mode-correct direction:

    PULL  → distance closes        PUSH  → distance opens
    HOLD  → target springs back to its captured point + velocity damped
    TOW   → target follows when the source moves
    mass  → a light hull moves more than a heavy one; a starbase barely moves
    recip → PULL also draws the source toward the target

Mirrors tests/integration/test_disruptor_fire_and_damage.py (build a firing
energy weapon, then drive it through the per-frame combat passes).  The effect
is exercised both directly (engine.appc.tractor.advance_tractors) and through
host_loop._advance_combat to confirm the wiring reaches it.
"""
from unittest.mock import patch

import App  # noqa: F401  (installs the SDK import finder via conftest)
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import TractorBeam, TractorBeamSystem
from engine.appc.properties import TractorBeamProperty, WeaponSystemProperty
from engine.appc.tractor import advance_tractors
from engine.host_loop import _advance_combat, _advance_weapons

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


def _target(pos, mass=100.0):
    t = ShipClass_Create("Target")
    t.SetWorldLocation(TGPoint3(*pos))
    t.SetMass(mass)
    return t


def _engage(parent, target, mode):
    parent.SetMode(mode)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, None)


def _dist(a, b):
    pa, pb = a.GetWorldLocation(), b.GetWorldLocation()
    dx, dy, dz = pa.x - pb.x, pa.y - pb.y, pa.z - pb.z
    return (dx*dx + dy*dy + dz*dz) ** 0.5


# ── PULL closes, PUSH opens ──────────────────────────────────────────────────

def test_pull_closes_distance():
    ship, parent = _source_with_tractor()
    target = _target((0, 50, 0))
    _engage(parent, target, TractorBeamSystem.TBS_PULL)
    start = _dist(ship, target)
    for _ in range(120):
        advance_tractors([ship, target], _DT)
    assert _dist(ship, target) < start - 1.0


def test_push_opens_distance():
    ship, parent = _source_with_tractor()
    target = _target((0, 50, 0))
    _engage(parent, target, TractorBeamSystem.TBS_PUSH)
    start = _dist(ship, target)
    for _ in range(120):
        advance_tractors([ship, target], _DT)
    assert _dist(ship, target) > start + 1.0


# ── Reciprocity: PULL draws the source toward the target ─────────────────────

def test_pull_is_reciprocal_on_source():
    ship, parent = _source_with_tractor()
    target = _target((0, 50, 0))
    _engage(parent, target, TractorBeamSystem.TBS_PULL)
    for _ in range(120):
        advance_tractors([ship, target], _DT)
    # Source started at y=0 and is drawn toward the target ahead (+y).
    assert ship.GetWorldLocation().y > 1.0
    # Target started at y=50 and is drawn back toward the source.
    assert target.GetWorldLocation().y < 49.0


# ── Mass: light hull moves more; starbase essentially immovable ──────────────

def test_lighter_target_moves_more_under_pull():
    ship_l, parent_l = _source_with_tractor()
    light = _target((0, 50, 0), mass=10.0)
    _engage(parent_l, light, TractorBeamSystem.TBS_PULL)

    ship_h, parent_h = _source_with_tractor()
    heavy = _target((0, 50, 0), mass=1000.0)
    _engage(parent_h, heavy, TractorBeamSystem.TBS_PULL)

    light_start = light.GetWorldLocation().y
    heavy_start = heavy.GetWorldLocation().y
    for _ in range(60):
        advance_tractors([ship_l, light], _DT)
        advance_tractors([ship_h, heavy], _DT)
    light_moved = light_start - light.GetWorldLocation().y
    heavy_moved = heavy_start - heavy.GetWorldLocation().y
    assert light_moved > heavy_moved


def test_starbase_mass_is_essentially_immovable():
    ship, parent = _source_with_tractor()
    station = _target((0, 50, 0), mass=1.0e6)
    _engage(parent, station, TractorBeamSystem.TBS_PULL)
    start = station.GetWorldLocation().y
    for _ in range(120):
        advance_tractors([ship, station], _DT)
    assert abs(station.GetWorldLocation().y - start) < 0.1


# ── HOLD: pin at captured point + damp velocity ──────────────────────────────

def test_hold_springs_target_back_to_captured_point():
    ship, parent = _source_with_tractor()
    target = _target((0, 50, 0))
    _engage(parent, target, TractorBeamSystem.TBS_HOLD)
    # First tick captures the hold-point (the rest position).
    advance_tractors([ship, target], _DT)
    # Something shoves the target away from the captured point.
    target.SetTranslateXYZ(0.0, 80.0, 0.0)
    shoved = abs(target.GetWorldLocation().y - 50.0)
    for _ in range(120):
        advance_tractors([ship, target], _DT)
    assert abs(target.GetWorldLocation().y - 50.0) < shoved - 1.0


def test_hold_damps_target_velocity():
    ship, parent = _source_with_tractor()
    target = _target((0, 50, 0))
    target.SetVelocity(TGPoint3(0.0, 10.0, 0.0))
    _engage(parent, target, TractorBeamSystem.TBS_HOLD)
    advance_tractors([ship, target], _DT)
    v = target.GetVelocity()
    assert abs(v.x) < 1e-6 and abs(v.y) < 1e-6 and abs(v.z) < 1e-6


# ── TOW: target follows when the source moves ────────────────────────────────

def test_tow_target_follows_source():
    ship, parent = _source_with_tractor()
    target = _target((0, 50, 0))
    _engage(parent, target, TractorBeamSystem.TBS_TOW)
    # First tick captures the body-frame tow offset.
    advance_tractors([ship, target], _DT)
    # The tower moves off along +x; the towed target should chase it.
    ship.SetTranslateXYZ(100.0, 0.0, 0.0)
    for _ in range(180):
        advance_tractors([ship, target], _DT)
    assert target.GetWorldLocation().x > 1.0


# ── Wiring: the effect is reached through host_loop._advance_combat ──────────

def test_effect_runs_through_advance_combat():
    ship, parent = _source_with_tractor()
    target = _target((0, 50, 0))
    _engage(parent, target, TractorBeamSystem.TBS_PULL)
    start = _dist(ship, target)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        for _ in range(120):
            _advance_weapons([ship, target], _DT)
            _advance_combat([ship, target], dt=_DT, host=None, ship_instances=None)
    assert _dist(ship, target) < start - 1.0


def test_non_tractor_ship_is_untouched():
    # A ship with no tractor system must not move under the tractor pass.
    plain = ShipClass_Create("Plain")
    plain.SetWorldLocation(TGPoint3(7, 8, 9))
    before = plain.GetWorldLocation()
    advance_tractors([plain], _DT)
    after = plain.GetWorldLocation()
    assert (after.x, after.y, after.z) == (before.x, before.y, before.z)
