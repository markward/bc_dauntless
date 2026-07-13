###############################################################################
# q13h_inheritance -- VEIN 6: the real class hierarchy (cls.__bases__)
#
# Question(s): docs/instrumented_experiments/2026-07-13-abi-surface-probe.md
#              For every App class, dump its direct base classes. Confirms from
#              the engine the object hierarchy CLAUDE.md documents by inference
#              (ObjectClass -> PhysicsObjectClass -> DamageableObject -> ShipClass).
# Needs combat state? NO.
# Output:      game/BCProbe_q13h.cfg
#
# Run in the -TestMode REPL with:  execfile('q13h_inheritance.py')
###############################################################################
# PYTHON 1.5: no "import X as Y" / no f-strings / no True-False / "except E,e:" /
# print is a STATEMENT / only App.g_kConfigMapping writes to disk.
###############################################################################

import App
import sys

_cfg      = App.g_kConfigMapping
_SECTION  = "BCProbe_q13h"
_CFG_FILE = "BCProbe_q13h.cfg"
_log = []

class _Probe: pass
_T_CLASS = type(_Probe)

def _exc_name(e):
    try: return e.__class__.__name__
    except AttributeError: return str(type(e))

def _emit(line): _log.append(line)

def _record(label, value):
    line = "%s = %s" % (str(label), str(value)); _log.append(line); print line

def _section(title):
    bar = "-- " + str(title) + " " + ("-" * max(1, 60 - len(str(title))))
    _log.append(bar); print bar

def _base_names(cls):
    out = []
    try:
        for _b in cls.__bases__:
            try: out.append(_b.__name__)
            except: out.append("?")
    except: pass
    return out

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
    _dir_app = []
    try: _dir_app = dir(App)
    except: _dir_app = []
    _class_names = []
    for _name in _dir_app:
        try: _v = getattr(App, _name)
        except: continue
        if type(_v) == _T_CLASS: _class_names.append(_name)
    _class_names.sort()

    _lines = []
    for _cname in _class_names:
        try: _cls = getattr(App, _cname)
        except: continue
        _bn = _base_names(_cls)
        if _bn: _lines.append("App.%s : %s" % (_cname, ", ".join(_bn)))
        else:   _lines.append("App.%s : (root)" % _cname)
    _lines.sort()

    _section("inventory")
    _record("python_version", sys.version)
    _record("classes", len(_class_names))
    _record("total_dump_lines", len(_lines))
    _section("inheritance")
    for _ln in _lines: _emit(_ln)

    _flush(); print "done (q13h) -- %d classes" % len(_class_names)
except Exception, _err:
    _record("FATAL", "%s: %s" % (_exc_name(_err), str(_err))); _flush(); print "done (fatal, q13h)"
