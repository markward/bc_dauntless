"""Weapon-system isinstance-based casts used by FireScript.

SDK pattern: `pPhaser = App.PhaserSystem_Cast(pWeaponSystem)` returns
the object if it's an instance of that class, else None — matches
`App.ObjectClass_Cast`."""
import App
from engine.appc.subsystems import (
    PhaserSystem, TorpedoSystem, TractorBeamSystem, ShipSubsystem,
    TorpedoTube, HullSubsystem,
)


def test_phaser_system_cast_returns_phaser():
    p = PhaserSystem("P")
    assert App.PhaserSystem_Cast(p) is p


def test_phaser_system_cast_returns_none_for_torpedo():
    t = TorpedoSystem("T")
    assert App.PhaserSystem_Cast(t) is None


def test_torpedo_system_cast_returns_torp():
    t = TorpedoSystem("T")
    assert App.TorpedoSystem_Cast(t) is t


def test_tractor_beam_system_cast_returns_tractor():
    tb = TractorBeamSystem("TB")
    assert App.TractorBeamSystem_Cast(tb) is tb


def test_ship_subsystem_cast_returns_subsystem():
    h = HullSubsystem("H")
    assert App.ShipSubsystem_Cast(h) is h


def test_ship_subsystem_cast_returns_none_for_non_subsystem():
    assert App.ShipSubsystem_Cast("not a subsystem") is None
    assert App.ShipSubsystem_Cast(None) is None


def test_torpedo_tube_cast_returns_tube():
    tt = TorpedoTube("Tube")
    assert App.TorpedoTube_Cast(tt) is tt


def test_torpedo_tube_cast_returns_none_for_phaser():
    p = PhaserSystem("P")
    assert App.TorpedoTube_Cast(p) is None
