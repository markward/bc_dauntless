"""Bible §7 motion — the first-order controller, warp, collisions, tractor.

    dv/dt = clamp(v_target − v, −MaxAccel, +MaxAccel)
    dω/dt = clamp(ω_target − ω, −MaxAngularAccel, +MaxAngularAccel)

constant acceleration at the hardpoint cap until within one cap-second of the
target, then exponential approach with a 1.0 s time constant.  Mass does not
enter.  Attacker parked 300 GU out so nothing collides.
"""
import pytest

from tests.oracle.conftest import bible_xfail

# (ship, speed @1 s, @2 s, @4 s, max) — bible §7.2, `motion_*_impulse`.
IMPULSE_PROFILES = [
    ("KessokHeavy", 2.226, 3.166, 3.630, 3.700),
    ("Galaxy", 1.500, 3.000, 5.635, 6.300),
    ("BirdOfPrey", 2.500, 4.726, 6.007, 6.200),
]
# (ship, ω @1 s, @2 s, @4 s, max rad/s) — `motion_*_{yaw,pitch,roll}`.
YAW_PROFILES = [
    ("KessokHeavy", 0.110, 0.180, 0.215, 0.220),
    ("Galaxy", 0.120, 0.219, 0.272, 0.280),
    ("BirdOfPrey", 0.304, 0.429, 0.491, 0.500),
]


def _sample_at(scene, times, read):
    """`read(scene)` at each offset in `times`, seconds after now."""
    t0 = scene.t
    out = {}
    for t, sc in scene.sample_until(max(times) + 0.02):
        for want in times:
            if want not in out and t - t0 >= want - 1e-6:
                out[want] = read(sc)
    return out


def _speeds_at(scene, ship, times):
    return _sample_at(scene, times, lambda sc: sc.speed_of(ship))


def _turn_rates_at(scene, ship, times):
    return _sample_at(scene, times, lambda sc: sc.turn_rate_of(ship))


@pytest.mark.parametrize("ship, v1, v2, v4, vmax", IMPULSE_PROFILES)
def test_m1_impulse_ramp_follows_the_1s_law(oracle, ship, v1, v2, v4, vmax):
    """M1 — speed at 1/2/4 s within 2 %, reaching MaxSpeed exactly."""
    s = oracle(attacker=ship, range_gu=300)
    s.full_impulse()
    v = _speeds_at(s, s.atk, (1.0, 2.0, 4.0))
    assert v[1.0] == pytest.approx(v1, rel=0.02)
    assert v[2.0] == pytest.approx(v2, rel=0.02)
    assert v[4.0] == pytest.approx(v4, rel=0.02)
    s.run(6.0)
    assert s.speed_of(s.atk) == pytest.approx(vmax, rel=0.005)


@bible_xfail("M2", "angular rate follows the same law: constant MaxAngularAccel then a 1 s exponential approach (Kessok 0.110 / 0.180 / 0.215)",
             "linear ramp all the way — reaches the cap at 2 s")
@pytest.mark.parametrize("ship, w1, w2, w4, wmax", YAW_PROFILES)
def test_m2_yaw_ramp_follows_the_1s_law(oracle, ship, w1, w2, w4, wmax):
    """M2 — `motion_*_yaw`; identical on yaw/pitch/roll.  Commanded at the
    hardpoint max through the direct API (the fraction API is the player's)."""
    s = oracle(attacker=ship, range_gu=300)
    s.yaw_direct(wmax)
    w = _turn_rates_at(s, s.atk, (1.0, 2.0, 4.0))
    assert w[1.0] == pytest.approx(w1, rel=0.02)
    assert w[2.0] == pytest.approx(w2, rel=0.02)
    assert w[4.0] == pytest.approx(w4, rel=0.02)


def test_m3_stopping_follows_the_same_law(oracle):
    """M3 — `motion_kessok_coast`: from 3.7 GU/s the Kessok falls at 2.5 GU/s²
    to 2.3, then decays e-fold per second: 0.92 @ 1.5 s, 0.51 @ 2.1 s,
    0.20 @ 3.0 s (± 5 %)."""
    s = oracle(attacker="KessokHeavy", range_gu=300)
    s.full_impulse()
    s.run(8.0)
    assert s.speed_of(s.atk) == pytest.approx(3.7, rel=0.01)
    s.full_impulse(fraction=0.0)
    v = _speeds_at(s, s.atk, (1.5, 2.1, 3.0))
    assert v[1.5] == pytest.approx(0.92, rel=0.05)
    assert v[2.1] == pytest.approx(0.51, rel=0.05)
    assert v[3.0] == pytest.approx(0.20, rel=0.05)


