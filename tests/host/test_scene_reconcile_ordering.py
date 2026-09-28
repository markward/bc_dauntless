"""Source-order guard: the scene reconcile runs AFTER the sim, right before
the transform push (system-frames Plan 3 final review I2, Ruling 10).

`_reconcile_runtime_instances` (render scope: keep / cull / hide),
`_reconcile_celestial_instances` (the viewed frame's map bodies, pushed in
the viewed set's coordinates) and `_check_mapped_bodies_untouched` all read
`frames.viewing_set()`. So do `_sync_instance_transforms`, the camera and
`_apply_render_origin`. When the reconcile ran BEFORE the frame's sim section
(input, weapons, combat, warp-state, collisions) and the push AFTER it, a
frame whose sim changed the view (a warp engaged from a key or click, the
non-flythrough warp path, a sibling-region ChangeRenderedSet) pushed map
bodies in the OLD view's coordinates for one frame -- Ona1 <-> Ona2 is
~50,000 GU -- and made cull/hide decisions a frame stale.

The host loop is one monolithic while-loop, so -- like
tests/host/test_camera_dt_wiring.py -- this guards the order in `run()`'s
source. The behaviour of the moved block itself (after a view change it
pushes the NEW view's coordinates) is pinned in
tests/integration/test_sky_round_trip.py.
"""
import inspect

from engine import host_loop


def _run_source() -> str:
    return inspect.getsource(host_loop.run)


def _at(src, needle, start=0):
    i = src.find(needle, start)
    assert i >= 0, "%r not found in host_loop.run" % needle
    return i


# Every call in the frame's sim section that can move the player to another
# set or change the rendered set, or that runs the world forward.
_SIM_CALLS = (
    "loop.tick()",
    "_apply_input(",
    "_poll_mouse_buttons(",
    "_poll_function_keys(",
    "_poll_fire_keys(",
    "_poll_raw_keyboard(",
    "_advance_weapons(",
    "_advance_combat(",
    "_warp_state.tick_warp_states(",
    "collisions.tick_collisions(",
    "dash.tick(",
    "handoff.tick(",
)


def test_the_scene_reconcile_runs_after_the_sim_and_before_the_push():
    src = _run_source()
    reconcile = _at(src, "_reconcile_scene(")
    push = _at(src, "_sync_instance_transforms(")
    for call in _SIM_CALLS:
        assert _at(src, call) < reconcile, (
            "the scene reconcile must run AFTER %s -- it reads the viewed "
            "set, which the sim may change this frame" % call)
    assert reconcile < push, (
        "the scene reconcile must run BEFORE _sync_instance_transforms: it is "
        "the first visibility writer, and the push ANDs with scope_hidden")


def test_the_scene_reconcile_precedes_every_other_visibility_writer():
    """INVARIANT: the scope reconcile is the FIRST visibility writer -- warp
    hide (inside _sync_instance_transforms), the SPV hull hide, bridge-player
    visibility and the cloak push all AND with scope_hidden."""
    src = _run_source()
    reconcile = _at(src, "_reconcile_scene(")
    for writer in ("_sync_instance_transforms(",
                   "r.set_visible(_player_iid_spv, False)",
                   "_apply_bridge_player_visibility(",
                   "_push_cloak_refraction("):
        assert reconcile < _at(src, writer), writer


def test_no_piece_of_the_scene_reconcile_is_called_on_its_own_in_run():
    """The four calls travel together, through _reconcile_scene only, so none
    can be left behind (or re-added) ahead of the sim."""
    src = _run_source()
    for piece in ("_ensure_system_loaded(", "_reconcile_runtime_instances(",
                  "_reconcile_celestial_instances(",
                  "_check_mapped_bodies_untouched("):
        assert piece not in src, piece


def test_reconcile_scene_loads_the_system_first_then_scope_then_bodies():
    """_ensure_system_loaded BEFORE the scope reconcile, so a region set it
    creates this tick is realized in the same pass."""
    body = inspect.getsource(host_loop._reconcile_scene)
    order = [_at(body, c) for c in ("_ensure_system_loaded(",
                                    "_reconcile_runtime_instances(",
                                    "_reconcile_celestial_instances(",
                                    "_check_mapped_bodies_untouched(")]
    assert order == sorted(order)


def test_player_identity_is_synced_before_the_sim_reads_the_player():
    """Ruling 11 (Plan 3 residual): the reconcile now runs after the sim, so
    a RecreatePlayer tick (QuickBattle's preload-done handler) must sync
    session.player BEFORE the frame's first `player = session.player` read --
    otherwise input, weapons, combat and the warp FSM drive the destroyed
    ship for a frame. The sync sits outside the sim-tick branch, so it also
    covers a frozen (paused) frame."""
    src = _run_source()
    preload = _at(src, "_fire_pending_preload_done()")
    sync = _at(src, "_sync_player_identity(", preload)
    first_read = _at(src, "player = session.player", preload)
    assert preload < sync < first_read
    for call in _SIM_CALLS[1:]:  # everything after loop.tick reads `player`
        assert sync < _at(src, call), call


def test_camera_radius_reseed_runs_after_reconcile_and_before_camera_compute():
    """_reconcile_camera_radius (the RecreatePlayer camera-radius fix) must
    run after EVERY _reconcile_scene call -- the reconcile is what realizes
    a just-created player ship and gives it a real GetRadius() -- and before
    _compute_camera, the single call site (shared by both the live and the
    frozen branch) that reads the cameras' seeded ship-radius framing."""
    src = _run_source()
    reconciles = []
    start = 0
    while True:
        i = src.find("_reconcile_scene(", start)
        if i < 0:
            break
        reconciles.append(i)
        start = i + 1
    assert len(reconciles) == 2, "expected one call in each of the live/frozen branches"

    compute = _at(src, "_compute_camera(")

    helper_calls = []
    start = 0
    while True:
        i = src.find("_reconcile_camera_radius(", start)
        if i < 0:
            break
        helper_calls.append(i)
        start = i + 1
    assert len(helper_calls) == 2, "expected one call in each of the live/frozen branches"

    for h in helper_calls:
        assert any(r < h for r in reconciles), (
            "_reconcile_camera_radius must run after a _reconcile_scene call")
        assert h < compute, (
            "_reconcile_camera_radius must run before _compute_camera")


def test_the_dash_tick_runs_after_collisions_and_before_the_hand_off():
    """The dash's drop-out (engine/appc/dash.py) reads the frame's final
    player pose and does its own hand-off, so it runs after the last mover
    (collisions) and before handoff.tick and the scene reconcile."""
    src = _run_source()
    collisions = _at(src, "collisions.tick_collisions(")
    dash_tick = _at(src, "dash.tick(")
    assert collisions < dash_tick < _at(src, "handoff.tick(") < _at(
        src, "_reconcile_scene(")
