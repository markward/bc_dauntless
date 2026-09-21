"""Bible §2 — beam weapons.  Reference emitter: Kessok Heavy Forward Beam 1..4,
MaxDamage 400, MaxDamageDistance 200, MaxCharge 7, at 57 GU dead ahead of a
parked Galaxy (`phaser_high_front_57.json` and siblings).

The model the captures confirm:
    rate_per_beam = MaxDamage × intensity_scale × min(1, MaxDamageDistance / range)
    intensity_scale: LOW 0.25   MED 0.5   HIGH 0.5
delivered as one quantum per beam every 0.53 s after a 1.156 s windup.
"""
import pytest

from tests.oracle.conftest import FRONT, bible_xfail

LOW, MED, HIGH = 0, 1, 2
KESSOK_BEAMS = 4
MAX_DAMAGE = 400.0


def _front_rate(scene, seconds=2.0):
    """Damage per second landing on the front face (shields up, face far from
    empty so nothing cascades to the hull).  Regen (~10/s) is inside the
    bible's tolerance at these rates."""
    before = scene.face(FRONT)
    scene.run(seconds)
    return (before - scene.face(FRONT)) / seconds


def test_b1_full_volley_total(oracle):
    """B1 — `phaser_high_front_57`: 5 469 measured; the 7 s charge at 1.0/s
    ends the volley, so the total is what lands on face + hull by 8 s."""
    s = oracle(attacker="KessokHeavy", range_gu=57)
    s.fire("phaser", intensity=HIGH)
    s.run(8.0)
    total = s.face_damage(FRONT) + s.hull_damage()
    assert total == pytest.approx(5400, rel=0.05)


def test_b2_med_equals_high(oracle):
    """B2 — `phaser_med_front_57`: 849/s vs 825/s; MED and HIGH share the 0.5
    scale, so the totals agree within 5 %."""
    high = oracle(attacker="KessokHeavy", range_gu=57)
    high.fire("phaser", intensity=HIGH)
    r_high = _front_rate(high)
    med = oracle(attacker="KessokHeavy", range_gu=57)
    med.fire("phaser", intensity=MED)
    r_med = _front_rate(med)
    assert r_med == pytest.approx(r_high, rel=0.05)


def test_b3_low_rate_is_half_of_high(oracle):
    """B3 — `phaser_low_front_57`: 408/s vs 825/s."""
    high = oracle(attacker="KessokHeavy", range_gu=57)
    high.fire("phaser", intensity=HIGH)
    r_high = _front_rate(high)
    low = oracle(attacker="KessokHeavy", range_gu=57)
    low.fire("phaser", intensity=LOW)
    r_low = _front_rate(low)
    assert r_low == pytest.approx(0.5 * r_high, rel=0.05)


def test_b3_low_never_damages_hull(oracle):
    """B3 — `phaser_low_front_57_noshields`: hull 0 after a full LOW volley on
    a bare hull (subsystems only: 'disable, don't destroy')."""
    s = oracle(attacker="KessokHeavy", range_gu=57)
    s.zero_shields()
    s.fire("phaser", intensity=LOW)
    s.run(8.0)
    assert s.hull_damage() == 0.0


@pytest.mark.parametrize("range_gu, factor", [(250, 0.80), (400, 0.50), (600, 1.0 / 3.0)])
def test_b4_rate_beyond_max_damage_distance_scales_by_r_over_d(oracle, range_gu, factor):
    """B4 — `phaser_high_front_{250,400,600}`: 683 / 418 / 283 per second
    against 825 at 57 GU, i.e. × R/d with R = 200."""
    near = oracle(attacker="KessokHeavy", range_gu=57)
    near.fire("phaser", intensity=HIGH)
    r_near = _front_rate(near)
    far = oracle(attacker="KessokHeavy", range_gu=range_gu)
    far.fire("phaser", intensity=HIGH)
    r_far = _front_rate(far)
    assert r_far == pytest.approx(r_near * factor, rel=0.06)


def test_b5_rate_inside_max_damage_distance_is_flat(oracle):
    """B5 — `phaser_high_front_150`: 832/s at 150 GU vs 825 at 57 (R = 200)."""
    near = oracle(attacker="KessokHeavy", range_gu=57)
    near.fire("phaser", intensity=HIGH)
    r_near = _front_rate(near)
    mid = oracle(attacker="KessokHeavy", range_gu=150)
    mid.fire("phaser", intensity=HIGH)
    r_mid = _front_rate(mid)
    assert r_mid == pytest.approx(r_near, rel=0.03)


@bible_xfail("B6", "first damage lands 1.156 s (70 ticks) after IsFiring goes true",
             "damage lands on the first tick — no windup")
def test_b6_windup_before_first_quantum(oracle):
    """B6 — identical in all 20 beam runs regardless of ship, intensity, range
    or face; a game-time constant (holds at time scale 0.5, F2)."""
    s = oracle(attacker="KessokHeavy", range_gu=57)
    s.fire("phaser", intensity=HIGH)
    first = None
    for t, sc in s.sample_until(2.0):
        if sc.face_damage(FRONT) > 0.0:
            first = t
            break
    assert first is not None
    assert first == pytest.approx(1.156, abs=0.05)


