"""Bible §3 pulse weapons and §4 torpedoes.

A bolt is one hit of `projectile GetDamage() × PulseWeapon.GetDamageScale()`;
a torpedo is one hit of the projectile script's GetDamage(), applied whole.
"""
import pytest

from tests.oracle.conftest import FRONT, bible_xfail


def _hits(scene, seconds, min_step=1.0):
    """(t, amount) for every tick the front face or hull dropped by more than
    `min_step` — i.e. every projectile impact (regen ticks are excluded)."""
    hits = []
    prev = scene.face(FRONT) + scene.hull.GetCondition()
    for t, sc in scene.sample_until(seconds):
        cur = sc.face(FRONT) + sc.hull.GetCondition()
        if prev - cur > min_step:
            hits.append((t, prev - cur))
        prev = cur
    return hits


def _launches(scene, seconds):
    """Tick times at which the number of projectiles in flight rose."""
    # StartFiring launches its first projectile synchronously, before the
    # first tick — count what is already in flight as launched at t=now.
    prev = scene.torpedoes_in_flight()
    times = [scene.t] * prev
    for t, sc in scene.sample_until(seconds):
        cur = sc.torpedoes_in_flight()
        if cur > prev:
            times.extend([t] * (cur - prev))   # two emitters can fire one tick
        prev = cur
    return times


# ── §3 pulse ─────────────────────────────────────────────────────────────────

@bible_xfail("P1", "Warbird RomulanCannon bolt lands as 200 (script 400 × DamageScale 0.5)",
             "lands as 400 — no DamageScale factor")
def test_p1_warbird_bolt_damage(oracle):
    """P1 — `pulse_warbird_front_40`: every bolt 200, exact."""
    s = oracle(attacker="Warbird", range_gu=40)
    s.fire("pulse")
    hits = _hits(s, 4.0)
    assert hits, "no bolts landed"
    assert all(d == pytest.approx(200.0, abs=1.0) for _, d in hits), hits


def test_p1_warbird_eight_bolts_per_burst(oracle):
    """P1 — 4 emitters, 8 bolts in 2.7 s (± 1 bolt), then recharge."""
    s = oracle(attacker="Warbird", range_gu=40)
    s.fire("pulse")
    launches = _launches(s, 2.7)
    assert 7 <= len(launches) <= 9, launches


def test_p2_bird_of_prey_bolt_damage(oracle):
    """P2 — `pulse_bop_front_40`: PulseDisruptor 220 lands whole."""
    s = oracle(attacker="BirdOfPrey", range_gu=40)
    s.fire("pulse")
    hits = _hits(s, 4.0)
    assert hits, "no bolts landed"
    # Two bolts can land on the same tick; each is a multiple of 220.
    for _, d in hits:
        n = round(d / 220.0)
        assert n >= 1 and d == pytest.approx(n * 220.0, abs=1.0)


@bible_xfail("P2", "Bird of Prey fires pairs every 2.28 s (± 0.1 s)",
             "pairs every ~2.45 s")
def test_p2_bird_of_prey_pairs_every_2_28_s(oracle):
    """P2 — pairs every 2.28 s (± 0.1 s)."""
    s = oracle(attacker="BirdOfPrey", range_gu=40)
    s.fire("pulse")
    launches = _launches(s, 10.0)
    # Collapse each pair (≤ 0.1 s apart) to its first launch.
    volleys = []
    for t in launches:
        if not volleys or t - volleys[-1] > 0.5:
            volleys.append(t)
    gaps = [b - a for a, b in zip(volleys, volleys[1:])]
    assert gaps, launches
    for g in gaps:
        assert g == pytest.approx(2.28, abs=0.1), gaps


def test_p3_bolt_damage_independent_of_range(oracle):
    """P3 — `pulse_warbird_front_{40,100,150}`: bursts 1501 / 1514 / 1526 —
    no range falloff on bolts (compared here per bolt, ± 2 %)."""
    per_bolt = {}
    for r in (40, 100, 150):
        s = oracle(attacker="Warbird", range_gu=r)
        s.fire("pulse")
        hits = _hits(s, 6.0)
        assert hits, "no bolts landed at %d GU" % r
        per_bolt[r] = sum(d for _, d in hits) / len(hits)
    assert per_bolt[100] == pytest.approx(per_bolt[40], rel=0.02)
    assert per_bolt[150] == pytest.approx(per_bolt[40], rel=0.02)


