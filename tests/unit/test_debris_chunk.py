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
    def GetRadius(self): return 3.0
    def GetObjID(self): return 4242


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
    # I1: the chunk's location is the PIECE's centre -- parent location plus
    # the body-frame centroid rotated into world (identity here), not the
    # parent's origin. Rotation then happens about the piece, not about a
    # point 2 GU away from it.
    assert c.GetWorldLocation().x == pytest.approx(12.0)
    assert c.GetWorldLocation().y == 0.0 and c.GetWorldLocation().z == 0.0
    assert c.GetMass() == pytest.approx(120.0 * 200 / 1000)
    assert c.GetRadius() == 0.5
    assert c.GetScale() == 1.0
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


def test_tick_collisions_runs_end_to_end_with_a_live_chunk():
    # C1: DebrisChunk has no transform-store slot (`_xform`), and
    # iter_collidables() yields live chunks, so resolve_collisions' bulk
    # get_positions([o._xform ...]) raised AttributeError on the first
    # spawned chunk -- inside tick_collisions, which host_loop.run() does not
    # guard, so the frame loop exited. This drives the real per-frame entry
    # point with a REAL ShipClass registered in a live set plus one chunk.
    import App
    from engine.appc.ships import ShipClass
    from engine.appc import debris_chunk as dc, collisions
    App.g_kSetManager._sets.clear()
    try:
        pSet = App.SetClass_Create()
        App.g_kSetManager.AddSet(pSet, "test")
        ship = ShipClass()
        ship.SetTranslateXYZ(50.0, 0.0, 0.0)
        ship.SetRadius(1.0)
        ship.SetMass(120.0)
        ship.SetVelocity(TGPoint3(0.0, 0.0, 0.0))
        pSet.AddObjectToSet(ship, "Ship")
        chunk = _spawn(dc)
        assert chunk in list(collisions.iter_collidables())
        hits = collisions.tick_collisions(1.0 / 60.0, {})
        assert hits == []                     # far apart: ran, nothing hit
    finally:
        App.g_kSetManager._sets.clear()


def test_spawn_rotates_the_centroid_into_world():
    from engine.appc import debris_chunk as dc
    parent = _Parent()
    parent._rot.MakeRotation(math.pi / 2, TGPoint3(0.0, 0.0, 1.0))   # yaw 90deg
    c = dc.spawn(7, parent, 200, (2.0, 0.0, 0.0), 0.5,
                 parent_mass=120.0, parent_occupied_cells=1000)
    loc = c.GetWorldLocation()
    # body +x under a 90deg yaw lands on world +/-y, never on +x
    assert loc.x == pytest.approx(10.0, abs=1e-6)
    assert abs(loc.y) == pytest.approx(2.0, abs=1e-6)


def test_pure_yaw_tumbles_in_place_and_swings_the_mesh_origin():
    # I1: with zero velocity and a pure yaw, the piece's centre (_loc) must
    # NOT move -- the old code rotated about the model origin, so a nacelle
    # 2 GU out orbited at ~0.8 GU/s. The pushed matrix's translation is the
    # MESH origin (_loc - R.centroid), which does swing round the fixed
    # centroid as R turns.
    from engine.appc import debris_chunk as dc
    r = _FakeRenderer()
    c = _spawn(dc)
    c._vel = TGPoint3(0.0, 0.0, 0.0)
    c._current_angular_velocity = TGPoint3(0.0, 0.0, math.pi / 2)
    dc.tick(0.0, r)
    m0 = list(r.transforms[c.iid])
    loc0 = c.GetWorldLocation()
    # mesh origin sits at _loc - centroid (identity R): 12 - 2 = 10
    assert (m0[3], m0[7], m0[11]) == pytest.approx((10.0, 0.0, 0.0))
    dc.tick(1.0, r)
    loc1 = c.GetWorldLocation()
    assert (loc1.x, loc1.y, loc1.z) == pytest.approx((loc0.x, loc0.y, loc0.z))
    m1 = list(r.transforms[c.iid])
    assert (m1[3], m1[7], m1[11]) != pytest.approx((m0[3], m0[7], m0[11]))
    # ...and by exactly the centroid's length: the origin stays 2 GU from
    # the fixed centroid.
    d = math.sqrt((m1[3] - loc1.x) ** 2 + (m1[7] - loc1.y) ** 2 + (m1[11] - loc1.z) ** 2)
    assert d == pytest.approx(2.0)


def _real_parent():
    from engine.appc.ships import ShipClass
    p = ShipClass()
    p.SetTranslateXYZ(0.0, 0.0, 0.0)
    p.SetRadius(3.0)
    p.SetMass(120.0)
    p.SetVelocity(TGPoint3(0.0, 0.0, 0.0))
    return p


def test_fresh_chunk_never_grinds_its_parent(monkeypatch):
    # I2: a chunk spawns INSIDE the parent's sphere and recedes at 0.15 GU/s,
    # so without a mask the grind channel abrades the parent for ~20 s.
    from engine.appc import debris_chunk as dc, collisions, combat
    hits = []
    monkeypatch.setattr(combat, "apply_hit", lambda *a, **k: hits.append(a))
    parent = _real_parent()
    c = dc.spawn(5, parent, 200, (1.0, 0.0, 0.0), 0.5,
                 parent_mass=120.0, parent_occupied_cells=1000)
    assert parent.GetObjID() in collisions._collision_disabled_ids(c)
    for _ in range(120):
        collisions.resolve_collisions([parent, c], dt=1.0 / 60.0)
    assert hits == []


