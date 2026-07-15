"""TractorBeamSystem held-fire dispatch — now on _HeldFireWeaponSystem.

Tractor beams used to inherit plain WeaponSystem.StartFiring (round-robin one
shot, no held state).  They now share the held-fire base with PhaserSystem /
PulseWeaponSystem, so:

1. SingleFire(1) (what every tractor hardpoint sets) keeps exactly ONE beam
   locked on the target per engage — a single grab beam.
2. update_weapons (the tractor's per-frame maintenance, driven by
   host_loop._pump_held_weapons) sustains that beam while the trigger (toggle)
   stays on; the beam does NOT auto-stop on charge depletion the way a phaser
   does (TractorBeam.UpdateCharge sustains it) — it is still firing well past
   the ~5 s its discharge rate would otherwise empty it.
3. _can_engage gates on TRACTOR_MAX_RANGE_GU: a target beyond range never
   engages, and a held beam whose target drifts out of range is dropped on the
   next update_weapons.

Mirrors tests/integration/test_pulse_singlefire_modes.py.
"""
from unittest.mock import patch

import App  # noqa: F401  (installs the SDK import finder via conftest)
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import TractorBeam, TractorBeamSystem
from engine.appc.properties import TractorBeamProperty, WeaponSystemProperty
from engine.appc.weapon_subsystems import TRACTOR_MAX_RANGE_GU


class _Target:
    """A live target at a settable world location."""
    def __init__(self, pos):
        self._pos = pos
    def GetWorldLocation(self):  return self._pos
    def SetWorldLocation(self, p): self._pos = p
    def IsDead(self):            return 0


def _make_emitter(name):
    """Charged tractor emitter with rechargeable values so the re-arm
    hysteresis is reachable (MinFiringCharge + 0.20*MaxCharge <= MaxCharge)."""
    emitter = TractorBeam(name)
    prop = TractorBeamProperty(name)
    prop.SetMaxCharge(5.0)
    prop.SetMinFiringCharge(3.0)
    prop.SetRechargeRate(0.5)
    prop.SetNormalDischargeRate(1.0)
    # Forward ±25° cone (default +Y direction) so an ahead target is in-arc and
    # a target behind is out-of-arc — exercises arc drop / re-acquire.
    prop.SetArcWidthAngles(-0.436332, 0.436332)
    prop.SetArcHeightAngles(-0.436332, 0.436332)
    emitter.SetProperty(prop)
    # Pass-4 copies property values onto runtime fields; do it explicitly.
    emitter._max_charge = 5.0
    emitter._min_firing_charge = 3.0
    emitter._recharge_rate = 0.5
    emitter._normal_discharge_rate = 1.0
    emitter._charge_level = 5.0   # MaxCharge -> CanFire true
    return emitter


def _build():
    """Ship with a TractorBeamSystem(SingleFire) owning two charged emitters,
    both with default forward orientation so an ahead target is in-arc.
    Returns (ship, parent_system)."""
    ship = ShipClass_Create("Test")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))

    parent = TractorBeamSystem("Tractors")
    parent.TurnOn()
    parent.SetProperty(WeaponSystemProperty("Tractors"))
    parent.SetSingleFire(1)
    parent._parent_ship = ship
    ship._tractor_beam_system = parent

    parent.AddChildSubsystem(_make_emitter("Aft Tractor"))
    parent.AddChildSubsystem(_make_emitter("Forward Tractor"))
    return ship, parent


def _num_firing(parent):
    return sum(1 for i in range(parent.GetNumWeapons())
               if parent.GetWeapon(i).IsFiring())


def _target_ahead(dist=50.0):
    return _Target(TGPoint3(0.0, dist, 0.0))


# ── SingleFire round-trip on the system (inherited from base) ────────────────

def test_single_fire_round_trips_on_tractor_system():
    parent = TractorBeamSystem("Tractors")
    parent.SetSingleFire(1)
    assert parent.GetSingleFire() == 1


# ── SingleFire(1): one sustained grab beam ───────────────────────────────────

def test_single_fire_engages_exactly_one_emitter():
    ship, parent = _build()
    target = _target_ahead()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, "hit")
    assert _num_firing(parent) == 1, "SingleFire tractor should engage one beam"
    assert parent.IsFiring() == 1
    assert parent.IsTryingToFire() == 1


