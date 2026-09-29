from pathlib import Path

import pytest

from engine import paths
from tools import gen_mesh_fixes as g

FIX_DIR = Path(__file__).resolve().parents[2] / "native" / "assets" / "mesh_fixes"


def test_committed_fixes_match_generator_output():
    host = pytest.importorskip("_dauntless_host")
    produced = {}
    for rel in g.STOCK_MESHES:
        # Ruling 5: fixes are stock-only, so resolve the raw stock root
        # (paths.game_root()), never paths.game_asset(rel) -- that prefers a
        # mod override, which would drift the hash against the committed fix.
        nif = paths.game_root() / rel
        if not nif.exists():
            pytest.skip("BC content not configured")
        data = nif.read_bytes()
        fix, _ = g.build_fix(host.nif_shapes(str(nif)), rel,
                             g.TARGET_OVERRIDES.get(rel),
                             g.UV_CLAMP_OVERRIDES.get(rel))
        produced[g.fnv1a64_hex(data) + ".json"] = g.dumps(fix)
    committed = {p.name: p.read_text() for p in FIX_DIR.glob("*.json")}
    assert committed == produced
