import App

from engine.appc.ship_iter import iter_ships
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

    def tick(self) -> None:
        # Drop the avoidance obstacle snapshot: a new tick means the world has
        # moved. Explicit rather than inferred from the clock -- see
        # collision_avoidance.invalidate_obstacle_snapshot.
        from engine.appc.collision_avoidance import invalidate_obstacle_snapshot
        invalidate_obstacle_snapshot()

        App.g_kTimerManager.tick(TICK_DELTA)
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
        # part of each ship's AI tree -- see docs/engine/avoidance-duplication.md.
        # A second pass here ran a full duplicate controller over every AI ship
        # and overwrote whatever the preprocessor had just decided, so real
        # missions paid for avoidance twice and discarded the first answer.
        #
        # Consequence, accepted deliberately: a ship whose doctrine does not
        # install AvoidObstacles now does not avoid. That matches BC, where the
        # behaviour is a node you opt into rather than a property of having an
        # AI at all. BasicAttack is one such doctrine.
        with _prof.scope("gl.motion"):
            tick_all_ship_motion(TICK_DELTA)

        with _prof.scope("gl.subsystems"):
            _update_ship_subsystems()

    def advance(self, n: int) -> None:
        for _ in range(n):
            self.tick()

    @property
    def game_time(self) -> float:
        return App.g_kTimerManager.get_time()


def _update_ship_subsystems() -> None:
    """Advance every live ship's shield / power / cloak / repair subsystem.

    Extracted from GameLoop.tick so the profiler can scope it without
    re-indenting the body (and so the scope covers the whole walk, including
    iter_ships itself, rather than only the per-ship work).
    """
    for ship in iter_ships():
        ss = ship.GetShieldSubsystem()
        if ss is not None:
            ss.Update(TICK_DELTA)
        ps = ship.GetPowerSubsystem()
        if ps is not None:
            ps.Update(TICK_DELTA)
        # Advance any in-progress cloak/decloak transition so it completes
        # (CloakShip preprocessor sets the intent; the timer lives here).
        cl = ship.GetCloakingSubsystem()
        if cl is not None:
            cl.Update(TICK_DELTA)
        # Repair bay: advance the repair queue (RE tick — see
        # RepairSubsystem.Update). AI ships repair themselves too.
        rs = ship.GetRepairSubsystem()
        if rs is not None:
            rs.Update(TICK_DELTA)


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
