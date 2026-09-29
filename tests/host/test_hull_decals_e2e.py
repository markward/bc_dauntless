"""End-to-end: Federation registry swap -> hull-name decal -> load_model.

Drives the real path a mission uses: `registry_texture.apply_class_default`
queues the Ambassador's default "Zhukov" registry the way MissionLib's
ship-change / QuickBattle setup does, `hull_decals.registry_stem` +
`hull_decals.decals_for` resolve the committed `Masks/decals.json` (Task 1-3),
and `renderer.load_model` (Task 4's binding) bakes the result into a distinct
model variant (Task 5 draws it in opaque.frag, not exercised headlessly here).

Host fixture mirrors tests/host/test_load_model_decals.py (Task 4): headless
GL init/shutdown around the binding calls, skip without a configured BC
content root.
"""
import os

import pytest

from tests.helpers import bc_assets
from engine.appc import hull_decals, registry_texture
from engine.appc.objects import ObjectClass
import engine.renderer as renderer

GAME_DATA = bc_assets.GAME_ROOT / "data"
AMBASSADOR_NIF = GAME_DATA / "Models" / "Ships" / "Ambassador" / "Ambassador.nif"
AMBASSADOR_TEX = GAME_DATA / "Models" / "Ships" / "Ambassador" / "High"


def _skip_unless_assets_available():
    if not AMBASSADOR_NIF.is_file():
        pytest.skip(f"BC asset not available at {AMBASSADOR_NIF}")
    if not AMBASSADOR_TEX.is_dir():
        pytest.skip(f"BC texture dir not available at {AMBASSADOR_TEX}")


def _init_host(label):
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    try:
        _dauntless_host.init(640, 480, label)
    except RuntimeError as e:
        pytest.skip(f"no GL context available: {e}")
    return _dauntless_host


@pytest.fixture(autouse=True)
def _clean():
    registry_texture.reset()
    hull_decals.reset()
    yield
    registry_texture.reset()
    hull_decals.reset()


def test_ambassador_zhukov_registry_resolves_and_loads_distinct_handle():
    _skip_unless_assets_available()

    # Queue the default Federation registry the way a mission does.
    ship = ObjectClass()
    ship.SetScript("ships.Ambassador")
    assert registry_texture.apply_class_default(ship) is True

    reps = registry_texture.replacements_for(ship)
    stem = hull_decals.registry_stem(reps)
    assert stem == "Zhukov"

    decals = hull_decals.decals_for("data/Models/Ships/Ambassador", stem)
    # Mark's uncommitted live saves may have added more placements
    # (`bottom`, `pylon`) on top of the committed `top` -- assert `top` is
    # present and correct, not an exact count (spec Review Focus 5).
    top = [d for d in decals
           if d[6].replace("\\", "/").lower().endswith("masks/zhukov/top.png")]
    assert len(top) == 1
    shape, origin, u_axis, v_axis, normal, depth, mask_path = top[0]
    assert shape == "amb saucer:0"

    host = _init_host("decal-e2e-test")
    try:
        h_registry = host.load_model(
            str(AMBASSADOR_NIF), str(AMBASSADOR_TEX), reps, decals)
        h_plain = host.load_model(
            str(AMBASSADOR_NIF), str(AMBASSADOR_TEX), None, None)
        assert h_registry != h_plain, (
            "a registry+decal load must not dedupe with a plain no-registry load")
    finally:
        host.shutdown()
