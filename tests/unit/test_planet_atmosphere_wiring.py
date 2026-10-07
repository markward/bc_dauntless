"""Planet atmosphere wiring (spec 2026-10-07 §4)."""
from engine import host_loop, planet_atmosphere
from engine.planets import atmosphere as atmo


class _R:
    def __init__(self):
        self.calls = []

    def set_instance_atmosphere(self, iid, params):
        self.calls.append((iid, params))


def test_toggle_defaults_on():
    assert planet_atmosphere.enabled() is True


def test_apply_pushes_resolved_params_and_records_live():
    r = _R()
    host_loop._apply_planet_atmosphere(r, "iid1", "Albirea3", "Albirea 3",
                                       "data/models/environment/PinkGasPlanet.nif")
    (iid, params), = r.calls
    assert iid == "iid1" and params is not None and params.thickness == 0.06
    (lp,) = atmo.live()
    assert lp.key == "pinkgasplanet" and lp.set_name == "Albirea3"


def test_apply_pushes_none_for_airless():
    r = _R()
    host_loop._apply_planet_atmosphere(r, "iid2", "Vesuvi5", "Mori", "x/moon.nif")
    assert r.calls == [("iid2", None)]


def test_apply_pushes_none_when_toggle_off():
    planet_atmosphere.set_enabled(False)
    r = _R()
    host_loop._apply_planet_atmosphere(r, "iid3", "Albirea3", "Albirea 3", "x/PinkGasPlanet.nif")
    assert r.calls == [("iid3", None)]
    assert atmo.live() == ()


def test_live_registry_clears_on_teardown():
    r = _R()
    host_loop._apply_planet_atmosphere(r, "iid4", "S", "N", "x/PinkGasPlanet.nif")
    atmo.clear_live()
    assert atmo.live() == ()


class _Iid:
    """pybind InstanceId stand-in: index/generation, no __eq__."""

    def __init__(self, index, generation):
        self.index = index
        self.generation = generation


def test_forget_live_matches_iid_by_index_and_generation():
    atmo.record_live(_Iid(3, 1), "pinkgasplanet", "S", "A", "x/PinkGasPlanet.nif")
    atmo.record_live(_Iid(3, 2), "pinkgasplanet", "S", "B", "x/PinkGasPlanet.nif")
    atmo.record_live(_Iid(4, 1), "pinkgasplanet", "S", "C", "x/PinkGasPlanet.nif")
    atmo.forget_live(_Iid(3, 1))      # a DIFFERENT wrapper of the same id
    assert [lp.obj_name for lp in atmo.live()] == ["B", "C"]


def test_clear_live_for_set_drops_only_set_realized_entries():
    atmo.record_live("p", "pinkgasplanet", "R1", "Planet", "x/PinkGasPlanet.nif")
    atmo.record_live("c", "pinkgasplanet", "R1", "Body", "x/PinkGasPlanet.nif",
                     source="celestial")
    atmo.clear_live_for_set("R1")
    assert [lp.iid for lp in atmo.live()] == ["c"]
