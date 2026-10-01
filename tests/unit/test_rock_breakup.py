from engine.rocks import breakup

_NAMES = ["Asteroid %d%s" % (i, c) for i in range(1, 9) for c in "abc"]
_MANY = ["Rock %d" % i for i in range(400)]


def _ranked(pieces, rank):
    return [p for p in pieces if p.rank == rank]


def test_plan_is_deterministic_per_name():
    assert breakup.plan("Asteroid 5b", 4.0) == breakup.plan("Asteroid 5b", 4.0)
    assert breakup.plan("Asteroid 5b", 4.0) != breakup.plan("Asteroid 6b", 4.0)


def test_offsets_are_unit_vectors():
    for p in breakup.plan("Asteroid 5b", 4.0):
        assert abs(sum(c * c for c in p.offset) - 1.0) < 1e-9


def test_radius_is_parent_radius_times_cube_root_of_volume():
    for p in breakup.plan("Asteroid 5b", 4.0):
        assert abs(p.radius_gu - 4.0 * p.v_ratio ** (1.0 / 3.0)) < 1e-9


# ── Size-mix split (live test 2026-10-01): 1 large, 3-5 medium, 5-8 small ────


def test_size_mix_dials():
    b = breakup
    assert (b.kLargeFracMin, b.kLargeFracMax) == (0.20, 0.30)
    assert (b.kMediumCountMin, b.kMediumCountMax) == (3, 5)
    assert (b.kMediumFracMin, b.kMediumFracMax) == (0.07, 0.12)
    assert (b.kSmallCountMin, b.kSmallCountMax) == (5, 8)
    assert (b.kSmallFracMin, b.kSmallFracMax) == (0.03, 0.06)
    assert b.kVolumeTotalMax == 1.0
    assert b.kMaxChunksPerDeath == 8
    assert b.kMaxMajorGeneration == 1
    assert b.kTargetableMinRadiusGU == 2.0
    for retired in ("kVolumeBudget", "kPieceCountMin", "kPieceCountMax"):
        assert not hasattr(b, retired)


def test_ranks_come_in_plan_order_with_counts_in_range():
    for name in _NAMES:
        pieces = breakup.plan(name, 6.0)
        ranks = [p.rank for p in pieces]
        assert ranks[0] == "large" and ranks.count("large") == 1
        nm, ns = ranks.count("medium"), ranks.count("small")
        assert breakup.kMediumCountMin <= nm <= breakup.kMediumCountMax
        assert breakup.kSmallCountMin <= ns <= breakup.kSmallCountMax
        assert ranks == ["large"] + ["medium"] * nm + ["small"] * ns


def test_fractions_in_range_unless_scaled_and_total_capped():
    b = breakup
    scaled_seen = False
    for name in _MANY:
        pieces = b.plan(name, 6.0)
        total = sum(p.v_ratio for p in pieces)
        assert total <= b.kVolumeTotalMax + 1e-12
        large = _ranked(pieces, "large")[0]
        assert b.kLargeFracMin <= large.v_ratio <= b.kLargeFracMax
        med, small = _ranked(pieces, "medium"), _ranked(pieces, "small")
        # Scaling only shrinks, small first: a medium is never above range,
        # a small never above range, and nothing is negative.
        for p in med:
            assert 0.0 < p.v_ratio <= b.kMediumFracMax
        for p in small:
            assert 0.0 <= p.v_ratio <= b.kSmallFracMax
        if any(p.v_ratio < b.kSmallFracMin for p in small):
            scaled_seen = True
            assert abs(total - b.kVolumeTotalMax) < 1e-9
        else:
            for p in med:
                assert b.kMediumFracMin <= p.v_ratio
    assert scaled_seen, "no name drew over the cap; widen _MANY"


def test_large_is_strictly_the_largest():
    for name in _MANY:
        pieces = breakup.plan(name, 6.0)
        large = _ranked(pieces, "large")[0]
        assert all(large.v_ratio > p.v_ratio for p in pieces if p is not large)


def test_different_names_give_different_splits():
    splits = {tuple(round(p.v_ratio, 9) for p in breakup.plan(n, 6.0))
              for n in _NAMES}
    assert len(splits) == len(_NAMES)


def test_average_total_is_about_085_to_1():
    totals = [sum(p.v_ratio for p in breakup.plan(n, 6.0)) for n in _MANY]
    assert 0.85 <= sum(totals) / len(totals) <= 1.0


