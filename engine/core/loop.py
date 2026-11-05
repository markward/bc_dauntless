import App

from engine.appc import native_combat, native_subsystems, passive_state
from engine.core import frame_profiler as _prof

TICK_RATE = 60
TICK_DELTA = 1.0 / TICK_RATE


class GameLoop:
    """Drives App.g_kTimerManager, App.g_kRealtimeTimerManager,
    g_kAIManager (TimeSliceProcess scheduler), the AI tree-walker driver,
    and live-ship subsystem updates at 60 Hz.

    Order per tick (matches Q2 closed at AI-first within the tick):
      1. Timer managers advance.
      2. AI tick:
         a. g_kAIManager dispatches due TimeSliceProcess callbacks.
         b. tick_all_ai walks every ship's AI subtree.
      3. Per-ship subsystem updates (shields etc.).
    Physics + render run downstream in host_loop, not here.
    """

    def __init__(self, owns_boundary: bool = True) -> None:
        """`owns_boundary`: this loop's tick is the whole sim tick (the
        headless harness, tools), so its end is the tick boundary where the
        held effects of every condition write and hit are delivered, the
        death check among them (effect_queue.boundary). The host passes
        False: its boundaries are the per-tick combat flush and the frame's
        end (host_loop)."""
        passive_state.configure()
        native_combat.configure()
        # Kernel M flies the motion stage (DAUNTLESS_NATIVE_MOTION, on
        # unless =0): after the mirror is live, which it needs.
        from engine.appc import native_motion
        native_motion.configure()
        self.owns_boundary = owns_boundary

    def tick(self) -> None:
        # The published-pose read window opens at this tick's publish
        # (native_motion.close_published): close one a driver left open
        # (no _advance_combat after the last tick, or one that raised
        # before it), so this tick's AI-stage K1 calls read live.
        from engine.appc import native_motion
        native_motion.close_published()
        # Drop the avoidance obstacle snapshot: a new tick means the world has
        # moved. Explicit rather than inferred from the clock -- see
        # collision_avoidance.invalidate_obstacle_snapshot.
        from engine.appc.collision_avoidance import invalidate_obstacle_snapshot
        invalidate_obstacle_snapshot()
        # Pulse banks re-read their projectile module after a cache reset.
        native_combat.refresh_stale_pulse_params()

        with _prof.scope("gl.timers.game"):
            App.g_kTimerManager.tick(TICK_DELTA)
        with _prof.scope("gl.timers.real"):
            App.g_kRealtimeTimerManager.tick(TICK_DELTA)

        from engine.appc.time_slice import g_kAIManager
        from engine.appc.ai_driver import tick_all_ai
        from engine.appc.ship_motion import tick_all_ship_motion
        from engine.appc.planet import evaluate_proximity_checks
        from engine.appc.defensive_cloak import tick_defensive_cloak
        game_time = App.g_kTimerManager.get_time()
        real_time = App.g_kRealtimeTimerManager.get_time()
        with _prof.scope("gl.timeslice"):
            g_kAIManager.tick(game_time=game_time, real_time=real_time)
        with _prof.scope("gl.cloak"):
            tick_defensive_cloak(TICK_DELTA)
        with _prof.scope("gl.ai"):
            tick_all_ai(game_time=game_time)
        # ET_SET_ALERT_LEVEL levels posted since the last tick land here, after
        # the AI window, where BC drained its event queue (ShipClass.ProcessEvent).
        from engine.appc.ships import apply_pending_alert_levels
        apply_pending_alert_levels()
        # Drive each bridge officer's CharacterClass animation queue one step --
        # the headless equivalent of host_loop._pump_character_queues. A
        # re-pointed CharacterAction (turn / glance / gesture / breathe / menu)
        # enqueues an AnimRec; without this drive the record never plays and its
        # on_complete -- the mission TGSequence's Completed() -- never fires,
        # stalling a bridge cutscene when a mission is run headless (e.g.
        # gameloop_harness). No clip-player controller exists here, so
        # _anim_play_now leaves the record unplayed and ReleaseCurrentAnimation
        # fires on_complete on the next drain. AI/Python-first ordering.
        with _prof.scope("gl.bridge_chars"):
            _pump_bridge_character_queues()
        # Per-tick proximity evaluation.  SDK conditions like
        # ConditionInRange register ProximityChecks; the per-tick sweep
        # fires events when objects cross the radius boundary.
        with _prof.scope("gl.proximity"):
            evaluate_proximity_checks()
        # NO avoidance phase here, deliberately. Avoidance is BC's
        # AvoidObstacles PREPROCESSOR, dispatched inside tick_all_ai above as
        # part of each ship's AI tree -- see docs/reference/engine/avoidance-duplication.md.
        # A second pass here ran a full duplicate controller over every AI ship
        # and overwrote whatever the preprocessor had just decided, so real
        # missions paid for avoidance twice and discarded the first answer.
        #
        # Consequence, accepted deliberately: a ship whose doctrine does not
        # install AvoidObstacles now does not avoid. That matches BC, where the
        # behaviour is a node you opt into rather than a property of having an
        # AI at all. BasicAttack is one such doctrine.
        # Warp-in slides and dewarp transitions advance on game time, before
        # motion: an arriving ship's pose is the drive's, and ship motion
        # skips it (warp_state.is_arriving). Warp-in spec 6.1 "Timing".
        from engine.appc import warp_state
        with _prof.scope("gl.warp_states"):
            warp_state.tick_warp_states(TICK_DELTA)
        from engine.systems import shuttle_service
        with _prof.scope("gl.shuttles"):
            shuttle_service.tick(TICK_DELTA)
        from engine.appc import warp_in_flash
        warp_in_flash.advance(TICK_DELTA)
        with _prof.scope("gl.motion"):
            tick_all_ship_motion(TICK_DELTA)

        from engine.rocks import motion as rock_motion
        with _prof.scope("gl.rock_motion"):
            rock_motion.tick_all(TICK_DELTA)

        from engine.rocks import death as rock_death
        with _prof.scope("gl.rock_death"):
            rock_death.advance(TICK_DELTA)

        with _prof.scope("gl.subsystems"):
            _update_ship_subsystems()

        # DAUNTLESS_NATIVE_AUDIT=1: every mirror row against its Python
        # object, once a tick, so a write that bypassed a NativeField is
        # caught where it happened (engine/appc/native_combat.py).
        if native_combat.audit_enabled():
            # After a drain: an off-main push queued since the last one is
            # not a bypass, and would read as Python != mirror.
            native_combat.drain()
            native_combat.audit_mirror()

        # The tick boundary when no host drives this loop: the held damage
        # effects are delivered, the death check among them (native damage
        # M2, M5; engine/appc/effect_queue.py).
        if self.owns_boundary:
            # The published-pose read window closes first: a combat step a
            # boundary-owning driver runs after this tick reads live
            # (native_motion.close_published).
            from engine.appc import effect_queue
            native_motion.close_published()
            effect_queue.boundary()
            # The mirror's pending frees and off-main pushes (spec
            # 2026-11-03 ruling R2): host_loop's tick boundary otherwise.
            native_combat.drain(boundary=True)

    def advance(self, n: int) -> None:
        for _ in range(n):
            self.tick()

    @property
    def game_time(self) -> float:
        return App.g_kTimerManager.get_time()


