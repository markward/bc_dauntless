###############################################################################
# TEMPLATE -- copy to tools/probes/q0N_<short_name>.py and edit
#
# Question(s): <which Q from which runbook in docs/instrumented_experiments/>
# Needs combat state? <yes | no -- if yes, operator must start Quick Battle
#                     and acquire a target (Tab) BEFORE running this probe>
# Output:      game/BCProbe_q0N.cfg, section [BCProbe_q0N]
#
# Run in the -TestMode REPL with:  execfile('q0N_<short_name>.py')
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
_SECTION = "BCProbe_q0N"             # <-- CHANGE qN to match the filename
_CFG_FILE = "BCProbe_q0N.cfg"        # <-- CHANGE qN to match the filename
_log = []

# CONSOLE OUTPUT DISCIPLINE -- the q13 friction lesson.
# print() is a SYNCHRONOUS write to the -TestMode console and is the dominant
# cost of a probe: q13's ~2000-line dump took ~30 MINUTES of console spam;
# buffering silently and printing nothing per line cut it to ~10 SECONDS.
# Therefore _record/_section are BUFFER-ONLY -- they append to _log and do NOT
# print. Only _echo() prints, and only for a handful of status lines. NEVER
# call _echo (or print) inside a data loop.
_VERBOSE = 0     # 1 = also echo every buffered line (SLOW; small interactive
                 #     runs only). Leave 0 for any real dump.

def _exc_name(e):
    """Exception class name -- safe against Python 1.5 string exceptions."""
    try:
        return e.__class__.__name__
    except AttributeError:
        return str(type(e))

def _echo(msg):
    """The ONLY unconditional console print. Reserve for status/summary lines
    (wrote / save FAILED / done / FATAL). NEVER call inside a data loop."""
    print msg

def _record(label, value):
    """Buffer "label = value" into the result log. BUFFER-ONLY -- does not
    print (see the console-output-discipline note above). The result file is
    built from _log, so output is unaffected; only console spam is removed."""
    line = "%s = %s" % (str(label), str(value))
    _log.append(line)
    if _VERBOSE:
        print line

def _try(label, fn, args):
    """Call fn(*args).  For top-level functions where the callable is already
    resolved (App.Game_GetCurrentPlayer, App.ShipClass_Cast).  Bare except
    also catches Python 1.5 string exceptions."""
    try:
        return apply(fn, args)
    except:
        _record(label + " FAILED",
                "exc_type=%s exc_value=%s" % (str(sys.exc_type), str(sys.exc_value)))
        return None

def _call(label, obj, name, args):
    """Resolve obj.<name> and call it with args.  Use this for any method
    reached through a SWIG-wrapped object -- _try("label", obj.method, args)
    evaluates the lookup BEFORE _try runs, so attribute errors escape the
    safety net.  _call does the getattr inside the try."""
    try:
        return apply(getattr(obj, name), args)
    except:
        _record(label + " FAILED",
                "exc_type=%s exc_value=%s" % (str(sys.exc_type), str(sys.exc_value)))
        return None

def _section(title):
    """Heading line in the result log. BUFFER-ONLY (see _record)."""
    bar = "-- " + str(title) + " " + ("-" * max(1, 60 - len(str(title))))
    _log.append(bar)
    if _VERBOSE:
        print bar

def _flush():
    """Write _log to cfg, then scrub the keys so Options.cfg stays clean."""
    n = len(_log)
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, _log[i])
    _cfg.SetIntValue(_SECTION, "n", n)
    try:
        _cfg.SaveConfigFile(_CFG_FILE)
        _echo("wrote " + _CFG_FILE + " with %d lines" % n)
    except Exception, _e:
        _echo("save FAILED: " + str(_e))
    # Scrub immediately -- single-threaded, no race window with the game.
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, "")
    _cfg.SetIntValue(_SECTION, "n", 0)

# === PROBE BODY ================================================================

try:
    _section("environment")
    _record("python_version", sys.version)
    _record("frame", App.g_kSystemWrapper.GetUpdateNumber())
    _record("game_time", App.g_kUtopiaModule.GetGameTime())

    # <-- YOUR PROBE LOGIC HERE.  Use _record(label, value) for everything
    #     that should land in the result file.

except Exception, _err:
    _record("FATAL", "%s: %s" % (_exc_name(_err), str(_err)))
    _echo("FATAL: %s: %s" % (_exc_name(_err), str(_err)))   # status line -> visible

# === END PROBE BODY ============================================================

_flush()
_echo("done")
