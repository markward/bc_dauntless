"""Rock promotion, headless end-to-end against the REAL native field
(rock-promotion plan Task 7, spec 2026-10-05 Sec 2-3). Unlike
tests/unit/test_rock_promotion.py (FakeR), this drives engine.rocks.promotion
against the actual _dauntless_host near field -- the real near catalogue, a
real NearField sourced from a full-density sphere, and the real renderer
facade -- so promotion's generator-rock match, native exclusion push, and
demotion all cross the real binding boundary at least once.
"""
import os

import App
import pytest

h = pytest.importorskip("_dauntless_host")

from engine import renderer  # noqa: E402
from engine.appc.ships import ShipClass_Create  # noqa: E402
from engine.rocks import death, far_dials, far_tier, promotion  # noqa: E402
from engine.rocks.rock import effective_radius  # noqa: E402
from tests.helpers.viewed_set import release_viewed_set, viewed_set  # noqa: E402


_SYSTEM = "E2E"  # arbitrary; must match the frame name pushed below


def _sphere_source(radius=1500.0):
    """One full-density SYSTEM-space sphere around the origin, no noise. A
    non-view-space source is kept only when its "frame" matches the system
    name far_set_frame was pushed with (FarField::refresh_active) -- unlike
    tests/host/test_rock_near_host.py, which anchors a VIEW-space sphere
    instead and never names a system.

    Deliberately bounded (not the brief's suggested 10,000 GU): with
    sphere_edge_frac 0.0 the field is uniformly full-density out to `radius`
    and exactly zero beyond it, so a player 2,000 GU from the centre (query
    radius promote_range_gu=300) sees nothing left at all once `radius` <=
    2,000 - 300. An unbounded full-density field is homogeneous everywhere,
    so "moved away -> nothing promoted" (step 5) could never hold -- moving
    would just promote a fresh batch of equally-dense rocks nearby."""
    return {
        "id": 1, "frame": _SYSTEM, "centre": (0.0, 0.0, 0.0), "normal": (0.0, 0.0, 1.0),
        "table": [], "outer_fade_gu": 0.0, "scale_height_frac": 0.03,
        "scale_height_min_gu": 1000.0, "seed": 5, "explicit_regions": [],
        "populations": [], "shape": "sphere", "procedural": False,
        "view_space": False, "sphere_radius_gu": radius, "sphere_edge_frac": 0.0}


def _set_camera_at_origin():
    h.set_camera(eye=(0.0, 0.0, 0.0), target=(0.0, 0.0, -1.0),
                 up=(0.0, 1.0, 0.0), fov_y_rad=1.0472, near=0.1, far=1.0e7)


def _stream_at_origin():
    """Push the real near catalogue + a full-density sphere source, exactly
    as tests/host/test_rock_near_host.py does, then stream one frame so the
    native near field actually holds cells around the origin."""
    far_tier.reset()
    far_tier._push_catalogue(renderer)
    h.far_set_enabled(True)
    h.far_set_dials({})
    h.far_set_sources([_sphere_source()])
    h.far_set_frame(_SYSTEM, (0.0, 0.0, 0.0))
    _set_camera_at_origin()
    h.frame()


@pytest.fixture
def host():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        h.init(64, 64, "test_rock_promotion_e2e")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        yield h
    finally:
        h.far_clear()
        h.far_set_dials({})
        h.far_set_enabled(True)
        h.rockfield_set_player(None)
        promotion.reset(renderer)
        far_dials.reset()
        far_tier.reset()
        h.shutdown()


@pytest.fixture
def world(host):
    """A viewed set holding the player at the origin, anchor (0, 0, 0), with
    the real near field already streamed around it."""
    App.g_kSetManager._sets.clear()
    far_dials.reset()
    pset = viewed_set()
    player = ShipClass_Create("Player")
    player.SetTranslateXYZ(0.0, 0.0, 0.0)
    pset.AddObjectToSet(player, "Player")
    promotion.reset(renderer)
    _stream_at_origin()
    yield pset, player
    promotion.reset(renderer)
    far_dials.reset()
    release_viewed_set()
    App.g_kSetManager._sets.clear()


def _move_player(player, x):
    player.SetTranslateXYZ(x, 0.0, 0.0)


def test_flying_through_a_full_density_field_promotes_targets_destroys_and_demotes(
        world, monkeypatch):
    pset, player = world
    pushed = []
    real_set_promoted = renderer.rockfield_set_promoted

    def spy_set_promoted(keys):
        keys = list(keys)
        pushed.append(keys)
        real_set_promoted(keys)

    monkeypatch.setattr(renderer, "rockfield_set_promoted", spy_set_promoted)

    # 1 + 2: a full-density field is already streamed by the `world` fixture.
    # 3: promote at t=0 and check every promoted rock against the native
    # query for its own key.
    promotion.tick(player, pset, 0.0, renderer)
    promoted = promotion.promoted()
    assert 1 <= len(promoted) <= far_dials.get("promote_max")

    range_gu = far_dials.get("promote_range_gu")
    min_r = far_dials.get("promote_min_radius_gu")
    hits = {hit["key"]: hit for hit in
            renderer.rockfield_query_large((0.0, 0.0, 0.0), range_gu, min_r)}
    for key, rock in promoted.items():
        assert rock.GetName() == promotion.field_name(key)
        assert not rock.GetName().startswith("Asteroid")
        radius = effective_radius(rock)
        assert radius >= far_dials.get("promote_min_radius_gu")
        hit = hits[key]
        loc = rock.GetWorldLocation()
        assert (loc.x, loc.y, loc.z) == pytest.approx(hit["pos"])
        assert radius == pytest.approx(hit["radius"])
    assert pushed[-1] == sorted(promoted)

    # 4: target one, kill it, let death retire it, then tick again.
    target_key, target_rock = next(iter(promoted.items()))
    player.SetTarget(target_rock.GetName())
    assert player.GetTarget() is target_rock
    death.begin(target_rock, killer=None)
    death.advance(1.0)                          # past kRockDeathLife (0.5s)
    assert target_rock.GetContainingSet() is None
    promotion.tick(player, pset, 1.0, renderer)
    assert target_key not in promotion.promoted()
    still_in_field = any(
        hit["key"] == target_key for hit in
        renderer.rockfield_query_large((0.0, 0.0, 0.0), range_gu, min_r))
    assert still_in_field, "the native field itself does not track Python death"
    assert target_key in pushed[-1], "a destroyed key must stay excluded"

    # 5: fly 2000 GU away -- every promoted rock demotes back to scenery.
    # (the dead rock's own breakup pieces are still in `pset`, named "Field
    # Rock .... - Remnant" / "-N" -- check the exact demoted names, not a
    # startswith, so they are not mistaken for a leaked promoted object.)
    before_move = promotion.promoted()
    _move_player(player, 2000.0)
    promotion.tick(player, pset, 2.0, renderer)
    assert promotion.promoted() == {}
    for key in before_move:
        assert pset.GetObject(promotion.field_name(key)) is None

    # Fly back: the destroyed key never regrows, even though it is still in
    # range and still in the native field.
    _move_player(player, 0.0)
    promotion.tick(player, pset, 3.0, renderer)
    assert target_key not in promotion.promoted()
