"""Real host frames, headless: host_loop._run_frame_sim driven with a
FrameSimContext built from the host's own controllers (native motion phase 4,
Task 1).

`headless_context` builds the context run() builds, with no window and no GL:
the REAL camera director, view mode, pause menu, player control and native
interpolation buffer; `h`, `perf_monitor_panel`, `crew_menu_panel` and
`configuration_panel` None; a controller stand-in with exactly
CONTROLLER_SURFACE; and the GL- or window-bound calls in HEADLESS_STANDINS
patched out. The frame clock is
scripted: `drive` picks each frame's wall delta so frame f runs exactly
`frame_ticks[f % len(frame_ticks)]` ticks.
"""
import random
from typing import Sequence

from engine import host_loop
from engine.appc import collisions
from engine.core.native_transform_buffer import NativeTransformBuffer
from engine.core.loop import TICK_DELTA

MISSION = "engine.dev_missions.combat_stress"

# run()'s spiral-of-death cap (its MAX_FRAME_DT local).
MAX_FRAME_DT = 0.25

# The scripted clock's first reading (any value: only deltas matter).
CLOCK_START = 1000.0

# What _run_frame_sim reads from the controller: the stand-in has exactly
# these, and the mirror test checks them on host_loop.HostController.
CONTROLLER_SURFACE = ("session", "pending_swap", "_drain_pending_swap",
                      "renderer")

# Every patched `module:attr`, with why it is stood in.
HEADLESS_STANDINS = {
    "engine.host_loop:_reconcile_scene":
        "realizes render instances (GL model loads)",
    "engine.host_loop:_reconcile_camera_radius":
        "pairs with the stood-in reconcile: no realized radius",
    "engine.host_loop:_sync_instance_transforms":
        "pushes poses to render instances (GL)",
    "engine.host_loop:_poll_function_keys": "reads the window's keys",
    "engine.host_loop:_poll_raw_keyboard": "reads the window's keys",
    "engine.host_loop:_poll_skip_dialogue": "reads the window's keys",
    "engine.host_loop:_poll_mouse_buttons": "reads the window's mouse",
    "engine.host_loop:_poll_modifier_chords": "reads the window's keys",
    "engine.host_loop:_poll_fire_keys":
        "reads the window's keys (a no-op; a scene drives its ops here)",
    "engine.renderer:nebula_lightning_enabled":
        "a renderer toggle (False: no nebula lightning)",
    "engine.renderer:volumetric_nebulae_enabled":
        "a renderer toggle (False: no nebula wake)",
    "engine.appc.debris_chunk:tick": "spawns debris render instances (GL)",
}


def _noop(*_a, **_k):
    return None


def _false(*_a, **_k):
    return False


_STANDIN_VALUE = {
    "engine.renderer:nebula_lightning_enabled": _false,
    "engine.renderer:volumetric_nebulae_enabled": _false,
}


class ScriptedClock:
    """host_loop._frame_clock's stand-in: returns `now`, which drive sets."""

    def __init__(self, now: float = CLOCK_START):
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Controller:
    """HostController's surface _run_frame_sim reads (CONTROLLER_SURFACE)."""

    def __init__(self, session):
        self.session = session
        self.pending_swap = None
        self.renderer = None

    def _drain_pending_swap(self) -> None:
        self.pending_swap = None


def headless_context(mp, scene, loop, *, tick_hook=None):
    """A FrameSimContext for `scene` (a loaded combat_stress with a `player`)
    driven by GameLoop `loop`; `tick_hook()` runs before each loop.tick()."""
    import importlib
    from engine import cameras
    from engine.bridge_camera_watch import BridgeCameraWatchController
    from engine.bridge_character_anim import BridgeCharacterAnimController
    from engine.bridge_character_walk import BridgeCharacterWalkController
    from engine.bridge_cutscene import BridgeCutsceneController
    from engine.bridge_idle_gestures import IdleGestureScheduler
    from engine.bridge_node_anim import BridgeNodeAnimController
    from engine.input_map import InputMap
    from engine.lip_sync_runtime import LipSyncRuntime
    from engine.ui.letterbox import LetterboxAnimator
    from engine import renderer as r

    for target in HEADLESS_STANDINS:
        mod_name, attr = target.split(":")
        mp.setattr(importlib.import_module(mod_name), attr,
                   _STANDIN_VALUE.get(target, _noop))
    clock = ScriptedClock()
    mp.setattr(host_loop, "_frame_clock", clock)

    session = host_loop.MissionSession(mission_name=MISSION)
    session.player = scene.player
    director = cameras._CameraDirector()
    xform_buf = NativeTransformBuffer()
    input_map = InputMap()

    def tick_gameloop():
        if tick_hook is not None:
            tick_hook()
        loop.tick()

    def snap_scene():
        director.snap()
        xform_buf.reset_all()

    resolve = host_loop._game_asset_path
    char_anim = BridgeCharacterAnimController(asset_resolver=resolve)
    node_anim = BridgeNodeAnimController(bridge_iid_getter=lambda: None,
                                         asset_resolver=resolve)
    char_anim.set_node_controller(node_anim)
    return host_loop.FrameSimContext(
        h=None,
        controller=_Controller(session),
        director=director,
        view_mode=host_loop._ViewModeController(),
        player_control=host_loop._PlayerControl(input_map),
        pause=host_loop._PauseMenuController(),
        input_map=input_map,
        xform_buf=xform_buf,
        tick_gameloop=tick_gameloop,
        snap_scene=snap_scene,
        close_star_map=_noop,
        consume_scroll=None,
        cef_send_wheel=None,
        crew_menu_panel=None,
        perf_monitor_panel=None,
        configuration_panel=None,
        collisions=collisions,
        verbose=False,
        tick_dt=TICK_DELTA,
        max_frame_dt=MAX_FRAME_DT,
        cutscene=BridgeCutsceneController(asset_resolver=resolve),
        bridge_camera=host_loop._BridgeCamera(),
        char_anim=char_anim,
        walk_ctrl=BridgeCharacterWalkController(
            realize_fn=_noop, asset_resolver=resolve),
        watch_ctrl=BridgeCameraWatchController(),
        idle_gestures=IdleGestureScheduler(random.Random(0xB1D6E)),
        node_anim=node_anim,
        lip_runtime=LipSyncRuntime(r, lambda: []),
        letterbox_anim=LetterboxAnimator(),
        accumulator=0.0,
        previous_real_time=clock(),
    )


