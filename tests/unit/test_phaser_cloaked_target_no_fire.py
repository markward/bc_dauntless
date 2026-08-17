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


class _SensorShip(_Ship):
    """Firing ship carrying a REAL SensorSubsystem at a Galaxy's 2000 GU base
    range, so its cloak bubble (flat CLOAK_DETECTION_BASE_GU plus 1%
    CLOAK_RANGE_FACTOR) is 30 GU rather than the 310 GU the sensor-less
    fallback would give. Mirrors
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

    Cloak bubble is now flat-10-plus-a-percentage of effective range rather
    than an absolute (see tests/unit/test_cloak_detection_contest.py). This
    ship models no BaseSensorRange, so its effective range is
    FALLBACK_RANGE_GU (30000) and its cloak bubble is 310 GU -- the 50 GU
    target below is inside it. The assertions are unchanged; the flag makes
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
    ship inside the flat-10-plus-1% bubble is a legal target and IS fired on.

    Uses _SensorShip (2000 GU sensors -> a 30 GU cloak bubble) rather than the
    30000 GU fallback, so both cases sit INSIDE the bank's 60 GU
    GetMaxDamageDistance and the only thing separating them is detectability --
    otherwise PhaserSystem._can_engage would be doing the work and the second
    assertion would pass for the wrong reason.
    """
    ship = _SensorShip(0, 0, 0)
    bank = _FakeBank()
    sys = _build_system([bank], ship)

    # 15 GU, inside the 30 GU cloak bubble and inside weapon range → fires.
    sys.StartFiring(target=_CloakedTarget(15, 0, 0))
    assert len(bank.fire_calls) == 1
    assert sys._fire_held is True

    # 45 GU: still inside the 60 GU weapon range, but well outside the cloak
    # bubble → undetectable, so no shot, no SFX, no held latch (the
    # ship's-horn guard).
    sys.StopFiring()
    bank.fire_calls.clear()
    sys.StartFiring(target=_CloakedTarget(45, 0, 0))
    assert bank.fire_calls == []
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


# ── held-trigger pump gate (host_loop._pump_held_weapons) ─────────────────

def test_pump_stops_when_target_cloaks_mid_burst(monkeypatch):
    """STOCK-BC BEHAVIOUR, held under ENHANCED_SENSOR_CONTEST = False.

    Same reason as the StartFiring case above: this ship's fallback 30000 GU
    effective range gives a 310 GU cloak bubble, so the 50 GU target below is
    detectable while cloaked with the flag at its default. Assertions
    unchanged; the companion below pins the default configuration.
    """
    import engine.appc.sensor_detection as sd
    monkeypatch.setattr(sd, "ENHANCED_SENSOR_CONTEST", False)
    from engine.host_loop import _pump_held_weapons
    ship = _Ship(0, 0, 0)
    bank = _FakeBank(can_fire=True)
    sys = _build_system([bank], ship)
    ship.GetPhaserSystem = lambda: sys   # pump walks ship getters

    # Start on a detectable target (latches held state).
    sys.StartFiring(target=_PlainTarget(50, 0, 0))
    assert sys._fire_held is True

    # Target cloaks mid-burst.
    sys._held_target = _CloakedTarget(50, 0, 0)
    bank.fire_calls.clear()
    _pump_held_weapons([ship], 0.34)

    assert bank.fire_calls == []            # no re-fire → no restarted SFX
    assert sys._fire_held is False          # held state cleared
    assert sys._held_target is None


def test_pump_continues_on_close_cloak_and_stops_outside_the_bubble():
    """INTENTIONAL DIVERGENCE (ENHANCED_SENSOR_CONTEST default-on): a target
    that cloaks while inside the bubble stays engaged; the burst only stops once
    it is outside. _SensorShip (30 GU bubble, 60 GU weapon range) keeps both
    cases inside weapon range so detectability is the only variable.
    """
    from engine.host_loop import _pump_held_weapons
    ship = _SensorShip(0, 0, 0)
    bank = _FakeBank(can_fire=True)
    sys = _build_system([bank], ship)
    ship.GetPhaserSystem = lambda: sys

    sys.StartFiring(target=_PlainTarget(15, 0, 0))
    assert sys._fire_held is True

    # Cloaks at 15 GU — inside the 30 GU bubble, so the burst continues.
    sys._held_target = _CloakedTarget(15, 0, 0)
    bank.fire_calls.clear()
    bank._firing = False                   # bank cycled
    _pump_held_weapons([ship], 0.34)
    assert len(bank.fire_calls) == 1
    assert sys._fire_held is True

    # Slips out to 45 GU — well outside the bubble, so the burst stops.
    sys._held_target = _CloakedTarget(45, 0, 0)
    bank.fire_calls.clear()
    bank._firing = False
    _pump_held_weapons([ship], 0.34)
    assert bank.fire_calls == []
    assert sys._fire_held is False
    assert sys._held_target is None


def test_held_tick_continues_when_target_detectable():
    """Control: a detectable held target keeps re-firing as banks recycle."""
    ship = _Ship(0, 0, 0)
    target = _PlainTarget(50, 0, 0)
    bank = _FakeBank(can_fire=True)
    sys = _build_system([bank], ship)

    sys.StartFiring(target=target)
    bank.fire_calls.clear()
    bank._firing = False  # bank cycled

    sys.update_weapons(0.34)   # 0.34 > the 0.33 inter-shot threshold

    assert len(bank.fire_calls) == 1
    assert sys._fire_held is True
