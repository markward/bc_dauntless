###############################################################################
# q01_console_io.py
#
# Question(s): Part A of 2026-06-29-weapon-exchange-console-probe.md --
#              "confirm the console's I/O" before any deterministic damage work.
# Needs combat state? no -- but Quick Battle helps because Game_GetCurrentPlayer
#              returns None on the main menu.
# Output:      game/BCProbe_q01.cfg, section [BCProbe_q01]
#
# Establishes, on the operator's machine:
#  - Python 1.5 version string and sys.path
#  - what bare-expression echo looks like (return values printed by the REPL?)
#  - whether Game_GetCurrentPlayer() yields a live player when called from a
#    probe (vs. only when typed at the prompt)
#  - whether AddDamage's parent class is reachable as App.DamageableObject
#  - whether TGPoint3 is constructible (needed by every later damage probe)
#
# Run:  execfile('q01_console_io.py')
###############################################################################

import App
import sys

_cfg = App.g_kConfigMapping
_SECTION = "BCProbe_q01"
_CFG_FILE = "BCProbe_q01.cfg"
_log = []

def _exc_name(e):
    # Python 1.5 allows string exceptions, which have no __class__.
    try:
        return e.__class__.__name__
    except AttributeError:
        return str(type(e))

def _record(label, value):
    line = "%s = %s" % (str(label), str(value))
    _log.append(line)
    print line

def _section(title):
    bar = "-- " + str(title) + " " + ("-" * max(1, 60 - len(str(title))))
    _log.append(bar)
    print bar

def _flush():
    n = len(_log)
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, _log[i])
    _cfg.SetIntValue(_SECTION, "n", n)
    try:
        _cfg.SaveConfigFile(_CFG_FILE)
        print "wrote " + _CFG_FILE + " with %d lines" % n
    except Exception, _e:
        print "save FAILED: " + str(_e)
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, "")
    _cfg.SetIntValue(_SECTION, "n", 0)

# === PROBE BODY ================================================================

try:
    _section("python host")
    _record("sys.version", sys.version)
    _record("sys.path", sys.path)
    _record("sys.stdout type", type(sys.stdout))
    _record("has getvalue", hasattr(sys.stdout, "getvalue"))

    _section("App module surface")
    _record("App.g_kSystemWrapper", App.g_kSystemWrapper)
    _record("App.g_kUtopiaModule", App.g_kUtopiaModule)
    _record("App.g_kConfigMapping", App.g_kConfigMapping)
    _record("App.g_kMusicManager exists", hasattr(App, "g_kMusicManager"))
    _record("App.DamageableObject exists", hasattr(App, "DamageableObject"))
    _record("App.TGPoint3 exists", hasattr(App, "TGPoint3"))

    _section("frame counters")
    _record("frame (GetUpdateNumber)", App.g_kSystemWrapper.GetUpdateNumber())
    _record("game_time (GetGameTime)", App.g_kUtopiaModule.GetGameTime())
    _record("real_time (GetRealTime)", App.g_kUtopiaModule.GetRealTime())

    _section("player ship")
    try:
        _player = App.Game_GetCurrentPlayer()
        _record("Game_GetCurrentPlayer()", _player)
        if _player is not None:
            _record("player.GetName()", _player.GetName())
            _loc = _player.GetWorldLocation()
            _record("loc type", type(_loc))
            _record("loc x", _loc.x)
            _record("loc y", _loc.y)
            _record("loc z", _loc.z)
            try:
                _tgt = _player.GetTarget()
                _record("player.GetTarget()", _tgt)
                if _tgt is not None:
                    _record("target.GetName()", _tgt.GetName())
                    _sh = _tgt.GetShields()
                    _record("target.GetShields()", _sh)
                    if _sh is not None:
                        _record("sh.GetNumShields()", _sh.GetNumShields())
                        _record("sh.GetCurShields(0)", _sh.GetCurShields(0))
                        _record("sh.GetMaxShields(0)", _sh.GetMaxShields(0))
                    _record("target.GetHull().GetCondition()",
                            _tgt.GetHull().GetCondition())
            except Exception, _e:
                _record("target read FAILED", "%s: %s" % (_exc_name(_e), str(_e)))
        else:
            _record("note", "no live player -- start Quick Battle and rerun")
    except Exception, _e:
        _record("player read FAILED", "%s: %s" % (_exc_name(_e), str(_e)))

    _section("TGPoint3 construction")
    # Confirmed: new_TGPoint3 takes 0 args. Construct then assign .x/.y/.z.
    try:
        _p = App.TGPoint3()
        _p.x = 1.0
        _p.y = 2.0
        _p.z = 3.0
        _record("TGPoint3() then x/y/z assign", _p)
        _record("p.x", _p.x)
        _record("p.y", _p.y)
        _record("p.z", _p.z)
    except Exception, _e:
        _record("TGPoint3 0-arg ctor FAILED", "%s: %s" % (_exc_name(_e), str(_e)))

except Exception, _err:
    _record("FATAL", "%s: %s" % (_exc_name(_err), str(_err)))

# === END PROBE BODY ============================================================

_flush()
print "done"