def drive(ctx, frame_ticks: Sequence[int], frames: int, on_frame=None):
    """Run `frames` host frames; frame f runs frame_ticks[f % len] ticks.
    `on_frame(f, result)` runs after each. Returns the FrameSimResults."""
    clock = host_loop._frame_clock
    assert isinstance(clock, ScriptedClock), "drive needs headless_context"
    results = []
    for f in range(frames):
        k = frame_ticks[f % len(frame_ticks)]
        clock.now += (k + 0.5) * ctx.tick_dt - ctx.accumulator
        result = host_loop._run_frame_sim(ctx, mx=0.0, my=0.0,
                                          cursor_in_panel=False)
        results.append(result)
        if on_frame is not None:
            on_frame(f, result)
    return results


# ── The golden scenes: a combat_stress fight through real host frames ───────

# Ticks per frame, cycled (a frame of 0 is a real host frame with no tick).
FRAME_TICKS = (3, 1, 6, 0, 2)

# The ops each frame draws from (k1_fight's _Scene.op kinds).
HOST_FRAME_OPS = ("fire",) * 4 + ("retarget",) * 2 + ("stop",)


def run(mp, env, spec, frame_ticks, frames, ops):
    """The GameLoop fight (k1_fight._loop_setup, host-owned boundary) driven
    by `frames` host frames through host_loop._run_frame_sim. Each tick is
    attributed by its index within its frame (GameLoop tick k and combat tick
    j of a frame starting at tick `first` are both `first + k`), so the
    batched and the whole-tick orders compare tick for tick. With `ops`,
    each frame's ops run inside the patched _poll_fire_keys, attributed to
    the tick before the frame. Returns the golden _Take."""
    import gc
    from tests.helpers import golden_fight as gf
    from tests.helpers import k1_fight as k1d

    k1d._loop_arm(mp, k1d.OFF, ticks=gf.WARM_UP_TICKS)
    gc.collect()
    scene, loop = k1d._loop_setup(mp, env, owns_boundary=False)
    frame = {"first": 1, "gameloop": 0, "combat": 0, "ops": 0}
    ran = {"ops": 0}
    notes = []

    def tick_hook():
        scene.tick = frame["first"] + frame["gameloop"]
        frame["gameloop"] += 1

    ctx = headless_context(mp, scene, loop, tick_hook=tick_hook)
    rng = random.Random(k1d.SEED)

    def poll_fire_keys(_h, _input_map):
        scene.tick = frame["first"] - 1
        for _ in range(rng.randint(0, 2)):
            scene.op(rng, ops)
            ran["ops"] += 1

    if ops:
        mp.setattr(host_loop, "_poll_fire_keys", poll_fire_keys)

    advance_weapons = host_loop._advance_weapons

    def counting_advance_weapons(ships, dt):
        scene.tick = frame["first"] + frame["combat"]
        frame["combat"] += 1
        return advance_weapons(ships, dt)

    boundary = host_loop._combat_tick_boundary

    def recording_boundary():
        result = boundary()
        scene.record()
        return result

    mp.setattr(host_loop, "_advance_weapons", counting_advance_weapons)
    mp.setattr(host_loop, "_combat_tick_boundary", recording_boundary)

    def begin(first):
        frame.update(first=first, gameloop=0, combat=0)

    def end(f, result):
        n = frame_ticks[f % len(frame_ticks)]
        assert result.sim_ticks == n, (f, result.sim_ticks, n)
        assert frame["gameloop"] == n and frame["combat"] == n, (f, n, frame)
        notes.append(("frame", frame["first"] - 1, n))
        scene.tick = frame["first"] - 1 + n
        begin(scene.tick + 1)

    begin(1)
    drive(ctx, frame_ticks, frames, on_frame=end)

    if ops:
        assert ran["ops"] > 0, "no op ran"
    assert scene.starts > 0
    if scene.native:
        gf.nc.audit_mirror()
        scene.audit = list(gf.nc.audit_failures())
        assert gf.nc._h.combat_k1_depth() == 0
    else:
        scene.audit = []
    scene.counts = gf.nc.counts()
    gf._check_native(scene)
    return gf._k1_take(scene, notes)
