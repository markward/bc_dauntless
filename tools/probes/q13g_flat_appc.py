###############################################################################
# q13g_flat_appc -- VEIN 5: the flat dir(Appc) C-function/name table
#
# Question(s): docs/instrumented_experiments/2026-07-13-abi-surface-probe.md
#              dir(Appc) is the raw SWIG export -- a superset of dir(App). Dump
#              every name, tagged whether it is also visible on App ("shared") or
#              only on Appc ("only"), so we see the raw engine functions the
#              shadow layer hides.
# Needs combat state? NO.
# Output:      game/BCProbe_q13g.cfg  (+ _<k>.cfg chunks if _CHUNK=1)
#
# Run in the -TestMode REPL with:  execfile('q13g_flat_appc.py')
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

_CHUNK      = 0
_CHUNK_SIZE = 400
_MAX_CHUNKS = 100

_cfg      = App.g_kConfigMapping
_CFG_BASE = "BCProbe_q13g"
_SECTION  = _CFG_BASE
_CFG_FILE = _CFG_BASE + ".cfg"
_log = []

def _exc_name(e):
    try: return e.__class__.__name__
    except AttributeError: return str(type(e))

def _emit(line): _log.append(line)

def _record(label, value):
    line = "%s = %s" % (str(label), str(value)); _log.append(line); print line

def _section(title):
    bar = "-- " + str(title) + " " + ("-" * max(1, 60 - len(str(title))))
    _log.append(bar); print bar

def _typename(v):
    try: return type(v).__name__
    except:
        s = str(type(v))
        try:
            a = s.index("'"); b = s.index("'", a + 1); return s[a+1:b]
        except: return s

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
    print "done (q13g, chunked, %d files)" % nchunks

# === PROBE BODY ================================================================
try:
    if _Appc is None:
        _section("inventory"); _record("Appc", "NOT importable"); _record("total_dump_lines", 0)
        _flush_single(); print "done (q13g) -- no Appc"
    else:
        print "q13g: reading dir(Appc) ..."
        _dApp = []; _dAppc = []
        try: _dApp = dir(App)
        except: _dApp = []
        try: _dAppc = dir(_Appc)
        except: _dAppc = []
        _appset = {}
        for _n in _dApp: _appset[_n] = 1
        _dAppc.sort()
        _section("inventory")
        _record("python_version", sys.version)
        _record("len_dir_App", len(_dApp))
        _record("len_dir_Appc", len(_dAppc))
        _only = 0
        for _n in _dAppc:
            if not _appset.has_key(_n): _only = _only + 1
        _record("count_Appc_only", _only)
        _record("total_dump_lines", len(_dAppc))
        _section("dir(Appc)")
        for _n in _dAppc:
            if _appset.has_key(_n): _tag = "shared"
            else: _tag = "only"
            try: _tn = _typename(getattr(_Appc, _n))
            except: _tn = "?"
            _emit("Appc.%s = %s %s" % (_n, _tag, _tn))
        if _CHUNK: _flush_chunked()
        else: _flush_single(); print "done (q13g) -- %d names, %d Appc-only" % (len(_dAppc), _only)
except Exception, _err:
    _record("FATAL", "%s: %s" % (_exc_name(_err), str(_err))); _flush_single(); print "done (fatal, q13g)"
