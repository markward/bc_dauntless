"""Every ship's render instance is given its SIM source (phase 3a).

`_sync_instance_transforms` pushes each ship's transform-store slot, its
uniform scale (`model_scale * GetScale()`) and its per-set VIEW offset through
`host_io.set_instance_sim_source`, so the gameplay point queries (mesh traces,
world_to_body, decals, hull damage, surface points) read the simulation pose
while the renderer draws the interpolated one. The push is guarded on the
last value sent, like the store binding, so a steady ship costs no crossing.

The binding is stubbed at the engine.host_io seam; the native half is pinned
by tests/host/test_sim_pose_hit_tests.py.
"""
import inspect
import re

import pytest

from engine import host_io, host_loop
from engine.core.native_transform_buffer import NativeTransformBuffer
from engine.systems import frames
from tests.unit.test_render_transform_binding import _FakeRenderer, _Obj

ZERO = (0.0, 0.0, 0.0)


@pytest.fixture
def sources(monkeypatch):
    """Record every set_instance_sim_source call; stub the store binding."""
    calls = []

    def _stub(iid, index, generation, scale, view_offset):
        calls.append((iid, index, generation, scale, tuple(view_offset)))
        return True

    monkeypatch.setattr(host_io, "set_instance_sim_source", _stub)
    monkeypatch.setattr(host_io, "set_instance_transform_slot",
                        lambda *a: True)
    return calls


def _scene():
    player, other = _Obj(), _Obj(x=40.0)
    session = host_loop.MissionSession("t")
    session.ship_instances[player] = 1
    session.ship_instances[other] = 2
    session.player = player
    return session, player, other


def _sync(session, player):
    host_loop._sync_instance_transforms(
        _FakeRenderer(), session, player, NativeTransformBuffer(), 0.5,
        game_time=1.0, model_scale=2.0)


def test_every_ship_gets_its_slot_scale_and_view_offset(sources):
    session, player, _other = _scene()
    _sync(session, player)
    assert set(sources) == {(1, 7, 1, 2.0, ZERO), (2, 7, 1, 2.0, ZERO)}
    assert len(sources) == 2


def test_sim_source_is_pushed_only_on_change(sources):
    session, player, other = _scene()
    _sync(session, player)
    _sync(session, player)
    assert len(sources) == 2, "re-pushed an unchanged sim source"
    other.GetScale = lambda: 3.0
    _sync(session, player)
    assert sources[2:] == [(2, 7, 1, 6.0, ZERO)]


def test_the_guard_is_pruned_with_the_instance(sources):
    session, player, other = _scene()
    _sync(session, player)
    del session.ship_instances[other]
    _sync(session, player)
    assert 2 not in session.sim_sources
    assert 1 in session.sim_sources


def test_a_sibling_region_ship_gets_frames_view_offset(sources, monkeypatch):
    """An in-space cutscene rendered at Ona2 while the player is in Ona1:
    the pushed offset must be exactly the one combat._resolve_hit_point
    shifts the ray by, or every mesh trace on that ship misses."""
    session, player, other = _scene()
    shift = (1000.0, -5.0, 2.5)
    monkeypatch.setattr(frames, "viewing_set", lambda: "ona1")
    monkeypatch.setattr(frames, "containing_set",
                        lambda obj: "ona2" if obj is other else "ona1")
    monkeypatch.setattr(frames, "offset_between",
                        lambda a, b: ZERO if a == b else shift)
    _sync(session, player)
    want = frames.view_offset(frames.containing_set(other))
    assert want == shift
    assert (2, 7, 1, 2.0, want) in sources
    assert (1, 7, 1, 2.0, ZERO) in sources


def test_mark_sim_source_pushes_even_over_a_stale_guard(sources):
    """Realize always pushes: a recycled instance id must not look already
    sourced (a fresh native instance starts with no source)."""
    session, player, _other = _scene()
    session.sim_sources[1] = (7, 1, 2.0, ZERO)
    host_loop._mark_sim_source(session, player, 1, 2.0)
    assert sources == [(1, 7, 1, 2.0, ZERO)]
    assert session.sim_sources[1] == (7, 1, 2.0, ZERO)


def test_both_realize_sites_mark_the_sim_source():
    src = inspect.getsource(host_loop)
    calls = [m.start() for m in re.finditer(r"^\s+_mark_rigged\(", src,
                                            re.MULTILINE)]
    assert len(calls) == 2, "expected exactly two realize sites"
    for at in calls:
        nxt = src[at:].splitlines()[1].strip()
        assert nxt.startswith("_mark_sim_source("), nxt


def test_hull_discharge_samples_the_drawn_hull():
    """The discharge sparks are VFX drawn on the hull the player sees."""
    src = inspect.getsource(host_loop)
    assert re.search(r"r\.instance_surface_points\(\s*_piid,\s*drawn=True\)",
                     src)


def test_spv_decal_pick_asks_for_the_drawn_pose(monkeypatch):
    """The SPV places a decal where the author clicked on the DRAWN hull."""
    import math
    from engine.manual_aim import AimCamera
    from engine.ui.spv_decals_pane import DecalsPaneMixin

    class _Pane(DecalsPaneMixin):
        def __init__(self):
            self._ship_getter = lambda: _Obj()
            self.camera = AimCamera(
                eye=(0.0, -20.0, 0.0), target=(0.0, 0.0, 0.0),
                up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(45.0),
                near=1.0, far=5000.0)

        def _decal_iid(self):
            return 9

    seen = {}

    def _trace(iid, origin, direction, max_dist, **kw):
        seen["trace"] = kw
        return ((0.0, -1.0, 0.0), (0.0, -1.0, 0.0), 19.0)

    def _w2b(iid, p, n, **kw):
        seen["w2b"] = kw
        return ((0.0, -1.0, 0.0), (0.0, -1.0, 0.0))

    monkeypatch.setattr(host_io, "ray_trace_mesh_pick", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "ray_trace_mesh", _trace)
    monkeypatch.setattr(host_io, "world_to_body", _w2b)
    hit = _Pane()._decal_hull_hit(320.0, 240.0, (640, 480))
    assert hit is not None
    assert seen["trace"] == {"drawn": True}
    assert seen["w2b"] == {"drawn": True}
