###############################################################################
# q13e_data_members -- VEIN 3: data-member schema of SWIG struct classes
#
# Question(s): docs/instrumented_experiments/2026-07-13-abi-surface-probe.md
#              ~20 classes expose fields through __getmethods__/__setmethods__
#              dicts (e.g. TorpedoAmmoType.m_fLaunchSpeed). Dump every readable /
#              writable member name per class. (Values need a live instance; the
#              schema is state-invariant and dumps at the menu.)
# Needs combat state? NO.
# Output:      game/BCProbe_q13e.cfg
#
# Run in the -TestMode REPL with:  execfile('q13e_data_members.py')
###############################################################################
# PYTHON 1.5: no "import X as Y" / no f-strings / no True-False / "except E,e:" /
# print is a STATEMENT / only App.g_kConfigMapping writes to disk.
###############################################################################

import App
import sys

_cfg      = App.g_kConfigMapping
_SECTION  = "BCProbe_q13e"
_CFG_FILE = "BCProbe_q13e.cfg"
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

def _keys(d):
    try:
        k = d.keys(); k.sort(); return k
    except: return []

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

    _blocks = []; _total = 0
    for _cname in _class_names:
        try: _cls = getattr(App, _cname)
        except: continue
        _gm = None; _sm = None
        try: _gm = _cls.__getmethods__
        except: _gm = None
        try: _sm = _cls.__setmethods__
        except: _sm = None
        if _gm is None and _sm is None: continue      # pure-method class, skip
        _rk = {}
        for _m in _keys(_gm): _rk[_m] = "r"
        for _m in _keys(_sm):
            if _rk.has_key(_m): _rk[_m] = "rw"
            else: _rk[_m] = "w"
        _members = _rk.keys(); _members.sort()
        _lines = []
        for _m in _members: _lines.append("App.%s.%s = %s" % (_cname, _m, _rk[_m]))
        if _lines: _blocks.append((_cname, _lines)); _total = _total + len(_lines)

    _section("inventory")
    _record("python_version", sys.version)
    _record("member_classes", len(_blocks))
    _record("total_dump_lines", _total)
    for _b in _blocks:
        _section("class " + _b[0])
        for _ln in _b[1]: _emit(_ln)

    _flush(); print "done (q13e) -- %d classes with data members" % len(_blocks)
except Exception, _err:
    _record("FATAL", "%s: %s" % (_exc_name(_err), str(_err))); _flush(); print "done (fatal, q13e)"
