###############################################################################
# q14_env -- engine environment census + shared-harness validation.
#
# Question(s): docs/instrumented_experiments/2026-07-13-env-and-harness-probe.md
#              Q14-1 sys.builtin_module_names, Q14-2 stdlib availability table,
#              Q14-3 sys.modules (menu vs battle diff), Q14-4 interpreter vitals,
#              Q14-5 probe_harness sanity (provenance() + persistent_owner()).
# Needs combat state? NO for the payload. Run ONCE at the boot menu, then ONCE in
#              a QuickBattle (Galaxy vs Galaxy) for the Q14-3 diff. The probe
#              auto-detects its phase from whether a current player exists.
# Output:      game/BCProbe_q14_<phase>.cfg, section [BCProbe_q14_<phase>]
#              (<phase> is "menu" or "battle").
#
# REQUIRES probe_harness.py in game/ (push.py copies it alongside this probe).
# Run in the -TestMode REPL with:  execfile('q14_env.py')
#
# PYTHON 1.5 CONSTRAINTS -- see console-probe-workflow.md
#   No "import X as Y" / no f-strings / no True/False (use 1/0) /
#   "except E, e:" (comma) / print is a STATEMENT / only App.g_kConfigMapping
#   writes to disk. All console output goes through the buffer-only harness.
###############################################################################

import App
import sys
import probe_harness
_h = probe_harness              # no "import X as Y" in Python 1.5

# --- knob -------------------------------------------------------------------
_CHUNK = 0          # set to 1 and re-run ONLY if the single-file write raised
                    #   or truncated (collect_q14.py would say so).

# --- phase auto-detection ---------------------------------------------------
_player = None
try:
    _player = App.Game_GetCurrentPlayer()
except:
    _player = None
if _player is not None:
    _PHASE = "battle"
else:
    _PHASE = "menu"

_h.configure("BCProbe_q14_" + _PHASE, "BCProbe_q14_" + _PHASE + ".cfg")

# stdlib modules the probe suite actually cares about. A FIXED literal list --
# no dynamic import gymnastics. cPickle/marshal matter for the BCS save work;
# math/types were the perennial "may be absent" hedges.
_CANDIDATES = ["sys", "os", "string", "math", "re", "time", "types",
               "cPickle", "pickle", "struct", "marshal", "copy", "random",
               "operator", "traceback", "cStringIO", "StringIO"]

try:
    # ---- provenance + harness sanity (Q14-5) -------------------------------
    _h.section("provenance")
    for _ln in _h.provenance():
        _h.emit(_ln)
    _h.record("phase", _PHASE)
    _po = _h.persistent_owner()
    _h.record("persistent_owner", _h.describe(_po))

    # ---- Q14-4 interpreter vitals ------------------------------------------
    _h.section("interpreter")
    _h.record("python_version", sys.version)
    try:
        _h.record("maxint", sys.maxint)
    except:
        _h.record("maxint", "?")
    try:
        _h.record("platform", sys.platform)
    except:
        _h.record("platform", "?")
    try:
        _h.record("copyright", sys.copyright)
    except:
        _h.record("copyright", "?")
    try:
        _h.record("prefix", sys.prefix)
    except:
        _h.record("prefix", "?")

    # ---- Q14-4 sys.path ----------------------------------------------------
    _h.section("sys.path")
    try:
        _p = sys.path
        for _i in range(len(_p)):
            _h.record("path%d" % _i, _p[_i])
        _h.record("n_path", len(_p))
    except:
        _h.record("sys.path", "read FAILED: %s" % str(sys.exc_value))

    # ---- Q14-1 builtin (compiled-in) modules -------------------------------
    _h.section("builtin_module_names")
    try:
        _bm = list(sys.builtin_module_names)
        _bm.sort()
        for _i in range(len(_bm)):
            _h.record("builtin%d" % _i, _bm[_i])
        _h.record("n_builtins", len(_bm))
    except:
        _h.record("builtins", "read FAILED: %s" % str(sys.exc_value))

    # ---- Q14-2 stdlib availability -----------------------------------------
    _h.section("stdlib availability")
    for _m in _CANDIDATES:
        try:
            __import__(_m)
            _h.record(_m, "available")
        except:
            _h.record(_m, "ABSENT: %s" % str(sys.exc_value))

    # ---- Q14-3 sys.modules (phase-sensitive: mission import graph) ---------
    _h.section("sys.modules")
    try:
        _mk = sys.modules.keys()
        _mk.sort()
        for _i in range(len(_mk)):
            _h.record("mod%d" % _i, _mk[_i])
        _h.record("n_modules", len(_mk))
    except:
        _h.record("sys.modules", "read FAILED: %s" % str(sys.exc_value))

    # ---- write -------------------------------------------------------------
    _n = _h.line_count()
    _h.section("summary")
    _h.record("data_lines", _n)          # off-box truncation sanity check
    if _CHUNK:
        _h.flush_chunked()
    else:
        _h.flush()
    _h.echo("done (phase=%s, %d lines)" % (_PHASE, _h.line_count()))

except Exception, _err:
    _h.record("FATAL", "%s: %s" % (_h.exc_name(_err), str(_err)))
    _h.echo("FATAL: %s: %s" % (_h.exc_name(_err), str(_err)))
    _h.flush()
