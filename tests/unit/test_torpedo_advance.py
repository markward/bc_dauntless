"""Torpedo motion: position += velocity*dt, age increments, TTL expires.
Homing: when target_ship is set and age < guidance_lifetime, velocity
turns toward the target up to max_angular_accel × dt.
Collision: sphere_hit against any ship except source; first hit wins.
"""
import pytest
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.projectiles import Torpedo, register, update_all, _active, _guide
from engine.appc.subsystems import ShipSubsystem


class _RotShip:
    def __init__(self, loc, rot):
        self._loc, self._rot = loc, rot
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot


def test_guide_homes_on_center_mass_ignoring_subsystem_lock():
    """Audited Torpedo::Guide always homes the target ship's hull centre —
    the fire-time subsystem aim offset is dead weight in flight (BC never
    re-reads it during guidance). A subsystem attached to the ship must NOT
    pull the steer toward its own position."""
    R = TGMatrix3(); R.MakeIdentity()
    ship = _RotShip(TGPoint3(0.0, 0.0, 0.0), R)
    sub = ShipSubsystem("Port Nacelle")
    sub._position = TGPoint3(0.0, 50.0, 0.0)   # +50 in ship local Y
    sub.SetParentShip(ship)

    t = Torpedo()
    # Position chosen so the bearing to the hull centre (0,0,0) and the
    # bearing to the subsystem (0,50,0) diverge.
    t._position = TGPoint3(100.0, -50.0, 0.0)
    t._velocity = TGPoint3(-10.0, 0.0, 0.0)
    t._max_angular_accel = 1000.0              # ample turn authority
    t._target_ship = ship

    _guide(t, dt=0.05)
    speed = t._velocity.Length()
    dir_y = t._velocity.y / speed
    # Bearing to hull centre from (100,-50,0): (-100,50,0) normalized -> y ~= 0.4472
    # Bearing to subsystem from (100,-50,0): (-100,100,0) normalized -> y ~= 0.7071
    assert dir_y == pytest.approx(0.4472, abs=1e-3)


@pytest.fixture(autouse=True)
def clear_registry():
    _active.clear()
    yield
    _active.clear()


def _torp_at(x, y, z, vx, vy, vz, ttl=30.0, age=0.0, src=None):
    t = Torpedo()
    t._position = TGPoint3(x, y, z)
    t._velocity = TGPoint3(vx, vy, vz)
    t._ttl = ttl
    t._age = age
    t._source_ship = src
    t._damage = 100.0
    register(t)
    return t


class _FakeShip:
    def __init__(self, x, y, z, radius=10.0, dead=False):
        self._loc = TGPoint3(x, y, z)
        self._r = radius
        self._dead = dead
        self._hull = None
        self._children = []
        self._shields = None

    def GetWorldLocation(self): return self._loc
    def GetRadius(self): return self._r
    def IsDead(self): return 1 if self._dead else 0
    def GetHull(self): return self._hull
    def GetShields(self): return self._shields
    def GetNumChildSubsystems(self): return len(self._children)
    def GetChildSubsystem(self, i): return self._children[i]
    # combat damage attribution (reached via _advance_combat ->
    # pump) walks ship.GetSubsystems()/GetObjID(); mirror ShipClass.
    def GetSubsystems(self): return list(self._children)
    def GetObjID(self): return id(self)


def test_torpedo_position_advances_by_velocity_dt():
    t = _torp_at(0, 0, 0, 10, 0, 0)
    update_all(dt=0.1, all_ships=[])
    assert t._position.x == pytest.approx(1.0)
    assert t._age == pytest.approx(0.1)


def test_torpedo_ttl_expires_removes_from_registry():
    _torp_at(0, 0, 0, 0, 0, 0, ttl=0.5, age=0.4)
    update_all(dt=0.2, all_ships=[])  # age becomes 0.6 > ttl
    assert _active == []


