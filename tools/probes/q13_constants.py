###############################################################################
# q13_constants -- ground-truth values for EVERY App constant (both scopes)
#
# Question(s): docs/instrumented_experiments/2026-07-13-constant-dump-probe.md
#              Q13-1 (module-scope scalars), Q13-2 (class-scope scalars),
#              Q13-3 (dir(App) type inventory), Q13-4 (state-invariance: run
#              once at the boot menu, once in a battle, then diff the two files).
# Needs combat state? NO for the menu phase. For the battle phase, start a
#              QuickBattle (Galaxy vs Galaxy -- see canonical-probe-scenarios.md)
#              and fly, THEN run this again. The probe auto-detects which phase
#              it is in from whether a current player exists -- no flag to edit.
# Output:      game/BCProbe_q13_<phase>.cfg, section [BCProbe_q13_<phase>]
#              (<phase> is "menu" or "battle"). Chunked fallback writes
#              game/BCProbe_q13_<phase>_<k>.cfg for k>=1.
#
# Run in the -TestMode REPL with:  execfile('q13_constants.py')
###############################################################################
#
# PYTHON 1.5 CONSTRAINTS -- read docs/instrumented_experiments/console-probe-workflow.md
#   No "import X as Y" / no f-strings / no True/False (use 1/0) /
#   "except E, e:" (comma) / print is a STATEMENT / only App.g_kConfigMapping
#   writes to disk (open() is blocked). dict.has_key() not "in". repr() exists.
#
###############################################################################

import App
import sys

# --- knobs -------------------------------------------------------------------
_CHUNK      = 0        # set to 1 and re-run ONLY if the single-file write
                       #   truncated (collect_q13.py prints COUNT MISMATCH) or
                       #   SaveConfigFile raised.
_CHUNK_SIZE = 400      # rows per file in chunked mode
_MAX_CHUNKS = 50       # hard cap (20000 rows); overflow is reported, not dropped
_STR_CAP    = 200      # truncate string constant values to this many repr chars

# --- phase auto-detection (Q13-4) -------------------------------------------
_player = None
try:
    _player = App.Game_GetCurrentPlayer()
except:
    _player = None
if _player is not None:
    _PHASE = "battle"
else:
    _PHASE = "menu"

_cfg      = App.g_kConfigMapping
_CFG_BASE = "BCProbe_q13_" + _PHASE
_SECTION  = _CFG_BASE
_CFG_FILE = _CFG_BASE + ".cfg"
_log = []

# --- Python 1.5 type sentinels (no reliance on the `types` module) ----------
_T_INT   = type(0)
_T_LONG  = type(0L)          # 0L literal is valid in 1.5
_T_FLOAT = type(0.0)
_T_STR   = type('')
class _Probe:
    def _m(self):
        pass
_T_CLASS = type(_Probe)      # <type 'class'>
_T_INST  = type(_Probe())    # <type 'instance'>
_SCALARS = (_T_INT, _T_LONG, _T_FLOAT, _T_STR)

def _exc_name(e):
    try:
        return e.__class__.__name__
    except AttributeError:
        return str(type(e))

def _emit(line):
    """Append a fully-formed dump line -- LOG ONLY, no console echo. Per-line
    print to the TestMode console is O(n) (or worse) per line and is the tar pit
    that made a full dump take tens of minutes; the bulk goes to the cfg, not
    the screen. Progress is visible via _section headers + the gather heartbeat."""
    _log.append(line)

def _record(label, value):
    """_record DOES echo (few lines: inventory + heartbeats)."""
    line = "%s = %s" % (str(label), str(value))
    _log.append(line)
    print line

def _section(title):
    bar = "-- " + str(title) + " " + ("-" * max(1, 60 - len(str(title))))
    _log.append(bar)
    print bar

def _typename(t):
    """Robust type name -- 1.5 type objects may lack __name__."""
    try:
        return t.__name__
    except:
        s = str(t)                       # e.g. "<type 'int'>"
        try:
            a = s.index("'")
            b = s.index("'", a + 1)
            return s[a + 1:b]
        except:
            return s

def _fmt_scalar(v):
    """Format one scalar: decimal(+hex) for int/long, repr for float/string."""
    t = type(v)
    tn = _typename(t)
    if t == _T_INT or t == _T_LONG:
        h = None
        if v >= 0:
            try:
                h = "0x%x" % v
            except:
                h = None
        if h is not None:
            return "%s (%s) %s" % (str(v), h, tn)
        return "%s %s" % (str(v), tn)
    if t == _T_FLOAT:
        return "%s %s" % (repr(v), tn)
    # string
    s = repr(v)
    if len(s) > _STR_CAP:
        s = s[:_STR_CAP] + "...(trunc)"
    return "%s %s" % (s, tn)

