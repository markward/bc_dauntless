from engine.appc.nebula_thunder import NebulaThunderDriver


def _run(driver, ticks, in_nebula=True, dt=1.0/60.0, fwd=(0.0, 1.0, 0.0)):
    """Advance `ticks` frames; return total flashes ever seen (by spawn count)."""
    t = 0.0
    seen = 0
    prev = 0
    for _ in range(ticks):
        t += dt
        driver.update(in_nebula, dt, t, fwd)
        n = len(driver.active_flashes())
        if n > prev:
            seen += (n - prev)
        prev = n
    return seen


def test_no_flashes_outside_nebula():
    d = NebulaThunderDriver(seed=1)
    # 60 s outside a nebula → never spawns.
    for i in range(60 * 60):
        d.update(False, 1.0/60.0, i/60.0)
    assert d.active_flashes() == []


def test_spawns_over_time_in_nebula():
    d = NebulaThunderDriver(seed=1)
    # ~60 s inside → at the ~12s cadence, several flashes spawn.
    seen = _run(d, 60 * 60)
    assert seen >= 2


def test_flash_envelope_rises_then_decays():
    d = NebulaThunderDriver(seed=1)
    # Force a deterministic single flash and sample its intensity curve.
    f = d._spawn_flash(game_time=0.0, camera_forward=(0.0, 1.0, 0.0))
    i_rise = d._envelope(f, 0.15)     # mid-rise
    i_peak = d._envelope(f, 0.35)     # just after rise+hold start
    i_late = d._envelope(f, 2.0)      # deep in decay
    assert 0.0 < i_rise < i_peak
    assert i_late < i_peak
    assert d._envelope(f, 100.0) == 0.0   # fully decayed → gone


def test_determinism_same_seed():
    a = NebulaThunderDriver(seed=42)
    b = NebulaThunderDriver(seed=42)
    for i in range(600):
        t = i/60.0
        a.update(True, 1.0/60.0, t)
        b.update(True, 1.0/60.0, t)
    da = [(round(f.intensity, 6), tuple(round(x, 6) for x in f.dir)) for f in a.active_flashes()]
    db = [(round(f.intensity, 6), tuple(round(x, 6) for x in f.dir)) for f in b.active_flashes()]
    assert da == db


def test_audio_scheduled_and_due_after_delay():
    d = NebulaThunderDriver(seed=1)
    d._spawn_flash(game_time=10.0, camera_forward=(0.0, 1.0, 0.0))
    # Nothing due immediately at spawn time.
    assert d.pop_due_audio(10.0) == []
    # By spawn + max delay, the rumble is due exactly once.
    due = d.pop_due_audio(10.0 + 2.5)
    assert due == ["AtmosphereRumble"]
    assert d.pop_due_audio(20.0) == []   # not re-fired


def test_reset_clears_state():
    d = NebulaThunderDriver(seed=1)
    _run(d, 60 * 60)
    d.reset()
    assert d.active_flashes() == []
    assert d.pop_due_audio(1e9) == []


def test_direction_biased_toward_camera_forward():
    d = NebulaThunderDriver(seed=7)
    fwd = (0.0, 1.0, 0.0)
    dots = []
    for _ in range(50):
        f = d._spawn_flash(game_time=0.0, camera_forward=fwd)
        dx, dy, dz = f.dir
        dots.append(dx*fwd[0] + dy*fwd[1] + dz*fwd[2])
    # Most flash directions point into the forward hemisphere (dot > 0).
    assert sum(1 for x in dots if x > 0.0) >= 40
