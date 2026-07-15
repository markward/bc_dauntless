"""Regression: StartFiring(target=None) on a held-fire energy weapon system
(phaser/pulse) must be a no-op — must NOT latch _fire_held.

SDK FireWeapons calls StartFiring(pShip.GetTarget()), and GetTarget() can
legitimately return None (no target selected). Before this fix, a None
target latched _fire_held, and host_loop's damage loop stopped each bank
per-frame (target is None) while the pump's re-fire kept re-latching it —
producing a ~3 Hz fire/stop flicker with SFX spam and (for pulse weapons)
real forward bolts fired with no target.

Torpedo dumbfire is NOT covered by this gate — TorpedoTube legitimately
arms with target=None (dumb-fire path), so the bail must live on
_HeldFireWeaponSystem (phaser/pulse/tractor base), not on WeaponSystem.
"""
from engine.appc.subsystems import PhaserSystem, PulseWeaponSystem


class _FakeBank:
    def __init__(self):
        self.fire_calls = []
        self._firing = False
    def CanFire(self):
        return 1
    def Fire(self, target, offset):
        self.fire_calls.append((target, offset))
        self._firing = True
    def IsFiring(self):
        return self._firing
    def StopFiring(self):
        self._firing = False
    def IsMemberOfGroup(self, g):
        return 1
    def IsDumbFire(self):
        return 0


def _build_system(cls, banks):
    sys = cls("test_weapons")
    sys.IsOn = lambda: True
    sys.GetParentShip = lambda: None
    sys._weapons = list(banks)
    sys.GetNumWeapons = lambda: len(banks)
    sys.GetWeapon = lambda i: banks[i] if 0 <= i < len(banks) else None
    return sys


def test_phaser_start_firing_none_target_is_noop():
    bank = _FakeBank()
    sys = _build_system(PhaserSystem, [bank])

    sys.StartFiring(target=None)

    assert sys._fire_held is False
    assert sys.GetNumTargets() == 0
    assert bank.fire_calls == []


def test_pulse_start_firing_none_target_is_noop():
    bank = _FakeBank()
    sys = _build_system(PulseWeaponSystem, [bank])

    sys.StartFiring(target=None)

    assert sys._fire_held is False
    assert sys.GetNumTargets() == 0
    assert bank.fire_calls == []


def test_phaser_none_target_pump_does_not_flicker():
    """Pump several frames after a None-target StartFiring: zero Fire calls,
    _fire_held never latches (no fire/stop flicker)."""
    from engine.host_loop import _pump_held_weapons

    bank = _FakeBank()
    sys = _build_system(PhaserSystem, [bank])

    class _Ship:
        def GetPhaserSystem(self):
            return sys

    ship = _Ship()
    sys.StartFiring(target=None)

    for _ in range(10):
        _pump_held_weapons([ship], 0.05)

    assert bank.fire_calls == []
    assert sys._fire_held is False
