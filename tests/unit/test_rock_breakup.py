from engine.rocks import breakup


def test_plan_is_deterministic_per_name():
    assert breakup.plan("Asteroid 5b", 4.0) == breakup.plan("Asteroid 5b", 4.0)
    assert breakup.plan("Asteroid 5b", 4.0) != breakup.plan("Asteroid 6b", 4.0)


def test_volume_budget_and_count():
    pieces = breakup.plan("Asteroid 5b", 4.0)
    assert breakup.kPieceCountMin <= len(pieces) <= breakup.kPieceCountMax
    assert abs(sum(p.v_ratio for p in pieces) - breakup.kVolumeBudget) < 1e-9
    for p in pieces:
        assert abs(p.radius_gu - 4.0 * p.v_ratio ** (1.0 / 3.0)) < 1e-9


def test_tiers_follow_thresholds():
    for name in ("a", "b", "c", "d", "e"):
        for p in breakup.plan(name, 4.0):
            if p.radius_gu >= breakup.kMajorMinRadiusGU:
                assert p.tier == "major"
            elif p.radius_gu >= breakup.kChunkMinRadiusGU:
                assert p.tier == "chunk"
            else:
                assert p.tier == "dust"


def test_small_rock_has_no_majors():
    assert all(p.tier != "major" for p in breakup.plan("x", 0.8))


def test_offsets_are_unit_vectors():
    for p in breakup.plan("Asteroid 5b", 4.0):
        assert abs(sum(c * c for c in p.offset) - 1.0) < 1e-9
