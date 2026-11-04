"""Gameplay consumers of mesh queries land on the SIM hull (phase 3a).

A real Galaxy instance whose DRAWN pose is pushed far from the ship's
transform-store pose, and whose sim source is set the way production sets
it (`host_loop._mark_sim_source`). Manual Aim, GetRandomPointOnModel and a
beam-style trace must then answer on the sim hull, and on a moving ship the
sim and drawn hits differ by at most the interpolation lag.
"""
import math
import os

import pytest

pytest.importorskip("_dauntless_host")

import _dauntless_host as _h  # noqa: E402

from engine import host_io, host_loop  # noqa: E402
from engine.appc import render_instances  # noqa: E402
from engine.appc.math import TGPoint3  # noqa: E402
from engine.core.transform_buffer import TransformBuffer  # noqa: E402
from tests.helpers import bc_assets  # noqa: E402

GALAXY_NIF = bc_assets.GAME_ROOT / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = bc_assets.GAME_ROOT / "data" / "Models" / "SharedTextures" / "FedShips" / "High"
S = host_loop.BC_MODEL_SCALE
DRAWN_SHIFT = 2000.0


@pytest.fixture
def galaxy():
    """(model, iid, model radius in GU at scale 1)."""
    if not GALAXY_NIF.is_file() or not GALAXY_TEX.is_dir():
        pytest.skip("BC assets not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        _h.init(256, 256, "sim-pose-consumers")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    render_instances.reset()
    try:
        model = _h.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
        centre, half = _h.model_aabb(model)
        radius = (math.sqrt(sum(h * h for h in half))
                  + math.sqrt(sum(c * c for c in centre))) * S
        yield model, _h.create_instance(model), radius
    finally:
        render_instances.reset()
        _h.shutdown()


def _target_at(x, y, z):
    from engine.appc.ships import ShipClass_Create
    t = ShipClass_Create("Galaxy")
    t.SetTranslateXYZ(x, y, z)
    return t


def _draw_off(iid, ship, dx):
    loc = ship.GetWorldLocation()
    drawn = TGPoint3(loc.x + dx, loc.y, loc.z)
    _h.set_world_transform(iid, host_loop._world_matrix_from(
        drawn, ship.GetWorldRotation(), S * ship.GetScale()))


def _source(ship, iid):
    host_loop._mark_sim_source(host_loop.MissionSession("t"), ship, iid, S)


def _dist(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def test_manual_aim_pick_lands_on_the_sim_hull(galaxy):
    """test_manual_aim.py's stored-offset test, through the REAL host_io
    trace (no ray_trace= double)."""
    from tests.unit.test_manual_aim import _Tcw, _aim_fixture
    _model, iid, radius = galaxy
    manual_aim, player, target, cam = _aim_fixture()
    _draw_off(iid, target, DRAWN_SHIFT)
    _source(target, iid)

    live = manual_aim.update(player=player, tcw=_Tcw(True),
                             ship_instances={target: iid}, is_exterior=True,
                             cursor_fb=(400.0, 300.0), viewport_fb=(800, 600),
                             cam=cam)

    assert live is True, "the pick missed the sim hull"
    o = player.GetTargetOffsetTG()
    hit = host_io.ray_trace_mesh(iid, cam.eye(), _unit_toward(cam), cam.far)
    assert hit is not None
    tl = target.GetWorldLocation()
    want = tuple(hit[0][i] - (tl.x, tl.y, tl.z)[i] for i in range(3))
    assert (o.x, o.y, o.z) == pytest.approx(want, abs=1e-4)
    assert math.sqrt(o.x * o.x + o.y * o.y + o.z * o.z) < radius


def _unit_toward(cam):
    from engine.manual_aim import cursor_ray
    return cursor_ray((400.0, 300.0), (800, 600), cam)[1]


def test_random_point_on_model_lies_on_the_sim_hull(galaxy):
    _model, iid, radius = galaxy
    ship = _target_at(30.0, -40.0, 5.0)
    _draw_off(iid, ship, DRAWN_SHIFT)
    _source(ship, iid)
    render_instances.register(ship, iid)
    centre = (30.0, -40.0, 5.0)
    for _ in range(20):
        p = ship.GetRandomPointOnModel()
        assert _dist((p.x, p.y, p.z), centre) <= radius


def test_sim_and_drawn_hits_differ_by_at_most_the_interpolation_lag(galaxy):
    """A ship moving +x at 6.3 GU/s: the store holds `cur`, the drawn pose is
    lerp(prev, cur, a). A broadside ray's two hits are (1 - a) ticks apart."""
    _model, iid, _radius = galaxy
    v, dt = 6.3, 1.0 / 60.0
    ship = _target_at(0.0, 0.0, 0.0)
    rot = ship.GetWorldRotation()
    buf = TransformBuffer()
    buf.set_current(iid, TGPoint3(0.0, 0.0, 0.0), rot)
    buf.roll()
    ship.SetTranslateXYZ(v * dt, 0.0, 0.0)
    buf.set_current(iid, ship.GetWorldLocation(), rot)
    _source(ship, iid)
    o, d = (1000.0, 0.0, 0.0), (-1.0, 0.0, 0.0)
    for a in (0.0, 0.25, 0.5, 0.99):
        loc, r = buf.sample(iid, a)
        _h.set_world_transform(iid, host_loop._world_matrix_from(loc, r, S))
        p_sim = host_io.ray_trace_mesh(iid, o, d, 2000.0)
        p_drawn = host_io.ray_trace_mesh(iid, o, d, 2000.0, drawn=True)
        assert p_sim is not None and p_drawn is not None
        gap = _dist(p_sim[0], p_drawn[0])
        assert gap <= (1.0 - a) * v * dt + 1e-3, a
        if a == 0.0:
            assert gap > 0.5 * v * dt, "premise: the sim hull is a tick ahead"
