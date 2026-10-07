"""Binding-level test for _dauntless_host.load_model's `geosphere` flag
(Task 3 of the planet-geosphere plan): `geosphere` is folded into the
model's dedupe identity, just like `scale`/texture_replacements/decals, and
passed through to assets::AssetCache::load so a qualifying planet NIF gets
its Model::sphere_map populated without disturbing the plain-load handle.
"""
import os

import pytest

from engine import paths
from tests.helpers import bc_assets


@pytest.fixture
def r():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    from engine import renderer
    try:
        renderer.init(64, 64, "load-model-geosphere-tests")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        yield renderer
    finally:
        renderer.shutdown()


def test_geosphere_load_is_a_distinct_cached_handle(r):
    nif = bc_assets.require_game_asset("data/Models/Environment/IcePlanet.NIF")
    search = [str(p) for p in paths.game_asset_dirs("data/Models/Environment")]

    plain = r.load_model(str(nif), search)
    geo = r.load_model(str(nif), search, geosphere=True)
    assert plain != geo
    assert r.load_model(str(nif), search, geosphere=True) == geo
    assert r.load_model(str(nif), search) == plain

    # Same bounds: BC's own mesh is kept in the variant, apply_geosphere only
    # adds Model::sphere_map alongside it -- compute_model_aabb walks
    # model.meshes/cpu_data, which apply_geosphere never touches.
    geo_center, geo_half = r.model_aabb(geo)
    plain_center, plain_half = r.model_aabb(plain)
    assert geo_center == pytest.approx(plain_center)
    assert geo_half == pytest.approx(plain_half)
