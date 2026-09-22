"""Bible §11 — the stock Quick Battle `BasicAttack` AI against a parked
Galaxy with its weapons live and nobody at the controls, from 150 GU dead
ahead, 90 s.  The AI is the SDK's own Python; what the oracle pins down is
the engine side it drives — speeds, turn rates, fire gates — and the
resulting trajectory (`ai_kessok_vs_parked_galaxy_med` and siblings).
"""
import pytest

from tests.oracle.conftest import bible_xfail

MED = 0.5


def _trajectory(scene, seconds, every_ticks=6):
    """[(t, range, speed, turn_rate, phasers_firing, torps_in_flight)]."""
    ps = scene.atk.GetPhaserSystem()
    banks = [ps.GetWeapon(i) for i in range(ps.GetNumWeapons())] if ps else []
    rows = []
    for t, sc in scene.sample_until(seconds, every_ticks=every_ticks):
        rows.append((t, sc.range_now(), sc.speed_of(sc.atk), sc.turn_rate_of(sc.atk),
                     any(b.IsFiring() for b in banks), sc.torpedoes_in_flight()))
    return rows


def test_a1_reaction_and_opens_fire_at_150_gu(oracle):
    """A1 — target acquired and weapons open at 150 GU ~4–6 s after the sim
    starts (± 0.5 s on the reaction; the range is the whole point)."""
    s = oracle(attacker="KessokHeavy", range_gu=150, settle_s=0.0)
    s.attach_basic_attack(MED)
    rows = _trajectory(s, 10.0)
    first = next((r for r in rows if r[4] or r[5] > 0), None)
    assert first is not None, "never fired"
    t, rng = first[0], first[1]
    assert rng > 140.0, "did not open at 150 GU: %.1f" % rng
    assert t < 8.0, "reaction %.1f s" % t


@bible_xfail("A4", "AI runs its impulse engines at 125 % power — every AI run peaks at exactly 1.25 × MaxSpeed (Kessok 4.63)",
             "engine power wanted stays 1.00; peaks at ~3.4 GU/s")
def test_a4_ai_runs_engines_at_125_percent(oracle):
    """A4 — `ai_*`."""
    s = oracle(attacker="KessokHeavy", range_gu=150, settle_s=0.0)
    s.attach_basic_attack(MED)
    rows = _trajectory(s, 60.0)
    peak = max(r[2] for r in rows)
    assert peak == pytest.approx(1.25 * 3.7, rel=0.02)


@bible_xfail("A2", "Kessok AI pass: close to ~47 GU, break away to ~123 GU, turn at 0.40 rad/s",
             "never turns (ω = 0 for 90 s), flies straight in and parks nose-to-nose at 8 GU")
def test_a2_kessok_pass_geometry(oracle):
    """A2 — `ai_kessok_vs_parked_galaxy_*`: closest approach 47.5 GU at t≈36,
    break-away to 123 by t≈60, identical at all three difficulties (± 5 GU)."""
    s = oracle(attacker="KessokHeavy", range_gu=150, settle_s=0.0)
    s.attach_basic_attack(MED)
    rows = _trajectory(s, 90.0)
    closest = min(r[1] for r in rows)
    assert closest == pytest.approx(47.5, abs=5.0)
    after = [r[1] for r in rows if r[0] > 50.0]
    assert max(after) == pytest.approx(123.0, abs=5.0)
    assert max(r[3] for r in rows) == pytest.approx(0.40, abs=0.05)


@bible_xfail("A7", "BoP AI: closest 37 GU, 7.75 GU/s, 0.72 rad/s",
             "the AI dies on its first charge toggle: ConditionPulseReady.ChargeToggled casts pEvent.GetSource() and gets None")
def test_a7_bird_of_prey_pass(oracle):
    """A7 — `ai_bop_vs_parked_galaxy_med` (± 5 %)."""
    s = oracle(attacker="BirdOfPrey", range_gu=150, settle_s=0.0)
    s.attach_basic_attack(MED)
    rows = _trajectory(s, 60.0)
    assert min(r[1] for r in rows) == pytest.approx(36.9, rel=0.05)
    assert max(r[2] for r in rows) == pytest.approx(7.75, rel=0.05)
    assert max(r[3] for r in rows) == pytest.approx(0.72, rel=0.05)


@bible_xfail("A3", "at difficulty 0.0 the AI NEVER fires torpedoes (phasers 94 %)",
             "fires torpedoes at LOW — no flag in BasicAttack.g_lAllFlags names torpedo use, so the gate is engine-side and missing")
def test_a3_low_difficulty_never_fires_torpedoes(oracle):
    """A3 — `ai_kessok_vs_parked_galaxy_low`: difficulty gates weapon use;
    torpedoes never at LOW, 42 % duty at MED."""
    low = oracle(attacker="KessokHeavy", range_gu=150, settle_s=0.0)
    low.attach_basic_attack(0.0)
    assert all(r[5] == 0 for r in _trajectory(low, 40.0))
    med = oracle(attacker="KessokHeavy", range_gu=150, settle_s=0.0)
    med.attach_basic_attack(MED)
    assert any(r[5] > 0 for r in _trajectory(med, 40.0))
