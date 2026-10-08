import json
import zlib

import pytest

from engine.planets import atmosphere as atmo
from engine.planets import surface as surf


@pytest.fixture
def catalogue(tmp_path, monkeypatch):
    path = tmp_path / "atmospheres.json"

    def write(obj):
        path.write_text(json.dumps(obj))
        atmo.reload()
    monkeypatch.setattr(atmo, "catalogue_path", lambda: path)
    yield write
    atmo.reload()


def test_each_type_parses(catalogue):
    for t in ("rocky", "desert", "ice", "gas", "ocean"):
        catalogue({"x": {"atmosphere": False, "surface": {"type": t}}})
        s = surf.resolve_surface("S", "N", "data/x.nif")
        assert s is not None and s.type == t


def test_type_none_is_no_detail(catalogue):
    catalogue({"x": {"atmosphere": False, "surface": {"type": "none"}}})
    assert surf.resolve_surface("S", "N", "x.NIF") is None


def test_airless_entry_keeps_surface(catalogue):
    catalogue({"moon": {"atmosphere": False, "surface": {"type": "rocky"}}})
    assert atmo.resolve("S", "Moon 1", "data/moon.nif") is None
    assert surf.resolve_surface("S", "Moon 1", "data/moon.nif").type == "rocky"


def test_unknown_surface_field_rejected_but_atmosphere_survives(catalogue, capsys):
    catalogue({"p": {"color": "#87B4FF", "thickness": 0.035, "density": 1.0, "limb": 1.0,
                     "surface": {"type": "rocky", "bogus": 1}}})
    assert surf.resolve_surface("S", "N", "p.nif") is None
    assert atmo.resolve("S", "N", "p.nif") is not None
    assert "bogus" in capsys.readouterr().err


def test_bad_type_rejected(catalogue):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "lava"}}})
    assert surf.resolve_surface("S", "N", "p.nif") is None


@pytest.mark.parametrize("field,value", [("ocean_tolerance", 0.0), ("ocean_tolerance", 1.5),
                                         ("strength", -0.1), ("strength", 4.1),
                                         ("albedo", 5.0), ("scale", 0.2), ("scale", 4.5)])
def test_ranges_enforced(catalogue, field, value):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "rocky", field: value}}})
    assert surf.resolve_surface("S", "N", "p.nif") is None


def test_malformed_warns_once(catalogue, capsys):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "lava"}}})
    surf.resolve_surface("S", "N", "p.nif")
    surf.resolve_surface("S", "N", "p.nif")
    assert capsys.readouterr().err.count("lava") == 1


def test_ocean_hex_to_linear(catalogue):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "rocky", "ocean": "#FF0000"}}})
    s = surf.resolve_surface("S", "N", "p.nif")
    assert s.ocean == pytest.approx((1.0, 0.0, 0.0))


def test_override_without_surface_inherits_stem(catalogue):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "ice"}},
               "Vesuvi6/Haven": {"color": "#87B4FF", "thickness": 0.02, "density": 1.0, "limb": 1.0}})
    assert surf.resolve_surface_key("Vesuvi6", "Haven", "p.nif") == "p"
    assert surf.resolve_surface("Vesuvi6", "Haven", "p.nif").type == "ice"


def test_override_with_surface_wins(catalogue):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "ice"}},
               "Vesuvi6/Haven": {"atmosphere": False, "surface": {"type": "desert"}}})
    assert surf.resolve_surface("Vesuvi6", "Haven", "p.nif").type == "desert"


def test_surface_only_override_keeps_stem_atmosphere(catalogue):
    # Spec §7: an override with no atmosphere fields inherits the stem's air
    # (the mirror of test_override_without_surface_inherits_stem).
    catalogue({"p": {"color": "#87B4FF", "thickness": 0.035, "density": 1.0, "limb": 1.0,
                     "surface": {"type": "ice"}},
               "Vesuvi6/Haven": {"surface": {"type": "desert"}}})
    assert atmo.resolve_key("Vesuvi6", "Haven", "p.nif") == "p"
    a = atmo.resolve("Vesuvi6", "Haven", "p.nif")
    assert a is not None and a.thickness == pytest.approx(0.035)
    assert surf.resolve_surface("Vesuvi6", "Haven", "p.nif").type == "desert"


def test_seed_is_crc32_of_key(catalogue):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "rocky"}}})
    assert surf.resolve_surface("S", "N", "p.nif").seed == zlib.crc32(b"p")


