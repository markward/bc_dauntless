"""`GetParentShip()` must reach the ship from ANY subsystem, not just top-level.

THE CRASH THIS FIXES (live, during a nine-Bird-of-Prey battle):

    ConditionPulseReady.py:172  ChargeToggled
      self.SetStateFromWeapons(App.ShipClass_Cast(pEvent.GetSource()))
    ConditionPulseReady.py:179  SetStateFromWeapons
      pSystem = pShip.GetPulseWeaponSystem()
    AttributeError: 'NoneType' object has no attribute 'GetPulseWeaponSystem'

`ConditionPulseReady` builds its charge-toggled event with
`pEvent.SetSource(pWeapon.GetParentShip())` (SDK line 161). `pWeapon` is a
pulse-weapon EMITTER — a CHILD of the PulseWeaponSystem — and
`ShipClass._attach_subsystem` sets `_parent_ship` only on TOP-LEVEL
subsystems. So the emitter's was None, the event carried a None source,
`ShipClass_Cast(None)` returned None, and the SDK dereferenced it. Fatal:
the AttributeError propagates straight out of the host frame loop.

Our own code already knew and routed around it — `weapon_subsystems.py`'s
`CalculateRoughDirection` docstring says "_climb_to_ship() — NOT
GetParentShip() … GetParentShip() would silently return None on every real
tube". But the SDK cannot route around our surface. BC's `GetParentShip`
returns the owning ship for any subsystem in the chain, so ours must too.

Recorded in the stbc-oracle ledger before this session as a known gap:
"BoP AI DIES at first charge toggle: ConditionPulseReady.ChargeToggled ->
ShipClass_Cast(pEvent.GetSource()) is None — our charge-toggled event has the
wrong source."
"""
import pytest

from engine.appc.ships import ShipClass
from engine.appc.weapon_subsystems import PhaserSystem, PhaserBank


def _ship_with_child_bank():
    """A real parent chain: ship -> PhaserSystem -> PhaserBank.

    Mirrors how the loader wires weapons — `_attach_subsystem` sets
    `_parent_ship` on the SYSTEM, and the emitter is added beneath it with
    `AddChildSubsystem`, which sets only `_parent_subsystem`.
    """
    ship = ShipClass()
    system = PhaserSystem("Phasers")
    ship._attach_subsystem(system)
    bank = PhaserBank("DorsalPhaser1")
    system.AddChildSubsystem(bank)
    return ship, system, bank


def test_a_top_level_subsystem_reaches_the_ship():
    """Unchanged behaviour — this half always worked."""
    ship, system, _bank = _ship_with_child_bank()
    assert system.GetParentShip() is ship


def test_a_CHILD_emitter_also_reaches_the_ship():
    """THE FIX. A pulse/phaser emitter is a child of its weapon system, so its
    own `_parent_ship` is never set. BC's GetParentShip still returns the ship,
    and the SDK depends on that — `ConditionPulseReady` stamps it onto an event
    source and immediately dereferences it."""
    ship, _system, bank = _ship_with_child_bank()
    assert bank.GetParentShip() is ship, (
        "a child emitter must reach its ship; returning None here is what "
        "crashed the host loop mid-combat")


def test_it_agrees_with_climb_to_ship():
    """The two must not disagree. Our own code calls `_climb_to_ship()` where
    the SDK calls `GetParentShip()`; if they answered differently, a weapon
    would aim from one ship and report from another."""
    ship, _system, bank = _ship_with_child_bank()
    assert bank.GetParentShip() is bank._climb_to_ship() is ship


def test_an_unattached_subsystem_still_returns_None():
    """No ship in the chain is a real answer, not an error. A freshly created
    subsystem has no owner until the loader attaches it, and callers guard on
    None."""
    assert PhaserBank("Orphan").GetParentShip() is None


def test_a_detached_chain_returns_None_rather_than_looping():
    """A system that was never attached to a ship still terminates. Guards the
    climb against a chain that ends in nothing."""
    system = PhaserSystem("Phasers")
    bank = PhaserBank("Bank")
    system.AddChildSubsystem(bank)
    assert bank.GetParentShip() is None


def test_the_climb_terminates_on_a_cycle():
    """`GetParentShip` now climbs, and a climb that reads each ancestor's
    `_parent_ship` FIELD cannot recurse back through `GetParentShip`. This
    pins that: a chain that points at itself must return None, not hang or
    blow the stack.

    A malformed chain is not expected in production — this exists because the
    obvious implementation (delegating to `_climb_to_ship`, whose loop calls
    `node.GetParentShip()`) WOULD have recursed.
    """
    a = PhaserBank("A")
    b = PhaserBank("B")
    a._parent_subsystem = b
    b._parent_subsystem = a
    assert a.GetParentShip() is None
