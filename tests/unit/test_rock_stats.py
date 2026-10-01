from engine.rocks import stats


def test_size_formula_calibrated_on_stock_asteroid():
    assert stats.size_hull(0.8) == 2500.0
    assert stats.size_mass(0.8) == 400.0
    assert abs(stats.size_hull(1.6) - 10000.0) < 1e-9
    assert abs(stats.size_mass(1.6) - 3200.0) < 1e-9


def test_piece_scaling():
    assert abs(stats.piece_hull(2500.0, 0.125) - 625.0) < 1e-9   # 0.125^(2/3) = 0.25
    assert stats.piece_mass(400.0, 0.125) == 50.0


def test_quantise_radius_two_significant_figures():
    assert stats.quantise_radius(1.2345) == 1.2
    assert stats.quantise_radius(0.0876) == 0.088
    assert stats.quantise_radius(5.0) == 5.0
    assert stats.quantise_radius(12.6) == 13.0