def test_held_tick_keeps_single_beam_engaged():
    ship, parent = _build()
    target = _target_ahead()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, "hit")
        parent.update_weapons(0.34)
    # Still exactly one beam — SingleFire branch must not light the second.
    assert _num_firing(parent) == 1


# ── Sustain: a tractor holds continuously, no depletion auto-stop ────────────

def test_tractor_sustains_past_depletion_window():
    ship, parent = _build()
    target = _target_ahead()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, "hit")
        assert _num_firing(parent) == 1
        # 10 s at discharge 1.0/s from MaxCharge 5.0 would empty a phaser
        # bank twice over; the tractor must still be holding.
        for _ in range(100):
            for i in range(parent.GetNumWeapons()):
                parent.GetWeapon(i).UpdateCharge(0.1)
            parent.update_weapons(0.34)
    assert _num_firing(parent) == 1, "tractor must sustain past the discharge window"


# ── _can_engage range gate ───────────────────────────────────────────────────

def test_out_of_range_target_never_engages():
    ship, parent = _build()
    target = _target_ahead(dist=TRACTOR_MAX_RANGE_GU + 50.0)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, "hit")
    assert _num_firing(parent) == 0
    assert parent.IsFiring() == 0


def test_held_beam_drops_when_target_leaves_range():
    ship, parent = _build()
    target = _target_ahead(dist=50.0)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, "hit")
        assert _num_firing(parent) == 1
        # Target warps out beyond tractor range -> next retry drops the beam.
        target.SetWorldLocation(TGPoint3(0.0, TRACTOR_MAX_RANGE_GU + 100.0, 0.0))
        parent.update_weapons(0.34)
    assert _num_firing(parent) == 0
    assert parent.IsFiring() == 0


# ── Arc loss drops the beam; it re-acquires while still toggled on ───────────

def test_arc_loss_drops_beam_then_reacquires():
    ship, parent = _build()
    target = _target_ahead(dist=50.0)   # in the forward cone
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, "hit")
        assert _num_firing(parent) == 1
        # A tight turn swings the target behind — out of every emitter's arc.
        target.SetWorldLocation(TGPoint3(0.0, -50.0, 0.0))
        parent.update_weapons(0.34)
        assert _num_firing(parent) == 0, "out-of-arc target must drop the beam"
        # Still engaged (never toggled off): swing it back into the arc and the
        # beam re-fires automatically on the next retry.
        target.SetWorldLocation(TGPoint3(0.0, 50.0, 0.0))
        parent.update_weapons(0.34)
        assert _num_firing(parent) == 1, "in-arc target must re-acquire the beam"


# ── Shield gate: a tractor grips only shields-down targets ───────────────────

def _shielded_target(charged: bool):
    """Target ship with a powered shield generator, charged or depleted."""
    from engine.appc.subsystems import ShieldSubsystem
    t = ShipClass_Create("Shielded")
    t.SetWorldLocation(TGPoint3(0.0, 50.0, 0.0))
    sh = ShieldSubsystem("Shields")
    sh.TurnOn()
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        sh.SetMaxShields(f, 100.0)                       # seeds current = max
        if not charged:
            sh.SetCurrentShields(f, 0.0)
    t.SetShieldSubsystem(sh)
    return t


def test_active_shields_block_engagement():
    ship, parent = _build()
    target = _shielded_target(charged=True)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, "hit")
    assert _num_firing(parent) == 0, "active shields must deflect the tractor"


def test_depleted_shields_allow_engagement():
    ship, parent = _build()
    target = _shielded_target(charged=False)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, "hit")
    assert _num_firing(parent) == 1, "down shields must let the tractor grip"


def test_shields_raised_mid_grip_drops_beam():
    from engine.appc.subsystems import ShieldSubsystem
    ship, parent = _build()
    target = _shielded_target(charged=False)   # starts grippable
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        parent.StartFiring(target, "hit")
        assert _num_firing(parent) == 1
        # Shields come back up -> next retry drops the beam (stays engaged).
        sh = target.GetShieldSubsystem()
        for f in range(ShieldSubsystem.NUM_SHIELDS):
            sh.SetCurrentShields(f, 100.0)
        parent.update_weapons(0.34)
        assert _num_firing(parent) == 0
