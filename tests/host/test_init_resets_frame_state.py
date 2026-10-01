"""init() must clear every piece of per-frame state that shutdown() clears.

THE INVARIANT: anything ``frame()`` consumes, and that a Python binding can
write while the host is down, has to be reset by ``init()``. ``shutdown()``
already clears all of it, so the only leak path is Python pushing descriptors
between sessions -- the ``_dauntless_host`` module object outlives an
init/shutdown pair, and none of the setters check whether a window exists.

A leak here is not a test-only artifact: anything that re-inits the host
inherits the previous scene's beams, lights, hologram mode and reticle. It was
first seen as a test-isolation failure (test_backdrops_integration's
empty-backdrop row is asserted FLAT and read 53 / 63 / 77-94 depending on how
many tests had run before it -- monotonic in leftover VFX).

Two tests, deliberately:

* a RUNTIME one that dirties everything reachable from Python and asserts the
  first frame of the next session is clean; and
* a STRUCTURAL one that diffs the globals ``shutdown()`` resets against those
  ``init()`` resets, which is what stops the NEXT descriptor list from being
  added to one end only. The runtime test cannot cover state Python has no
  setter for (``g_have_prev_viewproj``, the input edge maps); the structural
  one can, and does.
"""
import os
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
HOST_BINDINGS = PROJECT_ROOT / "native" / "src" / "host" / "host_bindings.cc"


def _beam():
    return {
        "emitter": (0.0, 0.0, 0.0),
        "target": (10.0, 0.0, 0.0),
        "color": (1.0, 0.5, 0.25, 1.0),
        "width": 2.0,
    }


def _dirty_every_reachable_global(h):
    """Push state through the public bindings with the host DOWN.

    This is the real leak path, so the test drives it rather than reaching
    into the module. Every call here writes a global that ``frame()`` reads.
    """
    h.set_phaser_beams([_beam()])
    h.set_tractor_beams([_beam()])
    h.set_spv_overlay_beams([_beam()])
    iid = h.InstanceId()          # default-constructed; never dereferenced here
    h.set_cloak_ships([(iid, 0.5)])
    h.set_hologram_ship(instance_id=iid, color=(1.0, 1.0, 1.0),
                        opacity_facing=0.2, opacity_grazing=0.7)
    h.set_hologram_only_mode(True, (0.1, 0.2, 0.3))
    h.set_spv_hull_mode(True)
    h.set_target_reticle(visible=True, ship_center=(1.0, 2.0, 3.0),
                         ship_radius=4.0, subtarget_pos=None,
                         bar_alignment=0.5)
    h.starmap_set_enabled(True)
    h.set_viewscreen_enabled(True)
    h.bridge_pass_set_enabled(True)
    h.set_transform_gizmo(origin=(0.0, 0.0, 0.0), axis_x=(1.0, 0.0, 0.0),
                          axis_y=(0.0, 1.0, 0.0), axis_z=(0.0, 0.0, 1.0),
                          length=25.0, highlight=-1, handle_kind=0)
    h.letterbox_set(0.5)
    h.set_render_origin(1.0e6, -2.0, 3.0)
    h.minors_add_cloud(_minor_cloud())
    h.minors_set_player(iid)
    h.minors_set_enabled(False)
    h.minors_set_dials({"shove_min_gups": 9.0})
    h.far_set_sources([_far_source()])
    h.far_set_rocks([{"instance": iid, "index": -1, "radius_mu": 1.0}])
    h.far_set_enabled(False)
    h.far_set_dials({"p_min": 0.5})


def _far_source():
    return {
        "id": 1, "frame": "Vesuvi", "centre": (0.0, 0.0, 0.0), "normal": (0.0, 0.0, 1.0),
        "table": [(0.0, 0.05), (226000.0, 0.5)], "outer_fade_gu": 20000.0,
        "scale_height_frac": 0.03, "scale_height_min_gu": 1000.0, "seed": 9,
        "explicit_regions": [], "populations": []}


def _minor_cloud():
    return dict(
        id=1, anchor="point", instance=None, point=(0.0, 0.0, -20.0),
        velocity=(0.0, 0.0, 0.0), t0=0.0, shell_inner=0.0, shell_outer=2.0,
        falloff=0.0, count=50, r_min=0.3, r_max=0.3, size_exponent=2.5,
        family=0, seed=1, orbit_rate=0.0, fade_in=False, debris=[])


