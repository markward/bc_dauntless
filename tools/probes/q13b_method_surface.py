###############################################################################
# q13b_method_surface -- method (callable) surface of every App class
#
# Question(s): docs/instrumented_experiments/2026-07-13-constant-dump-probe.md
#              Q13-5 (stretch) -- for every App class, the non-scalar attribute
#              names (methods) it exposes, so we can diff our shim's METHOD
#              coverage the same way q13 diffs its CONSTANT coverage.
# Needs combat state? NO -- method surface is bound at import, state-invariant.
#              Run once at the boot menu; no battle required.
# Output:      game/BCProbe_q13b.cfg, section [BCProbe_q13b].
#              Chunked fallback writes game/BCProbe_q13b_<k>.cfg for k>=1.
#
# Run in the -TestMode REPL with:  execfile('q13b_method_surface.py')
###############################################################################
#
# PYTHON 1.5 CONSTRAINTS -- read docs/instrumented_experiments/console-probe-workflow.md
#   No "import X as Y" / no f-strings / no True/False (use 1/0) /
#   "except E, e:" (comma) / print is a STATEMENT / only App.g_kConfigMapping
#   writes to disk (open() is blocked). dict.has_key() not "in".
#
###############################################################################

import App
import sys

# --- knobs -------------------------------------------------------------------
_CHUNK      = 0        # set to 1 and re-run ONLY if the single-file write
                       #   truncated (collect_q13.py prints COUNT MISMATCH) or
                       #   SaveConfigFile raised.
_CHUNK_SIZE = 400
_MAX_CHUNKS = 50

_cfg      = App.g_kConfigMapping
_CFG_BASE = "BCProbe_q13b"
_SECTION  = _CFG_BASE
_CFG_FILE = _CFG_BASE + ".cfg"
_log = []

# --- Python 1.5 type sentinels ----------------------------------------------
_T_INT   = type(0)
_T_LONG  = type(0L)
_T_FLOAT = type(0.0)
_T_STR   = type('')
class _Probe:
    def _m(self):
        pass
_T_CLASS = type(_Probe)
_T_INST  = type(_Probe())
_SCALARS = (_T_INT, _T_LONG, _T_FLOAT, _T_STR)

def _exc_name(e):
    try:
        return e.__class__.__name__
    except AttributeError:
        return str(type(e))

def _emit(line):
    _log.append(line)
    print line

def _record(label, value):
    _emit("%s = %s" % (str(label), str(value)))

def _section(title):
    bar = "-- " + str(title) + " " + ("-" * max(1, 60 - len(str(title))))
    _log.append(bar)
    print bar

def _class_attr_names(cls):
    """Union of dir(cls) and (recursively) its bases -- 1.5 dir() does NOT
    walk base classes."""
    names = {}
    try:
        for nm in dir(cls):
            names[nm] = 1
    except:
        pass
    try:
        for base in cls.__bases__:
            for nm in _class_attr_names(base):
                names[nm] = 1
    except:
        pass
    return names.keys()

def _flush_single():
    n = len(_log)
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, _log[i])
    _cfg.SetIntValue(_SECTION, "n", n)
    try:
        _cfg.SaveConfigFile(_CFG_FILE)
        print "wrote %s with %d lines" % (_CFG_FILE, n)
    except Exception, _e:
        print "save FAILED: " + str(_e)
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, "")
    _cfg.SetIntValue(_SECTION, "n", 0)

def _flush_chunked():
    n = len(_log)
    nchunks = 0
    i = 0
    while i < n and nchunks < _MAX_CHUNKS:
        chunk = _log[i:i + _CHUNK_SIZE]
        m = len(chunk)
        if nchunks == 0:
            fname = _CFG_FILE
        else:
            fname = "%s_%d.cfg" % (_CFG_BASE, nchunks)
        for j in range(m):
            _cfg.SetStringValue(_SECTION, "r%d" % j, chunk[j])
        _cfg.SetIntValue(_SECTION, "n", m)
        _cfg.SetIntValue(_SECTION, "chunk", nchunks)
        try:
            _cfg.SaveConfigFile(fname)
            print "wrote %s with %d lines (chunk %d)" % (fname, m, nchunks)
        except Exception, _e:
            print "save FAILED (%s): %s" % (fname, str(_e))
        for j in range(m):
            _cfg.SetStringValue(_SECTION, "r%d" % j, "")
        _cfg.SetIntValue(_SECTION, "n", 0)
        nchunks = nchunks + 1
        i = i + _CHUNK_SIZE
    if i < n:
        print "OVERFLOW: %d lines NOT written (cap %d chunks)" % (n - i, _MAX_CHUNKS)
    print "done (methods, chunked, %d files)" % nchunks

# === PROBE BODY ================================================================

try:
    _dir_app = []
    try:
        _dir_app = dir(App)
    except:
        _dir_app = []

    # classes only
    _class_names = []
    for _name in _dir_app:
        try:
            _v = getattr(App, _name)
        except:
            continue
        if type(_v) == _T_CLASS:
            _class_names.append(_name)
    _class_names.sort()

    # for each class: attribute names that are NOT scalars and NOT dunders =
    # its method / callable surface.
    _class_blocks = []          # list of (classname, [sorted method names])
    _method_total = 0
    for _cname in _class_names:
        try:
            _cls = getattr(App, _cname)
        except:
            continue
        _seen = {}
        _methods = []
        for _attr in _class_attr_names(_cls):
            if len(_attr) >= 2 and _attr[:2] == "__":
                continue
            if _seen.has_key(_attr):
                continue
            _seen[_attr] = 1
            try:
                _av = getattr(_cls, _attr)
            except:
                # unreadable attr -- still record the NAME so coverage diffs see it
                _methods.append(_attr)
                continue
            if type(_av) in _SCALARS:
                continue                       # scalars belong to q13, not here
            _methods.append(_attr)
        _methods.sort()
        if _methods:
            _class_blocks.append((_cname, _methods))
            _method_total = _method_total + len(_methods)

    _total_dump_lines = _method_total

    _section("inventory")
    _record("python_version", sys.version)
    _record("classes", len(_class_names))
    _record("total_dump_lines", _total_dump_lines)

    for _cb in _class_blocks:
        _section("class " + _cb[0])
        for _mname in _cb[1]:
            _emit("App.%s.%s" % (_cb[0], _mname))

    if _CHUNK:
        _flush_chunked()
    else:
        _flush_single()
        print "done (methods)"

except Exception, _err:
    _record("FATAL", "%s: %s" % (_exc_name(_err), str(_err)))
    _flush_single()
    print "done (fatal, methods)"

# === END PROBE BODY ============================================================
