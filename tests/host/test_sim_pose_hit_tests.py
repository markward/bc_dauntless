"""Gameplay point queries read the SIM pose, not the drawn one (phase 3a).

`set_instance_sim_source(iid, index, generation, scale, view_offset)` gives a
render instance its simulation pose: a transform-store slot, the uniform
scale and the per-set view offset. Every gameplay point query (mesh trace,
instance_translation, world_to_body, decals, hull damage, shield splash,
surface points) then composes the pose from the live store, while the drawn
pose (`world_linear` / `world_translation_d`, what set_world_transform last
pushed) stays what the renderer shows. Pick tools ask for the drawn pose
with `drawn=True`. No source, or a stale one, reads the drawn pose.
"""
import math
import os

import pytest

pytest.importorskip("_dauntless_host")

import _dauntless_host as _h  # noqa: E402

from engine import host_io, renderer  # noqa: E402
from engine.appc.math import TGMatrix3, TGPoint3  # noqa: E402
from engine.appc.objects import ObjectClass  # noqa: E402
from tests.helpers import bc_assets  # noqa: E402

GALAXY_NIF = bc_assets.GAME_ROOT / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = bc_assets.GAME_ROOT / "data" / "Models" / "SharedTextures" / "FedShips" / "High"


def _translation_mat(x, y, z, s=1.0):
    return [s, 0.0, 0.0, x,
            0.0, s, 0.0, y,
            0.0, 0.0, s, z,
            0.0, 0.0, 0.0, 1.0]


def _asymmetric_rotation() -> TGMatrix3:
    axis = TGPoint3(1.0, 2.0, 3.0)
    axis.Scale(1.0 / math.sqrt(14.0))
    m = TGMatrix3()
    m.MakeRotation(0.7, axis)
    return m


def _body_of(rot: TGMatrix3, t, s, p):
    """R^T (p - t) / s -- the inverse of a column-vector pose R*s, t."""
    d = [p[i] - t[i] for i in range(3)]
    return tuple(sum(_col(rot, c)[r] * d[r] for r in range(3)) / s
                 for c in range(3))


def _col(rot: TGMatrix3, c):
    v = rot.GetCol(c)
    return (v.x, v.y, v.z)


@pytest.fixture
def inst():
    i = _h.create_instance(0)
    yield i
    _h.destroy_instance(i)


def test_binding_present():
    assert hasattr(_h, "set_instance_sim_source")
    assert "set_instance_sim_source" in host_io._REQUIRED_BINDINGS


def test_host_io_set_sim_source_rejects_a_plain_int():
    assert host_io.set_instance_sim_source(7, 0, 0, 1.0, (0.0, 0.0, 0.0)) is False


def test_translation_is_the_store_pose_plus_view_offset(inst):
    o = ObjectClass()
    o.SetTranslateXYZ(100.0, 50.0, -7.0)
    _h.set_world_transform(inst, _translation_mat(0.0, 0.0, 0.0))
    assert host_io.set_instance_sim_source(inst, *o._xform, 2.0,
                                           (10.0, 0.0, 0.0)) is True
    assert _h.instance_translation(inst) == (110.0, 50.0, -7.0)
    assert _h.instance_translation(inst, drawn=True) == (0.0, 0.0, 0.0)
    # The store is read LIVE: moving the object moves the hit pose at once.
    o.SetTranslateXYZ(1.0, 2.0, 3.0)
    assert _h.instance_translation(inst) == (11.0, 2.0, 3.0)


def test_without_a_source_every_query_reads_the_drawn_pose(inst):
    _h.set_world_transform(inst, _translation_mat(5.0, 6.0, 7.0))
    assert _h.instance_translation(inst) == (5.0, 6.0, 7.0)
    assert _h.instance_translation(inst, drawn=True) == (5.0, 6.0, 7.0)
    body, _ = host_io.world_to_body(inst, (6.0, 6.0, 7.0), (0.0, 0.0, 1.0))
    assert body == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)
    # Setting and then clearing (index < 0) a source returns to the drawn pose.
    o = ObjectClass()
    o.SetTranslateXYZ(100.0, 0.0, 0.0)
    _h.set_instance_sim_source(inst, *o._xform, 1.0, (0.0, 0.0, 0.0))
    assert _h.instance_translation(inst) == (100.0, 0.0, 0.0)
    _h.set_instance_sim_source(inst, -1, 0, 1.0, (0.0, 0.0, 0.0))
    assert _h.instance_translation(inst) == (5.0, 6.0, 7.0)


def test_a_stale_source_falls_back_to_the_drawn_pose(inst):
    _h.set_world_transform(inst, _translation_mat(5.0, 6.0, 7.0))
    index, gen = _h.transform_alloc()
    _h.transform_set_position(index, gen, 100.0, 0.0, 0.0)
    _h.set_instance_sim_source(inst, index, gen, 1.0, (0.0, 0.0, 0.0))
    assert _h.instance_translation(inst) == (100.0, 0.0, 0.0)
    _h.transform_free(index, gen)
    assert _h.instance_translation(inst) == (5.0, 6.0, 7.0)
    # A recycled slot is never read through the old handle.
    index2, gen2 = _h.transform_alloc()
    try:
        _h.transform_set_position(index2, gen2, 999.0, 0.0, 0.0)
        assert _h.instance_translation(inst) == (5.0, 6.0, 7.0)
    finally:
        _h.transform_free(index2, gen2)


