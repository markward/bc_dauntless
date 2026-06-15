"""Torpedo motion: position += velocity*dt, age increments, TTL expires.
Homing: when target_ship is set and age < guidance_lifetime, velocity
turns toward the target up to max_angular_accel × dt.
Collision: sphere_hit against any ship except source; first hit wins.
"""
import pytest
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.projectiles import Torpedo, register, update_all, _active, _steer_toward
from engine.appc.subsystems import ShipSubsystem


class _RotShip:
    def __init__(self, loc, rot):
        self._loc, self._rot = loc, rot
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot


def test_steer_toward_homes_on_locked_subsystem():
    """Guidance must steer toward the locked subsystem's world position, not
    the target ship's hull centre, when the torpedo carries a subsystem lock."""
    R = TGMatrix3(); R.MakeIdentity()
    ship = _RotShip(TGPoint3(0.0, 0.0, 0.0), R)
    sub = ShipSubsystem("Port Nacelle")
    sub._position = TGPoint3(0.0, 50.0, 0.0)   # +50 in ship local Y
    sub.SetParentShip(ship)

    t = Torpedo()
    t._position = TGPoint3(100.0, 0.0, 0.0)
    t._velocity = TGPoint3(-10.0, 0.0, 0.0)    # heading straight at hull centre
    t._max_angular_accel = 10.0                # ample turn authority
    t._target_ship = ship
    t._target_subsystem = sub

    _steer_toward(t, ship, dt=0.05)
    # The subsystem at (0,50,0) is +Y of the hull centre; homing on it must
    # introduce a +Y velocity component (homing on the centre would not).
    assert t._velocity.y > 1e-6


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
    # subsystem_emitters._select_candidates (reached via _advance_combat ->
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


def test_torpedo_uses_host_ray_trace_mesh_when_supplied():
    """When host + ship_instances are supplied, hit_point comes from the
    mesh trace, not the post-advance position."""
    src = _FakeShip(-100, 0, 0)
    target = _FakeShip(5, 0, 0, radius=10.0)
    t = _torp_at(0, 0, 0, 10, 0, 0, src=src)

    class FakeHost:
        def ray_trace_mesh(self, iid, origin, direction, max_dist):
            return ((7.0, 7.0, 7.0), (0.0, 0.0, -1.0), 1.0)

    instance_sentinel = object()
    hits = update_all(
        dt=0.1, all_ships=[src, target],
        host=FakeHost(),
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
