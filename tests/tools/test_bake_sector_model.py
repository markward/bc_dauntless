from tools.bake_sector_model import build_sector_model, hex_to_rgb01


def test_hex_to_rgb01():
    assert hex_to_rgb01("#646392") == [0x64 / 255, 0x63 / 255, 0x92 / 255]


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
