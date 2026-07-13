###############################################################################
# q13f_globals -- VEIN 4: the Appc.globals namespace (engine globals/sentinels)
#
# Question(s): docs/instrumented_experiments/2026-07-13-abi-surface-probe.md
#              dir(Appc.globals) enumerates every engine global -- the g_k*
#              singletons plus sentinels like ANY_TARGET / INVALID_DESTINATION
#              that our shim must match. Dump each name, its type, and its scalar
#              value where one is readable.
# Needs combat state? NO.
# Output:      game/BCProbe_q13f.cfg
#
# Run in the -TestMode REPL with:  execfile('q13f_globals.py')
###############################################################################
# PYTHON 1.5: no "import X as Y" / no f-strings / no True-False / "except E,e:" /
# print is a STATEMENT / only App.g_kConfigMapping writes to disk.
###############################################################################

import App
import sys

_Appc = None
try:
    import Appc
    _Appc = Appc
except: _Appc = None

_cfg      = App.g_kConfigMapping
_SECTION  = "BCProbe_q13f"
_CFG_FILE = "BCProbe_q13f.cfg"
_log = []

_T_INT = type(0); _T_LONG = type(0L); _T_FLOAT = type(0.0); _T_STR = type('')
_SCALARS = (_T_INT, _T_LONG, _T_FLOAT, _T_STR)

def _exc_name(e):
    try: return e.__class__.__name__
    except AttributeError: return str(type(e))

def _emit(line): _log.append(line)

def _record(label, value):
    line = "%s = %s" % (str(label), str(value)); _log.append(line); print line

def _section(title):
    bar = "-- " + str(title) + " " + ("-" * max(1, 60 - len(str(title))))
    _log.append(bar); print bar

def _typename(t):
    try: return t.__name__
    except:
        s = str(t)
        try:
            a = s.index("'"); b = s.index("'", a + 1); return s[a+1:b]
        except: return s

def _flush():
    n = len(_log)
    for i in range(n): _cfg.SetStringValue(_SECTION, "r%d" % i, _log[i])
    _cfg.SetIntValue(_SECTION, "n", n)
    try:
        _cfg.SaveConfigFile(_CFG_FILE); print "wrote %s with %d lines" % (_CFG_FILE, n)
    except Exception, _e:
        print "save FAILED: " + str(_e)
    for i in range(n): _cfg.SetStringValue(_SECTION, "r%d" % i, "")
    _cfg.SetIntValue(_SECTION, "n", 0)

# === PROBE BODY ================================================================
try:
    _section("inventory")
    _record("python_version", sys.version)
    _record("Appc_importable", _Appc is not None)

    _glob = None
    try: _glob = _Appc.globals
    except: _glob = None
    if _glob is None:
        _record("Appc.globals", "absent")
        _record("total_dump_lines", 0)
        _flush(); print "done (q13f) -- no globals"
    else:
        _names = []
        try: _names = dir(_glob)
        except: _names = []
        _names.sort()
        _total = 0
        _section("Appc.globals")
        for _nm in _names:
            if len(_nm) >= 2 and _nm[:2] == "__": continue
            try: _v = getattr(_glob, _nm)
            except:
                _emit("Appc.globals.%s = <unreadable>" % _nm); _total = _total + 1; continue
            _t = type(_v); _tn = _typename(_t)
            if _t in _SCALARS:
                _emit("Appc.globals.%s = %s %s" % (_nm, repr(_v), _tn))
            else:
                _emit("Appc.globals.%s = <%s>" % (_nm, _tn))
            _total = _total + 1
        # patch total_dump_lines into the inventory (append a record after scan)
        _record("total_dump_lines", _total)
        _flush(); print "done (q13f) -- %d globals" % _total
except Exception, _err:
    _record("FATAL", "%s: %s" % (_exc_name(_err), str(_err))); _flush(); print "done (fatal, q13f)"
