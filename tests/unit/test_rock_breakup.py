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


# ── Tuned after live test 2026-10-01: fewer pieces, one major generation ─────
_NAMES = ["Asteroid %d%s" % (i, c) for i in range(1, 9) for c in "abc"]


def test_tuned_dials():
    assert (breakup.kPieceCountMin, breakup.kPieceCountMax) == (2, 3)
    assert breakup.kMaxMajorGeneration == 1
    assert breakup.kMaxChunksPerDeath == 3


def test_plan_is_deterministic_per_generation():
    for gen in (0, 1, 2):
        assert (breakup.plan("Asteroid 5b", 7.4, generation=gen)
                == breakup.plan("Asteroid 5b", 7.4, generation=gen))


def test_at_most_three_majors():
    for name in _NAMES:
        majors = [p for p in breakup.plan(name, 8.0) if p.tier == "major"]
        assert len(majors) <= 3


def test_generation_one_rock_spawns_no_majors_only_chunks_and_dust():
    for name in _NAMES:
        gen0 = breakup.plan(name, 8.0)
        gen1 = breakup.plan(name, 8.0, generation=1)
        assert all(p.tier in ("chunk", "dust") for p in gen1)
        # Would-be majors became chunks: same sizes, same volume budget.
        assert [p.radius_gu for p in gen1] == [p.radius_gu for p in gen0]
        assert sum(1 for p in gen1 if p.tier == "chunk") >= \
            sum(1 for p in gen0 if p.tier == "major")


def test_chunks_per_death_capped_keeping_the_largest(monkeypatch):
    """Unreachable at kPieceCountMax 3, so widen the count to prove the cap."""
    monkeypatch.setattr(breakup, "kPieceCountMax", 8)
    monkeypatch.setattr(breakup, "kPieceCountMin", 8)
    for name in _NAMES:
        pieces = breakup.plan(name, 6.0, generation=1)
        chunks = [p for p in pieces if p.tier == "chunk"]
        assert len(chunks) == breakup.kMaxChunksPerDeath
        demoted = [p for p in pieces if p.tier == "dust"
                   and p.radius_gu >= breakup.kChunkMinRadiusGU]
        assert demoted and min(c.radius_gu for c in chunks) >= \
            max(d.radius_gu for d in demoted)


def test_chunk_count_never_exceeds_cap():
    for name in _NAMES:
        for gen in (0, 1, 2):
            for r in (0.5, 1.5, 4.0, 8.0):
                chunks = [p for p in breakup.plan(name, r, generation=gen)
                          if p.tier == "chunk"]
                assert len(chunks) <= breakup.kMaxChunksPerDeath