def test_mask_clears_once_the_chunk_is_clear_of_the_parent():
    from engine.appc import debris_chunk as dc, collisions
    r = _FakeRenderer()
    parent = _real_parent()
    c = dc.spawn(5, parent, 200, (1.0, 0.0, 0.0), 0.5,
                 parent_mass=120.0, parent_occupied_cells=1000)
    dc.tick(1.0 / 60.0, r)
    assert parent.GetObjID() in collisions._collision_disabled_ids(c)   # still inside
    clear_dist = (c.GetRadius() + parent.GetRadius()) * collisions.COLLISION_RADIUS_SCALE
    c._loc = TGPoint3(clear_dist + 0.01, 0.0, 0.0)
    dc.tick(0.0, r)
    assert collisions._collision_disabled_ids(c) == frozenset()


def test_mask_clears_when_the_parent_is_gone():
    # The parent is held by weakref (a chunk outlives its parent by design).
    # A plain fake here, not a ShipClass: the ObjID registry
    # (engine/core/ids.py) pins every real object, so one can never be
    # collected inside a test.
    import gc
    from engine.appc import debris_chunk as dc, collisions
    r = _FakeRenderer()
    parent = _Parent()
    c = dc.spawn(5, parent, 200, (1.0, 0.0, 0.0), 0.5,
                 parent_mass=120.0, parent_occupied_cells=1000)
    assert c.origin_ship is parent            # weakref, dereferenced
    assert parent.GetObjID() in collisions._collision_disabled_ids(c)
    del parent
    gc.collect()
    assert c.origin_ship is None
    dc.tick(0.0, r)
    assert collisions._collision_disabled_ids(c) == frozenset()


def _impacting_ship_and_chunk(dc):
    from engine.appc.ships import ShipClass
    c = _spawn(dc, centroid=(0.0, 0.0, 0.0))
    c._loc = TGPoint3(0.0, 0.0, 0.0)
    c._vel = TGPoint3(+2.0, 0.0, 0.0)
    ship = ShipClass()
    ship.SetTranslateXYZ(0.7, 0.0, 0.0)
    ship.SetRadius(0.5)
    ship.SetMass(120.0)
    ship.SetVelocity(TGPoint3(-2.0, 0.0, 0.0))
    return ship, c


def test_a_chunk_impact_posts_no_collision_event(monkeypatch):
    # I3: MissionLib.FriendlyFireCollisionHandler does ObjectClass_Cast on
    # both parties and calls .GetName() on the result OUTSIDE its try; a
    # DebrisChunk casts to None, so an ET_OBJECT_COLLISION with a chunk party
    # is a traceback in every friendly-fire mission. The impact still lands
    # (impulse + damage) -- only the event is withheld.
    from engine.appc import debris_chunk as dc, collisions
    posted = []
    monkeypatch.setattr(collisions, "_emit_object_collision",
                        lambda *a, **k: posted.append(a))
    cloaked = []
    monkeypatch.setattr(collisions, "_emit_cloaked_collision",
                        lambda *a, **k: cloaked.append(a))
    ship, c = _impacting_ship_and_chunk(dc)
    hit = collisions._respond_pair(collisions._resolve_body(c),
                                   collisions._resolve_body(ship))
    assert hit is not None
    assert posted == [] and cloaked == []
    # ...and with the chunk on the B side too
    ship2, c2 = _impacting_ship_and_chunk(dc)
    hit = collisions._respond_pair(collisions._resolve_body(ship2),
                                   collisions._resolve_body(c2))
    assert hit is not None
    assert posted == [] and cloaked == []


def test_a_ship_ship_impact_still_posts_the_collision_event(monkeypatch):
    from engine.appc.ships import ShipClass
    from engine.appc import collisions
    posted = []
    monkeypatch.setattr(collisions, "_emit_object_collision",
                        lambda *a, **k: posted.append(a))
    a = ShipClass(); a.SetTranslateXYZ(0.0, 0.0, 0.0); a.SetRadius(0.5)
    a.SetMass(120.0); a.SetVelocity(TGPoint3(+2.0, 0.0, 0.0))
    b = ShipClass(); b.SetTranslateXYZ(0.7, 0.0, 0.0); b.SetRadius(0.5)
    b.SetMass(120.0); b.SetVelocity(TGPoint3(-2.0, 0.0, 0.0))
    hit = collisions._respond_pair(collisions._resolve_body(a),
                                   collisions._resolve_body(b))
    assert hit is not None
    assert len(posted) == 1


def test_mission_swap_destroys_every_chunk_through_the_controllers_renderer():
    # host_loop._drain_pending_swap must clear chunks through
    # self.renderer -- the one every other reset on that path uses -- so
    # the instance destroy is observable here, not sent to a module-level
    # alias that may be something else entirely.
    from engine.host_loop import HostController, MissionSession
    from engine.appc import debris_chunk as dc

    class _StubLoader:
        def load(self, name):
            return MissionSession(mission_name=name)

    r = _FakeRenderer()
    _spawn(dc, iid=31); _spawn(dc, iid=32)
    h = HostController()
    h.renderer = r
    h.loader = _StubLoader()
    h.session = MissionSession(mission_name="prev")
    h.swap_mission("Next.Mission")
    h._drain_pending_swap()
    assert dc.live() == []
    assert sorted(r.destroyed) == [31, 32]