@pytest.mark.parametrize("setting, cost", [(0, 0.5), (1, 1.0), (2, 2.0)])
def test_p4_power_setting_changes_shot_cost_not_damage(oracle, setting, cost):
    """P4 — `pulse_warbird_front_40_{meta,low,high}`: Warbird cannon MaxCharge
    2.0 drops 0.5 / 1.0 / 2.0 per bolt at LOW / MED / HIGH."""
    s = oracle(attacker="Warbird", range_gu=40)
    cannons = s.emitters("pulse")
    for c in cannons:
        c.SetPowerSetting(setting)
    before = [c.GetChargeLevel() for c in cannons]
    s.fire("pulse")
    s.step(3)                       # the first bolt of each cannon has left
    drops = [b - c.GetChargeLevel() for b, c in zip(before, cannons)]
    fired = [d for d in drops if d > 0.01]
    assert fired, drops
    for d in fired:
        assert d == pytest.approx(cost, abs=0.02), drops


# ── §4 torpedoes ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("attacker, damage", [("Galaxy", 500.0), ("Sovereign", 550.0)])
def test_t1_torpedo_hit_is_script_damage_applied_whole(oracle, attacker, damage):
    """T1 — `torpedo_{galaxy,sovereign}_front_57`: Photon 500, Photon2 550."""
    s = oracle(attacker=attacker, range_gu=57)
    s.fire("torpedo")
    hits = _hits(s, 6.0)
    assert len(hits) >= 4, hits
    for _, d in hits:
        assert d == pytest.approx(damage, abs=0.5)


def test_t1_positron_torpedo_2200(oracle):
    """T1 — `torpedo_kessok_front_57`: Positron 2200."""
    s = oracle(attacker="KessokHeavy", range_gu=57)
    s.fire("torpedo")
    hits = _hits(s, 16.0)
    assert len(hits) >= 2, hits
    for _, d in hits:
        assert d == pytest.approx(2200.0, abs=0.5)


@bible_xfail("T2", "tubes launch 0.656 s (40 ticks) apart, ± 1 tick",
             "gaps are 0.50 / 0.58 / 0.68 s — irregular")
def test_t2_tubes_fire_0_656_s_apart(oracle):
    """T2 — `torpedo_galaxy_front_57`: four forward tubes in sequence."""
    s = oracle(attacker="Galaxy", range_gu=57)
    s.fire("torpedo")
    launches = _launches(s, 3.0)
    assert len(launches) >= 4, launches
    gaps = [b - a for a, b in zip(launches, launches[1:4])]
    for g in gaps:
        assert g == pytest.approx(0.656, abs=0.02), gaps


@pytest.mark.parametrize("attacker, flight_s", [("Galaxy", 2.9), ("KessokHeavy", 13.3)])
def test_t3_flight_time_for_57_gu(oracle, attacker, flight_s):
    """T3 — Photon ≈ 2.9 s, Positron ≈ 13.3 s for 57 GU (± 0.5 s)."""
    s = oracle(attacker=attacker, range_gu=57)
    s.fire("torpedo")
    launches = _launches(s, 0.5)
    assert launches, "no launch"
    t0 = launches[0]
    hits = _hits(s, flight_s + 2.0)
    assert hits, "no hit"
    assert hits[0][0] - t0 == pytest.approx(flight_s, abs=0.5)


@bible_xfail("T4", "switching ammo type unloads the tubes: Sovereign ReloadDelay 40 s before the first quantum salvo",
             "SetAmmoType is a pure slot select — the new type fires immediately")
def test_t4_ammo_switch_unloads_tubes(oracle):
    """T4 — `torpedo_sovereign_quantum_57`: first quantum salvo needs ~45 s
    after `SetAmmoType(1)`; nothing launches in the first 30 s."""
    s = oracle(attacker="Sovereign", range_gu=57)
    s.weapon_system("torpedo").SetAmmoType(1)
    s.fire("torpedo")
    launches = _launches(s, 30.0)
    assert launches == [], launches
