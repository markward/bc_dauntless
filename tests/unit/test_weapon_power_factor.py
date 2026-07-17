"""Weapon charge and torpedo reload scale by parent system power factor.

Task 8: phaser/pulse idle recharge is multiplied by the parent weapon-system's
GetNormalPowerPercentage() (written directly as _power_factor in tests — branch
convention).  Torpedo UpdateReload uses factor-scaled threshold: the effective
delay is reload_delay / factor.  At factor 0 there is no recharge and no reload.

Fixtures copied verbatim from tests/unit/test_weapon_system_powered.py and
tests/unit/test_torpedo_tube_power_gate.py per Task 8 brief.

Torpedo reload runs on the GAME clock (App.g_kTimerManager._time), not
time.monotonic() — see tests/unit/test_torpedo_tube_reload.py.
"""
import pytest
from unittest.mock import patch

import App
from engine.appc.subsystems import (
    PhaserSystem, TorpedoSystem, TorpedoTube,
)
from engine.appc.weapon_subsystems import PhaserBank
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import WeaponSystemProperty


@pytest.fixture
def clock():
    """Drive the game clock directly, matching test_torpedo_tube_reload.py."""
    App.g_kTimerManager._time = 0.0

    def _set(t: float) -> None:
        App.g_kTimerManager._time = float(t)

    yield _set
    App.g_kTimerManager._time = 0.0


# ── Shared fixture helpers ──────────────────────────────────────────────────

def _phaser_fixture():
    """Build a PhaserSystem with one PhaserBank child.

    Cloned from test_weapon_system_powered.py conventions: bank starts at
    charge 0, MaxCharge 100, RechargeRate 10.0/s.  The system is ON.
    """
    system = PhaserSystem("PhaserSystem")
    system.TurnOn()
    system._power_factor = 1.0

    bank = PhaserBank("Bank1")
    bank._max_charge = 100.0
    bank._min_firing_charge = 20.0
    bank._recharge_rate = 10.0
    bank._normal_discharge_rate = 50.0
    bank._charge_level = 0.0
    system.AddChildSubsystem(bank)
    return system, bank


def _fresh_gain(system):
    """Return the charge gained by a fresh bank at factor 1.0 over 1 s.

    Mutates `system._power_factor` to 1.0, builds a bank, calls UpdateCharge(1.0),
    and returns the delta.
    """
    system._power_factor = 1.0
    bank = PhaserBank("Ref")
    bank._max_charge = 100.0
    bank._min_firing_charge = 20.0
    bank._recharge_rate = 10.0
    bank._normal_discharge_rate = 50.0
    bank._charge_level = 0.0
    system.AddChildSubsystem(bank)
    before = bank.GetChargeLevel()
    bank.UpdateCharge(1.0)
    return bank.GetChargeLevel() - before


def _torpedo_fixture():
    """Build a TorpedoSystem with one TorpedoTube child.

    Cloned from test_torpedo_tube_power_gate.py conventions.
    Tube starts loaded (_num_ready=1), reload_delay=40.0 s, max_ready=1.
    """
    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    system._power_factor = 1.0

    tube = TorpedoTube("Tube1")
    tube._max_ready = 1
    tube._num_ready = 1
    tube._reload_delay = 40.0
    tube._resize_slots()
    system.AddChildSubsystem(tube)
    return system, tube


# ── Phaser recharge tests ────────────────────────────────────────────────────

def test_phaser_recharge_scales_with_system_power_factor():
    """At factor 0.5 a phaser bank gains exactly half the charge it would at 1.0."""
    system, weapon = _phaser_fixture()
    system._power_factor = 0.5
    before = weapon.GetChargeLevel()
    weapon.UpdateCharge(1.0)
    gained_half = weapon.GetChargeLevel() - before

    weapon2_gain = _fresh_gain(system)   # resets system to 1.0, new bank
    assert abs(gained_half - 0.5 * weapon2_gain) < 1e-6


def test_phaser_recharge_zero_factor_gains_nothing():
    """At factor 0.0 an idle bank gains no charge at all."""
    system, weapon = _phaser_fixture()
    system._power_factor = 0.0
    before = weapon.GetChargeLevel()
    weapon.UpdateCharge(1.0)
    assert weapon.GetChargeLevel() == before


def test_phaser_recharge_full_factor_unchanged():
    """Factor 1.0 gives the normal (unscaled) gain."""
    system, weapon = _phaser_fixture()
    system._power_factor = 1.0
    before = weapon.GetChargeLevel()
    weapon.UpdateCharge(1.0)
    gained = weapon.GetChargeLevel() - before
    # Expect 10.0 (recharge_rate * 1.0 * dt 1.0), capped by headroom (100 - 0)
    assert abs(gained - 10.0) < 1e-9


