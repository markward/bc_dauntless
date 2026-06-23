from engine.appc.nebula_wake import NebulaWakeTracker, SPACING, N, LIFETIME


def test_no_points_outside_nebula():
    w = NebulaWakeTracker()
    for i in range(100):
        w.update(False, (float(i) * 100.0, 0.0, 0.0), i / 60.0)
    assert w.trail_points() == []


def test_no_points_when_pos_none():
    w = NebulaWakeTracker()
    for i in range(100):
        w.update(True, None, i / 60.0)
    assert w.trail_points() == []


def test_records_by_distance_not_per_tick():
    w = NebulaWakeTracker()
    # Move a tiny amount each tick (< SPACING) → only the first point lands.
    t = 0.0
    for i in range(50):
        t += 1.0 / 60.0
        w.update(True, (i * 0.1, 0.0, 0.0), t)   # 0.1 GU/tick << SPACING
    assert len(w.trail_points()) == 1            # spacing prevents new points


def test_records_a_new_point_each_spacing():
    w = NebulaWakeTracker()
    t = 0.0
    # Jump SPACING GU each tick → a new point every tick.
    for i in range(10):
        t += 1.0 / 60.0
        w.update(True, (i * SPACING, 0.0, 0.0), t)
    assert len(w.trail_points()) == 10


def test_stationary_lays_no_trail_growth():
    w = NebulaWakeTracker()
    t = 0.0
    w.update(True, (0.0, 0.0, 0.0), t)           # first point
    for _ in range(120):
        t += 1.0 / 60.0
        w.update(True, (0.0, 0.0, 0.0), t)       # never moves
    # No new points are added from standing still; the single initial point persists.
    assert len(w.trail_points()) <= 1


def test_caps_at_N():
    w = NebulaWakeTracker()
    t = 0.0
    for i in range(N * 3):
        t += 1.0 / 60.0
        w.update(True, (i * SPACING, 0.0, 0.0), t)
    assert len(w.trail_points()) <= N


def test_strength_fades_and_points_expire():
    w = NebulaWakeTracker()
    # Drop one point at t=0, then keep ticking in place past LIFETIME.
    w.update(True, (0.0, 0.0, 0.0), 0.0)
    s0 = w.trail_points()
    assert s0 and 0.0 < s0[0]["strength"] <= 1.0
    # Halfway through life: strength has dropped.
    w.update(True, (0.0, 0.0, 0.0), LIFETIME * 0.5)
    mid = w.trail_points()
    assert mid and mid[0]["strength"] < s0[0]["strength"]
    # Past life: the point is gone.
    w.update(True, (0.0, 0.0, 0.0), LIFETIME + 0.1)
    assert w.trail_points() == []


def test_clears_on_leaving_nebula():
    w = NebulaWakeTracker()
    t = 0.0
    for i in range(10):
        t += 1.0 / 60.0
        w.update(True, (i * SPACING, 0.0, 0.0), t)
    assert w.trail_points()
    w.update(False, (999.0, 0.0, 0.0), t + 0.1)
    assert w.trail_points() == []


def test_reset_clears():
    w = NebulaWakeTracker()
    t = 0.0
    for i in range(10):
        t += 1.0 / 60.0
        w.update(True, (i * SPACING, 0.0, 0.0), t)
    w.reset()
    assert w.trail_points() == []
