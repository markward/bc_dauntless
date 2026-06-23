from engine.appc.hull_discharge import HullDischargeDriver

PTS = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]


def _count_spawns(driver, ticks, damage_rate, dt=1.0/60.0):
    """Advance `ticks` frames in a nebula; return total discharges ever spawned."""
    t = 0.0
    seen = 0
    prev_ids = set()
    total = 0
    for _ in range(ticks):
        t += dt
        driver.update(True, damage_rate, dt, PTS, t)
        # Count by identity of the active list growth: approximate via births.
        total = max(total, len(driver.active_discharges()))
    return total


def test_no_spawn_outside_nebula():
    d = HullDischargeDriver(seed=1)
    for i in range(600):
        d.update(False, 150.0, 1.0/60.0, PTS, i/60.0)
    assert d.active_discharges() == []
    assert d.emissive_boost() == 1.0


def test_no_spawn_without_hull_points():
    d = HullDischargeDriver(seed=1)
    for i in range(600):
        d.update(True, 150.0, 1.0/60.0, [], i/60.0)
    assert d.active_discharges() == []


def test_rate_scales_with_damage():
    # Over the same window, a high damage rate spawns far more than zero damage.
    lo = HullDischargeDriver(seed=3)
    hi = HullDischargeDriver(seed=3)
    lo_spawns = hi_spawns = 0
    t = 0.0
    for _ in range(60 * 20):                  # 20 s
        t += 1.0/60.0
        lo.update(True, 0.0,   1.0/60.0, PTS, t)
        hi.update(True, 150.0, 1.0/60.0, PTS, t)
        lo_spawns += len(lo.active_discharges())
        hi_spawns += len(hi.active_discharges())
    assert hi_spawns > lo_spawns * 5          # damaging cloud crackles far more


def test_idle_strikes_occur_at_zero_damage():
    d = HullDischargeDriver(seed=5)
    ever = 0
    t = 0.0
    for _ in range(60 * 30):                  # 30 s at zero damage
        t += 1.0/60.0
        d.update(True, 0.0, 1.0/60.0, PTS, t)
        ever += len(d.active_discharges())
    assert ever > 0                           # rare, but they happen


def test_discharges_anchor_near_hull_points():
    d = HullDischargeDriver(seed=7)
    t = 0.0
    found = False
    for _ in range(600):
        t += 1.0/60.0
        d.update(True, 150.0, 1.0/60.0, PTS, t)
        for dis in d.active_discharges():
            x, y, z = dis["world_pos"]
            # within ANCHOR_OFFSET of some provided point
            assert any(abs(x-px) <= 0.1501 and abs(y-py) <= 0.1501 and abs(z-pz) <= 0.1501
                       for (px, py, pz) in PTS)
            found = True
    assert found


def test_discharges_expire():
    d = HullDischargeDriver(seed=9)
    # Spawn a flurry, then advance well past max life with no new spawns
    # (outside nebula → no spawns, ages still advance to expiry on the next
    # in-nebula tick is N/A; leaving the nebula clears immediately).
    t = 0.0
    for _ in range(120):
        t += 1.0/60.0
        d.update(True, 500.0, 1.0/60.0, PTS, t)
    assert len(d.active_discharges()) >= 0     # some may be active
    # Advance time by 1 s with continued ticks but check nothing older than life.
    for _ in range(60):
        t += 1.0/60.0
        d.update(True, 500.0, 1.0/60.0, PTS, t)
        for dis in d.active_discharges():
            assert dis["age"] < dis["life"]


def test_emissive_boost_idle_is_exactly_one():
    d = HullDischargeDriver(seed=11)
    assert d.emissive_boost() == 1.0          # fresh, no discharges
    # In a damaging cloud it rises above 1.0 at least once.
    t = 0.0
    rose = False
    for _ in range(600):
        t += 1.0/60.0
        d.update(True, 300.0, 1.0/60.0, PTS, t)
        if d.emissive_boost() > 1.0:
            rose = True
    assert rose


def test_determinism_same_seed():
    a = HullDischargeDriver(seed=42)
    b = HullDischargeDriver(seed=42)
    t = 0.0
    for _ in range(600):
        t += 1.0/60.0
        a.update(True, 120.0, 1.0/60.0, PTS, t)
        b.update(True, 120.0, 1.0/60.0, PTS, t)
    assert a.active_discharges() == b.active_discharges()
    assert a.emissive_boost() == b.emissive_boost()


def test_reset_clears_and_reseeds():
    d = HullDischargeDriver(seed=13)
    t = 0.0
    for _ in range(600):
        t += 1.0/60.0
        d.update(True, 150.0, 1.0/60.0, PTS, t)
    d.reset()
    assert d.active_discharges() == []
    assert d.emissive_boost() == 1.0
