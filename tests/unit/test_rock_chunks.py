"""Rock breakup chunks: chunk specs -> rendered, tumbling, colliding bodies
(rock-class spec §2)."""
import math

import App
import pytest

from tests.helpers.viewed_set import viewed_set, release_viewed_set
from tests.unit.test_rock_class import _make


class FakeRenderer:
    def __init__(self):
        self.loaded, self.created, self.flags = [], [], []
        self.transforms = {}
        self._next = 21

    def load_model(self, path, search, reps=None, decals=None, scale=1.0):
        self.loaded.append((path, scale))
        return 11

    def create_instance(self, handle):
        self.created.append(handle)
        self._next += 1
        return self._next

    def set_surface_rock(self, iid, v): self.flags.append((iid, v))
    def set_world_transform(self, iid, m): self.transforms[iid] = m
    def set_visible(self, iid, v): pass
    def destroy_instance(self, iid): pass


@pytest.fixture(autouse=True)
def _clean():
    from engine.appc import debris_chunk
    debris_chunk.clear(FakeRenderer())
    yield
    debris_chunk.clear(FakeRenderer())
    release_viewed_set()
    if App.g_kSetManager.GetSet("RockTest") is not None:
        App.g_kSetManager.DeleteSet("RockTest")


def _spec(radius=0.3, seed="Asteroid 5b#3", pSet=None, ghost_peers=()):
    from engine.rocks import death
    return death.ChunkSpec("silicate", seed, radius, 5.0, (1.0, 0.0, 0.0),
                           (0.1, 0.0, 0.0), (0.0, 0.2, 0.0), pSet, ghost_peers)


def test_chunk_spec_becomes_rendered_tumbling_body():
    from engine.appc import debris_chunk
    from engine.rocks import chunks, death

    r = FakeRenderer()
    death._chunk_specs.append(death.ChunkSpec(
        "silicate", "Asteroid 5b#3", 0.3, 5.0, (1.0, 0.0, 0.0),
        (0.1, 0.0, 0.0), (0.0, 0.2, 0.0), None))
    chunks.pump(r, session=None)
    assert r.loaded and "/fragments/silicate_" in r.loaded[0][0].replace("\\", "/")
    assert r.created == [11]
    assert (22, True) in r.flags
    live = debris_chunk.live()
    assert any(c.iid == 22 and abs(c.radius - 0.3) < 1e-9 for c in live)
    assert death.drain_chunk_specs() == []


def test_chunk_renders_at_its_radius_from_the_first_frame():
    """Every ship draws at BC_MODEL_SCALE x scale; the fragment loads at
    scale 1, where its bound radius is bound_radius_m / 1.75 model units. So
    (matrix column length) x (model bound radius) is the drawn radius in GU,
    and must equal radius_gu -- pushed at spawn, not a frame later."""
    from engine.rocks import catalogue, chunks, death
    r = FakeRenderer()
    death._chunk_specs.append(_spec(radius=0.3, pSet=viewed_set()))
    chunks.pump(r, session=None)
    (path, load_scale), = r.loaded
    rock = next(x for x in catalogue.load() if path in x.lod_paths)
    m = r.transforms[22]                          # row-major 4x4, flat
    col0 = math.sqrt(m[0] ** 2 + m[4] ** 2 + m[8] ** 2)
    model_radius = rock.bound_radius_m * catalogue.MODEL_UNITS_PER_METRE * load_scale
    assert col0 * model_radius == pytest.approx(0.3, rel=1e-6)


def test_chunks_share_one_model_load_per_fragment_and_quantise_radius():
    from engine.appc import debris_chunk
    from engine.rocks import chunks, death
    r = FakeRenderer()
    death._chunk_specs.append(_spec(radius=0.3))
    death._chunk_specs.append(_spec(radius=0.2345))
    chunks.pump(r, session=None)
    assert r.loaded[0] == r.loaded[1]             # same fragment, same load
    radii = sorted(c.radius for c in debris_chunk.live())
    assert radii == [0.23, 0.3]                   # 2 significant figures


def _in_set(obj, name):
    pSet = App.g_kSetManager.GetSet("RockTest")
    if pSet is None:
        pSet = App.SetClass_Create()
        App.g_kSetManager.AddSet(pSet, "RockTest")
    pSet.AddObjectToSet(obj, name)
    return pSet


def _masked(x, y):
    from engine.appc.collisions import _collision_disabled_ids
    return (y.GetObjID() in _collision_disabled_ids(x)
            or x.GetObjID() in _collision_disabled_ids(y))


