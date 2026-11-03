"""PhaserSystem.StartFiring + the host_loop held-trigger pump must NOT fire
(nor start the warm-up SFX) at a target the firing ship cannot detect — fully
cloaked being the canonical case.

Bug ("ship's horn"): an AI re-calls StartFiring every tick and the host loop
pumps every armed system every frame. Without a detectability gate at fire-
initiation, each call reached emitter.Fire() → _play_fire_sfx (the warm-up
sound); the per-tick damage chokepoint (host_loop, can_detect) then StopFiring'd
it the same frame; next tick it restarted → a continuous start/stop/restart
loop. The fire-initiation gate (_target_undetectable → can_detect) stops the
shot before any SFX, mirroring the authoritative host-loop chokepoint.

Mirrors the fixture shape of test_phaser_fire_range_gate.py.
"""
from engine.appc.math import TGPoint3
from engine.appc.subsystems import PhaserSystem
from tests.helpers.cloak_geometry import inside_gu, outside_gu

import App

# One set for every double here: the interim cross-set weapon guard
# (system-frames Plan 2 Ruling 5) puts a target outside the shooter's set --
# or a setless one -- out of phaser range.
_SHARED_SET = App.SetClass_Create()


class _FakeCloak:
    def __init__(self, cloaked):
        self._cloaked = cloaked
    def IsCloaked(self):
        return 1 if self._cloaked else 0


class _PlainTarget:
    """Detectable target (no cloak, an empty set → no concealment)."""
    def __init__(self, x, y, z):
        self._loc = TGPoint3(float(x), float(y), float(z))
    def GetWorldLocation(self):
        return self._loc
    def GetContainingSet(self):
        return _SHARED_SET
    def IsDead(self):
        return 0


class _CloakedTarget(_PlainTarget):
    """Fully cloaked target. GetCloakingSubsystem is class-level because
    sensor_detection._cloak_subsystem resolves it via type(target)."""
    def GetCloakingSubsystem(self):
        return _FakeCloak(cloaked=True)


class _Ship:
    """Firing ship. No sensor subsystem → can_detect uses the
    `sensorless_range_gu` dial, so a plain in-range target is detectable."""
    def __init__(self, x, y, z):
        self._loc = TGPoint3(float(x), float(y), float(z))
    def GetWorldLocation(self):
        return self._loc
    def GetContainingSet(self):
        return _SHARED_SET
    def GetWorldRotation(self):
        class _R:
            def GetCol(self, i):
                if i == 0: return TGPoint3(1.0, 0.0, 0.0)
                if i == 1: return TGPoint3(0.0, 1.0, 0.0)
                return TGPoint3(0.0, 0.0, 1.0)
        return _R()


class _SensorShip(_Ship):
    """Firing ship carrying a REAL SensorSubsystem at a Galaxy's 2000 GU base
    range, so its cloak bubble is set by an authored range rather than the
    `sensorless_range_gu` dial. Distances come from tests.helpers.cloak_geometry. Mirrors
    tests/unit/test_sensor_detection.py::_ship_with_sensor."""

    def __init__(self, x, y, z):
        super().__init__(x, y, z)
        from engine.appc.subsystems import SensorSubsystem
        self._sensors = SensorSubsystem("Sensors")
        self._sensors._max_condition = 100.0
        self._sensors._condition = 100.0
        self._sensors.SetBaseSensorRange(2000.0)

    def GetSensorSubsystem(self):
        return self._sensors


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
    # BC tick surface (update_weapons group walk).
    def IsMemberOfGroup(self, g):
        return 1
    def IsDumbFire(self):
        return 0


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

def test_start_firing_no_op_and_no_sfx_when_target_cloaked(monkeypatch):
    """STOCK-BC BEHAVIOUR, held under ENHANCED_SENSOR_CONTEST = False.

    Cloak bubble is now a flat floor plus a percentage of effective range
    rather than an absolute (see tests/unit/test_cloak_detection_contest.py).
    This ship models no BaseSensorRange, so its effective range is the
    `sensorless_range_gu` dial. Holding the flag off keeps this test about
    absolute cloak whether or not the 50 GU target sits inside that observer's
    bubble. The assertions are unchanged; the flag makes
    explicit the configuration they have always described. The companion test
    pins the default configuration.
    """
    import engine.appc.sensor_detection as sd
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    ship = _Ship(0, 0, 0)
    target = _CloakedTarget(50, 0, 0)  # in range, but cloaked
    bank = _FakeBank()
    sys = _build_system([bank], ship)

    sys.StartFiring(target=target)

    assert bank.fire_calls == []            # emitter.Fire never reached → no SFX
    assert bank.IsFiring() == 0
    # Held state must NOT latch — otherwise the host pump would keep trying.
    assert sys._fire_held is False


def test_start_firing_engages_close_cloaked_target_but_not_beyond_the_bubble():
    """INTENTIONAL DIVERGENCE (ENHANCED_SENSOR_CONTEST default-on): a cloaked
    ship inside the bubble is a legal target and IS fired on.

    Uses _SensorShip (2000 GU authored sensors) rather than the sensor-less
    `sensorless_range_gu` dial, and derives both distances from that bubble so
    both cases sit INSIDE the bank's 60 GU
    GetMaxDamageDistance and the only thing separating them is detectability --
    otherwise PhaserSystem._can_engage would be doing the work and the second
    assertion would pass for the wrong reason.
    """
    ship = _SensorShip(0, 0, 0)
    bank = _FakeBank()
    sys = _build_system([bank], ship)

    # Inside the cloak bubble and inside weapon range → engaged (the held
    # trigger latches; the shot itself is the native walk's, fire control
    # native only, M3: these fake banks have no mirror row to fire).
    sys.StartFiring(target=_CloakedTarget(inside_gu(), 0, 0))
    assert sys._fire_held is True

    # Still inside the 60 GU weapon range, but outside the cloak bubble →
    # undetectable, so no shot, no SFX, no held latch (the ship's-horn guard).
    sys.StopFiring()
    bank.fire_calls.clear()
    sys.StartFiring(target=_CloakedTarget(outside_gu(), 0, 0))
    assert bank.fire_calls == []
    assert sys._fire_held is False


def test_start_firing_dispatches_when_target_detectable():
    """Control: a detectable in-range target still fires (guards over-gating)."""
    ship = _Ship(0, 0, 0)
    target = _PlainTarget(50, 0, 0)
    bank = _FakeBank()
    sys = _build_system([bank], ship)

    sys.StartFiring(target=target)

    assert sys._fire_held is True       # engaged (the shot: the native walk)


# ── held-trigger pump gate (host_loop._pump_held_weapons) ─────────────────