@bible_xfail("B7", "each beam deposits a quantum of MaxDamage × 0.5 × 0.53125 = 106.25 every 0.53 s",
             "damage is continuous per tick (13.3 per tick for four beams at HIGH)")
def test_b7_damage_arrives_as_quanta(oracle):
    """B7 — `phaser_high_front_57`: after the windup, the face steps down in
    discrete quanta of 106.25 (±2 %) with ~0.35 s of nothing between volleys;
    on a per-tick model most ticks carry a fraction of a quantum."""
    s = oracle(attacker="KessokHeavy", range_gu=57)
    s.fire("phaser", intensity=HIGH)
    s.run(1.2)                      # past the windup
    steps = []
    prev = s.face(FRONT)
    for _, sc in s.sample_until(2.2):
        cur = sc.face(FRONT)
        if prev - cur > 1.0:        # ignore regen ticks
            steps.append(prev - cur)
        prev = cur
    assert steps, "no damage steps sampled"
    quantum = MAX_DAMAGE * 0.5 * 0.53125
    # Every step is one or more whole quanta (beams stagger 1–4 ticks, so a
    # tick may carry two).
    for d in steps:
        n = round(d / quantum)
        assert n >= 1 and d == pytest.approx(n * quantum, rel=0.02)


@bible_xfail("B8", "a bank preset to charge 3 (MinFiringCharge 4) fires at the full 805/s",
             "refuses to start below MinFiringCharge — rate 0 (the 'audited §1.6' "
             "start gate in PhaserBank.UpdateCharge is contradicted by the capture)")
def test_b8_rate_independent_of_remaining_charge(oracle):
    """B8 — `phaser_high_front_57_charge3`: a bank preset to charge 3 fires at
    the same 805/s.  The Kessok forward beams author MinFiringCharge 4.0, so
    this capture is also evidence about what MinFiringCharge gates."""
    full = oracle(attacker="KessokHeavy", range_gu=57)
    full.fire("phaser", intensity=HIGH)
    r_full = _front_rate(full)
    low = oracle(attacker="KessokHeavy", range_gu=57)
    for b in low.emitters("phaser"):
        b.SetChargeLevel(3.0)
    low.fire("phaser", intensity=HIGH)
    r_low = _front_rate(low)
    assert r_low == pytest.approx(r_full, rel=0.05)


def test_b8_rate_independent_of_power_wanted(oracle):
    """B8 — `phaser_high_front_57_power50`: SetPowerPercentageWanted(0.5) on
    the phaser system leaves the rate at 846/s."""
    full = oracle(attacker="KessokHeavy", range_gu=57)
    full.fire("phaser", intensity=HIGH)
    r_full = _front_rate(full)
    half = oracle(attacker="KessokHeavy", range_gu=57)
    half.weapon_system("phaser").SetPowerPercentageWanted(0.5)
    half.fire("phaser", intensity=HIGH)
    r_half = _front_rate(half)
    assert r_half == pytest.approx(r_full, rel=0.05)


@pytest.mark.parametrize("intensity, drain_per_s", [(HIGH, 1.0), (MED, 1.0), (LOW, 0.35)])
def test_b9_discharge_rate_by_intensity(oracle, intensity, drain_per_s):
    """B9 — HIGH/MED 1.0 charge/s (7 → 0 in 7.0 s), LOW 0.35/s."""
    s = oracle(attacker="KessokHeavy", range_gu=57)
    s.fire("phaser", intensity=intensity)
    fwd = [b for b in s.emitters("phaser") if b.GetMaxDamage() == MAX_DAMAGE]
    before = fwd[0].GetChargeLevel()
    s.run(3.0)
    assert (before - fwd[0].GetChargeLevel()) / 3.0 == pytest.approx(drain_per_s, rel=0.03)


def test_b9_bank_stops_at_zero_charge(oracle):
    """B9 — a bank stops the instant charge reaches 0; nothing lands after."""
    s = oracle(attacker="KessokHeavy", range_gu=57)
    s.fire("phaser", intensity=HIGH)
    s.run(7.5)
    fwd = [b for b in s.emitters("phaser") if b.GetMaxDamage() == MAX_DAMAGE]
    assert all(not b.IsFiring() for b in fwd)
    assert all(b.GetChargeLevel() < 0.2 for b in fwd)


@bible_xfail("F1", "Galaxy (SetSingleFire 1) fires ONE bank at a time, round-robin on exhaustion",
             "lights one bank on the first tick, then four at once")
def test_f1_federation_phasers_single_fire(oracle):
    """F1 — `phaser_galaxy_front_57`: bank 5 for 5.5 s, then bank 6, then
    bank 1 — never two at once."""
    s = oracle(attacker="Galaxy", range_gu=57)
    s.fire("phaser")
    banks = s.emitters("phaser")
    max_lit = 0
    for _, sc in s.sample_until(5.0, every_ticks=6):
        max_lit = max(max_lit, sum(1 for b in banks if b.IsFiring()))
    assert max_lit == 1
