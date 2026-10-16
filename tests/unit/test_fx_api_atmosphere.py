"""CreateAtmosphereFX -> mod-requested atmosphere; catalogue always wins
(spec 2026-10-16 §8.3)."""
import importlib

import pytest

from engine.planets import atmosphere


class _Set:
    def __init__(self, name):
        self._n = name

    def GetName(self):
        return self._n


class _Planet:
    """Mirrors the two Planet methods CreateAtmosphereFX reads."""
    def __init__(self, set_name, name):
        self._s, self._n = _Set(set_name), name

    def GetContainingSet(self):
        return self._s

    def GetName(self):
        return self._n


@pytest.fixture
def lib():
    return importlib.import_module("Custom.NanoFXv2.NanoFX_Lib")


@pytest.fixture(autouse=True)
def _clean():
    atmosphere.clear_requested()
    yield
    atmosphere.clear_requested()


def test_uncatalogued_planet_gets_the_class_preset(lib):
    lib.CreateAtmosphereFX(_Planet("ModSys1", "Mod World"),
                           "data/models/environment/zz_custom_world.nif", "Class-H")
    a = atmosphere.resolve("ModSys1", "Mod World", "data/models/environment/zz_custom_world.nif")
    preset = atmosphere.parse_entry("Class-H", atmosphere.class_preset("Class-H"))
    assert a == preset


def test_catalogued_stem_wins(lib):
    lib.CreateAtmosphereFX(_Planet("ModSys1", "Blue"),
                           "data/models/environment/earth.nif", "Class-H")
    a = atmosphere.resolve("ModSys1", "Blue", "data/models/environment/earth.nif")
    assert a == atmosphere.parse_entry("earth", atmosphere.load()["earth"])


def test_unknown_class_falls_back_to_default(lib):
    lib.CreateAtmosphereFX(_Planet("S", "P"), "data/x/zz_other.nif", "Class-Q")
    a = atmosphere.resolve("S", "P", "data/x/zz_other.nif")
    assert a == atmosphere.parse_entry("Class-M", atmosphere.class_preset("Class-M"))


def test_planet_without_a_set_logs_instead_of_silently_returning(lib, capsys):
    class _Loose:
        def GetContainingSet(self):
            return None

        def GetName(self):
            return "Drifter"

    lib.CreateAtmosphereFX(_Loose(), "data/x/zz.nif", "Class-H")
    err = capsys.readouterr().err
    assert "CreateAtmosphereFX" in err and "Drifter" in err
    assert atmosphere._requested == {}


def test_unrequested_uncatalogued_stays_airless():
    assert atmosphere.resolve("S", "P", "data/x/zz_nothing.nif") is None
