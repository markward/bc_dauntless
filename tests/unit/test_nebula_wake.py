from engine.appc.nebula_wake import NebulaWakeTracker, SPACING, N, LIFETIME, FRONT_RISE


def _em(key, x, y=0.0, z=0.0, size=0.25):
    return {"key": key, "pos": (x, y, z), "size": size}


def test_no_points_outside_nebula():
    w = NebulaWakeTracker()
    for i in range(100):
        w.update(False, [_em("a", float(i) * 100.0)], i / 60.0)
    assert w.trail_points() == []


def test_no_points_when_no_emitters():
    w = NebulaWakeTracker()
    for i in range(100):
        w.update(True, [], i / 60.0)
    assert w.trail_points() == []


def test_records_by_distance_not_per_tick():
    w = NebulaWakeTracker()
    t = 0.0
    step = SPACING / 100.0          # cumulative travel stays < SPACING
    for i in range(50):
        t += 1.0 / 60.0
        w.update(True, [_em("a", i * step)], t)
    assert len(w.trail_points()) == 1            # only the initial drop


def test_records_a_new_point_each_spacing():
    w = NebulaWakeTracker()
    t = 0.0
    for i in range(10):
        t += 1.0 / 60.0
        w.update(True, [_em("a", i * SPACING)], t)
    assert len(w.trail_points()) == 10


def test_two_emitters_are_independent():
    w = NebulaWakeTracker()
    t = 0.0
    # Two pods at different offsets, each moving by SPACING per tick.
    for i in range(8):
        t += 1.0 / 60.0
        w.update(True, [_em("port", i * SPACING, y=-1.0, size=0.25),
                        _em("star", i * SPACING, y=+1.0, size=0.40)], t)
    pts = w.trail_points()
    assert len(pts) == 16                          # 8 from each pod
    ys = sorted({round(p["pos"][1], 3) for p in pts})
    assert ys == [-1.0, 1.0]                        # both trails present
    # Each pod's points carry that pod's size.
    assert {p["size"] for p in pts if p["pos"][1] == -1.0} == {0.25}
    assert {p["size"] for p in pts if p["pos"][1] == +1.0} == {0.40}


def test_caps_at_N_per_emitter():
    w = NebulaWakeTracker()
    t = 0.0
    for i in range(N * 3):
        t += 1.0 / 60.0
        w.update(True, [_em("a", i * SPACING)], t)
    assert len(w.trail_points()) <= N


def test_point_carries_emitter_size():
    w = NebulaWakeTracker()
    w.update(True, [_em("a", 0.0, size=0.33)], 0.0)
    w.update(True, [_em("a", SPACING, size=0.33)], 0.1)
    pts = w.trail_points()
    assert pts and all(p["size"] == 0.33 for p in pts)


def test_strength_rises_then_fades_and_expires():
    w = NebulaWakeTracker()
    w.update(True, [_em("a", 0.0)], 0.0)
    born = w.trail_points()
    assert born and born[0]["strength"] == 0.0          # invisible at birth (no pop)
    w.update(True, [_em("a", 0.0)], FRONT_RISE * 0.5)
    rising = w.trail_points()
    assert rising and 0.0 < rising[0]["strength"] < 1.0
    w.update(True, [_em("a", 0.0)], FRONT_RISE)
    peak = w.trail_points()
    assert peak and peak[0]["strength"] > rising[0]["strength"]
    w.update(True, [_em("a", 0.0)], LIFETIME * 0.9)
    late = w.trail_points()
    assert late and late[0]["strength"] < peak[0]["strength"]
    w.update(True, [_em("a", 0.0)], LIFETIME + 0.1)
    assert w.trail_points() == []


def test_offline_emitter_trail_fades_then_drops_others_continue():
    w = NebulaWakeTracker()
    t = 0.0
    # Both pods lay a trail while moving.
    for i in range(5):
        t += 1.0 / 60.0
        w.update(True, [_em("port", i * SPACING, y=-1.0),
                        _em("star", i * SPACING, y=+1.0)], t)
    assert any(p["pos"][1] == -1.0 for p in w.trail_points())
    # "port" goes offline: only "star" is fed now. Port's points must fade out
    # over LIFETIME (not vanish instantly), while star keeps growing.
    start = t
    while t - start < LIFETIME + 0.2:
        t += 1.0 / 60.0
        w.update(True, [_em("star", (t * 60.0) * SPACING, y=+1.0)], t)
    pts = w.trail_points()
    assert pts and all(p["pos"][1] == +1.0 for p in pts)   # port fully faded; star remains


def test_clears_on_leaving_nebula():
    w = NebulaWakeTracker()
    t = 0.0
    for i in range(10):
        t += 1.0 / 60.0
        w.update(True, [_em("a", i * SPACING)], t)
    assert w.trail_points()
    w.update(False, [_em("a", 999.0)], t + 0.1)
    assert w.trail_points() == []


def test_reset_clears():
    w = NebulaWakeTracker()
    t = 0.0
    for i in range(10):
        t += 1.0 / 60.0
        w.update(True, [_em("a", i * SPACING)], t)
    w.reset()
    assert w.trail_points() == []


def test_deterministic():
    a = NebulaWakeTracker()
    b = NebulaWakeTracker()
    t = 0.0
    for i in range(60):
        t += 1.0 / 60.0
        ems = [_em("p", i * 0.5, y=-1.0), _em("s", i * 0.5, y=1.0)]
        a.update(True, ems, t)
        b.update(True, ems, t)
    assert a.trail_points() == b.trail_points()
