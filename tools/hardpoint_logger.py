###############################################################################
# hardpoint_logger.py
#
# Appended to game/scripts/App.py by tools/setup.py - captures per-phaser-
# bank hardpoint geometry for the hardpoint-scale investigation (see
# docs/instrumented_experiments/2026-05-15-hardpoint-scale-investigation.md).
#
# Hooks UtopiaModule.GetGameTime (per-tick heartbeat). Once per ship-spawn
# we walk the player ship's PhaserSystem subsystems and dump:
#   - bank N: name, SDK position, right axis, length, world location
#   - ship pose at the moment of capture (location + rotation rows)
#   - ship.GetRadius()
# to BCHardpointLog.cfg via SaveConfigFile.
#
# The dump REPLACES the previous keys, so the cfg always reflects the most
# recent capture. dump_id is monotonic so we can confirm instrumentation is
# alive.
#
# Python 1.5 constraints (see CLAUDE.md "Critical constraints"):
#   - no f-strings, no True/False literals, no "import X as Y"
#   - guard every import with try/except ImportError
#   - file I/O ONLY via g_kConfigMapping.SaveConfigFile
#   - os module is not available; only sys is reliably present
###############################################################################
try:
    _last_dump_wall = 0.0
    _dump_id = 0
    _DUMP_INTERVAL = 5.0
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

    def _dump_ship_pose(ship, cfg):
        loc = _safe_call(ship, "GetWorldLocation")
        if loc is not None:
            cfg.SetStringValue("BCHardpointLog", "ship_loc", _vec3_str(loc))
        try:
            rot = ship.GetWorldRotation()
            for row in (0, 1, 2):
                cfg.SetStringValue("BCHardpointLog",
                                    "ship_rot_row%d" % row,
                                    "%f %f %f" % (rot.GetRow(row).x,
                                                  rot.GetRow(row).y,
                                                  rot.GetRow(row).z))
        except:
            pass
        rad = _safe_call(ship, "GetRadius")
        if rad is not None:
            cfg.SetFloatValue("BCHardpointLog", "ship_radius", rad)
        try:
            cfg.SetStringValue("BCHardpointLog", "ship_class", ship.GetName())
        except:
            pass

    def _dump_bank(prefix, bank, cfg):
        try:
            cfg.SetStringValue("BCHardpointLog", prefix + "_name", bank.GetName())
        except:
            pass
        # SDK-declared local fields (sanity check - these should equal
        # the hardpoint script's SetPosition / SetRight / SetLength).
        pos = _safe_call(bank, "GetPosition")
        if pos is not None:
            cfg.SetStringValue("BCHardpointLog", prefix + "_local_pos", _vec3_str(pos))
        right = _safe_call(bank, "GetRight")
        if right is not None:
            cfg.SetStringValue("BCHardpointLog", prefix + "_local_right", _vec3_str(right))
        direction = _safe_call(bank, "GetDirection")
        if direction is not None:
            cfg.SetStringValue("BCHardpointLog", prefix + "_local_dir", _vec3_str(direction))
        length = _safe_call(bank, "GetLength")
        if length is not None:
            cfg.SetFloatValue("BCHardpointLog", prefix + "_length", float(length))
        # BC's interpretation: what world position the engine puts this
        # bank at. THIS is the value we need.
        wloc = _safe_call(bank, "GetWorldLocation")
        if wloc is not None:
            cfg.SetStringValue("BCHardpointLog", prefix + "_world_pos", _vec3_str(wloc))
        # Charge model (for Q-H6 sanity).
        try:
            prop = bank.GetProperty()
            cfg.SetFloatValue("BCHardpointLog", prefix + "_discharge", prop.GetNormalDischargeRate())
            cfg.SetFloatValue("BCHardpointLog", prefix + "_recharge",  prop.GetRechargeRate())
            cfg.SetFloatValue("BCHardpointLog", prefix + "_maxcharge", prop.GetMaxCharge())
            cfg.SetFloatValue("BCHardpointLog", prefix + "_minfire",   prop.GetMinFiringCharge())
        except:
            pass

    def _dump_now(cfg, wall, frame, game_time):
        global _dump_id
        _dump_id = _dump_id + 1
        cfg.SetIntValue("BCHardpointLog", "dump_id", _dump_id)
        cfg.SetFloatValue("BCHardpointLog", "wall", wall)
        cfg.SetIntValue("BCHardpointLog", "frame", frame)
        cfg.SetFloatValue("BCHardpointLog", "game_time", game_time)
        try:
            player = Game_GetCurrentPlayer()
        except:
            player = None
        if player is None:
            cfg.SetIntValue("BCHardpointLog", "player_present", 0)
            return
        cfg.SetIntValue("BCHardpointLog", "player_present", 1)
        _dump_ship_pose(player, cfg)
        # Walk phaser banks.
        try:
            phasers = player.GetPhaserSystem()
        except:
            phasers = None
        if phasers is None:
            cfg.SetIntValue("BCHardpointLog", "n_phasers", 0)
        else:
            n = phasers.GetNumChildSubsystems()
            cfg.SetIntValue("BCHardpointLog", "n_phasers", n)
            for i in range(n):
                bank = phasers.GetWeapon(i)
                if bank is not None:
                    _dump_bank("phaser%d" % i, bank, cfg)
        # Walk torpedo tubes too (for Q-H2 cross-axis comparison).
        try:
            torps = player.GetTorpedoSystem()
        except:
            torps = None
        if torps is None:
            cfg.SetIntValue("BCHardpointLog", "n_torps", 0)
        else:
            n = torps.GetNumChildSubsystems()
            cfg.SetIntValue("BCHardpointLog", "n_torps", n)
            for i in range(n):
                tube = torps.GetWeapon(i)
                if tube is not None:
                    _dump_bank("torp%d" % i, tube, cfg)

    def _GetGameTime_wrapped(self):
        global _last_dump_wall
        result = _orig_GetGameTime(self)
        try:
            import time
            wall = time.time()
        except:
            return result
        if wall - _last_dump_wall < _DUMP_INTERVAL:
            return result
        _last_dump_wall = wall
        try:
            cfg = g_kConfigMapping
        except:
            return result
        try:
            frame = g_kSystemWrapper.GetUpdateNumber()
        except:
            frame = 0
        try:
            _dump_now(cfg, wall, frame, result)
        except:
            try:
                import sys
                cfg.SetStringValue("BCHardpointLog", "dump_error",
                                    "%s %s" % (str(sys.exc_type), str(sys.exc_value)))
            except:
                pass
        try:
            cfg.SaveConfigFile("BCHardpointLog.cfg")
        except:
            pass
        return result

    UtopiaModule.GetGameTime = _GetGameTime_wrapped
except:
    # Any setup failure: try to leave a breadcrumb but don't crash the
    # game.  SaveConfigFile is the only allowed side effect.
    try:
        import sys
        g_kConfigMapping.SetStringValue("BCHardpointLog", "instr_error",
                                         "%s %s" % (str(sys.exc_type),
                                                      str(sys.exc_value)))
        g_kConfigMapping.SaveConfigFile("BCHardpointLog.cfg")
    except:
        pass
