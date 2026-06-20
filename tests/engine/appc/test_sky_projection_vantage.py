from engine.appc import sky_projection as sp


class _Set:
    def __init__(self, name): self._n = name
    def GetName(self): return self._n


_MODEL = {"systems": [{"id": "vesuvi", "position": [1.0, 2.0, 3.0]},
                      {"id": "tauceti", "position": [9.0, 9.0, 9.0]}],
          "nebulae": [], "starclouds": []}


def test_system_id_strips_region_number():
    assert sp.system_id_for_set("Vesuvi6") == "vesuvi"
    assert sp.system_id_for_set("Biranu1") == "biranu"


def test_system_id_maps_synthetic_members():
    assert sp.system_id_for_set("Starbase12") == "tauceti"
    assert sp.system_id_for_set("DryDock") == "tauceti"


def test_vantage_resolves_position():
    assert sp.vantage_for_set(_Set("Vesuvi6"), _MODEL) == [1.0, 2.0, 3.0]
    assert sp.vantage_for_set(_Set("Starbase12"), _MODEL) == [9.0, 9.0, 9.0]


def test_vantage_unmapped_returns_none():
    assert sp.vantage_for_set(_Set("Nowhere9"), _MODEL) is None
