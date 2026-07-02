"""PhaserSystem.StartFiring + retry_held_fire must NOT fire (nor start the
warm-up SFX) at a target the firing ship cannot detect — fully cloaked being
the canonical case.

Bug ("ship's horn"): an AI re-calls StartFiring every tick and the host loop
re-calls retry_held_fire every frame. Without a detectability gate at fire-
initiation, each call reached emitter.Fire() → _play_fire_sfx (the warm-up
sound); the per-tick damage chokepoint (host_loop, can_detect) then StopFiring'd
it the same frame; next tick it restarted → a continuous start/stop/restart
loop. The fire-initiation gate (_target_undetectable → can_detect) stops the
shot before any SFX, mirroring the authoritative host-loop chokepoint.

Mirrors the fixture shape of test_phaser_fire_range_gate.py.
"""
from engine.appc.math import TGPoint3
from engine.appc.subsystems import PhaserSystem


class _FakeCloak:
    def __init__(self, cloaked):
        self._cloaked = cloaked
    def IsCloaked(self):
        return 1 if self._cloaked else 0


class _PlainTarget:
    """Detectable target (no cloak, no set → no concealment)."""
    def __init__(self, x, y, z):
        self._loc = TGPoint3(float(x), float(y), float(z))
    def GetWorldLocation(self):
        return self._loc
    def IsDead(self):
        return 0


class _CloakedTarget(_PlainTarget):
    """Fully cloaked target. GetCloakingSubsystem is class-level because
    sensor_detection._cloak_subsystem resolves it via type(target)."""
    def GetCloakingSubsystem(self):
        return _FakeCloak(cloaked=True)


class _Ship:
    """Firing ship. No sensor subsystem → can_detect uses the fallback
    range, so a plain in-range target is detectable."""
    def __init__(self, x, y, z):
        self._loc = TGPoint3(float(x), float(y), float(z))
    def GetWorldLocation(self):
        return self._loc
    def GetWorldRotation(self):
        class _R:
            def GetCol(self, i):
                if i == 0: return TGPoint3(1.0, 0.0, 0.0)
                if i == 1: return TGPoint3(0.0, 1.0, 0.0)
                return TGPoint3(0.0, 0.0, 1.0)
        return _R()


class _FakeBank:
    """Bank capturing Fire()/StopFiring; wide arc so aim never gates."""
    def __init__(self, can_fire=True):
        self._can_fire = can_fire
        self._firing = False
        self.fire_calls = []
    def GetMaxDamageDistance(self):
        return 60.0
    def CanFire(self):
        return self._can_fire
    def Fire(self, target, offset):
        self.fire_calls.append((target, offset))
        self._firing = True
    def IsFiring(self):
        return self._firing
    def StopFiring(self):
        self._firing = False
    def GetPosition(self):
        return TGPoint3(0.0, 0.0, 0.0)
    def GetEmitterDirection(self):
        return TGPoint3(0.0, 1.0, 0.0)
    def GetFiringArc(self):
        return 360.0


def _build_system(banks, ship):
    sys = PhaserSystem("test_phasers")
    sys._parent_ship = ship
    sys.IsOn = lambda: True
    sys.GetParentShip = lambda: ship
    sys._weapons = list(banks)
    sys.GetNumWeapons = lambda: len(banks)
    sys.GetWeapon = lambda i: banks[i] if 0 <= i < len(banks) else None
    return sys


# ── StartFiring gate ──────────────────────────────────────────────────────

def test_start_firing_no_op_and_no_sfx_when_target_cloaked():
    ship = _Ship(0, 0, 0)
    target = _CloakedTarget(50, 0, 0)  # in range, but cloaked
    bank = _FakeBank()
    sys = _build_system([bank], ship)

    sys.StartFiring(target=target)

    assert bank.fire_calls == []            # emitter.Fire never reached → no SFX
    assert bank.IsFiring() == 0
    # Held state must NOT latch — otherwise retry_held_fire would keep trying.
    assert sys._fire_held is False


def test_start_firing_dispatches_when_target_detectable():
    """Control: a detectable in-range target still fires (guards over-gating)."""
    ship = _Ship(0, 0, 0)
    target = _PlainTarget(50, 0, 0)
    bank = _FakeBank()
    sys = _build_system([bank], ship)

    sys.StartFiring(target=target)

    assert len(bank.fire_calls) == 1
    assert sys._fire_held is True


# ── retry_held_fire gate ──────────────────────────────────────────────────

def test_retry_held_fire_stops_when_target_cloaks_mid_burst():
    ship = _Ship(0, 0, 0)
    bank = _FakeBank(can_fire=True)
    sys = _build_system([bank], ship)

    # Start on a detectable target (latches held state).
    sys.StartFiring(target=_PlainTarget(50, 0, 0))
    assert sys._fire_held is True

    # Target cloaks mid-burst.
    sys._held_target = _CloakedTarget(50, 0, 0)
    bank.fire_calls.clear()
    sys.retry_held_fire()

    assert bank.fire_calls == []            # no re-fire → no restarted SFX
    assert sys._fire_held is False          # held state cleared
    assert sys._held_target is None


def test_retry_held_fire_continues_when_target_detectable():
    """Control: a detectable held target keeps re-firing as banks recycle."""
    ship = _Ship(0, 0, 0)
    target = _PlainTarget(50, 0, 0)
    bank = _FakeBank(can_fire=True)
    sys = _build_system([bank], ship)

    sys.StartFiring(target=target)
    bank.fire_calls.clear()
    bank._firing = False  # bank cycled

    sys.retry_held_fire()

    assert len(bank.fire_calls) == 1
    assert sys._fire_held is True
