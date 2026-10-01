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


# ── Remnant + capped small rocks (live test 2026-10-01, third) ──────────────
# 30% of the parent's volume is ONE remnant; up to 12 small rocks of
# 0.5-1.5 GU take what they can of the other 70%; the rest is dust.


def _small_range(R):
    b = breakup
    rr = R * b.kRemnantFrac ** (1.0 / 3.0)
    if rr < b.kSmallRadiusMinGU:
        return b.kTinySmallRadiusMinFrac * rr, b.kTinySmallRadiusMaxFrac * rr
    return b.kSmallRadiusMinGU, min(b.kSmallRadiusMaxGU, rr)


def test_remnant_split_dials():
    b = breakup
    assert b.kRemnantFrac == 0.30
    assert b.kSmallMaxCount == 12
    assert (b.kSmallRadiusMinGU, b.kSmallRadiusMaxGU) == (0.5, 1.5)
    assert b.kSmallVolumeFrac == 0.70
    assert (b.kTinySmallRadiusMinFrac, b.kTinySmallRadiusMaxFrac) == (0.3, 0.9)
    assert b.kMajorMinRadiusGU == 1.0
    assert b.kMaxChunksPerDeath == 8
    assert b.kMaxMajorGeneration == 1
    assert b.kTargetableMinRadiusGU == 2.0
    for retired in ("kVolumeBudget", "kPieceCountMin", "kPieceCountMax",
                    "kLargeFracMin", "kLargeFracMax", "kMediumCountMin",
                    "kMediumCountMax", "kMediumFracMin", "kMediumFracMax",
                    "kSmallCountMin", "kSmallCountMax", "kSmallFracMin",
                    "kSmallFracMax", "kVolumeTotalMax"):
        assert not hasattr(b, retired), retired


def test_exactly_one_remnant_first_at_030():
    for name in _NAMES:
        for R in (0.3, 2.5, 3.0, 7.44):
            pieces = breakup.plan(name, R)
            ranks = [p.rank for p in pieces]
            assert ranks[0] == "remnant" and ranks.count("remnant") == 1
            assert set(ranks[1:]) <= {"small"}
            rem = pieces[0]
            assert rem.v_ratio == 0.30
            assert abs(rem.radius_gu - R * 0.30 ** (1.0 / 3.0)) < 1e-9


def test_small_radii_in_range_count_and_volume_capped():
    for name in _MANY[:100] + _NAMES:
        for R in (0.3, 0.6, 1.2, 2.5, 3.0, 5.0, 7.44, 12.0):
            pieces = breakup.plan(name, R)
            rem, small = pieces[0], pieces[1:]
            lo, hi = _small_range(R)
            assert len(small) <= breakup.kSmallMaxCount
            for p in small:
                assert lo - 1e-9 <= p.radius_gu <= hi + 1e-9
                assert p.radius_gu <= rem.radius_gu + 1e-9
            assert sum(p.v_ratio for p in small) <= breakup.kSmallVolumeFrac + 1e-12


def test_big_parent_gives_twelve_small_rocks_and_the_rest_dust():
    """At 7.4 GU twelve 1.5 GU rocks hold only ~0.10 of the volume, so the
    count cap binds and roughly 0.6 of the parent becomes dust."""
    for name in _NAMES:
        pieces = breakup.plan(name, 7.4)
        small = pieces[1:]
        assert len(small) == 12
        took = sum(p.v_ratio for p in small)
        assert took <= 12 * (1.5 / 7.4) ** 3 + 1e-12
        assert 1.0 - 0.30 - took > 0.55              # dust


def test_mid_parent_small_rocks_take_about_half_the_parent():
    """At 3.0 GU a small rock is 0.005-0.125 of the volume. The count cap
    still binds for most names (12 pieces average ~0.53), so the total only
    sometimes approaches the 0.70 budget, and never exceeds it."""
    totals = []
    for name in _MANY[:200]:
        small = breakup.plan(name, 3.0)[1:]
        assert 1 <= len(small) <= 12
        totals.append(sum(p.v_ratio for p in small))
    assert max(totals) <= 0.70 + 1e-12
    assert max(totals) >= 0.65                 # the budget does bind for some
    assert min(totals) >= 0.20
    assert 0.45 <= sum(totals) / len(totals) <= 0.62


def test_tiny_parent_scales_small_range_to_the_remnant():
    """Remnant below kSmallRadiusMinGU: smalls are 0.3-0.9 x its radius."""
    R = 0.6                                   # remnant 0.40 GU
    for name in _NAMES:
        pieces = breakup.plan(name, R)
        rr = pieces[0].radius_gu
        assert rr < breakup.kSmallRadiusMinGU
        assert pieces[1:]
        for p in pieces[1:]:
            assert 0.3 * rr - 1e-9 <= p.radius_gu <= 0.9 * rr + 1e-9


def test_different_names_give_different_splits():
    splits = {tuple(round(p.v_ratio, 9) for p in breakup.plan(n, 6.0))
              for n in _NAMES}
    assert len(splits) == len(_NAMES)


# ── Tiers ────────────────────────────────────────────────────────────────────


def test_remnant_is_a_major_and_smalls_tier_by_radius():
    for name in _NAMES:
        for R in (3.0, 5.0, 7.44):
            pieces = breakup.plan(name, R)
            assert pieces[0].tier == "major"
            for p in pieces[1:]:
                if p.radius_gu >= breakup.kMajorMinRadiusGU:
                    assert p.tier == "major"
                else:
                    assert p.tier in ("chunk", "dust")   # dust only by the cap


def test_small_majors_and_chunks_both_occur():
    tiers = {p.tier for n in _NAMES for p in breakup.plan(n, 7.44)[1:]}
    assert {"major", "chunk"} <= tiers


def test_major_floor_and_dust_floor_still_apply():
    for name in _NAMES:
        for r in (0.1, 0.3, 1.2, 2.5):
            for p in breakup.plan(name, r):
                if p.radius_gu < breakup.kChunkMinRadiusGU:
                    assert p.tier == "dust"
                elif p.radius_gu < breakup.kMajorMinRadiusGU:
                    assert p.tier in ("chunk", "dust")
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
    """Generation 1: the remnant + 12 smalls are chunk candidates, cut to the
    8 largest -- the remnant, being largest, is always kept."""
    for name in _NAMES:
        pieces = breakup.plan(name, 6.0, generation=1)
        assert pieces[0].tier == "chunk"
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
# Majors on random directions nearly always held one near-parallel pair
# overlapping past kGhostMaxTime, which then ground (scenario A). Every major
# (the remnant and each small rock >= 1 GU) takes a spread direction, and they
# fly apart at 0.8 GU/s.


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
                    assert gap >= need, (name, R, a.radius_gu, b.radius_gu, gap, need)