def _update_ship_subsystems() -> None:
    """Advance every live ship's shield / power / cloak / repair subsystem
    and articulation: the native subsystem stage
    (engine/appc/native_subsystems.py; native/src/combat/src/
    subsystem_step.cc), the only one (phase 6 A1 Task 8 deleted the Python
    stage). Rocks are excluded -- a rock's shield/power/cloak/repair/
    articulation never ticks (rock-class spec §1).

    Extracted from GameLoop.tick so the profiler can scope it without
    re-indenting the body (and so the scope covers the whole walk).
    """
    native_subsystems.step_all(TICK_DELTA)


def _pump_bridge_character_queues() -> None:
    """Drive every bridge officer's CharacterClass animation queue one step.

    The headless equivalent of host_loop._pump_character_queues (the live game
    wires it in _pump_char_anim, before the clip-player drains). Enumerates the
    "bridge" set's CharacterClass members and calls UpdateAnimationQueue() on
    each -- no _render_instance filter (headless has no renderer), unlike the
    host's _live_bridge_characters. Best-effort: a missing bridge set, a member
    without the method, or a raising queue must never stall the loop.

    ASYMMETRY (intentional): the host's _live_bridge_characters filters out
    hidden/render-instance-less officers, so a record carrying a live on_complete
    that is enqueued and then the officer HIDES before the queue drains it would
    stop being pumped under the host (a hang the headless path, which pumps all
    members, would not have). No SDK path hits this today -- moves carry
    on_complete=None and retire ~1 tick after start, before CS_HIDDEN is set --
    but the queue must never be made to hold a live callback across a hide."""
    bridge = App.g_kSetManager.GetSet("bridge")
    if bridge is None:
        return
    from engine.appc.characters import CharacterClass
    try:
        members = bridge.GetClassObjectList(CharacterClass)
    except Exception:
        return
    for ch in members or []:
        fn = getattr(ch, "UpdateAnimationQueue", None)
        if fn is None:
            continue
        try:
            fn()
        except Exception:
            pass