def test_over_cap_scales_small_first_then_medium(monkeypatch):
    """Force every draw to its maximum (1.38 total): smalls absorb the
    excess first. With smalls already at 0, the mediums shrink next."""
    b = breakup
    monkeypatch.setattr(b, "kLargeFracMin", b.kLargeFracMax)
    monkeypatch.setattr(b, "kMediumCountMin", b.kMediumCountMax)
    monkeypatch.setattr(b, "kMediumFracMin", b.kMediumFracMax)
    monkeypatch.setattr(b, "kSmallCountMin", b.kSmallCountMax)
    monkeypatch.setattr(b, "kSmallFracMin", b.kSmallFracMax)
    pieces = b.plan("Asteroid 5b", 6.0)
    assert abs(sum(p.v_ratio for p in pieces) - 1.0) < 1e-9
    assert all(abs(p.v_ratio - 0.12) < 1e-12 for p in _ranked(pieces, "medium"))
    # 1 - 0.30 - 5 x 0.12 = 0.10 over 8 smalls
    assert all(abs(p.v_ratio - 0.0125) < 1e-12 for p in _ranked(pieces, "small"))
    monkeypatch.setattr(b, "kMediumFracMax", 0.18)
    monkeypatch.setattr(b, "kMediumFracMin", 0.18)
    pieces = b.plan("Asteroid 5b", 6.0)
    assert abs(sum(p.v_ratio for p in pieces) - 1.0) < 1e-9
    assert all(p.v_ratio == 0.0 for p in _ranked(pieces, "small"))
    assert all(abs(p.v_ratio - 0.14) < 1e-12 for p in _ranked(pieces, "medium"))


# ── Tiers: large/medium are majors, small are chunks ─────────────────────────


def test_large_and_medium_are_majors_and_small_are_chunks_on_a_big_rock():
    for name in _NAMES:
        for p in breakup.plan(name, 8.0):
            if p.rank in ("large", "medium"):
                assert p.tier == "major"
            else:
                assert p.tier == "chunk"      # whatever its radius


def test_small_is_a_chunk_even_above_the_major_floor():
    big_smalls = [p for p in breakup.plan("Asteroid 5b", 20.0)
                  if p.rank == "small"]
    assert big_smalls and all(p.radius_gu >= breakup.kMajorMinRadiusGU
                              for p in big_smalls)
    assert all(p.tier == "chunk" for p in big_smalls)


def test_major_floor_and_dust_floor_still_apply():
    for name in _NAMES:
        for r in (0.3, 1.2, 2.5):
            for p in breakup.plan(name, r):
                if p.radius_gu < breakup.kChunkMinRadiusGU:
                    assert p.tier == "dust"
                elif p.rank == "small" or p.radius_gu < breakup.kMajorMinRadiusGU:
                    assert p.tier in ("chunk", "dust")   # dust only by the cap
                else:
                    assert p.tier == "major"


def test_small_rock_has_no_majors():
    assert all(p.tier != "major" for p in breakup.plan("x", 0.8))


def test_plan_is_deterministic_per_generation():
    for gen in (0, 1, 2):
        assert (breakup.plan("Asteroid 5b", 7.4, generation=gen)
                == breakup.plan("Asteroid 5b", 7.4, generation=gen))


def test_generation_one_rock_spawns_no_majors_only_chunks_and_dust():
    for name in _NAMES:
        gen0 = breakup.plan(name, 8.0)
        gen1 = breakup.plan(name, 8.0, generation=1)
        assert all(p.tier in ("chunk", "dust") for p in gen1)
        assert [p.radius_gu for p in gen1] == [p.radius_gu for p in gen0]


def test_chunks_per_death_capped_keeping_the_largest():
    """Generation 1: 1 + 3-5 + 5-8 chunk candidates, cut to the 8 largest."""
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


# ── Spread majors (ruling after live test 2026-10-01) ────────────────────────
# Six 3-5 GU majors on random directions nearly always held one near-parallel
# pair overlapping past kGhostMaxTime, which then ground (scenario A). The
# large and medium pieces take spread directions, and fly apart at 0.8 GU/s.


def test_separation_speed_dial():
    assert breakup.kSeparationSpeedGU == 0.8


def test_no_sibling_major_pair_overlaps_at_the_ghost_cap():
    """Model of death._break_up: piece i starts at parent_radius x 0.5 along
    its offset and moves out at kSeparationSpeedGU along it (the parent's own
    velocity is common to all and cancels). At kGhostMaxTime every pair of
    majors must be kGhostSeparationMarginGU clear at their BUILT radii."""
    from engine.rocks.stats import quantise_radius
    T = breakup.kGhostMaxTime
    for R in (3.0, 5.0, 7.44, 8.5):
        for name in _MANY[:200] + _NAMES:
            majors = [p for p in breakup.plan(name, R) if p.tier == "major"]
            for i, a in enumerate(majors):
                for b in majors[i + 1:]:
                    d = sum((x - y) ** 2 for x, y in zip(a.offset, b.offset)) ** 0.5
                    gap = d * (R * 0.5 + breakup.kSeparationSpeedGU * T)
                    need = (quantise_radius(a.radius_gu)
                            + quantise_radius(b.radius_gu)
                            + breakup.kGhostSeparationMarginGU)
                    assert gap >= need, (name, R, a.rank, b.rank, gap, need)
