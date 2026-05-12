"""PhaserSystem identity fields: weapon-system type, single-fire, aimed."""
from engine.appc.subsystems import PhaserSystem


def test_defaults():
    p = PhaserSystem("Phaser System")
    assert p.GetWeaponSystemType() == 0
    assert p.GetSingleFire() == 0
    assert p.GetAimedWeapon() == 0


def test_setters_persist():
    p = PhaserSystem("Phaser System")
    p.SetWeaponSystemType(1)
    p.SetSingleFire(1)
    p.SetAimedWeapon(0)
    assert p.GetWeaponSystemType() == 1
    assert p.GetSingleFire() == 1
    assert p.GetAimedWeapon() == 0
