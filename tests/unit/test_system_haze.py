import pytest

from engine import dev_mode, host_loop
from engine import dev_nebula_dials as D
from engine import system_haze
from engine.cameras import SCENE_FAR_GU
from engine.systems import profile as P
from engine.systems.map import Body, Region, SystemMap
from tests.unit.test_system_nebula_feed import _R, _map, _patch


@pytest.fixture(autouse=True)
def _dials(monkeypatch):
    monkeypatch.setattr(D, "_dials", dict(D.DEFAULTS))


def test_profile_dict_matches_the_push(monkeypatch):
    m = _map()
    _patch(monkeypatch, m)
    r = _R()
    host_loop._push_system_nebula(r, object(), [], False)
    built = system_haze.profile_dict(
        m, veil=D.veil(), dials=D.current(), far_gu=SCENE_FAR_GU)
    assert built == r.profiles[0]


def test_none_without_profile():
    m = SystemMap(system="X",
                  bodies=[Body("Star", "Star", 2000.0, (0.0, 0.0, 0.0))],
                  regions=[Region("R", (1.0, 0.0, 0.0), 1.0)])
    assert system_haze.profile_dict(
        m, veil=0.5, dials=D.current(), far_gu=1.0) is None


def test_none_without_star():
    m = _map()
    m.bodies = []
    assert system_haze.profile_dict(
        m, veil=0.5, dials=D.current(), far_gu=1.0) is None
    assert system_haze.profile_dict(
        None, veil=0.5, dials=D.current(), far_gu=1.0) is None


def test_for_set_unknown_set_is_none():
    assert system_haze.profile_dict_for_set("NoSuchSet_xyz") is None
