import math

from tools.bake_sector_model import build_sector_model, hex_to_rgb01


def test_hex_to_rgb01():
    assert hex_to_rgb01("#646392") == [0x64 / 255, 0x63 / 255, 0x92 / 255]


def _dist(a, b):
    return math.sqrt(sum((a[k] - b[k]) ** 2 for k in range(3)))


def test_home_hazard_nebula_extends_to_envelop_its_system():
    # The Vesuvi situation: the system anchor sits just OUTSIDE its own hazard
    # nebula (dist 30 > radius 29.5), so the procedural sky would never envelop
    # there. The bake must extend a `{system}-haz{n}` nebula's radius so its
    # owning system falls comfortably inside it.
    map_data = {
        "systems": [{"id": "vesuvi", "position": [200.75, 91.62, -10.89], "name": "Vesuvi"}],
        "nebulae": [{"id": "vesuvi-haz0", "position": [200.75, 121.62, -10.89],
                     "radius": 29.5, "color": "#9b5ab9", "type": "hazard"}],
    }
    neb = build_sector_model(map_data)["nebulae"][0]
    dist = _dist(neb["position"], [200.75, 91.62, -10.89])
    assert neb["radius"] > dist, (
        "home system must sit inside its own hazard nebula (radius %.2f vs dist %.2f)"
        % (neb["radius"], dist))


def test_hazard_nebula_already_containing_system_is_unchanged():
    # belaruz-style: the system is already well inside; the bake must not shrink
    # or needlessly inflate it.
    map_data = {
        "systems": [{"id": "belaruz", "position": [123.49, 50.83, -10.23], "name": "Belaruz"}],
        "nebulae": [{"id": "belaruz-haz0", "position": [123.15, 67.72, -10.84],
                     "radius": 26.0, "color": "#646392", "type": "hazard"}],
    }
    neb = build_sector_model(map_data)["nebulae"][0]
    assert neb["radius"] == 26.0


def test_unowned_nebula_radius_untouched():
    # A nebula whose id has no `-haz` owner (or whose owner system is absent)
    # keeps its baked radius.
    map_data = {
        "systems": [],
        "nebulae": [{"id": "treknebula6.tga", "position": [0, 0, 0], "radius": 24.0,
                     "color": "#646392"}],
    }
    assert build_sector_model(map_data)["nebulae"][0]["radius"] == 24.0


def test_build_sector_model_shapes():
    map_data = {
        "systems": [{"id": "vesuvi", "position": [1.0, 2.0, 3.0], "name": "Vesuvi"}],
        "nebulae": [{"position": [4.0, 5.0, 6.0], "radius": 26.0, "color": "#646392",
                     "type": "ambient", "name": "x"}],
        "galaxies": [{"position": [7.0, 8.0, 9.0], "size": 91.9,
                      "appearance": {"swatch": {"meanColor": [89, 74, 82]}}}],
    }
    out = build_sector_model(map_data)
    # build_sector_model back-fills `warp_points` for any system id found in the
    # on-disk baked sector_model.json, so assert the core mapping (id/position)
    # rather than exact dict equality — the optional enrichment key depends on
    # the baked catalog and must not break this unit test.
    assert len(out["systems"]) == 1
    assert out["systems"][0]["id"] == "vesuvi"
    assert out["systems"][0]["position"] == [1.0, 2.0, 3.0]
    neb = out["nebulae"][0]
    assert neb["position"] == [4.0, 5.0, 6.0] and neb["radius"] == 26.0
    assert neb["color"] == [0x64 / 255, 0x63 / 255, 0x92 / 255]
    sc = out["starclouds"][0]
    assert sc["position"] == [7.0, 8.0, 9.0] and sc["size"] == 91.9
    assert sc["color"] == [89 / 255, 74 / 255, 82 / 255]


def test_galaxy_missing_swatch_uses_default():
    out = build_sector_model({"galaxies": [{"position": [0, 0, 0], "size": 1.0, "appearance": {}}]})
    assert out["starclouds"][0]["color"] == [120 / 255, 120 / 255, 140 / 255]
