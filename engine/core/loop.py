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
        game_time = App.g_kTimerManager.get_time()
        real_time = App.g_kRealtimeTimerManager.get_time()
        g_kAIManager.tick(game_time=game_time, real_time=real_time)
        tick_all_ai(game_time=game_time)
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
