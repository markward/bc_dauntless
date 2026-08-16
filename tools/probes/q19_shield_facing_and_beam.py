###############################################################################
# Question(s): Q1, Q2 from
#              docs/instrumented_experiments/2026-08-16-shield-facing-and-beam-falsifiers.md
# Needs combat state? YES -- operator must start Quick Battle, be in a ship with
#                     phasers, and have a TARGET ACQUIRED (Tab) before running.
#                     The target must start with FULL SHIELDS.
# Output:      game/BCProbe_q19.cfg, section [BCProbe_q19]
#
# Run in the -TestMode REPL with:  execfile('q19_shield_facing_and_beam.py')
###############################################################################
#
# PYTHON 1.5 CONSTRAINTS -- read docs/instrumented_experiments/console-probe-workflow.md
#
# - No "import X as Y"          -> import X; Y = X
# - No f-strings                -> "%s %d" % (s, n)
# - No True/False               -> 1 / 0
# - except SomeError, e:        (comma, NOT "as")
# - print is a STATEMENT        -> print x  (no parens around the whole expr)
# - Only App.g_kConfigMapping writes outside this process. open() is blocked.
#
###############################################################################

import App
import sys

_cfg = App.g_kConfigMapping
_SECTION = "BCProbe_q19"
_CFG_FILE = "BCProbe_q19.cfg"
_log = []

_VERBOSE = 0

def _exc_name(e):
    try:
        return e.__class__.__name__
    except AttributeError:
        return str(type(e))

def _echo(msg):
    print msg

def _record(label, value):
    line = "%s = %s" % (str(label), str(value))
    _log.append(line)
    if _VERBOSE:
        print line

def _try(label, fn, args):
    try:
        return apply(fn, args)
    except:
        _record(label + " FAILED",
                "exc_type=%s exc_value=%s" % (str(sys.exc_type), str(sys.exc_value)))
        return None

def _call(label, obj, name, args):
    try:
        return apply(getattr(obj, name), args)
    except:
        _record(label + " FAILED",
                "exc_type=%s exc_value=%s" % (str(sys.exc_type), str(sys.exc_value)))
        return None

def _section(title):
    bar = "-- " + str(title) + " " + ("-" * max(1, 60 - len(str(title))))
    _log.append(bar)
    if _VERBOSE:
        print bar

def _flush():
    n = len(_log)
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, _log[i])
    _cfg.SetIntValue(_SECTION, "n", n)
    try:
        _cfg.SaveConfigFile(_CFG_FILE)
        _echo("wrote " + _CFG_FILE + " with %d lines" % n)
    except Exception, _e:
        _echo("save FAILED: " + str(_e))
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, "")
    _cfg.SetIntValue(_SECTION, "n", 0)


def _snapshot_facings(pShields, tag):
    """Record all six facings' absolute charge and percentage under `tag`.

    Q1 turns entirely on WHICH INDEX MOVES, so every index is recorded every
    time -- never just the one we expect.
    """
    for i in range(6):
        cur = _call("cur[%d]" % i, pShields, "GetCurShields", (i,))
        pct = _call("pct[%d]" % i, pShields, "GetSingleShieldPercentage", (i,))
        _record("%s.cur[%d]" % (tag, i), cur)
        _record("%s.pct[%d]" % (tag, i), pct)


# === PROBE BODY ================================================================

try:
    _section("environment")
    _record("python_version", sys.version)
    _record("frame", App.g_kSystemWrapper.GetUpdateNumber())
    _record("game_time", App.g_kUtopiaModule.GetGameTime())

    pGame = _try("Game_GetCurrentGame", App.Game_GetCurrentGame, ())
    pPlayer = None
    if pGame:
        pPlayer = _call("GetPlayer", pGame, "GetPlayer", ())
    _record("player", pPlayer and _call("player.GetName", pPlayer, "GetName", ()))

    pTarget = None
    if pPlayer:
        pTarget = _call("GetTarget", pPlayer, "GetTarget", ())
    _record("target", pTarget and _call("target.GetName", pTarget, "GetName", ()))

    if pTarget is None:
        _record("ABORT", "no target acquired -- press Tab to acquire one, then re-run")
    else:
        _section("target geometry (to interpret the facing index)")
        # The facing index is meaningless without knowing where the shot came
        # from RELATIVE TO THE TARGET'S BODY FRAME. Record both world positions
        # and the target's rotation columns so the runbook can work out the
        # approach aspect offline rather than trusting the operator's estimate.
        tpos = _call("target.GetWorldLocation", pTarget, "GetWorldLocation", ())
        ppos = _call("player.GetWorldLocation", pPlayer, "GetWorldLocation", ())
        if tpos:
            _record("target.pos", "%f %f %f" % (tpos.x, tpos.y, tpos.z))
        if ppos:
            _record("player.pos", "%f %f %f" % (ppos.x, ppos.y, ppos.z))
        trot = _call("target.GetWorldRotation", pTarget, "GetWorldRotation", ())
        if trot:
            for c in range(3):
                col = _call("col%d" % c, trot, "GetCol", (c,))
                if col:
                    _record("target.rot.col%d" % c, "%f %f %f" % (col.x, col.y, col.z))
        _record("target.radius", _call("radius", pTarget, "GetRadius", ()))

        pShields = _call("target.GetShields", pTarget, "GetShields", ())
        _record("target.has_shields", pShields is not None)

        if pShields:
            _section("Q1 -- PRE-FIRE facing snapshot (all six)")
            _record("GetNumShields", _call("n", pShields, "GetNumShields", ()))
            _snapshot_facings(pShields, "pre")

            _section("Q1 -- max shields per facing (to normalise the delta)")
            for i in range(6):
                _record("max[%d]" % i, _call("max[%d]" % i, pShields, "GetMaxShields", (i,)))

            _section("Q2 -- breach/damaged flags PRE")
            # The two queries are specified to be able to DISAGREE:
            # IsShieldBreached is computed (disabled/off, or charge < 1.0, or
            # the flag), IsShieldDamaged reads the raw byte. Record both.
            for i in range(6):
                _record("pre.breached[%d]" % i,
                        _call("b[%d]" % i, pShields, "IsShieldBreached", (i,)))
                _record("pre.damaged[%d]" % i,
                        _call("d[%d]" % i, pShields, "IsShieldDamaged", (i,)))

            _section("phaser state (for the 0.5s pulse question)")
            pPhasers = _call("player.GetPhaserSystem", pPlayer, "GetPhaserSystem", ())
            if pPhasers:
                _record("phaser.power_level", _call("pl", pPhasers, "GetPowerLevel", ()))

    _section("OPERATOR STEP")
    _record("next", "Fire ONE short phaser burst at the recorded aspect, then "
                    "re-run this probe. Compare pre.* from run 1 with pre.* "
                    "from run 2 -- the index whose cur[] dropped is the facing "
                    "that took the hit for that approach aspect.")

except Exception, _err:
    _record("FATAL", "%s: %s" % (_exc_name(_err), str(_err)))
    _echo("FATAL: %s: %s" % (_exc_name(_err), str(_err)))

# === END PROBE BODY ============================================================

_flush()
_echo("done")
