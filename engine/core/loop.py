import App

from engine.appc.ship_iter import iter_ships

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
        App.g_kTimerManager.tick(TICK_DELTA)
        App.g_kRealtimeTimerManager.tick(TICK_DELTA)

        from engine.appc.time_slice import g_kAIManager
        from engine.appc.ai_driver import tick_all_ai
        from engine.appc.ship_motion import tick_all_ship_motion
        from engine.appc.collision_avoidance import tick_collision_avoidance
        from engine.appc.planet import evaluate_proximity_checks
        from engine.appc.defensive_cloak import tick_defensive_cloak
        game_time = App.g_kTimerManager.get_time()
        real_time = App.g_kRealtimeTimerManager.get_time()
        g_kAIManager.tick(game_time=game_time, real_time=real_time)
        tick_defensive_cloak(TICK_DELTA)
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
        _pump_bridge_character_queues()
        # Per-tick proximity evaluation.  SDK conditions like
        # ConditionInRange register ProximityChecks; the per-tick sweep
        # fires events when objects cross the radius boundary.
        evaluate_proximity_checks()
        # Collision avoidance overrides the heading of any AI ship on an
        # imminent collision course, AFTER the AI has set its heading and
        # BEFORE motion integrates. Restores the original Appc autopilot's
        # obstacle avoidance (the SDK movement scripts only command a
        # heading; the C++ autopilot steered around obstacles).
        tick_collision_avoidance()
        tick_all_ship_motion(TICK_DELTA)

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

    def advance(self, n: int) -> None:
        for _ in range(n):
            self.tick()

    @property
    def game_time(self) -> float:
        return App.g_kTimerManager.get_time()


def _pump_bridge_character_queues() -> None:
    """Drive every bridge officer's CharacterClass animation queue one step.

    The headless equivalent of host_loop._pump_character_queues (the live game
    wires it in _pump_char_anim, before the clip-player drains). Enumerates the
    "bridge" set's CharacterClass members and calls UpdateAnimationQueue() on
    each -- no _render_instance filter (headless has no renderer), unlike the
    host's _live_bridge_characters. Best-effort: a missing bridge set, a member
    without the method, or a raising queue must never stall the loop."""
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
