"""Host smoke test (Task 11 of the rock-catalogue plan): a real catalogue rock,
loaded through the C++ host at the stock asteroid's bounding radius, comes back
with an AABB in the right ballpark. This is the end-to-end check that the
committed catalogue, engine/rocks/catalogue.py's scale math, and the glTF
loader (native/src/assets/src/gltf_load.cc) agree with each other.
"""
import os
from pathlib import Path

import pytest


@pytest.fixture
def host():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    try:
        _dauntless_host.init(64, 64, "rock-catalogue-tests")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        yield _dauntless_host
    finally:
        _dauntless_host.shutdown()


def test_catalogue_rock_loads_at_stock_size(host):
    from engine.rocks import catalogue as rc

    rock = rc.pick("Unknown Debris 4")
    assert rock is not None
    s = rc.load_scale(rock, "asteroid1.nif")
    handle = host.load_model(
        rock.lod_paths[0], [str(Path(rock.lod_paths[0]).parent)], None, None, s)
    (_c, half) = host.model_aabb(handle)
    assert max(half) <= rc.STOCK_RADIUS_MU["asteroid1.nif"] * 1.001
    assert max(half) >= rc.STOCK_RADIUS_MU["asteroid1.nif"] * 0.5


@pytest.mark.parametrize("stock", sorted(["asteroid.nif", "asteroid1.nif",
                                          "asteroid2.nif", "asteroid3.nif"]))
def test_prebake_target_matches_the_loaded_model_source(host, stock):
    """The boot pre-bake's rock target string is the SAME string the loaded
    model's Model::source carries -- the .dhv cache key. Built by C++'s
    assets::hull_source_string (float32 %.6g), never Python formatting."""
    from engine.appc import hull_volume
    from engine.rocks import catalogue as rc

    rock = rc.pick("Unknown Debris 4")
    s = rc.load_scale(rock, stock)
    targets = hull_volume.rock_bake_targets(stock, 10.0)
    handle = host.load_model(
        rock.lod_paths[0], [str(Path(rock.lod_paths[0]).parent)], None, None, s)
    source = host.model_source(handle)
    assert "#s=" in source
    assert (source, 10.0) in targets
    assert host.hull_source_string(rock.lod_paths[0], s) == source


def test_tiny_distinct_scales_get_distinct_handles(host):
    """load_model's dedupe key must format the scale like Model::source
    (%.6g), not std::to_string (%f), which collapses 1e-7 and 2e-7 onto
    "0.000000" and hands the second load the first one's model."""
    from engine.rocks import catalogue as rc

    rock = rc.pick("Unknown Debris 4")
    search = [str(Path(rock.lod_paths[0]).parent)]
    h1 = host.load_model(rock.lod_paths[0], search, None, None, 1e-7)
    h2 = host.load_model(rock.lod_paths[0], search, None, None, 2e-7)
    assert h1 != h2
    assert host.model_source(h1) != host.model_source(h2)
