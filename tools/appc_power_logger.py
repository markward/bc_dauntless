###############################################################################
# appc_power_logger.py
#
# Appended to game/scripts/App.py by setup.py (via SHIM_SNIPPET selection).
# Runs inside the App module namespace (UtopiaModule, g_kSystemWrapper,
# g_kConfigMapping, Game_GetCurrentPlayer all available directly).
#
# Purpose: capture ground-truth battery-discharge behaviour of the ORIGINAL
# engine. Mark takes a Galaxy to red alert, sets all four power groups to 125%,
# engages the tractor on an asteroid, and lets it run until power depletes.
#
# We wrap UtopiaModule.GetGameTime (the per-tick heartbeat, same seam as
# appc_logger.py). Every ~2.0s of GAME time we capture one compact power sample.
#
# --- Tick-log section (reused from appc_logger.py) -------------------------
#   Controlled by _TICKLOG_ENABLED. When 0, the per-frame tick buffer is NOT
#   recorded (keeps BCTickLog.cfg small so the p* power samples dominate).
#   Tick log format:  "wall frame game_time" (only when enabled)
#
# --- Power-sample section (new) --------------------------------------------
#   Key "pfields"  = documented column order (single string).
#   Key "pcount"   = number of samples N.
#   Keys "p0".."pN-1" = one compact space-separated numeric sample each.
#
# Field order (pfields), all guarded; a missing/None value is written "NA":
#   0  game_time
#   1  MainBatteryPower
#   2  BackupBatteryPower
#   3  PowerOutput
#   4  MainConduitCapacity
#   5  BackupConduitCapacity
#   6  AvailablePower
#   7  PowerDispensed
#   8  PowerWanted
#   9  ConditionPercentage        (of the PowerSubsystem)
#   10 impulse GetPowerPercentageWanted
#   11 warp    GetPowerPercentageWanted
#   12 shields GetPowerPercentageWanted   (GetShields())
#   13 phasers GetPowerPercentageWanted
#   14 torps   GetPowerPercentageWanted
#   15 pulse   GetPowerPercentageWanted
#   16 sensors GetPowerPercentageWanted
#   17 tractor firing flag         (1 = any tractor weapon IsFiring, else 0)
#
# Python 1.5 compatible: no f-strings, no True/False, no import X as Y,
# no os module, no open()/stdout. Output ONLY via g_kConfigMapping.Set*Value +
# SaveConfigFile("BCTickLog.cfg").
###############################################################################
try:
    import time

    _time_func = time.clock

    # Flip to 1 to also record the per-frame tick heartbeat (bloats the file).
    _TICKLOG_ENABLED = 0
    # Game-time seconds between power samples.
    _POWER_INTERVAL = 2.0

    _last_frame = -1
    _ticks = []
    _psamples = []
    _last_power_gt = -1000.0

    _orig_GetGameTime = UtopiaModule.GetGameTime

    _NA = "NA"

    def _num(fn):
        # Call a zero-arg accessor, return a compact string; "NA" on any error.
        try:
            v = fn()
            if v == None:
                return _NA
            return "%g" % v
        except:
            return _NA

    def _slider(pSub):
        # GetPowerPercentageWanted of a PoweredSubsystem handle; None-guarded.
        if pSub == None:
            return _NA
        try:
            return "%g" % pSub.GetPowerPercentageWanted()
        except:
            return _NA

    def _tractor_firing(pPlayer):
        # Same walk PowerDisplay.HandleTractor uses:
        #   for i in range(pTractors.GetNumChildSubsystems()):
        #       if pTractors.GetWeapon(i).IsFiring(): firing
        try:
            pTractors = pPlayer.GetTractorBeamSystem()
            if pTractors == None:
                return _NA
            n = pTractors.GetNumChildSubsystems()
            i = 0
            while i < n:
                pW = pTractors.GetWeapon(i)
                if pW != None:
                    if pW.IsFiring():
                        return "1"
                i = i + 1
            return "0"
        except:
            return _NA

    def _capture_power(game_time):
        # Build one compact sample string. Every field guarded independently.
        cols = []
        cols.append("%g" % game_time)

        pPlayer = None
        try:
            pPlayer = Game_GetCurrentPlayer()
        except:
            pPlayer = None

        if pPlayer == None:
            # No player yet (menus). Emit game_time + all NA so the row count
            # still advances and the analyzer can skip it.
            k = 1
            while k < 18:
                cols.append(_NA)
                k = k + 1
            _psamples.append(" ".join(cols))
            return

        pPower = None
        try:
            pPower = pPlayer.GetPowerSubsystem()
        except:
            pPower = None

        if pPower == None:
            cols.append(_NA); cols.append(_NA); cols.append(_NA)
            cols.append(_NA); cols.append(_NA); cols.append(_NA)
            cols.append(_NA); cols.append(_NA); cols.append(_NA)
        else:
            cols.append(_num(pPower.GetMainBatteryPower))
            cols.append(_num(pPower.GetBackupBatteryPower))
            cols.append(_num(pPower.GetPowerOutput))
            cols.append(_num(pPower.GetMainConduitCapacity))
            cols.append(_num(pPower.GetBackupConduitCapacity))
            cols.append(_num(pPower.GetAvailablePower))
            cols.append(_num(pPower.GetPowerDispensed))
            cols.append(_num(pPower.GetPowerWanted))
            cols.append(_num(pPower.GetConditionPercentage))

        # 7 slider systems (impulse, warp, shields, phasers, torps, pulse, sensors)
        try:
            cols.append(_slider(pPlayer.GetImpulseEngineSubsystem()))
        except:
            cols.append(_NA)
        try:
            cols.append(_slider(pPlayer.GetWarpEngineSubsystem()))
        except:
            cols.append(_NA)
        try:
            cols.append(_slider(pPlayer.GetShields()))
        except:
            cols.append(_NA)
        try:
            cols.append(_slider(pPlayer.GetPhaserSystem()))
        except:
            cols.append(_NA)
        try:
            cols.append(_slider(pPlayer.GetTorpedoSystem()))
        except:
            cols.append(_NA)
        try:
            cols.append(_slider(pPlayer.GetPulseWeaponSystem()))
        except:
            cols.append(_NA)
        try:
            cols.append(_slider(pPlayer.GetSensorSubsystem()))
        except:
            cols.append(_NA)

        cols.append(_tractor_firing(pPlayer))

        _psamples.append(" ".join(cols))

    def _flush():
        if _TICKLOG_ENABLED:
            i = 0
            for line in _ticks:
                g_kConfigMapping.SetStringValue("BCTickLog", "t" + str(i), line)
                i = i + 1
            g_kConfigMapping.SetIntValue("BCTickLog", "count", len(_ticks))
        g_kConfigMapping.SetStringValue("BCTickLog", "pfields",
            "game_time main backup output mainconduit backupconduit available dispensed wanted condpct impulse warp shields phasers torps pulse sensors tractor")
        j = 0
        for line in _psamples:
            g_kConfigMapping.SetStringValue("BCTickLog", "p" + str(j), line)
            j = j + 1
        g_kConfigMapping.SetIntValue("BCTickLog", "pcount", len(_psamples))
        g_kConfigMapping.SaveConfigFile("BCTickLog.cfg")

    def _on_get_game_time(self):
        global _last_frame, _last_save, _last_power_gt
        game_time = _orig_GetGameTime(self)
        frame = g_kSystemWrapper.GetUpdateNumber()
        wall = _time_func()
        if frame != _last_frame:
            if _TICKLOG_ENABLED:
                _ticks.append("%f %d %f" % (wall, frame, game_time))
            _last_frame = frame
            # Power sample on GAME-time cadence.
            if game_time - _last_power_gt >= _POWER_INTERVAL:
                _capture_power(game_time)
                _last_power_gt = game_time
            # Flush on WALL-time cadence (reuse the 30s rhythm).
            if wall - _last_save >= 30.0:
                _flush()
                _last_save = wall
        return game_time

    _last_save = _time_func()
    UtopiaModule.GetGameTime = _on_get_game_time

except:
    try:
        import sys
        g_kConfigMapping.SetStringValue("BCTickLog", "err_type", str(sys.exc_type))
        g_kConfigMapping.SetStringValue("BCTickLog", "err_value", str(sys.exc_value))
        g_kConfigMapping.SaveConfigFile("BCTickLog.cfg")
    except:
        pass
