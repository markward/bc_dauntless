from engine.appc import nebula_density as nd


def test_fbm_is_deterministic_and_bounded():
    a = nd.fbm(1.5, 2.5, 3.5)
    b = nd.fbm(1.5, 2.5, 3.5)
    assert a == b                      # deterministic
    assert 0.0 <= a <= 1.0             # value-noise fbm stays in [0,1]


def test_fbm_varies_across_space():
    # Two well-separated points should differ (it's noise, not a constant).
    assert abs(nd.fbm(0.0, 0.0, 0.0) - nd.fbm(10.3, -4.1, 7.7)) > 0.05


def test_density_zero_outside_all_spheres():
    spheres = [(0.0, 0.0, 0.0, 100.0)]
    seed = nd.seed_for(0.0, 0.0, 0.0)
    # 500 GU out is well outside the 100 GU sphere → no cloud.
    assert nd.density(500.0, 0.0, 0.0, spheres, seed,
                      freq=0.01, gain=1.6, density_floor=0.4, drift_t=0.0) == 0.0


def test_density_in_range_inside_sphere():
    spheres = [(0.0, 0.0, 0.0, 100.0)]
    seed = nd.seed_for(0.0, 0.0, 0.0)
    vals = [nd.density(x, 0.0, 0.0, spheres, seed,
                       freq=0.05, gain=1.6, density_floor=0.4, drift_t=0.0)
            for x in range(-90, 91, 5)]
    assert all(0.0 <= v <= 1.0 for v in vals)
    assert max(vals) > 0.0             # at least some cloud inside
    assert max(vals) > min(vals)  # density varies across the sphere (clumps)


def test_seed_differs_per_nebula():
    assert nd.seed_for(0.0, 0.0, 0.0) != nd.seed_for(1500.0, 0.0, 0.0)


def test_fbm_golden_values_pin_constants():
    # Pinned so the hash/fbm constants can't silently drift (GPU/CPU parity guard).
    assert abs(nd.fbm(1.5, 2.5, 3.5) - 0.43832942533588964) < 1e-9
    assert abs(nd._hash13(1.0, 2.0, 3.0) - 0.17883083253718723) < 1e-9


def test_density_golden_value():
    # Pinned so the whole pipeline (hash/fbm/density) stays constant (CPU/GPU agreement).
    spheres = [(0.0, 0.0, 0.0, 100.0)]
    seed = nd.seed_for(0.0, 0.0, 0.0)
    v = nd.density(20.0, 10.0, 5.0, spheres, seed, freq=0.05, gain=1.6, density_floor=0.4, drift_t=0.0)
    assert abs(v - 0.20645526505610945) < 1e-9
