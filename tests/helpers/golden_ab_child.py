"""One side of a golden A/B run (tools/golden_ab_side.py starts it with pytest
inside a source tree). Skips unless GOLDEN_AB_OUT is set.

Imports nothing from tests/helpers except golden_fight and bc_assets, so it
runs in an older base tree. GOLDEN_AB_LIST=1 writes the scene names as JSON;
otherwise GOLDEN_AB_SCENE is run and its rows written as one zlib'd JSON
array, a row at a time."""
import json
import os
import tempfile
import zlib

import pytest


def _write_rows(path, rows):
    z = zlib.compressobj()
    with open(path, "wb") as f:
        f.write(z.compress(b"["))
        for i, row in enumerate(rows):
            if i:
                f.write(z.compress(b","))
            f.write(z.compress(json.dumps(
                row, sort_keys=True, separators=(",", ":")).encode()))
        f.write(z.compress(b"]"))
        f.write(z.flush())


def test_child():
    out = os.environ.get("GOLDEN_AB_OUT")
    if not out:
        pytest.skip("only runs as a golden A/B child")
    from tests.helpers import bc_assets, golden_fight
    if os.environ.get("GOLDEN_AB_LIST"):
        with open(out, "w") as f:
            json.dump(sorted(golden_fight.SCENES), f)
        return
    bc_assets.require_game_dir("data/Models/Ships/BirdOfPrey")
    os.environ["DAUNTLESS_MODS_DIR"] = tempfile.mkdtemp(prefix="golden_ab_no_mods")
    rows = golden_fight.run_scene(os.environ["GOLDEN_AB_SCENE"], "native")
    _write_rows(out, rows)
