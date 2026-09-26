"""A glow region authored on ANY subsystem dims and flickers with it.

The Ship Property Viewer lets a region be authored on any subsystem ("Any
subsystem is light-capable now -- no impulse/warp/sensor gate",
engine/ui/ship_property_viewer.py), but ShipGlowController only registered
regions on warp pods, impulse pods and the sensor array. A region on a
disruptor cannon was saved and never reached the renderer, so its glow texture
stayed at full brightness while the cannon was disabled or destroyed.

Assertions are on the calls the renderer receives.
"""
import logging

from engine.appc import subsystem_glow as sg
from engine.appc.properties import WeaponSystemProperty


class _Point:
    def __init__(self, x, y, z):
        self._x, self._y, self._z = x, y, z
    def GetX(self): return self._x
    def GetY(self): return self._y
    def GetZ(self): return self._z


class _Sub:
    """A leaf subsystem carrying (by default) one baked Box region."""

    def __init__(self, name, pos, baked=True):
        self._name, self._pos, self._baked = name, _Point(*pos), baked
        self.disabled = self.destroyed = False
    def GetName(self): return self._name
    def GetPosition(self): return self._pos
    def IsDisabled(self): return self.disabled
    def IsDestroyed(self): return self.destroyed
    def GetNumChildSubsystems(self): return 0
    def GetProperty(self):
        if not self._baked:
            return None
        prop = WeaponSystemProperty(self._name)
        prop.SetGlowRegionShape(0, "Box")
        prop.SetGlowRegionScale(0, 0.25, 0.25, 0.25)
        return prop


class _Ship:
    """Reachable through the SPV walker's standard getters only."""

    def __init__(self, impulse=None, weapons=None):
        self._impulse, self._weapons = impulse, weapons
    def GetWarpEngineSubsystem(self): return None
    def GetImpulseEngineSubsystem(self): return self._impulse
    def GetSensorSubsystem(self): return None
    def GetPulseWeaponSystem(self): return self._weapons


class _Renderer:
    def __init__(self, capacity=12):
        self._next = 0
        self._capacity = capacity
        self.box_calls, self.cylinder_calls, self.sphere_calls = [], [], []
        self.dim_calls, self.gain_calls = [], []
    def _alloc(self):
        if self._next >= self._capacity:
            return -1
        self._next += 1
        return self._next - 1
    def add_box_region(self, iid, center, half, forward=(0.0, 1.0, 0.0),
                       up=(0.0, 0.0, 1.0)):
        self.box_calls.append((iid, center, half))
        return self._alloc()
    def add_cylinder_region(self, iid, center, axis, radius, length):
        self.cylinder_calls.append((iid, center))
        return self._alloc()
    def add_sphere_region(self, iid, center, radius):
        self.sphere_calls.append((iid, center))
        return self._alloc()
    def set_glow_region_dim(self, iid, idx, dim, etime, flick):
        self.dim_calls.append((idx, dim, etime, flick))
    def set_glow_region_gain(self, iid, idx, gain, gate=(0.0, 0.0, 0.0)):
        self.gain_calls.append((idx, gain))


CANNON = (1.008, 0.45, -0.67)


def test_a_region_on_a_WEAPON_subsystem_is_registered():
    cannon = _Sub("Port Cannon", CANNON)
    r = _Renderer()
    sg.ShipGlowController(r, 7, _Ship(weapons=cannon))
    assert r.box_calls == [(7, CANNON, (0.25, 0.25, 0.25))]


def test_a_weapon_region_dims_and_flickers_with_its_subsystem():
    cannon = _Sub("Port Cannon", CANNON)
    r = _Renderer()
    ctrl = sg.ShipGlowController(r, 7, _Ship(weapons=cannon))

    ctrl.update(now=10.0)
    assert r.dim_calls[-1] == (0, 1.0, -1.0, 0.0)       # healthy
    cannon.disabled = True
    ctrl.update(now=20.0)
    assert r.dim_calls[-1] == (0, 0.0, 20.0, 1.0)       # disabled: flicker
    cannon.disabled, cannon.destroyed = False, True
    ctrl.update(now=30.0)
    assert r.dim_calls[-1] == (0, 0.0, 30.0, 0.0)       # destroyed: off


def test_a_weapon_region_is_not_an_impulse_boost():
    """Throttle brightening belongs to impulse pods only."""
    cannon = _Sub("Port Cannon", CANNON)
    r = _Renderer()
    ctrl = sg.ShipGlowController(r, 7, _Ship(weapons=cannon))
    ctrl.update(now=10.0, throttle_frac=1.0)
    assert r.gain_calls == []


def test_an_impulse_pod_is_registered_ONCE_and_still_boosts():
    """The walker also reaches the impulse pod; it must not double-register."""
    impulse = _Sub("Impulse", (0.0, -0.5, 0.0))
    r = _Renderer()
    ctrl = sg.ShipGlowController(r, 7, _Ship(impulse=impulse))
    assert len(r.box_calls) == 1
    ctrl.update(now=10.0, throttle_frac=1.0)
    assert r.gain_calls, "the impulse region must keep its throttle boost"


def test_an_unbaked_subsystem_gets_nothing():
    r = _Renderer()
    sg.ShipGlowController(r, 7, _Ship(weapons=_Sub("Port Cannon", CANNON,
                                                    baked=False)))
    assert r.box_calls == [] and r.cylinder_calls == [] and r.sphere_calls == []


def test_a_region_past_the_per_ship_cap_WARNS(caplog):
    """Twelve per ship (kMaxGlowRegions). Past that the renderer returns -1;
    the region must not vanish silently."""
    cannon = _Sub("Port Cannon", CANNON)
    r = _Renderer(capacity=0)
    with caplog.at_level(logging.WARNING):
        sg.ShipGlowController(r, 7, _Ship(weapons=cannon))
    assert any("Port Cannon" in rec.getMessage() for rec in caplog.records)


def test_caller_supplied_regions_replace_the_property():
    """The SPV refresh hands the controller its effective (saved-this-session)
    specs, which have not reached the live property yet."""
    cannon = _Sub("Port Cannon", CANNON, baked=False)
    spec = {"shape": "Sphere", "position": CANNON, "radius": (0.3,),
            "axis": None, "extent": None, "scale": None, "orientation": None}
    r = _Renderer()
    sg.ShipGlowController(r, 7, _Ship(weapons=cannon),
                          regions_of=lambda sub: [spec] if sub is cannon else [])
    assert r.sphere_calls == [(7, CANNON)]
