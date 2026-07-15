"""PhaserBank.CanFire fidelity (Task 10, audited §1.6).

The audited decompiled CanFire is SIMPLER than the invented refire
hysteresis it replaces: charge only needs to reach MinFiringCharge to
START a beam; once firing, sustaining it only needs charge > 0. That
start/sustain ASYMMETRY *is* BC's hysteresis — REFIRE_HEADROOM_FRACTION
and the ``_armed`` latch are gone.

Also covers: the ship-alive gate, the disabled-product gate, the
condition-scaled recharge, the SetPowerLevel clamp, GetChargePercentage's
off/disabled gate, and the phaser first-shot ET_WEAPON_FIRED post.
"""
import pytest

import App
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass
from engine.appc.subsystems import PhaserSystem, PhaserBank


def make_charged_bank(*, min_firing=1.0, charge=5.0, max_charge=10.0,
                       recharge=1.0, discharge=1.0, condition_pct=1.0):
    """A single PhaserBank under a powered PhaserSystem on a ship, seeded
    with an explicit charge model.  Mirrors the _bank()/_firing_phaser_system()
    pattern in tests/unit/test_weapons_disabled_blocks_fire.py."""
    ship = ShipClass()
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    sys_ = PhaserSystem("Phasers")
    sys_.TurnOn()
    ship.SetPhaserSystem(sys_)

    bank = PhaserBank("Bank0")
    bank._max_charge = max_charge
    bank._charge_level = charge
    bank._min_firing_charge = min_firing
    bank._recharge_rate = recharge
    bank._normal_discharge_rate = discharge
    bank._max_condition = 100.0
    bank._condition = 100.0 * condition_pct
    sys_.AddChildSubsystem(bank)
    return bank


def make_target():
    """Straight ahead of the ship on model-Y — inside every default arc."""
    class _T:
        def GetWorldLocation(self):
            return TGPoint3(0.0, 100.0, 0.0)
        def IsDead(self):
            return False
    return _T()


@pytest.fixture
def recorded_events():
    """Collect ET_WEAPON_FIRED event-type ids the engine posts, in order.
    Mirrors tests/unit/test_torpedo_fire_gates.py's fixture of the same
    name."""
    seen = []
    globals()["_collect"] = lambda _obj, evt: seen.append(evt.GetEventType())
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_WEAPON_FIRED, object(), __name__ + "._collect")
    yield seen
    App.g_kEventManager._broadcast_handlers.pop(App.ET_WEAPON_FIRED, None)


# ── CanFire start/sustain asymmetry (the hysteresis) ────────────────────────

def test_start_needs_min_firing_charge_but_sustain_only_needs_nonzero():
    bank = make_charged_bank(min_firing=2.0, charge=1.0)
    assert bank.CanFire() == 0            # below start threshold
    bank._charge_level = 2.0
    bank.Fire(target=make_target())
    bank._charge_level = 0.5              # drained mid-beam
    assert bank.CanFire() == 1            # sustain: > 0 suffices
    bank._charge_level = 0.0
    assert bank.CanFire() == 0


def test_restart_after_depletion_needs_min_firing_charge_no_headroom():
    bank = make_charged_bank(min_firing=2.0, charge=2.0, max_charge=10.0)
    bank.Fire(target=make_target())
    bank._charge_level = 0.0
    bank.UpdateCharge(0.016)              # depletion auto-stop
    assert bank.IsFiring() == 0
    bank._charge_level = 2.0              # exactly MinFiringCharge — enough
    assert bank.CanFire() == 1            # (old code demanded 2.0 + 20% of 10)


# ── Ship-alive + disabled-product gates ─────────────────────────────────────

def test_dead_ship_cannot_fire():
    bank = make_charged_bank(min_firing=1.0, charge=5.0)
    ship = bank._climb_to_ship()
    ship.IsDead = lambda: True
    assert bank.CanFire() == 0


def test_disabled_product_gate_blocks_when_combined_condition_below_threshold():
    bank = make_charged_bank(min_firing=1.0, charge=5.0)
    bank._disabled_percentage = 0.5
    bank._condition = 40.0    # 40% of max_condition (100) -> combined 0.4 < 0.5
    assert bank.CanFire() == 0


def test_disabled_product_gate_uses_parent_condition_too():
    bank = make_charged_bank(min_firing=1.0, charge=5.0)
    bank._disabled_percentage = 0.5
    parent = bank.GetParentSubsystem()
    parent._condition = 40.0   # parent at 40% -> combined 1.0*0.4 = 0.4 < 0.5
    parent._max_condition = 100.0
    assert bank.CanFire() == 0


# ── Recharge scales with condition ──────────────────────────────────────────

def test_recharge_scales_with_condition():
    healthy = make_charged_bank(charge=0.0, recharge=1.0, condition_pct=1.0)
    damaged = make_charged_bank(charge=0.0, recharge=1.0, condition_pct=0.5)
    healthy.UpdateCharge(1.0)
    damaged.UpdateCharge(1.0)
    assert abs(healthy._charge_level - 2 * damaged._charge_level) < 1e-9


# ── SetPowerLevel clamp ──────────────────────────────────────────────────────

def test_set_power_level_clamps():
    sys_ = PhaserSystem("Phasers")
    sys_.SetPowerLevel(5)
    assert sys_.GetPowerLevel() == 2      # BC: uninitialized-stack bug; we clamp
    sys_.SetPowerLevel(-3)
    assert sys_.GetPowerLevel() == 0


# ── GetChargePercentage off/disabled gate ───────────────────────────────────

def test_get_charge_percentage_zero_when_parent_off():
    bank = make_charged_bank(min_firing=1.0, charge=5.0, max_charge=10.0)
    bank.GetParentSubsystem().TurnOff()
    assert bank.GetChargePercentage() == 0.0


def test_get_charge_percentage_zero_when_bank_disabled():
    bank = make_charged_bank(min_firing=1.0, charge=5.0, max_charge=10.0)
    bank._condition = 0.0     # fully disabled at the default 0.25 threshold
    assert bank.GetChargePercentage() == 0.0


def test_get_charge_percentage_nonzero_when_healthy_and_powered():
    bank = make_charged_bank(min_firing=1.0, charge=5.0, max_charge=10.0)
    assert bank.GetChargePercentage() == 0.5


# ── Phaser first-shot ET_WEAPON_FIRED ────────────────────────────────────────

def test_phaser_first_shot_posts_weapon_fired(recorded_events):
    bank = make_charged_bank(min_firing=1.0, charge=5.0)
    bank.Fire(target=make_target())
    assert App.ET_WEAPON_FIRED in recorded_events
    n = recorded_events.count(App.ET_WEAPON_FIRED)
    bank.Fire(target=make_target())       # already firing — no re-post
    assert recorded_events.count(App.ET_WEAPON_FIRED) == n