def test_torpedo_collides_with_ship_sphere():
    src = _FakeShip(-100, 0, 0)
    target = _FakeShip(5, 0, 0, radius=10.0)
    t = _torp_at(0, 0, 0, 10, 0, 0, src=src)
    hits = update_all(dt=0.1, all_ships=[src, target])
    # Position advances to (1,0,0); distance to (5,0,0) = 4 < radius 10 ⇒ hit
    assert len(hits) == 1
    assert hits[0][0] is t
    assert hits[0][1] is target
    # 4-tuple: (torpedo, ship, hit_point, hit_normal). Headless (no host) →
    # hit_point degrades to torpedo._position and the normal is None (no mesh trace).
    assert len(hits[0]) == 4
    assert hits[0][2].x == pytest.approx(t._position.x)
    assert hits[0][2].y == pytest.approx(t._position.y)
    assert hits[0][2].z == pytest.approx(t._position.z)
    assert hits[0][3] is None
    assert _active == []


def test_torpedo_skips_source_ship():
    src = _FakeShip(0, 0, 0, radius=10.0)
    t = _torp_at(0, 0, 0, 1, 0, 0, src=src)
    update_all(dt=0.1, all_ships=[src])
    assert _active == [t]


def test_torpedo_skips_dead_ship():
    src = _FakeShip(-100, 0, 0)
    target = _FakeShip(5, 0, 0, radius=10.0, dead=True)
    _torp_at(0, 0, 0, 10, 0, 0, src=src)
    hits = update_all(dt=0.1, all_ships=[src, target])
    assert hits == []


def test_homing_torpedo_steers_toward_target():
    src = _FakeShip(-100, 0, 0)
    target = _FakeShip(0, 100, 0, radius=1.0)
    t = _torp_at(0, 0, 0, 10, 0, 0, src=src)
    t._target_ship = target
    t._guidance_lifetime = 10.0
    t._max_angular_accel = 1.0
    update_all(dt=0.1, all_ships=[src, target])
    assert t._velocity.y > 0.5
    assert t._velocity.x < 10.0
    speed = (t._velocity.x**2 + t._velocity.y**2 + t._velocity.z**2) ** 0.5
    assert speed == pytest.approx(10.0, abs=0.01)


def test_dumbfire_velocity_unchanged():
    src = _FakeShip(-100, 0, 0)
    t = _torp_at(0, 0, 0, 10, 0, 0, src=src)
    t._target_ship = None
    update_all(dt=0.1, all_ships=[src])
    assert t._velocity.x == 10.0
    assert t._velocity.y == 0.0


def test_homing_past_guidance_lifetime_stops_steering():
    src = _FakeShip(-100, 0, 0)
    target = _FakeShip(0, 100, 0)
    t = _torp_at(0, 0, 0, 10, 0, 0, age=5.0, src=src)
    t._target_ship = target
    t._guidance_lifetime = 3.0
    t._max_angular_accel = 1.0
    initial_vx = t._velocity.x
    update_all(dt=0.1, all_ships=[src, target])
    assert t._velocity.x == initial_vx


def test_torpedo_uses_host_ray_trace_mesh_when_supplied(monkeypatch):
    """When ship_instances is supplied, hit_point comes from the mesh trace
    (host_io.ray_trace_mesh), not the post-advance position."""
    from engine import host_io
    src = _FakeShip(-100, 0, 0)
    target = _FakeShip(5, 0, 0, radius=10.0)
    t = _torp_at(0, 0, 0, 10, 0, 0, src=src)

    monkeypatch.setattr(
        host_io, "ray_trace_mesh",
        lambda iid, origin, direction, max_dist: ((7.0, 7.0, 7.0), (0.0, 0.0, -1.0), 1.0))

    instance_sentinel = object()
    hits = update_all(
        dt=0.1, all_ships=[src, target],
        ship_instances={target: instance_sentinel},
    )
    assert len(hits) == 1
    _, ship, hit_point, hit_normal = hits[0]
    assert ship is target
    assert hit_point.x == pytest.approx(7.0)
    assert hit_point.y == pytest.approx(7.0)
    assert hit_point.z == pytest.approx(7.0)
    # Mesh trace also carries the surface normal through to the hit tuple.
    assert hit_normal.x == pytest.approx(0.0)
    assert hit_normal.y == pytest.approx(0.0)
    assert hit_normal.z == pytest.approx(-1.0)