def test_phaser_recharge_boosted_factor():
    """Factor 1.25 (overclock) gives 1.25× gain."""
    system, weapon = _phaser_fixture()
    system._power_factor = 1.25
    before = weapon.GetChargeLevel()
    weapon.UpdateCharge(1.0)
    gained = weapon.GetChargeLevel() - before
    assert abs(gained - 12.5) < 1e-9


def test_phaser_no_parent_recharges_normally():
    """A bank with no parent subsystem falls back to factor 1.0."""
    bank = PhaserBank("Orphan")
    bank._max_charge = 100.0
    bank._min_firing_charge = 20.0
    bank._recharge_rate = 10.0
    bank._normal_discharge_rate = 50.0
    bank._charge_level = 0.0
    before = bank.GetChargeLevel()
    bank.UpdateCharge(1.0)
    assert abs(bank.GetChargeLevel() - before - 10.0) < 1e-9


# ── Torpedo reload tests ─────────────────────────────────────────────────────

def test_torpedo_reload_stalls_at_zero_factor(clock):
    """factor 0 ⇒ UpdateReload never loads a new torpedo, regardless of elapsed time."""
    system, tube = _torpedo_fixture()
    system._power_factor = 0.0

    # Fire so num_ready drops to 0 and a slot starts cooling.
    # Bypass projectile spawn by not binding a script — Fire fails CanFire check
    # (num_ready=1 with parent on, so it will succeed), but we need _spawn to be
    # a no-op.  Use the property path: tube has no property, so _spawn_torpedo
    # silently no-ops; Fire still decrements _num_ready and stamps the slot.
    clock(100.0)
    tube.Fire(target=None, offset=None)
    assert tube._num_ready == 0

    # Elapse far more than reload_delay so the normal threshold is already exceeded.
    clock(100.0 + 1000.0)

    # With factor 0.0 UpdateReload should return early without reloading.
    tube.UpdateReload(0.0)
    assert tube._num_ready == 0


def test_torpedo_reload_threshold_scales_with_factor(clock):
    """At factor 0.5 the effective reload delay doubles (reload_delay / 0.5 = 80 s)."""
    system, tube = _torpedo_fixture()
    system._power_factor = 0.5
    tube._reload_delay = 40.0

    clock(100.0)
    tube.Fire()
    assert tube._num_ready == 0

    # 50 s elapsed — beyond the stock 40 s but below the factor-scaled 80 s.
    # At factor 0.5 the tube should NOT reload.
    clock(150.0)
    tube.UpdateReload(0.0)
    assert tube._num_ready == 0, "Should not reload at half-power: 50 s < 80 s threshold"


def test_torpedo_reload_completes_at_full_factor(clock):
    """At factor 1.0 the tube reloads after the normal delay."""
    system, tube = _torpedo_fixture()
    system._power_factor = 1.0
    tube._reload_delay = 40.0

    clock(100.0)
    tube.Fire()
    assert tube._num_ready == 0

    # 50 s elapsed > 40 s delay, factor 1.0 ⇒ should reload
    clock(150.0)
    tube.UpdateReload(0.0)
    assert tube._num_ready == 1


def test_torpedo_reload_fast_at_boosted_factor(clock):
    """At factor 2.0 the effective threshold is 20 s (40/2); 25 s elapsed ⇒ reloads."""
    system, tube = _torpedo_fixture()
    system._power_factor = 2.0
    tube._reload_delay = 40.0

    clock(100.0)
    tube.Fire()
    assert tube._num_ready == 0

    clock(125.0)
    tube.UpdateReload(0.0)
    assert tube._num_ready == 1


def test_torpedo_reload_no_parent_uses_normal_delay(clock):
    """A tube with no parent subsystem reloads against the normal delay (factor 1.0).

    Fire() requires a parent (CanFire gates on GetParentSubsystem()), so an
    orphan tube can't fire itself into a cooling slot — seed the slot array
    directly to simulate one round that started cooling at t=100 (zero progress,
    last advanced at t=100 under the accumulator model).
    """
    tube = TorpedoTube("Orphan")
    tube._max_ready = 1
    tube._num_ready = 0
    tube._reload_delay = 40.0
    tube._resize_slots()

    clock(100.0)
    tube._reload_timers[0] = 0.0            # freshly cooling: 0 progress banked
    tube._reload_advanced_at[0] = 100.0     # started cooling at t=100

    # 50 s elapsed x factor 1.0 (no parent) = 50 >= 40 delay ⇒ should reload
    clock(150.0)
    tube.UpdateReload(0.0)
    assert tube._num_ready == 1