def test_world_to_body_inverts_the_sim_pose(inst):
    rot = _asymmetric_rotation()
    o = ObjectClass()
    o.SetTranslateXYZ(3.0, -4.0, 5.0)
    o.SetMatrixRotation(rot)
    _h.set_world_transform(inst, _translation_mat(500.0, 0.0, 0.0))
    off = (10.0, 0.0, 0.0)
    _h.set_instance_sim_source(inst, *o._xform, 2.0, off)
    t = (13.0, -4.0, 5.0)
    p = (20.0, 3.0, -1.0)
    body, _ = host_io.world_to_body(inst, p, (0.0, 0.0, 1.0))
    assert body == pytest.approx(_body_of(rot, t, 2.0, p), abs=1e-5)
    drawn, _ = host_io.world_to_body(inst, p, (0.0, 0.0, 1.0), drawn=True)
    assert drawn == pytest.approx((p[0] - 500.0, p[1], p[2]), abs=1e-5)


def test_hull_damage_and_decal_record_the_sim_body_point(inst):
    rot = _asymmetric_rotation()
    o = ObjectClass()
    o.SetTranslateXYZ(3.0, -4.0, 5.0)
    o.SetMatrixRotation(rot)
    _h.set_world_transform(inst, _translation_mat(500.0, 0.0, 0.0, 0.5))
    _h.set_instance_sim_source(inst, *o._xform, 2.0, (0.0, 0.0, 0.0))
    p = (4.0, -3.0, 6.0)
    n = (0.0, 0.0, 1.0)
    host_io.hull_damage_add(inst, p, n, 0.3, 1.0, 1)
    host_io.damage_decal_add(inst, p, n, 0.3, 1.0, 1, 0.0)
    want = _body_of(rot, (3.0, -4.0, 5.0), 2.0, p)
    (rec,) = _h._test_only_hull_damage_records(inst)
    (decal,) = _h._test_only_damage_decals(inst)
    assert rec["centre"] == pytest.approx(want, abs=1e-4)
    assert decal["point"] == pytest.approx(want, abs=1e-4)
    assert rec["centre"] == pytest.approx(
        host_io.world_to_body(inst, p, n)[0], abs=1e-4)
    # GU -> model units by the sim scale (equal to the drawn one in play,
    # where scale is never interpolated; different here to pin the source).
    assert rec["reach"] == pytest.approx(0.3 / 2.0, rel=1e-5)


# -- traces and surface points on a real model --------------------------------

@pytest.fixture
def galaxy():
    if not GALAXY_NIF.is_file() or not GALAXY_TEX.is_dir():
        pytest.skip("BC assets not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        _h.init(256, 256, "sim-pose-hit-tests")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        model = _h.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        yield _h.create_instance(model)
    finally:
        _h.shutdown()


def test_ray_hits_the_sim_hull_not_the_drawn_one(galaxy):
    iid = galaxy
    o = ObjectClass()
    o.SetTranslateXYZ(0.0, 0.0, 0.0)
    _h.set_world_transform(iid, _translation_mat(2000.0, 0.0, 0.0))
    _h.set_instance_sim_source(iid, *o._xform, 1.0, (0.0, 0.0, 0.0))
    d = (0.0, 0.0, 1.0)
    hit = host_io.ray_trace_mesh(iid, (0.0, 0.0, -1000.0), d, 2000.0)
    assert hit is not None
    assert abs(hit[0][0]) < 1.0
    assert host_io.ray_trace_mesh(iid, (2000.0, 0.0, -1000.0), d, 2000.0) is None
    drawn = host_io.ray_trace_mesh(iid, (2000.0, 0.0, -1000.0), d, 2000.0,
                                   drawn=True)
    assert drawn is not None
    assert abs(drawn[0][0] - 2000.0) < 1.0
    assert host_io.ray_trace_mesh(iid, (0.0, 0.0, -1000.0), d, 2000.0,
                                  drawn=True) is None


def test_surface_points_follow_the_sim_pose(galaxy):
    iid = galaxy
    _h.set_world_transform(iid, _translation_mat(2000.0, 0.0, 0.0))
    drawn = renderer.instance_surface_points(iid)
    assert drawn, "premise: the Galaxy has surface points"
    o = ObjectClass()
    o.SetTranslateXYZ(-30.0, 4.0, 0.0)
    _h.set_instance_sim_source(iid, *o._xform, 1.0, (5.0, 0.0, 0.0))
    sim = renderer.instance_surface_points(iid)
    shift = (-25.0 - 2000.0, 4.0, 0.0)
    assert len(sim) == len(drawn)
    for s, dp in zip(sim, drawn):
        assert s == pytest.approx(
            (dp[0] + shift[0], dp[1] + shift[1], dp[2] + shift[2]), abs=1e-3)
    again = renderer.instance_surface_points(iid, drawn=True)
    assert len(again) == len(drawn)
    for a, b in zip(again, drawn):
        assert a == pytest.approx(b, abs=1e-6)
