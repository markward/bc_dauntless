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


def test_seed_is_crc32_of_key(catalogue):
    catalogue({"p": {"atmosphere": False, "surface": {"type": "rocky"}}})
    assert surf.resolve_surface("S", "N", "p.nif").seed == zlib.crc32(b"p")


def test_to_binding_shapes():
    assert surf.to_binding(None) is None
    s = surf.Surface(type="gas", ocean=None, seed=7)
    assert surf.to_binding(s) == (4, (0.0, 0.0, 0.0), False, 0.15, 1.0, 1.0, 1.0, 7)
    s2 = surf.Surface(type="rocky", ocean=(0.1, 0.2, 0.3), seed=1)
    assert surf.to_binding(s2)[1:3] == ((0.1, 0.2, 0.3), True)


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
