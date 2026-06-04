"""PhaserSystem.StartFiring + retry_held_fire honour the global phaser
fire-range gate (PHASER_MAX_RANGE_GU = 700 GU ≈ 122.5 km).

In stock BC the gate is a single engine-wide constant, not per-bank —
MaxDamageDistance controls damage falloff shape, not firing range.
"""
import pytest

from engine.appc.math import TGPoint3
from engine.appc.subsystems import PhaserSystem, PHASER_MAX_RANGE_GU


class _Target:
    def __init__(self, x, y, z):
        self._loc = TGPoint3(float(x), float(y), float(z))
    def GetWorldLocation(self):
        return self._loc
    def IsDead(self):
        return 0


class _Ship:
    def __init__(self, x, y, z):
        self._loc = TGPoint3(float(x), float(y), float(z))
    def GetWorldLocation(self):
        return self._loc
    def GetWorldRotation(self):
        # Identity rotation — no rotation needed for these tests.
        class _R:
            def GetCol(self, i):
                if i == 0: return TGPoint3(1.0, 0.0, 0.0)
                if i == 1: return TGPoint3(0.0, 1.0, 0.0)
                return TGPoint3(0.0, 0.0, 1.0)
        return _R()


class _FakeBank:
    """Stub bank reporting max damage distance + Fire/CanFire capture."""
    def __init__(self, max_damage_distance, can_fire=True):
        self._mdd = float(max_damage_distance)
        self._can_fire = can_fire
        self._firing = False
        self.fire_calls = []
    def GetMaxDamageDistance(self):
        return self._mdd
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
        return 360.0  # wide arc so direction never gates


# ── helpers ────────────────────────────────────────────────────────────────

def _build_system(banks, ship):
    """Build a PhaserSystem populated with the given banks, parented to ship."""
    sys = PhaserSystem("test_phasers")
    sys._parent_ship = ship
    # Force IsOn() True regardless of subsystem-condition details.
    sys.IsOn = lambda: True
    sys.GetParentShip = lambda: ship
    sys._weapons = list(banks)
    sys.GetNumWeapons = lambda: len(banks)
    sys.GetWeapon = lambda i: banks[i] if 0 <= i < len(banks) else None
    return sys


# ── target_in_system_range ────────────────────────────────────────────────

def test_global_constant_matches_observed_bc_range():
    """Sanity: PHASER_MAX_RANGE_GU = 700 GU = 122.5 km (HUD-observed in
    stock BC, Galaxy class)."""
    assert PHASER_MAX_RANGE_GU == 700.0


def test_target_well_within_global_range_returns_true():
    ship = _Ship(0, 0, 0)
    target = _Target(500, 0, 0)
    banks = [_FakeBank(max_damage_distance=60.0)]  # Galaxy-like
    sys = _build_system(banks, ship)
    assert sys._target_in_system_range(ship, target) is True


def test_target_at_global_range_boundary_returns_true():
    ship = _Ship(0, 0, 0)
    target = _Target(PHASER_MAX_RANGE_GU, 0, 0)
    banks = [_FakeBank(max_damage_distance=60.0)]
    sys = _build_system(banks, ship)
    assert sys._target_in_system_range(ship, target) is True


def test_target_beyond_global_range_returns_false():
    ship = _Ship(0, 0, 0)
    target = _Target(PHASER_MAX_RANGE_GU + 1.0, 0, 0)
    banks = [_FakeBank(max_damage_distance=60.0)]
    sys = _build_system(banks, ship)
    assert sys._target_in_system_range(ship, target) is False


def test_gate_ignores_per_bank_max_damage_distance():
    """A target far beyond any bank's MaxDamageDistance but within the
    global range should still pass the gate — MaxDamageDistance only
    shapes damage, not range."""
    ship = _Ship(0, 0, 0)
    target = _Target(500, 0, 0)  # well beyond bank's 60 GU MDD
    banks = [_FakeBank(max_damage_distance=60.0)]
    sys = _build_system(banks, ship)
    assert sys._target_in_system_range(ship, target) is True


def test_legacy_no_world_location_falls_through():
    """Ship without GetWorldLocation — non-positional tests still pass."""
    class _BareShip: pass
    class _BareTarget: pass
    banks = [_FakeBank(max_damage_distance=100.0)]
    sys = _build_system(banks, _BareShip())
    assert sys._target_in_system_range(_BareShip(), _BareTarget()) is True


# ── StartFiring gate ──────────────────────────────────────────────────────

def test_start_firing_no_op_when_target_out_of_range():
    ship = _Ship(0, 0, 0)
    target = _Target(PHASER_MAX_RANGE_GU + 100.0, 0, 0)
    bank = _FakeBank(max_damage_distance=60.0)
    sys = _build_system([bank], ship)

    sys.StartFiring(target=target)

    assert bank.fire_calls == []
    # _fire_held must NOT latch — otherwise a single out-of-range trigger
    # would leave the held-fire flag set indefinitely.
    assert sys._fire_held is False


def test_start_firing_dispatches_when_target_in_range():
    ship = _Ship(0, 0, 0)
    target = _Target(500, 0, 0)
    bank = _FakeBank(max_damage_distance=60.0)
    sys = _build_system([bank], ship)

    sys.StartFiring(target=target)

    assert len(bank.fire_calls) == 1
    assert sys._fire_held is True


# ── retry_held_fire gate ──────────────────────────────────────────────────

def test_retry_held_fire_stops_when_target_drifts_out_of_range():
    ship = _Ship(0, 0, 0)
    bank = _FakeBank(max_damage_distance=60.0, can_fire=False)
    sys = _build_system([bank], ship)

    # Simulate trigger held with target initially in range.
    in_range = _Target(50, 0, 0)
    sys.StartFiring(target=in_range)
    assert sys._fire_held is True

    # Now move the target out of range.
    sys._held_target = _Target(PHASER_MAX_RANGE_GU + 100.0, 0, 0)

    bank.fire_calls.clear()
    sys.retry_held_fire()

    assert bank.fire_calls == []
    # StopFiring should fire — clears _fire_held + _held_target.
    assert sys._fire_held is False
    assert sys._held_target is None


def test_retry_held_fire_continues_when_target_in_range():
    ship = _Ship(0, 0, 0)
    target = _Target(50, 0, 0)
    bank = _FakeBank(max_damage_distance=60.0, can_fire=True)
    sys = _build_system([bank], ship)

    sys.StartFiring(target=target)
    bank.fire_calls.clear()
    bank._firing = False   # Simulate bank cycled

    sys.retry_held_fire()

    assert len(bank.fire_calls) == 1
    assert sys._fire_held is True
