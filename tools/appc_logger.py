###############################################################################
# appc_logger.py
#
# Appended to game/scripts/App.py by setup.py.
# Runs inside the App module namespace (UtopiaModule, g_kSystemWrapper,
# g_kConfigMapping all available directly).
#
# Wraps GetGameTime (AI call timing -- Q1/Q2) and TGEventManager.AddEvent
# (event dispatch timing -- OQ-4.2).
#
# Tick log format:  "wall frame game_time frame_pos_s real_time"
# Event log format: "wall frame frame_pos_s"
#
# Python 1.5 compatible: no f-strings, no True/False, no import X as Y.
###############################################################################
try:
    import time

    _time_func = time.clock
    _last_frame = -1
    _ticks = []
    _ev_log = []
    _EV_MAX = 200
    _orig_GetGameTime = UtopiaModule.GetGameTime
    _orig_AddEvent = TGEventManager.AddEvent

    def _flush():
        i = 0
        for line in _ticks:
            g_kConfigMapping.SetStringValue("BCTickLog", "t" + str(i), line)
            i = i + 1
        g_kConfigMapping.SetIntValue("BCTickLog", "count", len(_ticks))
        j = 0
        for line in _ev_log:
            g_kConfigMapping.SetStringValue("BCTickLog", "ev" + str(j), line)
            j = j + 1
        g_kConfigMapping.SetIntValue("BCTickLog", "evcount", len(_ev_log))
        g_kConfigMapping.SaveConfigFile("BCTickLog.cfg")

    def _on_get_game_time(self):
        global _last_frame, _last_save
        game_time = _orig_GetGameTime(self)
        real_time = g_kUtopiaModule.GetRealTime()
        frame = g_kSystemWrapper.GetUpdateNumber()
        wall = _time_func()
        frame_pos = g_kSystemWrapper.GetTimeSinceFrameStart()
        if frame != _last_frame:
            _ticks.append("%f %d %f %f %f" % (wall, frame, game_time, frame_pos, real_time))
            _last_frame = frame
            if wall - _last_save >= 30.0:
                _flush()
                _last_save = wall
        return game_time

    def _on_add_event(self, pEvent):
        if len(_ev_log) < _EV_MAX:
            frame = g_kSystemWrapper.GetUpdateNumber()
            pos = g_kSystemWrapper.GetTimeSinceFrameStart()
            wall = _time_func()
            _ev_log.append("%f %d %f" % (wall, frame, pos))
        return _orig_AddEvent(self, pEvent)

    _last_save = _time_func()
    UtopiaModule.GetGameTime = _on_get_game_time
    TGEventManager.AddEvent = _on_add_event

except:
    try:
        import sys
        g_kConfigMapping.SetStringValue("BCTickLog", "err_type", str(sys.exc_type))
        g_kConfigMapping.SetStringValue("BCTickLog", "err_value", str(sys.exc_value))
        g_kConfigMapping.SaveConfigFile("BCTickLog.cfg")
    except:
        pass
