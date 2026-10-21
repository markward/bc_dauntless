"""after_wear: the gate and the spawn path a severed piece goes through.

hull_breakup used to have a carve twin (after_carve over hull_split_detached);
the tests that pinned the shared parts of that path -- which ships may shed at
all, sub-floor bursts, the bounds-based subsystem kill and the orphaned-chunk
cleanup -- now drive the plating-wear path (after_wear over hull_split_parts),
which is the only one. The rest of after_wear is pinned by
tests/unit/test_hull_breakup_parts.py."""
import pytest

from engine import host_io
from engine.appc.math import TGPoint3, TGMatrix3


class _Sub:
    def __init__(self, pos, name):
        self._pos = pos; self.name = name; self.condition = 100.0
    def GetPosition(self): return self._pos
    def GetName(self): return self.name
    def SetCondition(self, v): self.condition = v
    def IsDestroyed(self): return self.condition <= 0.0


class _Ship:
    def __init__(self, radius=3.5, subs=()):
        self._r = radius; self._subs = list(subs)
        self._loc = TGPoint3(0, 0, 0); self._rot = TGMatrix3()
        self._articulation_poses = {}
    def GetRadius(self): return self._r
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetVelocity(self): return TGPoint3(0, 0, 0)
    def GetMass(self): return 120.0
    def GetScale(self): return 1.0
    def GetHull(self): return None
    def _iter_subsystems(self): return iter(self._subs)


@pytest.fixture(autouse=True)
def _clean():
    from engine.appc import debris_chunk as dc, damage_geometry as dg
    from engine.appc import hull_breakup
    class _R:
        def set_world_transform(self, *a): pass
        def destroy_instance(self, *a): pass
    dc.clear(_R()); dg.reset(); hull_breakup.reset()
    yield
    dc.clear(_R()); dg.reset(); hull_breakup.reset()


def _piece(iid, voxels, centroid, lo, hi, total=1500):
    return {"parts": [0], "instance_id": iid, "voxels": voxels,
            "total_voxels": total, "centroid": centroid,
            "bounds_min": lo, "bounds_max": hi, "radius_gu": 0.5}


def _split(monkeypatch, pieces):
    monkeypatch.setattr(host_io, "hull_split_parts", lambda iid: list(pieces))


def test_a_shuttle_never_sheds(monkeypatch):
    """The Shuttle is the ONLY stock hull below the gate since 2026-09-23 (the
    floor moved 2.381 -> 0.6). This used to be a Galor, which now sheds."""
    from engine.appc import hull_breakup
    _split(monkeypatch, [_piece(9, 500, (1, 0, 0), (0.5, -.5, -.5), (1.5, .5, .5))])
    ship = _Ship(radius=0.141)                    # Shuttle: below the gate
    assert hull_breakup.after_wear(ship, 11) == []


def test_a_bird_of_prey_now_sheds(monkeypatch):
    """The ship the floor was lowered FOR. A regression restoring the old 2.381
    would leave every larger hull working while silently un-breaking this one."""
    from engine.appc import hull_breakup
    _split(monkeypatch, [_piece(9, 500, (1, 0, 0), (0.5, -.5, -.5), (1.5, .5, .5))])
    ship = _Ship(radius=1.335)                    # BirdOfPrey: above the gate
    assert len(hull_breakup.after_wear(ship, 11)) == 1


def test_a_severed_piece_becomes_a_chunk(monkeypatch):
    from engine.appc import hull_breakup, debris_chunk as dc
    _split(monkeypatch, [_piece(9, 500, (1, 0, 0), (0.5, -.5, -.5), (1.5, .5, .5))])
    ship = _Ship(radius=3.5)                      # Galaxy: above the gate
    chunks = hull_breakup.after_wear(ship, 11)
    assert len(chunks) == 1 and chunks[0].iid == 9
    assert chunks[0].GetMass() == pytest.approx(120.0 * 500 / 1500)
    assert chunks[0] in dc.live()


def test_a_piece_with_no_chunk_instance_bursts_instead(monkeypatch):
    from engine.appc import hull_breakup, debris_chunk as dc
    _split(monkeypatch, [_piece(None, 3, (1, 0, 0), (0.9, -.1, -.1), (1.1, .1, .1))])
    bursts = []
    monkeypatch.setattr(hull_breakup, "_burst", lambda ship, iid, c: bursts.append(c))
    assert hull_breakup.after_wear(_Ship(radius=3.5), 11) == []
    assert bursts == [(1, 0, 0)]
    assert dc.live() == []


def test_an_unlabelled_mount_dies_by_the_pieces_bounds(monkeypatch):
    """No part label at the mount (headless: structure_part_at is -1): the
    piece's bounds decide."""
    from engine.appc import hull_breakup
    inside = _Sub(TGPoint3(1.0, 0.0, 0.0), "Port Nacelle")
    outside = _Sub(TGPoint3(-1.0, 0.0, 0.0), "Bridge")
    ship = _Ship(radius=3.5, subs=[inside, outside])
    monkeypatch.setattr(host_io, "structure_part_at", lambda iid, p: -1)
    _split(monkeypatch, [_piece(9, 500, (1, 0, 0), (0.5, -.5, -.5), (1.5, .5, .5))])
    hull_breakup.after_wear(ship, 11)
    assert inside.IsDestroyed()
    assert not outside.IsDestroyed()


def test_nothing_severed_is_a_noop(monkeypatch):
    from engine.appc import hull_breakup, debris_chunk as dc
    _split(monkeypatch, [])
    assert hull_breakup.after_wear(_Ship(radius=3.5), 11) == []
    assert dc.live() == []


def test_a_spawn_failure_destroys_the_instance_the_native_side_already_made(monkeypatch):
    # hull_split_parts has ALREADY created the renderer instance by the time
    # Python spawns the body. If spawn raises, the instance must be destroyed,
    # not left orphaned (invisible to the cap, the clear, and the collision
    # system) for the rest of the mission.
    from engine import renderer
    from engine.appc import hull_breakup, debris_chunk as dc
    _split(monkeypatch, [_piece(9, 500, (1, 0, 0), (0.5, -.5, -.5), (1.5, .5, .5))])
    def _boom(*a, **k):
        raise RuntimeError("spawn failed")
    monkeypatch.setattr(dc, "spawn", _boom)
    destroyed = []
    monkeypatch.setattr(renderer, "destroy_instance", lambda iid: destroyed.append(iid))
    assert hull_breakup.after_wear(_Ship(radius=3.5), 11) == []
    assert destroyed == [9]
    assert dc.live() == []


def test_the_carve_half_is_gone():
    from engine.appc import hull_breakup
    for name in ("after_carve", "_check", "_pending", "_last_check"):
        assert not hasattr(hull_breakup, name), name