# The exact keys frame_state_debug() reports, with the value that means
# "clean". Written out rather than derived so that dropping a key from the
# binding fails this test instead of silently shrinking its coverage.
CLEAN = {
    "phaser_beams": 0,
    "tractor_beams": 0,
    "spv_overlay_beams": 0,
    "torpedoes": 0,
    "hit_vfx": 0,
    "shockwaves": 0,
    "particle_emitters": 0,
    "dynamic_lights": 0,
    "lens_flares": 0,
    "hull_discharges": 0,
    "cloak_ships": 0,
    "subsystem_pins": 0,
    "debug_cylinders": 0,
    "debug_boxes": 0,
    "debug_spheres": 0,
    "debug_cones": 0,
    "backdrops": 0,
    "suns": 0,
    "dust_planets": 0,
    "nebulae": 0,
    "nebula_wake": 0,
    "nebula_godrays": 0,
    "hologram_ship_active": False,
    "hologram_only_mode": False,
    "spv_hull_mode": False,
    # set_instance_decals overrides (the SPV decal preview). Python cannot
    # set one with the host down -- it needs a live instance -- so this row
    # pins the clear itself rather than a between-sessions push.
    "instance_decal_overrides": 0,
    "target_reticle_visible": False,
    "starmap_enabled": False,
    "viewscreen_enabled": False,
    "bridge_pass_enabled": False,
    "transform_gizmo_length": 0.0,
    "have_prev_viewproj": False,
    "letterbox_covered": 0.0,
    "sky_dirty": True,
    "prev_input_edges": 0,
    "render_origin": (0.0, 0.0, 0.0),
    # Fresh passes after init: no origin-dependent history carried over.
    "dust_motion_history": False,
    "nebula_history": False,
    # Minor rocks: the field's clouds, the on/off toggle, the contact player,
    # one native dial standing for all of them, and the per-model-handle hull
    # AABB cache (handles are reissued from 1 by every init()).
    "minor_clouds": 0,
    "minors_enabled": True,
    "minor_player": False,
    "minor_shove_min_gups": 0.3,
    "minor_aabb_cache": 0,
    # Far tier: disc sources, flagged rocks, the toggle and one dial (p_min,
    # which sets both the tier ladder's and the generator's).
    "far_sources": 0,
    "far_rocks": 0,
    "far_enabled": True,
    "far_p_min": 0.25,
}


def test_init_clears_state_pushed_while_the_host_was_down():
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host as h

    _dirty_every_reachable_global(h)

    try:
        h.init(64, 64, "reset-frame-state")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        state = h.frame_state_debug()
        assert set(state) == set(CLEAN), (
            "frame_state_debug() keys drifted from what this test pins")
        dirty = {k: v for k, v in state.items() if v != CLEAN[k]}
        assert not dirty, (
            "init() left last session's frame state in place: %r" % (dirty,))
    finally:
        h.shutdown()


def test_shutdown_leaves_the_same_state_clean():
    """The other half of the invariant. shutdown() is where this was already
    right; pin it so the extraction into reset_frame_state() cannot regress it.
    """
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host as h

    try:
        h.init(64, 64, "reset-frame-state-shutdown")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        _dirty_every_reachable_global(h)
    finally:
        h.shutdown()

    state = h.frame_state_debug()
    dirty = {k: v for k, v in state.items() if v != CLEAN[k]}
    assert not dirty, "shutdown() left frame state in place: %r" % (dirty,)


# ── Structural: the two lists cannot drift again ───────────────────────────


def _function_body(src: str, signature: str) -> str:
    """Return the body of a top-level function, using the column-0 closing
    brace as the terminator (the convention this file already follows)."""
    start = src.index(signature)
    end = src.index("\n}\n", start)
    return src[start:end]


def _globals_reset_in(body: str) -> set:
    """Globals the body assigns, clears or resets."""
    found = set()
    for m in re.finditer(r"\b(g_\w+)\s*(?:=|\.clear\(\)|\.reset\(\))", body):
        found.add(m.group(1))
    return found


def test_init_resets_every_non_gl_global_that_shutdown_resets():
    """The drift guard. Any global reset in shutdown() but not in init() (or
    the shared reset_frame_state() both call) is the exact bug this file
    exists for: shutdown() clears it, init() does not, so Python can push it
    across a session boundary.

    Pure source analysis -- no GL, so it runs everywhere.
    """
    src = HOST_BINDINGS.read_text(encoding="utf-8")
    shared = _function_body(src, "void reset_frame_state()")
    init = _function_body(src, "void init(int width, int height,")
    shutdown = _function_body(src, "void shutdown()")

    assert "reset_frame_state();" in init, "init() must call reset_frame_state()"
    assert "reset_frame_state();" in shutdown, (
        "shutdown() must call reset_frame_state()")

    shared_names = _globals_reset_in(shared)
    init_names = _globals_reset_in(init) | shared_names
    shutdown_names = _globals_reset_in(shutdown) | shared_names

    # Owners of GL handles: shutdown() destroys them (the context is going
    # away), init() constructs them fresh with make_unique, which the regex
    # above sees as an assignment -- so those land in both sets naturally.
    # g_cache is the only legitimate asymmetry: it is a lazily-built asset
    # cache that shutdown() releases with the GL context and load_model()
    # rebuilds on demand; there is nothing for init() to reset.
    allowed_shutdown_only = {"g_cache"}

    missing = shutdown_names - init_names - allowed_shutdown_only
    assert not missing, (
        "shutdown() resets these but init() does not -- Python can push them "
        "across a session boundary: %s" % sorted(missing))


