"""App.Weapon_Cast / App.PulseWeaponSystem_Cast are real downcasts.

Both were undefined, so App.__getattr__ returned a truthy _NamedStub:
- AI/PlainAI/IntelligentCircleObject.py:62-64 built its weapon list out of stubs
  (heatmap rank 10, 250 hits/session).
- AI/Preprocessors.py:771-778 took the pulse branch on every weapon system, then
  int()-coerced the stub to 0 in range(GetNumChildSubsystems()) — so the AI never
  enumerated pulse-weapon firing directions at all (heatmap ranks 15/17, 151 hits).
"""
import App
from engine.appc.weapon_subsystems import (
    PulseWeaponSystem, PhaserSystem, TorpedoSystem, TractorBeamSystem,
    PhaserBank, PulseWeapon, TractorBeam, TorpedoTube,
)


def test_pulse_weapon_system_cast_accepts_a_pulse_system():
    sys_ = PulseWeaponSystem()
    assert App.PulseWeaponSystem_Cast(sys_) is sys_


def test_pulse_weapon_system_cast_rejects_a_phaser_system():
    assert App.PulseWeaponSystem_Cast(PhaserSystem()) is None


def test_pulse_weapon_system_cast_rejects_none_and_arbitrary_objects():
    assert App.PulseWeaponSystem_Cast(None) is None
    assert App.PulseWeaponSystem_Cast(object()) is None


def test_weapon_cast_rejects_a_weapon_system():
    """A *System* is a container of weapons, not a weapon."""
    assert App.Weapon_Cast(PhaserSystem()) is None


def test_weapon_cast_rejects_none_and_arbitrary_objects():
    assert App.Weapon_Cast(None) is None
    assert App.Weapon_Cast(object()) is None


def test_weapon_cast_accepts_a_torpedo_tube():
    """TorpedoTube is the one leaf emitter that already inherits Weapon
    directly in our engine (weapon_subsystems.py)."""
    tube = TorpedoTube()
    assert App.Weapon_Cast(tube) is tube


def test_weapon_cast_accepts_a_phaser_bank():
    """PhaserBank inherits WeaponSystem (not Weapon) in our engine's class
    hierarchy, but it IS the real-SDK leaf emitter under a PhaserSystem
    container — Weapon_Cast must still accept it."""
    bank = PhaserBank()
    assert App.Weapon_Cast(bank) is bank


def test_weapon_cast_accepts_a_pulse_weapon():
    weapon = PulseWeapon()
    assert App.Weapon_Cast(weapon) is weapon


def test_weapon_cast_accepts_a_tractor_beam():
    beam = TractorBeam()
    assert App.Weapon_Cast(beam) is beam


def test_weapon_cast_rejects_other_weapon_system_containers():
    assert App.Weapon_Cast(TorpedoSystem()) is None
    assert App.Weapon_Cast(TractorBeamSystem()) is None
    assert App.Weapon_Cast(PulseWeaponSystem()) is None


def test_weapon_cast_does_not_crash_when_ct_weapon_is_unmapped(monkeypatch):
    """Minor fix: subsystem_class_for_ct(CT_WEAPON) can return None for an
    unmapped/undefined CT_* constant (e.g. a _NamedStub fall-through) --
    isinstance(obj, None) raises TypeError, not a clean rejection. Weapon_Cast
    must stay total: reject cleanly (return None) instead of crashing."""
    import engine.appc.subsystem_types as subsystem_types
    monkeypatch.setattr(subsystem_types, "subsystem_class_for_ct", lambda ct: None)
    tube = TorpedoTube()
    assert App.Weapon_Cast(tube) is None
