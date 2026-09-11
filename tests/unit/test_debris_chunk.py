"""A detached hull chunk is a persistent, tumbling, colliding body."""
import math
import pytest

from engine.appc.math import TGPoint3, TGMatrix3


class _FakeRenderer:
    def __init__(self):
        self.transforms = {}
        self.destroyed = []

    def set_world_transform(self, iid, mat):
        self.transforms[iid] = mat

    def destroy_instance(self, iid):
        self.destroyed.append(iid)


class _Parent:
    def __init__(self):
        self._loc = TGPoint3(10.0, 0.0, 0.0)
        self._rot = TGMatrix3()
        self._vel = TGPoint3(1.0, 0.0, 0.0)

    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetVelocity(self): return self._vel
    def GetMass(self): return 120.0
    def GetScale(self): return 1.0


@pytest.fixture(autouse=True)
def _clean():
    from engine.appc import debris_chunk as dc
    dc.clear(_FakeRenderer())
    yield
    dc.clear(_FakeRenderer())


def _spawn(dc, iid=101, cells=200, centroid=(2.0, 0.0, 0.0), radius=0.5, rng=None):
    return dc.spawn(iid, _Parent(), cells, centroid, radius,
                    parent_mass=120.0, parent_occupied_cells=1000, rng=rng)


def test_spawn_places_the_chunk_on_the_parent_and_pushes_it_away():
    from engine.appc import debris_chunk as dc
    c = _spawn(dc)
    assert c.GetWorldLocation().x == 10.0            # parent's position
    assert c.GetMass() == pytest.approx(120.0 * 200 / 1000)
    assert c.GetRadius() == 0.5
    v = c.GetVelocity()
    # parent velocity (1,0,0) + separation along centre->centroid (+x)
    assert v.x == pytest.approx(1.0 + dc.kChunkSeparationSpeed)
    assert v.y == 0.0 and v.z == 0.0
    w = c._current_angular_velocity
    assert math.sqrt(w.x * w.x + w.y * w.y + w.z * w.z) == pytest.approx(dc.kChunkTumbleRate)
    assert c.IsImmobile() is False
    assert c.GetHull() is None


def test_tick_integrates_position_and_pushes_a_transform():
    from engine.appc import debris_chunk as dc
    r = _FakeRenderer()
    c = _spawn(dc)
    x0 = c.GetWorldLocation().x
    dc.tick(0.5, r)
    assert c.GetWorldLocation().x == pytest.approx(x0 + 0.5 * (1.0 + dc.kChunkSeparationSpeed))
    assert c.iid in r.transforms


def test_tick_rotates_by_angular_velocity():
    from engine.appc import debris_chunk as dc
    c = _spawn(dc)
    c._current_angular_velocity = TGPoint3(0.0, 0.0, math.pi / 2)   # yaw 90deg/s
    before = c.GetWorldRotation().GetCol(1)
    dc.tick(1.0, _FakeRenderer())
    after = c.GetWorldRotation().GetCol(1)
    # forward has rotated ~90 degrees about the body Z axis
    dot = before.x * after.x + before.y * after.y + before.z * after.z
    assert abs(dot) < 1e-3


def test_cap_evicts_the_oldest_and_destroys_its_instance():
    from engine.appc import debris_chunk as dc
    r = _FakeRenderer()
    first = _spawn(dc, iid=1000)
    for i in range(dc.kMaxLiveChunks):
        _spawn(dc, iid=2000 + i)
    dc.tick(0.0, r)   # eviction is applied on tick so the renderer is in hand
    assert first not in dc.live()
    assert 1000 in r.destroyed
    assert len(dc.live()) == dc.kMaxLiveChunks


def test_clear_destroys_every_instance():
    from engine.appc import debris_chunk as dc
    r = _FakeRenderer()
    _spawn(dc, iid=1); _spawn(dc, iid=2)
    dc.clear(r)
    assert dc.live() == []
    assert sorted(r.destroyed) == [1, 2]


def test_chunks_are_collidable_and_take_impulses():
    # Correction 2: the ship must be a REAL ShipClass built the way
    # tests/unit/test_collisions.py's _ship() helper does it -- the _Parent
    # fake is not a ShipClass and would be classified immovable. And the
    # ship sits at x=0.7, not 0.8: with both radii 0.5 and
    # COLLISION_RADIUS_SCALE 0.8 the effective boundary is 0.8, and
    # dist2 >= sum_r*sum_r at exactly 0.8 is NOT an overlap.
    from engine.appc.ships import ShipClass
    from engine.appc import debris_chunk as dc
    from engine.appc.collisions import _resolve_body, _respond_pair
    c = _spawn(dc, centroid=(0.0, 0.0, 0.0))
    c._loc = TGPoint3(0.0, 0.0, 0.0)
    c._vel = TGPoint3(+2.0, 0.0, 0.0)
    ship = ShipClass()
    ship.SetTranslateXYZ(0.7, 0.0, 0.0)
    ship.SetRadius(0.5)
    ship.SetMass(120.0)
    ship.SetVelocity(TGPoint3(-2.0, 0.0, 0.0))
    hit = _respond_pair(_resolve_body(c), _resolve_body(ship))
    assert hit is not None
    assert c.__dict__.get("_collision_velocity") is not None   # impulse landed


def test_iter_collidables_yields_live_chunks():
    from engine.appc import debris_chunk as dc
    from engine.appc.collisions import iter_collidables
    c = _spawn(dc)
    assert c in list(iter_collidables())
