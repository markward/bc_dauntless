"""Bindings that hand Python a point derived from inst->world return it in
VIEW space, whatever the render origin (system-frames Plan 3, Task 6).

Since Task 5, inst->world is RENDER space for a Space-pass instance (the
floating origin subtracted). instance_node_world, instance_surface_points and
get_instance_bounds add that origin back, so their callers -- the SPV's
framing, the nebula hull discharges, GetRandomPointOnModel -- keep speaking
the viewed set's coordinates. And the developer character spawn, framed in
front of the (render-space) camera, lands where the camera is looking rather
than one origin short of it.
"""
import os

import pytest

from tests.helpers import bc_assets

GALAXY_NIF = bc_assets.GAME_ROOT / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"
GALAXY_TEX = bc_assets.GAME_ROOT / "data" / "Models" / "SharedTextures" / "FedShips" / "High"

X = 1000.0            # float-exact, so the origin-0 baseline is exact too
ORIGIN = (X - 50.0, 0.0, 0.0)


def _translation_mat(x, y, z):
    return [1.0, 0.0, 0.0, x,
            0.0, 1.0, 0.0, y,
            0.0, 0.0, 1.0, z,
            0.0, 0.0, 0.0, 1.0]


@pytest.fixture
def host():
    if not GALAXY_NIF.is_file() or not GALAXY_TEX.is_dir():
        pytest.skip("BC assets not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host as h
    try:
        h.init(256, 256, "render-space-bindings")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        yield h
    finally:
        h.set_render_origin(0.0, 0.0, 0.0)
        h.shutdown()


@pytest.fixture
def galaxy(host):
    model = host.load_model(str(GALAXY_NIF), str(GALAXY_TEX))
    iid = host.create_instance(model)
    host.set_world_transform(iid, _translation_mat(X, 0.0, 0.0))
    return host, iid


def _at_origin(h, origin):
    h.set_render_origin(*origin)
    h._test_only_sync_instance_transforms()     # the resolve frame() runs


def test_get_instance_bounds_is_view_space(galaxy):
    h, iid = galaxy
    _at_origin(h, (0.0, 0.0, 0.0))
    base = h.get_instance_bounds(iid)
    _at_origin(h, ORIGIN)
    moved = h.get_instance_bounds(iid)
    assert moved == pytest.approx(base, abs=1e-3)


def test_instance_surface_points_are_view_space(galaxy):
    h, iid = galaxy
    _at_origin(h, (0.0, 0.0, 0.0))
    base = h.instance_surface_points(iid)
    assert base, "premise: the Galaxy has surface points"
    _at_origin(h, ORIGIN)
    moved = h.instance_surface_points(iid)
    assert len(moved) == len(base)
    for m, b in zip(moved[:16], base[:16]):
        assert m == pytest.approx(b, abs=1e-3)


def test_instance_node_world_is_view_space(galaxy):
    h, iid = galaxy
    _at_origin(h, (0.0, 0.0, 0.0))
    base = h.instance_node_world(iid, "Scene Root", False)
    assert base is not None, "premise: the Galaxy has a Scene Root node"
    _at_origin(h, ORIGIN)
    moved = h.instance_node_world(iid, "Scene Root", False)
    assert moved == pytest.approx(base, abs=1e-3)
    assert moved[3] == pytest.approx(X, abs=1e-3)


def test_the_dev_spawn_lands_in_front_of_the_render_space_camera(host):
    # The space camera is pushed in RENDER space (eye at ~0); the spawn is
    # framed on it and must be stored in VIEW space -- the origin added back
    # once, not subtracted a second time by the resolve.
    host.set_camera(eye=(0.0, 0.0, 0.0), target=(0.0, 1.0, 0.0),
                    up=(0.0, 0.0, 1.0), fov_y_rad=0.6, near=1.0, far=1e5)
    host.set_render_origin(0.0, 0.0, 0.0)
    a = host.spawn_test_character(str(GALAXY_NIF))
    at_zero = host.instance_translation(a)
    host.set_render_origin(*ORIGIN)
    b = host.spawn_test_character(str(GALAXY_NIF))
    moved = host.instance_translation(b)
    assert moved == pytest.approx(
        (at_zero[0] + ORIGIN[0], at_zero[1], at_zero[2]), abs=1e-3)


# ── a mission swap resets the origin AND what the passes remember of it ────

def _nebula():
    return {"spheres": [(0.0, 50.0, 0.0, 40.0)], "rgb": (0.5, 0.5, 0.5),
            "visibility": 10.0, "external_tex": "", "internal_tex": "",
            "fbm": (0.02, 1.0, 0.2), "seed": (1.0, 2.0, 3.0)}


def test_reset_render_origin_forgets_the_passes_origin_tracking(host):
    # Run frames at a far origin so the dust smear and the volumetric
    # nebula's temporal history both remember it. The volumetric toggle is a
    # process global (default ON) that host_loop reads to decide what to
    # build, so it is restored exactly -- leaving it off perturbed later tests.
    was_volumetric = host.volumetric_nebulae_enabled()
    host.set_game_root(str(bc_assets.GAME_ROOT))     # the dust sprite
    host.set_camera(eye=(0.0, 0.0, 0.0), target=(0.0, 1.0, 0.0),
                    up=(0.0, 0.0, 1.0), fov_y_rad=0.6, near=1.0, far=1e5)
    host.volumetric_nebulae_set_enabled(True)
    try:
        host.set_nebulae([_nebula()])
        host.set_render_origin(1.0e6, 0.0, 0.0)
        host.frame()
        host.frame()
        before = host.frame_state_debug()
        assert before["dust_motion_history"] is True, "premise: dust tracked"
        assert before["nebula_history"] is True, "premise: nebula history"
        host.reset_render_origin()
        after = host.frame_state_debug()
        assert after["render_origin"] == (0.0, 0.0, 0.0)
        # The next frame at origin 0 must not read a 1e6 GU jump as camera
        # travel: no dust smear from it, no history reprojected across it.
        assert after["dust_motion_history"] is False
        assert after["nebula_history"] is False
    finally:
        host.set_nebulae([])
        host.volumetric_nebulae_set_enabled(was_volumetric)
