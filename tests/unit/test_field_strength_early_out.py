"""field_strength_at skips position work when the viewed set has no field."""
import pytest

from engine.rocks import density, far_dials, far_tier
from engine.systems import frames


@pytest.fixture(autouse=True)
def _clean():
    far_dials.reset()
    far_tier.reset()
    yield
    far_dials.reset()
    far_tier.reset()


class _Loc:
    x, y, z = 10.0, 0.0, 0.0


class _Player:
    def __init__(self):
        self.calls = 0

    def GetWorldLocation(self):
        self.calls += 1
        return _Loc()


def _sphere(radius=1000.0, edge=0.2):
    return density.DiscSource(
        id=1, frame="Beol4", centre_gu=(0.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0),
        table=[], outer_fade_gu=0.0, scale_height_frac=0.0,
        scale_height_min_gu=0.0, families={"silicate": 1.0}, seed=1,
        shape="sphere", procedural=False, view_space=True,
        sphere_radius_gu=radius, sphere_edge_frac=edge)


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(frames, "viewing_set", lambda: "view")
    monkeypatch.setattr(frames, "containing_set", lambda p: "view")
    return monkeypatch


def test_no_tiles_no_belt_returns_zero_without_position_work(world):
    far_tier._tiles = []
    world.setattr(far_tier, "frame_for", lambda v: ("Sys", (0.0, 0.0, 0.0)))
    world.setattr(density, "sources_for_system", lambda s: [])
    p = _Player()
    assert far_tier.field_strength_at(p) == 0.0
    assert p.calls == 0


def test_unset_tiles_one_set_frame_returns_zero_without_position_work(world):
    far_tier._tiles = far_tier._UNSET
    world.setattr(far_tier, "frame_for", lambda v: (None, (0.0, 0.0, 0.0)))
    p = _Player()
    assert far_tier.field_strength_at(p) == 0.0
    assert p.calls == 0


def test_belt_present_still_computes(world):
    far_tier._tiles = []
    src = _sphere()
    world.setattr(far_tier, "frame_for", lambda v: ("Sys", (0.0, 0.0, 0.0)))
    world.setattr(density, "sources_for_system", lambda s: [src])
    p = _Player()
    expected = far_tier.source_strength(src, (10.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    assert expected == 1.0
    assert far_tier.field_strength_at(p) == expected
    assert p.calls == 1


def test_tiles_present_still_computes(world):
    far_tier._tiles = [_sphere()]
    world.setattr(far_tier, "frame_for", lambda v: (None, (0.0, 0.0, 0.0)))
    p = _Player()
    assert far_tier.field_strength_at(p) == 1.0
    assert p.calls == 1
