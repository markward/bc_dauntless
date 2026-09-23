"""A severed part's debris chunk must inherit the parent's render state.

REGRESSION (finding I2). `renderer.create_instance(model)` hands back an
instance with `Instance::world` at IDENTITY and `Instance::rim_eligible`
false. Left uncopied, that meant two live bugs:

  * no Fresnel rim -- the chunk read as a different material from the hull
    it just left (rim_eligible defaults false; planets and debris share
    that default on purpose, but a ship-hull chunk must not).
  * a one-frame flash at the world origin, in MODEL units, at scale 1
    (100x too big) -- `debris_chunk.tick` (which pushes the chunk's real,
    drifting transform) runs on the NEXT tick, and a severance triggered
    from inside `collisions.tick_collisions` happens AFTER this frame's
    `debris_chunk.tick` already ran.

The native voxel-chunk path (`host_bindings.cc`'s hull-split binding, ~line
4470) already copies world/visible/pass/comm_set_id/rim_eligible/
rim_strength/emissive_scale from parent to child for exactly this reason;
this mirrors it for the appendage-severance chunk, using what Python can
actually reach (there is no getter for a live instance's current pass /
comm_set_id / rim_eligible / rim_strength / visible -- see the fix report).
"""
import pytest

from engine.appc import part_detach_render
from engine.appc.math import TGPoint3, TGMatrix3


class _FakeRenderer:
    def __init__(self, model=77):
        self.model = model
        self.created = []
        self.world = {}
        self.visible = {}
        self.rim_eligible = {}
        self.rim_strength = {}
        self.emissive = {}

    def create_instance(self, model):
        iid = 900 + len(self.created)
        self.created.append(model)
        return iid

    def set_world_transform(self, iid, mat):
        self.world[iid] = mat

    def set_visible(self, iid, v):
        self.visible[iid] = v

    def set_rim_eligible(self, iid, v):
        self.rim_eligible[iid] = v

    def set_rim_strength(self, iid, v):
        self.rim_strength[iid] = v

    def set_emissive_scale(self, iid, v):
        self.emissive[iid] = v


class _Ship:
    """Stands in for a ShipClass. Mirrors only the surface _spawn_chunk touches."""

    def __init__(self):
        self._articulation_leaf = "birdofprey"
        self._loc = TGPoint3(10.0, 20.0, 30.0)
        self._rot = TGMatrix3()

    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetVelocity(self): return TGPoint3(0.0, 0.0, 0.0)
    def GetScale(self): return 1.0
    def GetMass(self): return 4000.0
    def GetSpecularKs(self): return None


@pytest.fixture
def fr(monkeypatch):
    from engine import renderer as real_renderer, host_io
    from engine.appc import debris_chunk

    fake = _FakeRenderer()
    monkeypatch.setattr(real_renderer, "create_instance", fake.create_instance)
    monkeypatch.setattr(real_renderer, "set_world_transform", fake.set_world_transform)
    monkeypatch.setattr(real_renderer, "set_visible", fake.set_visible)
    monkeypatch.setattr(real_renderer, "set_rim_eligible", fake.set_rim_eligible)
    monkeypatch.setattr(real_renderer, "set_rim_strength", fake.set_rim_strength)
    monkeypatch.setattr(real_renderer, "set_emissive_scale", fake.set_emissive_scale)
    monkeypatch.setattr(host_io, "instance_model", lambda iid: fake.model)
    monkeypatch.setattr(host_io, "set_instance_node_hidden", lambda *a, **k: True)
    monkeypatch.setattr(debris_chunk, "spawn", lambda *a, **k: None)
    return fake


def test_the_chunk_gets_the_parents_world_pose_not_identity(fr):
    """REGRESSION: was IDENTITY (origin, scale 1) -- 100x too big at (0,0,0)."""
    ship = _Ship()
    part_detach_render._spawn_chunk(ship, ship_iid=1, part_name="left wing01")

    chunk_iid = 900
    assert chunk_iid in fr.world, "the chunk must get an explicit world transform"
    mat = fr.world[chunk_iid]
    assert (mat[3], mat[7], mat[11]) == pytest.approx((10.0, 20.0, 30.0)), (
        "translation must match the parent ship's world location")
    assert mat[0] == pytest.approx(0.01), (
        "scale must be BC_MODEL_SCALE, not the create_instance default of 1.0")


def test_the_chunk_is_rim_eligible(fr):
    """REGRESSION: was False -- the chunk had no Fresnel rim, a visibly
    different material from the hull it just left."""
    ship = _Ship()
    part_detach_render._spawn_chunk(ship, ship_iid=1, part_name="left wing01")

    chunk_iid = 900
    assert fr.rim_eligible.get(chunk_iid) is True


def test_the_chunk_is_visible_and_normally_lit(fr):
    ship = _Ship()
    part_detach_render._spawn_chunk(ship, ship_iid=1, part_name="left wing01")

    chunk_iid = 900
    assert fr.visible.get(chunk_iid) is True
    assert fr.emissive.get(chunk_iid) == pytest.approx(1.0)
