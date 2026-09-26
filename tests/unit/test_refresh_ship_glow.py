"""SPV Save re-registers a ship's glow regions, so an authored region shows
without reloading the mission.

ShipGlowController registered regions once, at spawn, and nothing cleared an
instance's regions, so a region authored in the Ship Property Viewer did not
appear until the ship was rebuilt. The saved specs have not reached the live
property yet (they do on the next ship build), so the refresh is fed the SPV's
effective specs, exactly as refresh_ship_emitters is for cast lights.
"""
import types

import pytest

from engine import host_loop
from engine.appc.subsystem_glow import ShipGlowController


class _Point:
    def __init__(self, x, y, z): self._v = (x, y, z)
    def GetX(self): return self._v[0]
    def GetY(self): return self._v[1]
    def GetZ(self): return self._v[2]


class _Sub:
    def __init__(self, name, pos):
        self._name, self._pos = name, _Point(*pos)
    def GetName(self): return self._name
    def GetPosition(self): return self._pos
    def GetProperty(self): return None
    def IsDisabled(self): return False
    def IsDestroyed(self): return False
    def GetNumChildSubsystems(self): return 0


class _Ship:
    def __init__(self, cannon): self._cannon = cannon
    def GetWarpEngineSubsystem(self): return None
    def GetImpulseEngineSubsystem(self): return None
    def GetSensorSubsystem(self): return None
    def GetPulseWeaponSystem(self): return self._cannon


class _Renderer:
    def __init__(self):
        self.log = []
        self._next = 0
    def clear_glow_regions(self, iid):
        self.log.append(("clear", iid))
        self._next = 0
    def add_sphere_region(self, iid, center, radius):
        self.log.append(("sphere", iid, tuple(center), radius))
        self._next += 1
        return self._next - 1
    def add_box_region(self, iid, center, half, forward=None, up=None):
        self.log.append(("box", iid, tuple(center)))
        self._next += 1
        return self._next - 1
    def add_cylinder_region(self, iid, center, axis, radius, length):
        self.log.append(("cylinder", iid, tuple(center)))
        self._next += 1
        return self._next - 1


CANNON = (1.008, 0.45, -0.67)
SPEC = {"shape": "Sphere", "position": CANNON, "radius": (0.3,),
        "axis": None, "extent": None, "scale": None, "orientation": None}


@pytest.fixture
def rig(monkeypatch):
    rend = _Renderer()
    monkeypatch.setattr(host_loop, "r", rend)
    cannon = _Sub("Port Cannon", CANNON)
    ship = _Ship(cannon)
    session = types.SimpleNamespace(ship_instances={ship: 42},
                                    ship_glow_controllers={})
    return rend, ship, cannon, session


def test_save_CLEARS_then_re_registers_the_saved_region(rig):
    rend, ship, cannon, session = rig
    host_loop.refresh_ship_glow(session, ship, {id(cannon): [SPEC]})
    assert rend.log[0] == ("clear", 42), "old regions must go before new ones"
    assert ("sphere", 42, CANNON, 0.3) in rend.log
    assert isinstance(session.ship_glow_controllers[42], ShipGlowController)


def test_a_removed_region_is_gone_after_the_refresh(rig):
    rend, ship, cannon, session = rig
    host_loop.refresh_ship_glow(session, ship, {id(cannon): []})
    assert rend.log == [("clear", 42)]


def test_no_render_instance_is_a_no_op(rig):
    rend, ship, cannon, session = rig
    session.ship_instances = {}
    host_loop.refresh_ship_glow(session, ship, {id(cannon): [SPEC]})
    assert rend.log == []
    assert session.ship_glow_controllers == {}


def test_a_refresh_failure_never_raises(rig, monkeypatch):
    """Best-effort, like the emitter refresh: it must never break Save."""
    rend, ship, cannon, session = rig
    def boom(iid):
        raise RuntimeError("native failure")
    monkeypatch.setattr(rend, "clear_glow_regions", boom)
    host_loop.refresh_ship_glow(session, ship, {id(cannon): [SPEC]})
