"""PulseWeaponProperty.SetModuleName / GetModuleName — per-cannon projectile
module accessor. Hardpoint scripts call e.g. PortCannon.SetModuleName(
"Tactical.Projectiles.PulseDisruptor"); the pulse-firing path reads it back to
find the projectile script. Six ships use six modules, all via SetModuleName.
"""
from engine.appc.properties import PulseWeaponProperty


def test_get_module_name_default_empty():
    p = PulseWeaponProperty("PortCannon")
    assert p.GetModuleName() == ""


def test_set_get_module_name_roundtrip():
    p = PulseWeaponProperty("PortCannon")
    p.SetModuleName("Tactical.Projectiles.PulseDisruptor")
    assert p.GetModuleName() == "Tactical.Projectiles.PulseDisruptor"


def test_set_module_name_coerces_to_str():
    p = PulseWeaponProperty("PortCannon")
    p.SetModuleName(12345)
    assert isinstance(p.GetModuleName(), str)
    assert p.GetModuleName() == "12345"


def test_cooldown_time_still_works():
    p = PulseWeaponProperty("PortCannon")
    p.SetCooldownTime(0.4)
    assert p.GetCooldownTime() == 0.4
