"""EnergyWeapon.UpdateCharge(dt): fills at _recharge_rate when on + idle,
drains while firing, auto-stops at zero.

The PhaserBank drain is BC's power-level table (PP_HIGH default → 1.0/s), NOT
the `discharge=` value seeded below — that property is dead on the phaser
path (tests/unit/test_energy_weapon_discharge_source.py).  The seeds here
happen to equal the HIGH table entry, so the expected values are unchanged.
"""
from engine.appc.subsystems import PhaserBank, PhaserSystem


def _bank(on=True, charge=5.0, max_charge=5.0, recharge=0.5, discharge=1.0,
          min_firing_charge=3.0):
    bank = PhaserBank("Test")
    parent = PhaserSystem("Phasers")
    if on:
        parent.TurnOn()
    parent.AddChildSubsystem(bank)
    bank._max_charge = max_charge
    bank._min_firing_charge = min_firing_charge
    bank._charge_level = charge
    bank._recharge_rate = recharge
    bank._normal_discharge_rate = discharge
    return bank


def test_update_charge_fills_when_on_and_idle():
    bank = _bank(on=True, charge=2.0, recharge=0.5)
    bank.UpdateCharge(dt=1.0)
    assert bank.GetChargeLevel() == 2.5


def test_update_charge_caps_at_max():
    bank = _bank(on=True, charge=4.5, recharge=0.5, max_charge=5.0)
    bank.UpdateCharge(dt=2.0)
    assert bank.GetChargeLevel() == 5.0


def test_update_charge_drains_when_firing():
    bank = _bank(on=True, charge=5.0, discharge=1.0)
    bank.Fire(target=None, offset=None)
    bank.UpdateCharge(dt=0.5)
    assert bank.GetChargeLevel() == 4.5


def test_update_charge_auto_stops_when_drained():
    bank = _bank(on=True, charge=1.0, discharge=2.0, min_firing_charge=0.5)
    bank.Fire(target=None, offset=None)
    bank.UpdateCharge(dt=1.0)
    assert bank.GetChargeLevel() == 0.0
    assert bank.IsFiring() == 0


def test_update_charge_holds_when_off_and_idle():
    """Spec: turning weapons off does NOT drain stored charge."""
    bank = _bank(on=False, charge=4.0, recharge=0.5)
    bank.UpdateCharge(dt=10.0)
    assert bank.GetChargeLevel() == 4.0


def test_update_charge_zero_dt_no_op():
    bank = _bank(on=True, charge=3.0)
    bank.UpdateCharge(dt=0.0)
    assert bank.GetChargeLevel() == 3.0
