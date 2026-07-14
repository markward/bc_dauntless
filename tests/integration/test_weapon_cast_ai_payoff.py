"""Payoff evidence for App.Weapon_Cast / App.PulseWeaponSystem_Cast (Task 7).

Both casts were undefined `_NamedStub`s before this fix. This file proves
two real SDK code paths, driven end-to-end through the engine's own AI
loader (`PlainAI_Create(...).SetScriptModule(...)`), now behave correctly
on a real ship instead of silently degrading:

1. AI/PlainAI/IntelligentCircleObject.py:44-64 — `self.lWeapons` is built
   from `App.Weapon_Cast(pSystem.GetChildSubsystem(iWeapon))`, `if pWeapon:`.
   Before the fix this always appended a truthy `_NamedStub` (whether or not
   the child was actually a leaf weapon); after the fix it appends the real
   leaf emitters and rejects non-weapons cleanly (`Weapon_Cast` returns
   `None` for anything that isn't a leaf).

2. AI/Preprocessors.py:771-778 (FireScript.GetWeaponInfo, called from
   CheckGoodShot) — `pPulseSystem = App.PulseWeaponSystem_Cast(pWeaponSystem)`,
   then `range(pPulseSystem.GetNumChildSubsystems())`. Before the fix,
   `App.PulseWeaponSystem_Cast` was an undefined `_NamedStub`; the stub
   result of calling it was itself truthy (`pPulseSystem != None` passed),
   but `pPulseSystem.GetNumChildSubsystems()` was ALSO a stub, and
   `range()` coerces it via `int() == 0` — so the loop body never ran and
   `lDirections` stayed empty no matter how many pulse weapons the ship had.
   After the fix, `PulseWeaponSystem_Cast` returns the real system and the
   loop enumerates every child pulse weapon's firing direction.
"""
import App
from engine.appc.ai import PreprocessingAI_Create, PlainAI_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import HullSubsystem
from engine.appc.weapon_subsystems import (
    PhaserSystem, PhaserBank, TorpedoSystem, TorpedoTube,
    PulseWeaponSystem, PulseWeapon, TractorBeamSystem, TractorBeam,
)
from engine.appc.properties import PulseWeaponProperty


def _reset_app_state():
    App.g_kSetManager._sets.clear()


def _fully_kitted_ship():
    """A ship carrying one of every weapon-system container, each with a
    single leaf emitter child — the shape IntelligentCircleObject and
    FireScript both walk."""
    ship = ShipClass()
    ship._hull = HullSubsystem("H")
    ship._hull.SetMaxCondition(1000.0)

    phasers = PhaserSystem("Phasers")
    bank = PhaserBank("P1")
    phasers.AddChildSubsystem(bank)
    ship.SetPhaserSystem(phasers)

    torps = TorpedoSystem("Torps")
    tube = TorpedoTube("T1")
    torps.AddChildSubsystem(tube)
    ship.SetTorpedoSystem(torps)

    pulses = PulseWeaponSystem("Pulses")
    pulse = PulseWeapon("PW1")
    pulses.AddChildSubsystem(pulse)
    ship.SetPulseWeaponSystem(pulses)

    tractors = TractorBeamSystem("Tractors")
    tractor = TractorBeam("TB1")
    tractors.AddChildSubsystem(tractor)
    ship.SetTractorBeamSystem(tractors)

    return ship, {
        "bank": bank, "tube": tube, "pulse": pulse, "tractor": tractor,
        "phasers": phasers, "torps": torps, "pulses": pulses,
        "tractors": tractors,
    }


def test_intelligent_circle_object_builds_real_weapon_list_not_stubs():
    """Rank-10 stub (250 hits/session): App.Weapon_Cast.

    Before the fix, every child of every weapon-system container
    (including tractor-beam children, which the script explicitly skips
    via IsTypeOf(CT_TRACTOR_BEAM_SYSTEM)) would have produced a truthy
    _NamedStub appended to lWeapons -- garbage in, garbage out for the
    shield/weapon-angle caching that consumes it. After the fix, lWeapons
    holds exactly the real leaf emitters."""
    _reset_app_state()
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ship, parts = _fully_kitted_ship()
    pSet.AddObjectToSet(ship, "Ours")

    pp = PreprocessingAI_Create(ship, "ICO")
    from AI.PlainAI.IntelligentCircleObject import IntelligentCircleObject
    ico = IntelligentCircleObject(pp)

    # Real leaf-weapon identities, not stubs standing in for them.
    assert set(ico.lWeapons) == {parts["bank"], parts["tube"], parts["pulse"]}
    # The tractor beam is explicitly skipped by the script's
    # IsTypeOf(CT_TRACTOR_BEAM_SYSTEM) guard, so it must never appear.
    assert parts["tractor"] not in ico.lWeapons
    for weapon in ico.lWeapons:
        assert not isinstance(weapon, App._NamedStub)

    _reset_app_state()


def test_fire_script_pulse_branch_enumerates_real_directions():
    """Ranks 15/17 stub (151 hits/session): App.PulseWeaponSystem_Cast.

    Drives the real AI/Preprocessors.py FireScript.GetWeaponInfo pulse
    branch on a PulseWeaponSystem with two pulse-weapon children. Before
    this fix the branch always produced an empty lDirections regardless of
    how many pulse weapons the ship had (int()-coercion of the
    GetNumChildSubsystems() stub to 0); after the fix it walks both real
    children.

    GetLaunchSpeed() on a leaf PulseWeapon is a separate, unrelated
    engine gap (never implemented on PulseWeapon/WeaponSystem) --
    stubbed here per-instance purely so this SDK function can run to
    completion; it is explicitly NOT part of this task's fix."""
    _reset_app_state()
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass()
    ship._hull = HullSubsystem("H")
    ship._hull.SetMaxCondition(1000.0)

    pulses = PulseWeaponSystem("Pulses")
    pulse_a = PulseWeapon("PW1")
    pulse_b = PulseWeapon("PW2")
    for pw in (pulse_a, pulse_b):
        pw.SetProperty(PulseWeaponProperty("PWProp"))
        # Orthogonal, out-of-scope gap -- see docstring above.
        pw.GetLaunchSpeed = lambda: 30.0
    pulses.AddChildSubsystem(pulse_a)
    pulses.AddChildSubsystem(pulse_b)
    ship.SetPulseWeaponSystem(pulses)
    pSet.AddObjectToSet(ship, "Ours")

    plain = PlainAI_Create(ship, "FirePP")
    from AI.Preprocessors import FireScript
    fs = FireScript("Target")
    fs.pCodeAI = plain

    lDirections, fSpeed = fs.GetWeaponInfo(pulses)

    assert len(lDirections) == 2, (
        "expected FireScript.GetWeaponInfo to enumerate both pulse-weapon "
        "children; before the fix this was always empty"
    )
    assert fSpeed == 30.0

    _reset_app_state()