def test_m5_impulse_fraction_clamps_at_one(oracle):
    """M5 — `motion_kessok_impulse{125,200}`: SetImpulse(1.25) and (2.0) both
    give 3.700."""
    for f in (1.25, 2.0):
        s = oracle(attacker="KessokHeavy", range_gu=300)
        s.full_impulse(fraction=f)
        s.run(10.0)
        assert s.speed_of(s.atk) == pytest.approx(3.700, rel=0.005), f


@bible_xfail("M5", "v_target = MaxSpeed × impulse fraction × engine power fraction: at 125 % power the Kessok cruises at 4.625",
             "the power fraction only widens the cap; SetImpulse(1.0) still targets 1.0 × MaxSpeed = 3.70")
def test_m5_engine_power_fraction_does_not_clamp(oracle):
    """M5 — `motion_kessok_impulse_power125`: at SetPowerPercentageWanted(1.25)
    the Kessok cruises at 4.625 = 1.25 × 3.7 — how AI ships exceed MaxSpeed."""
    s = oracle(attacker="KessokHeavy", range_gu=300)
    s.atk.GetImpulseEngineSubsystem().SetPowerPercentageWanted(1.25)
    s.full_impulse()
    s.run(10.0)
    assert s.speed_of(s.atk) == pytest.approx(4.625, rel=0.005)


def test_m5_impulse_fraction_is_linear_below_one(oracle):
    """W2 corollary — `motion_kessok_impulse{020,050}`: 0.2 → 0.740,
    0.5 → 1.850, readable back with GetImpulse()."""
    for f, v in ((0.2, 0.740), (0.5, 1.850)):
        s = oracle(attacker="KessokHeavy", range_gu=300)
        s.full_impulse(fraction=f)
        s.run(8.0)
        assert s.speed_of(s.atk) == pytest.approx(v, rel=0.01), f
        assert s.atk.GetImpulse() == pytest.approx(f, abs=1e-3)


@bible_xfail("M6", "SetTargetAngularVelocityDirect(1.0 rad/s) ramps at MaxAngularAccel and settles at 1.0 — 4.5× the hardpoint max; only the fraction command is capped",
             "capped at MaxAngularVelocity (0.220)")
def test_m6_direct_angular_command_is_uncapped(oracle):
    """M6 — `motion_kessok_yawdirect`.  This is what the AI turns with: 0.40
    rad/s on a 0.22-rad/s Kessok (§11.6)."""
    s = oracle(attacker="KessokHeavy", range_gu=300)
    s.yaw_direct(1.0)
    s.run(12.0)
    assert s.turn_rate_of(s.atk) == pytest.approx(1.0, rel=0.03)


# ── §7.3 in-system warp ────────────────────────────────────────────────────────────

@bible_xfail("W1", "in-system warp is a step to exactly 75.0 GU/s for every ship, duration = distance / 75, exit at MaxSpeed",
             "cruises at 100 × MaxSpeed (Kessok 370 GU/s) and exits at the pre-warp speed")
def test_w1_in_system_warp_speed_and_exit(oracle):
    """W1 — `warp_kessok_rest_{600,2000}`: 7.25 s for 550 GU; drop-out at the
    requested stop distance (asked 50, 54–61 measured); exit at 3.62."""
    s = oracle(attacker="KessokHeavy", range_gu=600)
    s.atk.InSystemWarp(s.tgt, 50.0)
    peak = 0.0
    exit_speed = None
    for t, sc in s.sample_until(20.0):
        v = sc.speed_of(sc.atk)
        peak = max(peak, v)
        if exit_speed is None and getattr(sc.atk, "_insystem_warp_transit", None) is None and t > 0.5:
            exit_speed = v
            break
    assert peak == pytest.approx(75.0, rel=0.01)
    assert s.range_now() == pytest.approx(55.0, abs=10.0)
    assert exit_speed == pytest.approx(3.62, rel=0.05)


# ── §7.4 collisions ────────────────────────────────────────────────────────────────

RAMS = [
    # rammer, mass, impact speed, Galaxy speed after (elastic), damage to Galaxy
    ("KessokHeavy", 500.0, 3.70, 5.97, 5870.0),
    ("Galaxy", 120.0, 6.21, 6.21, 6089.0),
    ("BirdOfPrey", 45.0, 6.17, 3.36, 3527.0),
]


def _ram(oracle, rammer):
    """Full impulse into the parked Galaxy from 30 GU; run until the first
    hull damage, then a little more for the post-impact speeds."""
    s = oracle(attacker=rammer, range_gu=30)
    s.full_impulse()
    for t, sc in s.sample_until(15.0):
        if sc.hull_damage() > 0.0:
            break
    first = s.hull_damage()
    s.run(0.25)
    return s, first


