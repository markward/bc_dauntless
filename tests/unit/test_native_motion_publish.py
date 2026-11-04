"""The published-pose buffer (native motion phase 2, Task 6).

The motion stage's last act (``ship_motion.tick_all_ship_motion``, in both
switch states) copies every ship row's pose and ``_velocity`` into a native
buffer tagged with the stage's tick number. Nothing reads it in play yet.
"""
import pytest

import App

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_motion_published"),
    reason="native combat bindings not built")

from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import native_motion as nm  # noqa: E402
from engine.appc import ship_motion  # noqa: E402
from engine.appc.math import TGPoint3  # noqa: E402
from engine.appc.ships import ShipClass  # noqa: E402
from engine.core.game import _set_current_game  # noqa: E402
from tests.unit.test_native_motion_driver import (  # noqa: E402
    DT, OFF, _Flight, _ModShip, _drifting, _engine, _fly, _set, _ship)
from engine.appc import warp_flight  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    _set_current_game(None)
    App.g_kSetManager._sets.clear()
    nc.reset()
    nc.configure({})
    nm.reset()
    nm.configure({})
    yield
    App.g_kSetManager._sets.clear()
    nc.reset()
    _set_current_game(None)


def _scene():
    pSet = _set("S")
    a = _ship("A", pSet, (0.01, 0.02, -0.005))
    b = _ship("B", pSet, (0.3, -0.1, 0.05))
    _fly(a)
    _drifting(b)
    return pSet, a, b


def _published():
    tick, rows = _h.combat_motion_published()
    return tick, {h: (p, r, v) for h, p, r, v in rows}


def _expect(ship):
    p = ship.GetTranslate()
    v = ship.__dict__["_velocity"]
    return ((p.x, p.y, p.z),
            tuple(ship.GetWorldRotation().as_tuple()),
            (v.x, v.y, v.z))


def test_buffer_equals_the_store_after_a_tick():
    _, a, b = _scene()
    ship_motion.tick_all_ship_motion(DT)
    tick, buf = _published()
    assert tick == 1
    for s in (a, b):
        got = buf[s.__dict__["_nslot"]]
        want = _expect(s)
        assert [x.hex() for x in got[0]] == [x.hex() for x in want[0]]
        assert [x.hex() for x in got[1]] == [x.hex() for x in want[1]]
        assert [x.hex() for x in got[2]] == [x.hex() for x in want[2]]


def test_tick_tag_advances_once_per_tick():
    _scene()
    for want in (1, 2, 3):
        ship_motion.tick_all_ship_motion(DT)
        assert _published()[0] == want


def test_a_later_teleport_does_not_change_the_buffer_until_the_next_stage():
    _, a, _b = _scene()
    ship_motion.tick_all_ship_motion(DT)
    h = a.__dict__["_nslot"]
    before = _published()[1][h][0]
    a.SetTranslateXYZ(500.0, 600.0, 700.0)
    assert _published()[1][h][0] == before
    ship_motion.tick_all_ship_motion(DT)
    after = _published()[1][h][0]
    assert after[0] > 400.0


def test_ship_with_no_row_is_absent():
    pSet, a, b = _scene()
    a.__dict__["_nslot"] = -1
    ship_motion.tick_all_ship_motion(DT)
    _, buf = _published()
    assert len(buf) == 1
    assert b.__dict__["_nslot"] in buf


def test_ship_spawned_mid_tick_appears_after_the_next_motion_stage():
    pSet, a, b = _scene()
    ship_motion.tick_all_ship_motion(DT)
    c = _ship("C", pSet, (1.0, 2.0, 3.0))
    _fly(c)
    assert c.__dict__["_nslot"] not in _published()[1]
    ship_motion.tick_all_ship_motion(DT)
    assert c.__dict__["_nslot"] in _published()[1]


def _assert_all_fields(ship, buf):
    got = buf[ship.__dict__["_nslot"]]
    p = ship.GetWorldLocation()
    v = ship.GetVelocityTG()
    want = ((p.x, p.y, p.z), tuple(ship.GetWorldRotation().as_tuple()),
            (v.x, v.y, v.z))
    for g, w in zip(got, want):
        assert len(g) == len(w)
        assert [x.hex() for x in g] == [x.hex() for x in w]


def test_published_with_the_switch_off_too():
    _, a, b = _scene()
    nm.reset()
    nm.configure(OFF)
    ship_motion.tick_all_ship_motion(DT)
    tick, buf = _published()
    assert tick == 1
    assert nm.counts()["native_calls"] == 0
    assert len(buf) == 2
    for s in (a, b):
        _assert_all_fields(s, buf)


def test_python_owned_warp_row_publishes_its_python_pose(monkeypatch):
    pSet = _set("S")
    a = _ship("A", pSet, (0.01, 0.02, -0.005))
    w = _ship("W", pSet, (0.3, -0.1, 0.05))
    c = _ship("C", pSet, (-0.02, 0.01, 0.03))
    for s in (a, w, c):
        _fly(s)
    w._insystem_warp_transit = _Flight()

    def step(ship, dt):          # a Python-owned segment row
        ship.SetTranslateXYZ(7.25, -3.5, 1.125)
        ship.SetVelocity(TGPoint3(0.75, 0.5, -0.25))
        return True

    monkeypatch.setattr(warp_flight, "step", step)
    ship_motion.tick_all_ship_motion(DT)
    assert nm.counts()["warp_rows"] == 1
    _, buf = _published()
    assert len(buf) == 3
    assert buf[w.__dict__["_nslot"]][0] == (7.25, -3.5, 1.125)
    assert buf[w.__dict__["_nslot"]][2] == (0.75, 0.5, -0.25)
    for s in (a, w, c):
        _assert_all_fields(s, buf)


def test_row_handed_back_to_python_publishes_its_python_pose():
    pSet = _set("S")
    a = _ship("A", pSet, (0.01, 0.02, -0.005))
    m = _ship("M", pSet, (0.3, -0.1, 0.05), cls=_ModShip)
    _fly(a)
    _drifting(m)
    ship_motion.tick_all_ship_motion(DT)
    assert nm.counts()["python_rows"]       # M ran in Python
    _, buf = _published()
    assert len(buf) == 2
    for s in (a, m):
        _assert_all_fields(s, buf)


def test_a_non_tgpoint3_velocity_row_is_skipped():
    """A row whose _velocity is not a TGPoint3 (state 2: a tuple) has no
    velocity the buffer can hold, so it is left out; its neighbours stay."""
    pSet, a, b = _scene()
    b._stationary = True        # immobile: motion passes it over untouched
    b._velocity = (1.0, 2.0, 3.0)
    ship_motion.tick_all_ship_motion(DT)
    _, buf = _published()
    assert b.__dict__["_nslot"] not in buf
    assert a.__dict__["_nslot"] in buf


def test_reset_clears_the_buffer():
    _scene()
    ship_motion.tick_all_ship_motion(DT)
    assert _published()[1]
    nm.reset()
    assert _published() == (0, {})
