"""STOCK_RADIUS_MU matches the real stock NIFs (asset-backed; BC content via engine.paths)."""
import math

import pytest

from engine.rocks import catalogue as rc

h = pytest.importorskip("_dauntless_host")


def _max_vertex_radius(shapes) -> float:
    max_r = 0.0
    for shape in shapes:
        for v in shape["vertices"]:
            r = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
            if r > max_r:
                max_r = r
    return max_r


@pytest.mark.parametrize("name", ["asteroid", "asteroid1", "asteroid2", "asteroid3"])
def test_stock_radius_matches_nif(name):
    from engine import paths
    p = paths.game_asset(f"data/Models/Misc/Asteroids/{name}.NIF")
    assert p.is_file(), f"BC content not configured: {p}"
    radius = _max_vertex_radius(h.nif_shapes(str(p)))
    assert abs(radius - rc.STOCK_RADIUS_MU[f"{name}.nif"]) < 0.01 * radius