def _chunk_breakup():
    from engine.appc import debris_chunk
    from engine.rocks import breakup, chunks, death
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(2.0)                 # "Asteroid 5b" at 2.0: majors + chunks
    pSet = _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    n = sum(1 for p in breakup.plan("Asteroid 5b", 2.0) if p.tier == "major")
    majors = [pSet.GetObject("Asteroid 5b-%d" % i) for i in range(1, n + 1)]
    r = FakeRenderer()
    chunks.pump(r, session=None)
    return rock, pSet, majors, debris_chunk.live(), r


def _still(chunks_):
    from engine.appc.math import TGPoint3
    for c in chunks_:
        c._vel = TGPoint3(0.0, 0.0, 0.0)


def _assert_all_masked(rock, majors, live, want):
    for i, c in enumerate(live):
        assert _masked(c, rock) is want
        for m in majors:
            assert _masked(c, m) is want
        for d in live[i + 1:]:
            assert _masked(c, d) is want


def test_chunks_ghost_their_breakup_while_overlapping():
    """Carried ruling, tuned after live test 2026-10-01: chunks of one
    breakup ignore each other, the parent and its major pieces until their
    contact spheres are clear, not for a fixed 1 s."""
    from engine.appc import debris_chunk
    rock, pSet, majors, live, r = _chunk_breakup()
    assert len(live) >= 2 and majors
    for c in live:
        assert c.GetContainingSet() is pSet
    _assert_all_masked(rock, majors, live, True)
    _still(live)
    for _ in range(150):                # 2.5 s, nothing moves
        debris_chunk.tick(1.0 / 60.0, r)
    assert _masked(live[0], live[1]) and _masked(live[0], majors[0])


def test_chunks_unmask_within_one_tick_of_separating():
    from engine.appc import debris_chunk
    from engine.appc.math import TGPoint3
    rock, pSet, majors, live, r = _chunk_breakup()
    _still(live)
    debris_chunk.tick(1.0 / 60.0, r)
    assert _masked(live[0], live[1])
    for i, o in enumerate(majors + live):
        o.SetTranslateXYZ(100.0 * (i + 1), 0.0, 0.0)
    debris_chunk.tick(1.0 / 60.0, r)
    _assert_all_masked(rock, majors, live, False)


def test_chunk_ghost_cap_forces_unmask():
    from engine.appc import debris_chunk
    from engine.rocks import breakup
    rock, pSet, majors, live, r = _chunk_breakup()
    _still(live)
    debris_chunk.tick(breakup.kGhostMaxTime - 0.01, r)
    assert _masked(live[0], live[1])
    debris_chunk.tick(0.02, r)
    _assert_all_masked(rock, majors, live, False)


def test_chunk_ghost_drops_a_peer_that_is_gone():
    from engine.appc import debris_chunk
    rock, pSet, majors, live, r = _chunk_breakup()
    _still(live)
    pSet.DeleteObjectFromSet(majors[0].GetName())
    debris_chunk.tick(1.0 / 60.0, r)                # must not raise
    for c in live:
        assert majors[0] not in c._ghost_peers


def test_spawn_body_registers_a_colliding_body():
    from engine.appc import collisions, debris_chunk
    from engine.appc.math import TGMatrix3, TGPoint3
    R = TGMatrix3()
    R.MakeIdentity()
    c = debris_chunk.spawn_body(
        9, loc=TGPoint3(1.0, 2.0, 3.0), rot=R, vel=TGPoint3(0.0, 0.0, 0.0),
        angular=TGPoint3(0.0, 0.0, 0.0), mass=5.0, radius=0.3, scale=2.0)
    assert c in debris_chunk.live()
    assert c in list(collisions.iter_collidables())
    assert (c.GetMass(), c.GetRadius(), c.GetScale()) == (5.0, 0.3, 2.0)
    assert c.component_cells == 0
    debris_chunk.tick(0.1, FakeRenderer())         # sentinel origin is safe


def test_host_frame_pumps_rock_breakup_after_collisions():
    """The frame loop (render-side, not run headless) drains both queues right
    after collisions, so a rock killed by a collision this frame bursts and
    sheds its chunks this frame."""
    import inspect
    from engine import host_loop
    src = inspect.getsource(host_loop)
    at = src.index('frame_profiler.scope("sim.collisions")')
    scope = src.index('frame_profiler.scope("sim.rock_breakup")', at)
    assert src.index("rock_vfx.pump()", scope) < src.index("rock_chunks.pump(r, session)", scope)
    assert scope - at < 600           # immediately after, not somewhere later
