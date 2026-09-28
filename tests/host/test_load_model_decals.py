"""Hull-name decals through the real _dauntless_host.load_model binding.

Task 4 (host binding accepts decals): the dedupe key folds the decal list
in, so two registries on the same NIF produce distinct handles, the same
registry+decals repeats the first handle, and decals=None still works
(byte-identical to the pre-decal call). A malformed decal entry must not
throw out of load_model (spec S5) -- it's skipped with a single stderr
warning instead.
"""
import os

import pytest

from tests.helpers import bc_assets
from engine.appc import hull_decals

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


def test_load_model_decals_distinct_and_dedupe():
    _skip_unless_assets_available()
    zhukov = hull_decals.decals_for("data/Models/Ships/Ambassador", "Zhukov")
    excalibur = hull_decals.decals_for("data/Models/Ships/Ambassador", "Excalibur")
    assert zhukov, "expected the committed Zhukov 'top' decal to resolve"
    assert excalibur, "expected the committed Excalibur 'top' decal to resolve"

    host = _init_host("decal-test")
    try:
        h_zhukov = host.load_model(str(AMBASSADOR_NIF), str(AMBASSADOR_TEX), None, zhukov)
        h_excalibur = host.load_model(str(AMBASSADOR_NIF), str(AMBASSADOR_TEX), None, excalibur)
        assert h_zhukov != h_excalibur, "different registries must not share a handle"

        h_zhukov_again = host.load_model(str(AMBASSADOR_NIF), str(AMBASSADOR_TEX), None, zhukov)
        assert h_zhukov_again == h_zhukov, "same decals must dedupe to the first handle"

        h_none = host.load_model(str(AMBASSADOR_NIF), str(AMBASSADOR_TEX), None, None)
        assert h_none not in (h_zhukov, h_excalibur), (
            "decals=None must be a distinct variant from either registry")
    finally:
        host.shutdown()


def test_load_model_decals_malformed_entry_does_not_throw(capfd):
    _skip_unless_assets_available()
    host = _init_host("decal-malformed-test")
    try:
        # Wrong arity (missing the mask path) and a non-numeric vector --
        # both must be skipped, not raise, and each warns exactly once.
        bad_decals = [
            ("amb saucer:0", (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
             (0.0, 0.0, 1.0), 1.0),  # missing mask path: arity 6, not 7
            ("amb saucer:0", ("not", "a", "vector"), (1.0, 0.0, 0.0),
             (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), 1.0, "/nonexistent/mask.png"),
        ]
        handle = host.load_model(
            str(AMBASSADOR_NIF), str(AMBASSADOR_TEX), None, bad_decals)
        assert handle > 0
    finally:
        host.shutdown()
    captured = capfd.readouterr()
    assert "load_model" in captured.err
    assert captured.err.count("malformed decal") == 2
