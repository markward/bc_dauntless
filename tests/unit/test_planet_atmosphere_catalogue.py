"""Planet atmosphere catalogue (spec docs/superpowers/specs/2026-10-07-planet-atmosphere-design.md §3)."""
import json

import pytest

from engine.planets import atmosphere as atmo


def _write(tmp_path, monkeypatch, data):
    root = tmp_path / "assets"
    (root / "planets").mkdir(parents=True)
    (root / "planets" / "atmospheres.json").write_text(json.dumps(data))
    monkeypatch.setattr("engine.paths.project_asset_root", lambda: root)
    atmo.reload()


GAS = {"color": "#FF9A96", "thickness": 0.06, "density": 1.4, "limb": 1.0}


def test_nif_stem_casefolds_and_drops_extension():
    assert atmo.nif_stem("data/models/environment/GreenPurplePlanet.nif") == "greenpurpleplanet"
    assert atmo.nif_stem("/abs/Environment/GreenPurplePlanet.NIF") == "greenpurpleplanet"


def test_srgb_hex_to_linear():
    assert atmo.srgb_hex_to_linear("#FFFFFF") == pytest.approx((1.0, 1.0, 1.0))
    assert atmo.srgb_hex_to_linear("#000000") == pytest.approx((0.0, 0.0, 0.0))
    r, _, _ = atmo.srgb_hex_to_linear("#808080")
    assert r == pytest.approx(0.2158605, abs=1e-5)


def test_stem_entry_resolves(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"pinkgasplanet": GAS})
    a = atmo.resolve("Geble3", "Geble 3", "data/models/environment/PinkGasPlanet.nif")
    assert a is not None and a.thickness == 0.06 and a.density == 1.4 and a.limb == 1.0
    assert a.sunset_color == a.color


def test_set_name_override_wins_over_stem(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"pinkgasplanet": GAS, "Geble3/Geble 3": {"atmosphere": False}})
    assert atmo.resolve("Geble3", "Geble 3", "x/PinkGasPlanet.nif") is None
    assert atmo.resolve("Albirea3", "Albirea 3", "x/PinkGasPlanet.nif") is not None
    assert atmo.resolve_key("Geble3", "Geble 3", "x/PinkGasPlanet.nif") == "Geble3/Geble 3"
    assert atmo.resolve_key("Albirea3", "Albirea 3", "x/PinkGasPlanet.nif") == "pinkgasplanet"


def test_bare_name_is_not_a_key(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"Geble 3": GAS})
    assert atmo.resolve("Geble3", "Geble 3", "x/RockyPlanet.nif") is None


def test_override_key_is_case_sensitive(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"geble3/geble 3": GAS})
    assert atmo.resolve("Geble3", "Geble 3", "x/RockyPlanet.nif") is None


def test_missing_is_none(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {})
    assert atmo.resolve("S", "N", "x/Unknown.nif") is None
    assert atmo.resolve_key("S", "N", "x/Unknown.nif") is None


@pytest.mark.parametrize("bad", [
    {"color": "#FF9A96", "thickness": 0.06, "density": 1.4},                # missing limb
    {**GAS, "thickness": 0.0},                                               # out of range
    {**GAS, "thickness": 0.3},
    {**GAS, "density": 5.0},
    {**GAS, "limb": -1.0},
    {**GAS, "color": "pink"},
    {**GAS, "surface": "gas"},                                               # unknown field
])
def test_malformed_entry_warns_once_and_is_none(tmp_path, monkeypatch, capsys, bad):
    _write(tmp_path, monkeypatch, {"pinkgasplanet": bad})
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif") is None
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif") is None
    err = capsys.readouterr().err
    assert err.count("pinkgasplanet") == 1


def test_parse_entry_missing_limb_raises_valueerror():
    with pytest.raises(ValueError, match="missing required field"):
        atmo.parse_entry("k", {"color": "#FF9A96", "thickness": 0.06, "density": 1.4})


def test_parse_entry_missing_color_raises_valueerror():
    with pytest.raises(ValueError, match="missing required field"):
        atmo.parse_entry("k", {"thickness": 0.06, "density": 1.4, "limb": 1.0})


def test_missing_file_is_empty_and_warns_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("engine.paths.project_asset_root", lambda: tmp_path / "nowhere")
    atmo.reload()
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif") is None
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif") is None
    assert capsys.readouterr().err.count("atmospheres.json") == 1


def test_path_is_resolved_at_use(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"pinkgasplanet": GAS})
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif") is not None
    other = tmp_path / "other"
    (other / "planets").mkdir(parents=True)
    (other / "planets" / "atmospheres.json").write_text("{}")
    monkeypatch.setattr("engine.paths.project_asset_root", lambda: other)
    assert atmo.resolve("S", "N", "x/PinkGasPlanet.nif") is None   # memo is keyed by path


def test_shipped_catalogue_is_valid_and_covers_every_stock_stem():
    atmo.reload()
    raw = atmo.load()
    assert set(atmo.STOCK_STEMS) <= set(raw)
    for key, entry in raw.items():
        atmo.parse_entry(key, entry)          # raises on malformed
    assert not any("/" in k for k in raw), "spec §3.4: no per-planet overrides ship"


def test_shipped_tiers_match_the_spec():
    atmo.reload()
    a = atmo.resolve("S", "N", "x/PinkGasPlanet.nif")
    assert (a.thickness, a.density, a.limb) == (0.06, 1.4, 1.0)
    a = atmo.resolve("S", "N", "x/GreenPurplePlanet.nif")
    assert (a.thickness, a.density, a.limb) == (0.035, 1.0, 1.0)
    a = atmo.resolve("S", "N", "x/IcePlanet.nif")
    assert (a.thickness, a.density, a.limb) == (0.02, 0.5, 0.8)
    for airless in ("moon", "rockyplanet", "grayplanet", "tanplanet"):
        assert atmo.resolve("S", "N", f"x/{airless}.nif") is None


# ---- Live registry: clear_live_for_set (fix round 1 finding 1) ------------

@pytest.fixture(autouse=True)
def _reset_live():
    atmo.clear_live()
    yield
    atmo.clear_live()


def test_clear_live_for_set_removes_only_that_sets_entries():
    atmo.record_live(1, "k1", "SetA", "N1", "x.nif")
    atmo.record_live(2, "k2", "SetB", "N2", "y.nif")
    atmo.record_live(3, "k3", "SetA", "N3", "z.nif")

    atmo.clear_live_for_set("SetA")

    remaining = atmo.live()
    assert {lp.set_name for lp in remaining} == {"SetB"}
    assert [lp.iid for lp in remaining] == [2]


def test_clear_live_for_set_with_no_matching_entries_is_a_noop():
    atmo.record_live(1, "k1", "SetB", "N1", "x.nif")
    atmo.clear_live_for_set("SetA")
    assert len(atmo.live()) == 1