# ── Minor rocks (minor-rocks plan Task 8) ──────────────────────────────────


def test_minors_state_cleared_by_reset():
    """A mission's minor clouds, player, dials, toggle and hull-AABB cache must
    not survive a shutdown()/init() pair: a leftover cloud would draw with the
    next session's recycled model handles, and a cached AABB keyed on a
    recycled handle would size the player's contact box from the wrong hull.

    Dirtied in a LIVE session (the AABB cache only fills inside frame()),
    unlike the host-down push above.
    """
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host as h
    from engine.rocks import catalogue

    try:
        h.init(64, 64, "reset-minors")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        rock = catalogue.pick("x", kind="fragment", family="silicate")
        model = h.load_model(rock.lod_paths[0], [], None, decals=None, scale=1.0)
        h.minors_set_fragments(0, [(model, model, rock.bound_radius_m / 1.75)])
        h.minors_add_cloud(_minor_cloud())
        h.minors_set_player(h.create_instance(model))
        h.minors_set_dials({"shove_min_gups": 9.0})
        h.set_camera(eye=(0.0, 0.0, 0.0), target=(0.0, 0.0, -1.0),
                     up=(0.0, 1.0, 0.0), fov_y_rad=1.0472, near=0.1, far=1.0e6)
        h.frame()                                # fills the AABB cache
        h.minors_set_enabled(False)
        live = h.frame_state_debug()
        assert live["minor_clouds"] == 1 and live["minor_player"] is True
        assert live["minor_aabb_cache"] == 1 and live["minors_enabled"] is False
        assert live["minor_shove_min_gups"] == 9.0
    finally:
        h.shutdown()

    try:
        h.init(64, 64, "reset-minors-2")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        state = h.frame_state_debug()
        minor_rows = {k: v for k, v in state.items() if "minor" in k}
        assert minor_rows == {k: v for k, v in CLEAN.items() if "minor" in k}
    finally:
        h.shutdown()


# ── Far tier (far-tier plan Task 8) ────────────────────────────────────────


def test_far_state_cleared_by_reset():
    """A mission's disc sources, flagged rocks, toggle and dials must not
    survive a shutdown()/init() pair, and a recycled instance must come back
    mesh-only (far_fade 0): a leftover fade of 1 hides the hull outright.
    """
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host as h
    from engine.rocks import catalogue

    def rock_instance():
        rock = catalogue.pick("x", kind="fragment", family="silicate")
        model = h.load_model(rock.lod_paths[0], [], None, decals=None, scale=1.0)
        return h.create_instance(model)

    try:
        h.init(64, 64, "reset-far")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        rock = rock_instance()
        h.set_world_transform(rock, [1.0, 0, 0, 0, 0, 1.0, 0, 0,
                                     0, 0, 1.0, -10000.0, 0, 0, 0, 1.0])
        h.far_set_sources([_far_source()])
        h.far_set_rocks([{"instance": rock, "index": -1, "radius_mu": 1.0}])
        h.set_camera(eye=(0.0, 0.0, 0.0), target=(0.0, 0.0, -1.0),
                     up=(0.0, 1.0, 0.0), fov_y_rad=1.0472, near=0.1, far=1.0e7)
        h.frame()                                  # drives the fade to 1
        assert h.far_debug_fade(rock) == 1.0
        h.far_set_dials({"p_min": 0.5})
        live = h.frame_state_debug()
        assert live["far_sources"] == 1 and live["far_rocks"] == 1
        assert live["far_p_min"] == 0.5
    finally:
        h.shutdown()
    # Set with the host down: the toggle is a plain global.
    h.far_set_enabled(False)

    try:
        h.init(64, 64, "reset-far-2")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        state = h.frame_state_debug()
        far_rows = {k: v for k, v in state.items() if k.startswith("far_")}
        assert far_rows == {k: v for k, v in CLEAN.items() if k.startswith("far_")}
        recycled = rock_instance()
        assert recycled.index == rock.index
        assert h.far_debug_fade(recycled) == 0.0
    finally:
        h.shutdown()
