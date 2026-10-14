"""Host-loop running-light wiring (running-lights spec §4.3)."""
import pytest

import App
from engine import host_loop
from engine.appc import running_light_dials
from engine.appc.math import TGPoint3
from engine.appc.properties import TGModelPropertySet
from engine.appc.subsystems import CloakingSubsystem


class _FakeRenderer:
    def __init__(self):
        self.lights = {}
        self.levels = None
        self.dials = None
    def set_running_lights(self, iid, lights, phase):
        self.lights[iid] = (list(lights), phase)
    def set_running_light_levels(self, levels):
        self.levels = list(levels)
    def set_running_light_dials(self, size_gu_per_radius, min_px, intensity):
        self.dials = (size_gu_per_radius, min_px, intensity)


class _Ship:
    def __init__(self, n_lights=2, name="USS Voyager", cloak=None, power=None):
        self._pset = TGModelPropertySet()
        for i in range(n_lights):
            p = App.BlinkingLightProperty_Create("L%d" % i)
            pt = TGPoint3(); pt.SetXYZ(float(i), 0.0, 0.0)
            p.SetPosition(pt)
            self._pset.AddToSet("Scene Root", p)
        self._name, self._cloak, self._power = name, cloak, power
    def GetPropertySet(self): return self._pset
    def GetName(self): return self._name
    def GetCloakingSubsystem(self): return self._cloak
    def GetPowerSubsystem(self): return self._power
    def IsDying(self): return 0
    def IsDead(self): return 0


class _Session:
    def __init__(self, mapping):
        self.ship_instances = dict(mapping)
        self.ship_running_lights = {}
        self.scope_hidden = set()


def test_register_sends_lights_once_with_phase():
    r = _FakeRenderer()
    ship = _Ship(n_lights=2)
    s = _Session({ship: 7})
    host_loop._register_running_lights(r, s, ship, 7)
    lights, phase = r.lights[7]
    assert len(lights) == 2 and len(lights[0]) == 9
    assert s.ship_running_lights == {7: phase}


def test_register_unlit_ship_sends_nothing():
    r = _FakeRenderer()
    ship = _Ship(n_lights=0)
    s = _Session({ship: 7})
    host_loop._register_running_lights(r, s, ship, 7)
    assert r.lights == {}
    assert s.ship_running_lights == {}


def test_push_sends_levels_and_dials_for_lit_ships():
    r = _FakeRenderer()
    lit, unlit = _Ship(2, name="A"), _Ship(0, name="B")
    s = _Session({lit: 1, unlit: 2})
    host_loop._register_running_lights(r, s, lit, 1)
    host_loop._register_running_lights(r, s, unlit, 2)
    host_loop._push_running_lights(r, s)
    assert r.levels == [(1, 1.0)]
    assert r.dials == tuple(running_light_dials.current().values())


def test_push_scope_hidden_ship_is_dark():
    r = _FakeRenderer()
    ship = _Ship(2)
    s = _Session({ship: 3})
    host_loop._register_running_lights(r, s, ship, 3)
    s.scope_hidden.add(3)
    host_loop._push_running_lights(r, s)
    assert r.levels == [(3, 0.0)]


def test_push_reads_cloak_fraction():
    c = CloakingSubsystem("Cloak")
    c.StartCloaking()
    c.Update(c._transition_duration * 0.5)
    frac = c.GetTransitionFraction()
    r = _FakeRenderer()
    ship = _Ship(2, cloak=c)
    s = _Session({ship: 4})
    host_loop._register_running_lights(r, s, ship, 4)
    host_loop._push_running_lights(r, s)
    assert r.levels[0][1] == pytest.approx(1.0 - frac)


def test_push_ship_without_cloak_or_power_subsystem_is_lit():
    r = _FakeRenderer()
    ship = _Ship(1, cloak=None, power=None)
    s = _Session({ship: 5})
    host_loop._register_running_lights(r, s, ship, 5)
    host_loop._push_running_lights(r, s)
    assert r.levels == [(5, 1.0)]


def test_push_with_no_lit_ships_sends_nothing():
    r = _FakeRenderer()
    host_loop._push_running_lights(r, _Session({}))
    assert r.levels is None and r.dials is None


def test_push_drops_a_lit_iid_whose_ship_is_gone():
    r = _FakeRenderer()
    ship = _Ship(1)
    s = _Session({ship: 6})
    host_loop._register_running_lights(r, s, ship, 6)
    s.ship_instances.clear()        # removed without the pop (defensive)
    host_loop._push_running_lights(r, s)
    assert r.levels == [(6, 0.0)]


def test_mission_session_teardown_clears_running_lights():
    class _R:
        def destroy_instance(self, iid):
            pass
    sess = host_loop.MissionSession(mission_name="t")
    sess.ship_running_lights[9] = 1.0
    sess.teardown(_R())
    assert sess.ship_running_lights == {}
