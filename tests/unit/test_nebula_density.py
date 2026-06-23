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
                      freq=0.01, gain=1.6, floor=0.4, drift_t=0.0) == 0.0


def test_density_in_range_inside_sphere():
    spheres = [(0.0, 0.0, 0.0, 100.0)]
    seed = nd.seed_for(0.0, 0.0, 0.0)
    vals = [nd.density(x, 0.0, 0.0, spheres, seed,
                       freq=0.05, gain=1.6, floor=0.4, drift_t=0.0)
            for x in range(-90, 91, 5)]
    assert all(0.0 <= v <= 1.0 for v in vals)
    assert max(vals) > 0.0             # at least some cloud inside
    assert min(vals) == 0.0 or max(vals) > min(vals)  # varies (clumps)


def test_seed_differs_per_nebula():
    assert nd.seed_for(0.0, 0.0, 0.0) != nd.seed_for(1500.0, 0.0, 0.0)
