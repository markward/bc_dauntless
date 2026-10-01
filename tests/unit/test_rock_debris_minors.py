"""Breakup debris becomes a free minor cloud (minor-rocks spec §4): the pure
side -- breakup.plan has no per-death chunk cap, and death.debris_specs turns
a plan's chunk pieces plus seeded gravel into the free cloud's debris list.
The death -> register_free_cloud wiring is in test_rock_death.py; the
registry's halo detach is in test_minor_registry.py."""
import math
import zlib

import pytest

from engine.rocks import breakup, death
from engine.rocks import minor_dials as md


@pytest.fixture(autouse=True)
def _dials():
    md.reset()
    yield
    md.reset()


def test_plan_has_no_per_death_chunk_cap():
    assert not hasattr(breakup, "kMaxChunksPerDeath")
    pieces = breakup.plan("Asteroid 9", 7.44, generation=1)   # every major demoted
    assert sum(1 for p in pieces if p.tier == "chunk") > 8


def test_debris_specs_follow_rules_and_cap():
    pieces = breakup.plan("Asteroid 9", 7.44)
    at = [(0.1 * i, 0.0, 0.0) for i in range(len(pieces))]
    out = death.debris_specs("Asteroid 9", pieces, at,
                             loc=(0.0, 0.0, 0.0), parent_v=(0.0, 0.0, 0.0),
                             vels=[(0.8, 0.0, 0.0)] * len(pieces), R=7.44)
    assert 0 < len(out) <= md.get("max_debris_per_death")
    radii = [d["radius"] for d in out]
    assert radii == sorted(radii, reverse=True)
    assert all(set(d) == {"offset", "v0", "radius", "seed"} for d in out)
    again = death.debris_specs("Asteroid 9", pieces, at, (0.0, 0.0, 0.0),
                               (0.0, 0.0, 0.0), [(0.8, 0.0, 0.0)] * len(pieces), 7.44)
    assert out == again                                  # deterministic


def test_chunk_pieces_carry_offset_v0_radius_and_seed_relative_to_the_parent(
        monkeypatch):
    """Only tier "chunk" pieces join, each relative to the parent's centre
    and velocity, seeded by plan index. Gravel off isolates them."""
    monkeypatch.setitem(md._dials, "debris_gravel_per_gu", 0.0)
    pieces = [
        breakup.PieceSpec(2.0, (1.0, 0.0, 0.0), 0.3, "major", "remnant"),
        breakup.PieceSpec(0.6, (0.0, 1.0, 0.0), 0.01, "chunk", "small"),
        breakup.PieceSpec(0.05, (0.0, 0.0, 1.0), 0.0, "dust", "small"),
        breakup.PieceSpec(0.4, (0.0, 0.0, 1.0), 0.01, "chunk", "small"),
    ]
    at = [(10.0, 0.0, 0.0), (11.0, 2.0, 3.0), (0.0, 0.0, 0.0), (12.0, 0.0, 4.0)]
    vels = [(0.0, 0.0, 0.0), (5.0, 1.0, 0.0), (0.0, 0.0, 0.0), (5.0, 0.0, -1.0)]
    out = death.debris_specs("Rock", pieces, at, (10.0, 0.0, 0.0),
                             (5.0, 0.0, 0.0), vels, 4.0)
    assert out == (
        {"offset": (1.0, 2.0, 3.0), "v0": (0.0, 1.0, 0.0), "radius": 0.6,
         "seed": zlib.crc32(b"Rock#1")},
        {"offset": (2.0, 0.0, 4.0), "v0": (0.0, 0.0, -1.0), "radius": 0.4,
         "seed": zlib.crc32(b"Rock#3")},
    )


def test_gravel_count_ranges_and_seeds():
    """No plan pieces: the debris is all gravel -- round(per_gu x R) pieces,
    radius in the gravel range, offset within half the parent radius, speed
    0.5-1.0 x kSeparationSpeedGU, seeded "<name>#g<j>"."""
    R = 3.2
    out = death.debris_specs("Rock", [], [], (0.0, 0.0, 0.0), (0.0, 0.0, 0.0),
                             [], R)
    n = round(md.get("debris_gravel_per_gu") * R)
    assert len(out) == n == 13
    lo, hi = md.get("debris_gravel_r_min_gu"), md.get("debris_gravel_r_max_gu")
    sp = breakup.kSeparationSpeedGU
    for d in out:
        assert lo <= d["radius"] <= hi
        assert math.hypot(*d["offset"]) <= R * 0.5 + 1e-9
        assert 0.5 * sp - 1e-9 <= math.hypot(*d["v0"]) <= sp + 1e-9
    assert sorted(d["seed"] for d in out) == sorted(
        zlib.crc32(("Rock#g%d" % j).encode("utf-8")) for j in range(n))


def test_total_is_capped_keeping_the_largest(monkeypatch):
    monkeypatch.setitem(md._dials, "max_debris_per_death", 5)
    pieces = [breakup.PieceSpec(0.5 + 0.01 * i, (1.0, 0.0, 0.0), 0.0,
                                "chunk", "small") for i in range(3)]
    at = [(0.0, 0.0, 0.0)] * 3
    out = death.debris_specs("Rock", pieces, at, (0.0, 0.0, 0.0),
                             (0.0, 0.0, 0.0), [(0.0, 0.0, 0.0)] * 3, 4.0)
    assert len(out) == 5
    # The three chunks (>= 0.5 GU) outrank every gravel piece (<= 0.3 GU).
    assert [d["radius"] for d in out[:3]] == [0.52, 0.51, 0.5]


def test_host_frame_pumps_rock_vfx_after_collisions_and_no_chunks():
    """Kept from the retired test_rock_chunks.py: the frame loop drains the
    death-VFX queue right after collisions, so a rock killed by a collision
    this frame bursts this frame. Its debris no longer goes through the host
    loop at all (a free minor cloud), so nothing pumps rock chunks."""
    import inspect
    from engine import host_loop
    src = inspect.getsource(host_loop)
    at = src.index('frame_profiler.scope("sim.collisions")')
    scope = src.index('frame_profiler.scope("sim.rock_breakup")', at)
    assert src.index("rock_vfx.pump()", scope) - at < 800
    assert "rock_chunks" not in src