@bible_xfail("C1", "collision is perfectly elastic with the hardpoint masses: the rammed Galaxy leaves at 2·mₐ·v/(mₐ+mₜ)",
             "no bounce — the target stays at rest and the rammer sits penetrated")
@pytest.mark.parametrize("rammer, mass, v_impact, v_target_after, _dmg", RAMS)
def test_c1_elastic_bounce(oracle, rammer, mass, v_impact, v_target_after, _dmg):
    """C1 — `ram_*`: post-impact speeds ± 3 %."""
    s, _ = _ram(oracle, rammer)
    assert s.speed_of(s.tgt) == pytest.approx(v_target_after, rel=0.03)


@pytest.mark.parametrize("rammer, mass, v_impact, _v, damage", [
    pytest.param(*RAMS[0], marks=bible_xfail(
        "C2", "Kessok Heavy (mass 500) ramming a Galaxy deals 5870 ± 10 %",
        "KE-based coefficient gives ~3300")),
    RAMS[1],
    pytest.param(*RAMS[2], marks=bible_xfail(
        "C2", "Bird of Prey (mass 45) ramming a Galaxy deals 3527 ± 10 %",
        "KE-based coefficient gives ~3100")),
])
def test_c2_ram_damage_is_8_2_times_impulse(oracle, rammer, mass, v_impact, _v, damage):
    """C2 — `ram_*`: first-impact damage to the parked Galaxy = 8.2 × J with
    J = 2μv (5870 / 6089 / 3527 ± 10 %).  Only the equal-mass Galaxy pairing
    lands inside tolerance on today's KE-based coefficient."""
    s, first = _ram(oracle, rammer)
    assert first == pytest.approx(damage, rel=0.10)


@pytest.mark.parametrize("rammer", ["KessokHeavy", "Galaxy", "BirdOfPrey"])
def test_c2_collision_damage_bypasses_shields(oracle, rammer):
    """C2 — every face unchanged in all three ram runs."""
    s, first = _ram(oracle, rammer)
    assert first > 0.0
    assert all(s.face_damage(i) == 0.0 for i in range(6)), s.faces()


# ── §7.5 tractor beam ──────────────────────────────────────────────────────────────

def _tractor(oracle, mode, range_gu=15.0, shields_up=False):
    s = oracle(attacker="Galaxy", range_gu=range_gu)
    if not shields_up:
        s.zero_shields()
    s.fire("tractor", tractor_mode=mode)
    return s


def _engaged(scene):
    return any(b.IsFiring() for b in scene.emitters("tractor"))


@pytest.mark.parametrize("range_gu, engages", [(115.0, True), (125.0, False)])
def test_r1_engagement_gate_is_max_damage_distance(oracle, range_gu, engages):
    """R1 — `tractor_engage_*`: hits at 20/60/100/115, never at 125/150; the
    gate is the projector's MaxDamageDistance (118)."""
    s = _tractor(oracle, "hold", range_gu=range_gu)
    s.run(0.5)
    assert _engaged(s) is engages


def test_r1_engages_through_shields(oracle):
    s = _tractor(oracle, "hold", range_gu=20.0, shields_up=True)
    s.run(0.5)
    assert _engaged(s)


def test_r1_no_charge_drain_while_holding(oracle):
    s = _tractor(oracle, "hold", range_gu=15.0)
    s.run(25.0)
    assert _engaged(s)
    assert all(b.GetChargeLevel() == pytest.approx(5.0, abs=0.01) for b in s.emitters("tractor"))


@bible_xfail("R2", "a parked target is moved toward the projector at 0.17–0.23 GU/s in EVERY mode (push pulls too) and stops at 10.0 GU (pull/push/tow) or 12.3 (hold) from 15",
             "hold/tow do not move it, pull closes at ~0.6 GU/s to 11.8, push shoves it away at ~8 GU/s")
@pytest.mark.parametrize("mode, stop_gu", [("hold", 12.3), ("pull", 10.0), ("push", 10.0), ("tow", 10.0)])
def test_r2_parked_target_creeps_to_a_fixed_stop_range(oracle, mode, stop_gu):
    """R2 — `tractor_galaxy_galaxy_{hold,pull,push,tow}`, from 15 GU."""
    s = _tractor(oracle, mode, range_gu=15.0)
    r0 = s.range_now()
    s.run(5.0)
    creep = (r0 - s.range_now()) / 5.0
    assert creep == pytest.approx(0.20, abs=0.05), mode
    s.run(25.0)
    assert s.range_now() == pytest.approx(stop_gu, rel=0.10), mode