def _class_attr_names(cls):
    """Union of dir(cls) and (recursively) its bases -- 1.5 dir() does NOT
    walk base classes, so a constant defined on a base would be missed."""
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

# --- flush: single-file (primary) -------------------------------------------
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
    # scrub immediately -- single-threaded, no race with the game loop
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, "")
    _cfg.SetIntValue(_SECTION, "n", 0)

# --- flush: chunked multi-file (fallback) -----------------------------------
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
        # scrub THIS chunk before building the next -- keeps the live section
        # to one chunk's worth of keys at any instant.
        for j in range(m):
            _cfg.SetStringValue(_SECTION, "r%d" % j, "")
        _cfg.SetIntValue(_SECTION, "n", 0)
        nchunks = nchunks + 1
        i = i + _CHUNK_SIZE
    if i < n:
        # never silently truncate -- the header's total_dump_lines will also
        # flag this off-box, but shout here too.
        print "OVERFLOW: %d lines NOT written (cap %d chunks)" % (n - i, _MAX_CHUNKS)
    print "done (phase=%s, chunked, %d files)" % (_PHASE, nchunks)

# === PROBE BODY ================================================================

try:
    # ---- module scope: classify every dir(App) name -----------------------
    _dir_app = []
    print "q13: scanning dir(App) ..."
    try:
        _dir_app = dir(App)
    except:
        _dir_app = []

    _module_scalar_lines = []
    _class_names = []
    _n_instances = 0
    _n_others = 0
    for _name in _dir_app:
        try:
            _v = getattr(App, _name)
        except:
            _n_others = _n_others + 1
            continue
        _t = type(_v)
        if _t in _SCALARS:
            _module_scalar_lines.append("App.%s = %s" % (_name, _fmt_scalar(_v)))
        elif _t == _T_CLASS:
            _class_names.append(_name)
        elif _t == _T_INST:
            _n_instances = _n_instances + 1
        else:
            _n_others = _n_others + 1
    _module_scalar_lines.sort()
    _class_names.sort()
    _ntotal = len(_class_names)
    print "q13: %d classes to walk" % _ntotal

    # ---- class scope: scalars on every class (Q13-2) -----------------------
    _class_blocks = []          # list of (classname, [sorted lines])
    _class_scalar_total = 0
    _idx = 0
    for _cname in _class_names:
        _idx = _idx + 1
        if (_idx % 100) == 0:                  # gather heartbeat -- pinpoints a hang
            print "q13: walked %d/%d classes" % (_idx, _ntotal)
        try:
            _cls = getattr(App, _cname)
        except:
            continue
        _seen = {}
        _lines = []
        for _attr in _class_attr_names(_cls):
            if len(_attr) >= 2 and _attr[:2] == "__":
                continue                       # skip dunders (__doc__ etc.)
            try:
                _av = getattr(_cls, _attr)
            except:
                continue
            if type(_av) in _SCALARS:
                _key = "App.%s.%s" % (_cname, _attr)
                if not _seen.has_key(_key):
                    _seen[_key] = 1
                    _lines.append("%s = %s" % (_key, _fmt_scalar(_av)))
        _lines.sort()
        if _lines:
            _class_blocks.append((_cname, _lines))
            _class_scalar_total = _class_scalar_total + len(_lines)

    _total_dump_lines = len(_module_scalar_lines) + _class_scalar_total

    # ---- inventory header FIRST (the anti-truncation invariant) ------------
    _section("inventory")
    _record("python_version", sys.version)
    _record("phase", _PHASE)
    _record("dir_App_names", len(_dir_app))
    _record("module_scalars", len(_module_scalar_lines))
    _record("classes", len(_class_names))
    _record("instances", _n_instances)
    _record("others", _n_others)
    _record("class_scalars", _class_scalar_total)
    _record("total_dump_lines", _total_dump_lines)

    # ---- module scalar block -----------------------------------------------
    _section("module scalars")
    for _ln in _module_scalar_lines:
        _emit(_ln)

    # ---- per-class blocks --------------------------------------------------
    for _cb in _class_blocks:
        _section("class " + _cb[0])
        for _ln in _cb[1]:
            _emit(_ln)

    if _CHUNK:
        _flush_chunked()
    else:
        _flush_single()
        print "done (phase=%s)" % _PHASE

except Exception, _err:
    _record("FATAL", "%s: %s" % (_exc_name(_err), str(_err)))
    _flush_single()             # best-effort dump of whatever we gathered
    print "done (fatal, phase=%s)" % _PHASE

# === END PROBE BODY ============================================================
