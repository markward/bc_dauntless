###############################################################################
# q13c_symbol_map -- VEIN 1: method -> C symbol name, for the whole surface
#
# Question(s): docs/instrumented_experiments/2026-07-13-abi-surface-probe.md
#              For every method on every App class, recover the backing C symbol
#              via im_func.__name__ (e.g. App.ShipClass.GetHull -> ShipClass_GetHull).
#              Bridges the Python API to the RE'd binary (FUN_* <-> named symbols).
# Needs combat state? NO -- static surface, run once at the boot menu.
# Output:      game/BCProbe_q13c.cfg  (+ _<k>.cfg chunks if _CHUNK=1)
#
# Run in the -TestMode REPL with:  execfile('q13c_symbol_map.py')
###############################################################################
# PYTHON 1.5: no "import X as Y" / no f-strings / no True-False / "except E,e:" /
# print is a STATEMENT / only App.g_kConfigMapping writes to disk.
###############################################################################

import App
import sys

_CHUNK      = 0
_CHUNK_SIZE = 400
_MAX_CHUNKS = 100

_cfg      = App.g_kConfigMapping
_CFG_BASE = "BCProbe_q13c"
_SECTION  = _CFG_BASE
_CFG_FILE = _CFG_BASE + ".cfg"
_log = []

_T_INT = type(0); _T_LONG = type(0L); _T_FLOAT = type(0.0); _T_STR = type('')
class _Probe:
    def _m(self): pass
_T_CLASS = type(_Probe)
_SCALARS = (_T_INT, _T_LONG, _T_FLOAT, _T_STR)

def _exc_name(e):
    try: return e.__class__.__name__
    except AttributeError: return str(type(e))

def _emit(line):        # LOG ONLY -- no console echo (bulk)
    _log.append(line)

def _record(label, value):
    line = "%s = %s" % (str(label), str(value)); _log.append(line); print line

def _section(title):
    bar = "-- " + str(title) + " " + ("-" * max(1, 60 - len(str(title))))
    _log.append(bar); print bar

def _class_attr_names(cls):
    names = {}
    try:
        for nm in dir(cls): names[nm] = 1
    except: pass
    try:
        for base in cls.__bases__:
            for nm in _class_attr_names(base): names[nm] = 1
    except: pass
    return names.keys()

def _flush_single():
    n = len(_log)
    for i in range(n): _cfg.SetStringValue(_SECTION, "r%d" % i, _log[i])
    _cfg.SetIntValue(_SECTION, "n", n)
    try:
        _cfg.SaveConfigFile(_CFG_FILE); print "wrote %s with %d lines" % (_CFG_FILE, n)
    except Exception, _e:
        print "save FAILED: " + str(_e)
    for i in range(n): _cfg.SetStringValue(_SECTION, "r%d" % i, "")
    _cfg.SetIntValue(_SECTION, "n", 0)

def _flush_chunked():
    n = len(_log); nchunks = 0; i = 0
    while i < n and nchunks < _MAX_CHUNKS:
        chunk = _log[i:i + _CHUNK_SIZE]; m = len(chunk)
        if nchunks == 0: fname = _CFG_FILE
        else: fname = "%s_%d.cfg" % (_CFG_BASE, nchunks)
        for j in range(m): _cfg.SetStringValue(_SECTION, "r%d" % j, chunk[j])
        _cfg.SetIntValue(_SECTION, "n", m); _cfg.SetIntValue(_SECTION, "chunk", nchunks)
        try:
            _cfg.SaveConfigFile(fname); print "wrote %s (%d lines, chunk %d)" % (fname, m, nchunks)
        except Exception, _e:
            print "save FAILED (%s): %s" % (fname, str(_e))
        for j in range(m): _cfg.SetStringValue(_SECTION, "r%d" % j, "")
        _cfg.SetIntValue(_SECTION, "n", 0)
        nchunks = nchunks + 1; i = i + _CHUNK_SIZE
    if i < n: print "OVERFLOW: %d lines NOT written" % (n - i)
    print "done (q13c, chunked, %d files)" % nchunks

def _c_symbol(m):
    f = m
    try: f = m.im_func
    except: f = m
    try: return f.__name__
    except: return "?"

# === PROBE BODY ================================================================
try:
    print "q13c: scanning classes ..."
    _dir_app = []
    try: _dir_app = dir(App)
    except: _dir_app = []
    _class_names = []
    for _name in _dir_app:
        try: _v = getattr(App, _name)
        except: continue
        if type(_v) == _T_CLASS: _class_names.append(_name)
    _class_names.sort()
    _ntotal = len(_class_names); print "q13c: %d classes" % _ntotal

    _blocks = []; _total = 0; _idx = 0
    for _cname in _class_names:
        _idx = _idx + 1
        if (_idx % 100) == 0: print "q13c: %d/%d" % (_idx, _ntotal)
        try: _cls = getattr(App, _cname)
        except: continue
        _seen = {}; _lines = []
        for _attr in _class_attr_names(_cls):
            if len(_attr) >= 2 and _attr[:2] == "__": continue
            if _seen.has_key(_attr): continue
            _seen[_attr] = 1
            try: _av = getattr(_cls, _attr)
            except: continue
            if type(_av) in _SCALARS: continue      # scalars are q13's job
            _lines.append("App.%s.%s -> %s" % (_cname, _attr, _c_symbol(_av)))
        _lines.sort()
        if _lines: _blocks.append((_cname, _lines)); _total = _total + len(_lines)

    _section("inventory")
    _record("python_version", sys.version)
    _record("classes", len(_class_names))
    _record("total_dump_lines", _total)
    for _b in _blocks:
        _section("class " + _b[0])
        for _ln in _b[1]: _emit(_ln)

    if _CHUNK: _flush_chunked()
    else: _flush_single(); print "done (q13c)"
except Exception, _err:
    _record("FATAL", "%s: %s" % (_exc_name(_err), str(_err))); _flush_single(); print "done (fatal, q13c)"
