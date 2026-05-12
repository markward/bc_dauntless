###############################################################################
# scale_logger.py
#
# Appended to game/scripts/App.py by tools/setup.py — this is the alternative
# instrumentation snippet for the system-scale investigation (see
# docs/instrumented_experiments/2026-05-12-system-scale-investigation.md).
#
# Hooks UtopiaModule.GetGameTime (per-tick heartbeat). Every DUMP_INTERVAL
# seconds of wall time, walks the currently-rendered SetClass and writes each
# object's class / name / radius / scale / world position plus the active
# camera's frustum to BCScaleLog.cfg.
#
# Each dump REPLACES the previous keys, so the cfg always reflects the most
# recent capture. Latest dump_id is monotonic so the analyzer can confirm
# instrumentation was actually running.
#
# Python 1.5 constraints (see CLAUDE.md "Critical constraints"):
#   - no f-strings, no True/False literals, no "import X as Y"
#   - guard every import with try/except ImportError
#   - file I/O ONLY via g_kConfigMapping.SaveConfigFile
#   - os module is not available; only sys is reliably present
###############################################################################
try:
    import time
    _wall = time.clock
    _last_dump_wall = 0.0
    _dump_id = 0
    _DUMP_INTERVAL = 10.0
    _MAX_OBJECTS = 200
    _orig_GetGameTime = UtopiaModule.GetGameTime

    def _vec3_str(v):
        try:
            return "%f %f %f" % (v.x, v.y, v.z)
        except:
            return ""

    def _safe_call(obj, attr):
        try:
            return getattr(obj, attr)()
        except:
            return None

    def _classname(obj):
        try:
            return obj.__class__.__name__
        except:
            return "<unknown>"

    def _model_path(obj):
        path = _safe_call(obj, "GetModelPath")
        if path is not None:
            return path
        path = _safe_call(obj, "GetModelFileName")
        if path is not None:
            return path
        return ""

    def _dump_camera(pSet, cfg):
        try:
            cam = pSet.GetActiveCamera()
        except:
            cam = None
        if cam is None:
            cfg.SetIntValue("BCScaleLog", "cam_present", 0)
            return
        cfg.SetIntValue("BCScaleLog", "cam_present", 1)
        loc = _safe_call(cam, "GetWorldLocation")
        fwd = _safe_call(cam, "GetWorldForward")
        up  = _safe_call(cam, "GetWorldUp")
        if loc is not None: cfg.SetStringValue("BCScaleLog", "cam_eye", _vec3_str(loc))
        if fwd is not None: cfg.SetStringValue("BCScaleLog", "cam_fwd", _vec3_str(fwd))
        if up  is not None: cfg.SetStringValue("BCScaleLog", "cam_up",  _vec3_str(up))
        try:
            frus = cam.GetNiFrustum()
            cfg.SetFloatValue("BCScaleLog", "cam_left",   frus.m_fLeft)
            cfg.SetFloatValue("BCScaleLog", "cam_right",  frus.m_fRight)
            cfg.SetFloatValue("BCScaleLog", "cam_top",    frus.m_fTop)
            cfg.SetFloatValue("BCScaleLog", "cam_bottom", frus.m_fBottom)
            cfg.SetFloatValue("BCScaleLog", "cam_near",   frus.m_fNear)
            cfg.SetFloatValue("BCScaleLog", "cam_far",    frus.m_fFar)
        except:
            pass

    def _dump_set(pSet, cfg):
        try:
            cfg.SetStringValue("BCScaleLog", "set_name", pSet.GetName())
        except:
            cfg.SetStringValue("BCScaleLog", "set_name", "<unknown>")
        try:
            obj = pSet.GetFirstObject()
        except:
            obj = None
        i = 0
        while obj is not None and i < _MAX_OBJECTS:
            try:
                prefix = "obj" + str(i) + "_"
                cfg.SetStringValue("BCScaleLog", prefix + "type",  _classname(obj))
                name = _safe_call(obj, "GetName")
                cfg.SetStringValue("BCScaleLog", prefix + "name",  name or "")
                cfg.SetStringValue("BCScaleLog", prefix + "model", _model_path(obj))
                r = _safe_call(obj, "GetRadius")
                if r is not None:
                    cfg.SetFloatValue("BCScaleLog", prefix + "radius", float(r))
                s = _safe_call(obj, "GetScale")
                if s is not None:
                    cfg.SetFloatValue("BCScaleLog", prefix + "scale", float(s))
                loc = _safe_call(obj, "GetWorldLocation")
                if loc is not None:
                    cfg.SetStringValue("BCScaleLog", prefix + "pos", _vec3_str(loc))
            except:
                pass
            try:
                obj = pSet.GetNextObject(obj)
            except:
                obj = None
            i = i + 1
        cfg.SetIntValue("BCScaleLog", "n_objects", i)

    def _do_dump(now, frame):
        global _dump_id
        _dump_id = _dump_id + 1
        cfg = g_kConfigMapping
        cfg.SetIntValue("BCScaleLog", "dump_id", _dump_id)
        cfg.SetFloatValue("BCScaleLog", "wall", now)
        cfg.SetIntValue("BCScaleLog", "frame", frame)
        try:
            pSet = g_kSetManager.GetRenderedSet()
        except:
            pSet = None
        if pSet is None:
            cfg.SetIntValue("BCScaleLog", "no_set", 1)
            try:
                cfg.SaveConfigFile("BCScaleLog.cfg")
            except:
                pass
            return
        cfg.SetIntValue("BCScaleLog", "no_set", 0)
        try:
            _dump_set(pSet, cfg)
        except:
            cfg.SetStringValue("BCScaleLog", "set_error", "exception in _dump_set")
        try:
            _dump_camera(pSet, cfg)
        except:
            cfg.SetStringValue("BCScaleLog", "cam_error", "exception in _dump_camera")
        try:
            cfg.SaveConfigFile("BCScaleLog.cfg")
        except:
            pass

    def _on_get_game_time(self):
        global _last_dump_wall
        try:
            now = _wall()
            if (now - _last_dump_wall) >= _DUMP_INTERVAL:
                _last_dump_wall = now
                try:
                    frame = self.GetUpdateNumber()
                except:
                    frame = -1
                _do_dump(now, frame)
        except:
            try:
                import sys
                g_kConfigMapping.SetStringValue("BCScaleLog", "wrapper_error",
                                                str(sys.exc_info()[0]))
                g_kConfigMapping.SaveConfigFile("BCScaleLog.cfg")
            except:
                pass
        return _orig_GetGameTime(self)

    UtopiaModule.GetGameTime = _on_get_game_time

except:
    # Snippet must never crash the game. Failures are silent — the cfg simply
    # won't appear, which the analyzer treats as "instrumentation didn't run".
    pass