def test_to_binding_shapes():
    assert surf.to_binding(None) is None
    s = surf.Surface(type="gas", ocean=None, seed=7)
    assert surf.to_binding(s) == (4, (0.0, 0.0, 0.0), False, 0.15, 1.0, 1.0, 1.0, 7)
    s2 = surf.Surface(type="rocky", ocean=(0.1, 0.2, 0.3), seed=1)
    assert surf.to_binding(s2)[1:3] == ((0.1, 0.2, 0.3), True)


# ---- reload: refreshes the shared memo, spares atmosphere's own dial
# overrides (fix round 1, I1) -------------------------------------------

def test_reload_refreshes_the_shared_catalogue_memo(catalogue):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "rocky"}}})
    assert surf.resolve_surface("S", "N", "p.nif").type == "rocky"

    # Edit the file directly (not through the `catalogue` fixture's own
    # atmo.reload() call) and call surf.reload(): the new type must be
    # picked up, proving surf.reload() refreshes the shared atmosphere file
    # memo (engine.planets.atmosphere.reload_file()), not just its own
    # `_overrides`.
    path = atmo.catalogue_path()
    path.write_text(json.dumps({"p": {"atmosphere": False, "surface": {"type": "ice"}}}))
    surf.reload()
    assert surf.resolve_surface("S", "N", "p.nif").type == "ice"


def test_reload_does_not_clear_the_atmosphere_dial_groups_overrides(catalogue):
    """surf.reload() refreshes the shared file memo via
    atmosphere.reload_file(), which -- unlike the full atmosphere.reload()
    -- never touches `atmosphere._overrides`. The "surface" dial group's
    reload action must not silently undo the "atmosphere" dial group's live
    tuning."""
    catalogue({"p": {"color": "#87B4FF", "thickness": 0.035, "density": 1.0,
                     "limb": 1.0, "surface": {"type": "rocky"}}})
    override = atmo.Atmosphere(color=(1.0, 0.0, 0.0), sunset_color=(1.0, 0.0, 0.0),
                               thickness=0.5, density=2.0, limb=2.0)
    atmo.set_override("p", override)
    surf.reload()
    assert atmo.resolve("S", "N", "p.nif") is override


def test_live_registry_set_scoping():
    surf.clear_live()
    surf.record_live("a", "S1", "P", "p.nif")
    surf.record_live("b", "S2", "P", "p.nif")
    surf.record_live("c", "S1", "Q", "q.nif", source="celestial")
    surf.clear_live_for_set("S1")
    assert [lp.iid for lp in surf.live()] == ["b", "c"]
    surf.forget_live("b")
    assert [lp.iid for lp in surf.live()] == ["c"]
    surf.clear_live()


SEED = {
    "rocky": {"moon", "grayplanet", "rockyplanet", "tanplanet", "redplanet", "brownplanet",
              "greenplanet", "slimegreenplanet", "rootbeerplanet", "aquaplanet",
              "bluegrayplanet", "greenpurpleplanet", "purplewhiteplanet", "earth", "planet",
              "lavenderplanet"},
    "desert": {"sulfurplanet", "dryplanet", "bluetanplanet", "brownblueplanet"},
    "ice": {"snowplanet", "iceplanet"},
    "gas": {"pinkgasplanet", "bluewhitegasplanet", "tangasplanet", "gasgiant", "redswirlplanet"},
    "ocean": {"purpleplanet", "brightgreenplanet", "turquoiseplanet", "bluerockyplanet"},
}
WITH_OCEAN = {"aquaplanet", "bluegrayplanet", "greenpurpleplanet", "purplewhiteplanet", "earth",
              "planet", "dryplanet", "bluetanplanet", "brownblueplanet", "iceplanet"}


def test_shipped_catalogue_seeds_every_stock_stem():
    atmo.reload()
    seen = set()
    for t, stems in SEED.items():
        for stem in stems:
            s = surf.resolve_surface("", "", f"data/models/environment/{stem}.nif")
            assert s is not None and s.type == t, stem
            assert (s.ocean is not None) == (stem in WITH_OCEAN), stem
            seen.add(stem)
    assert seen == set(atmo.STOCK_STEMS)
    for stem in atmo.STOCK_STEMS:   # air untouched by the edit
        atmo.resolve("", "", f"{stem}.nif")
