"""A phaser bank lights only at MinFiringCharge, fresh or after running dry.

Measured on the original (stbc-oracle results_win_charge, Windows, real time):
Galaxy and Sovereign banks (MaxCharge 5, MinFiringCharge 3, recharge 0.08/s)
preset to 0.1-2.0 never fire in 11 s of held fire; preset to 2.5 the first bank
lights when it has recharged to 3.0 (~6.25 s after the fire order); from 2.9,
3.0 and 3.5 a bank lights on reaching 3.0. Once lit a bank drains to 0. With
the trigger held, a drained bank relights at 3.01, 37.5-37.9 s after emptying
(3.0 / 0.08).
"""
import pytest

HIGH = 2


def _fire_and_watch(sc, seconds):
    banks = sc.emitters("phaser")
    sc.fire("phaser", intensity=HIGH)
    t0 = sc.t
    first = None   # (seconds after the fire order, charge when it lit)
    for _ in range(int(seconds * 60)):
        sc.step(1)
        if first is None:
            on = [b for b in banks if b.IsFiring()]
            if on:
                first = (sc.t - t0, on[0].GetChargeLevel())
    return first


@pytest.mark.parametrize("attacker,target", [("Galaxy", "Sovereign"), ("Sovereign", "Galaxy")])
@pytest.mark.parametrize("charge", [0.1, 0.5, 1.0, 2.0])
def test_a_bank_below_min_firing_charge_never_starts(oracle, attacker, target, charge):
    sc = oracle(attacker=attacker, target=target, range_gu=57.0)
    for b in sc.emitters("phaser"):
        b.SetChargeLevel(charge)
    sh0 = sum(sc.shields.GetCurShields(f) for f in range(6))
    assert _fire_and_watch(sc, 11.0) is None
    assert sum(sc.shields.GetCurShields(f) for f in range(6)) >= sh0 - 1e-6


@pytest.mark.parametrize("attacker,target", [("Galaxy", "Sovereign"), ("Sovereign", "Galaxy")])
def test_a_bank_lights_once_it_recharges_to_min_firing_charge(oracle, attacker, target):
    sc = oracle(attacker=attacker, target=target, range_gu=57.0)
    for b in sc.emitters("phaser"):
        b.SetChargeLevel(2.5)
    first = _fire_and_watch(sc, 11.0)
    assert first is not None
    t, c = first
    assert c == pytest.approx(3.0, abs=0.02)
    assert t == pytest.approx(0.5 / 0.08, abs=0.2)


@pytest.mark.parametrize("charge", [3.0, 3.5])
def test_a_bank_at_or_above_min_firing_charge_starts_at_once(oracle, charge):
    sc = oracle(attacker="Galaxy", target="Sovereign", range_gu=57.0)
    for b in sc.emitters("phaser"):
        b.SetChargeLevel(charge)
    first = _fire_and_watch(sc, 2.0)
    assert first is not None and first[0] < 0.1


def test_a_lit_bank_drains_to_zero_and_relights_at_min_firing_charge(oracle):
    sc = oracle(attacker="Sovereign", target="Galaxy", range_gu=57.0)
    banks = sc.emitters("phaser")
    sc.fire("phaser", intensity=HIGH)
    lows, relit = {}, {}
    for _ in range(70 * 60):
        sc.step(1)
        for i, b in enumerate(banks):
            c = b.GetChargeLevel()
            if b.IsFiring():
                if i in lows and i not in relit:
                    relit[i] = (sc.t - lows[i], c)
            elif c <= 1e-6 and i not in lows:
                lows[i] = sc.t
    assert lows, "no bank ran dry"
    assert relit, "no drained bank relit with the trigger held"
    for i, (gap, c) in relit.items():
        assert c == pytest.approx(3.0, abs=0.02)
        assert gap == pytest.approx(3.0 / 0.08, abs=0.6)
