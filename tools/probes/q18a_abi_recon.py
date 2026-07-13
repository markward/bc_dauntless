###############################################################################
# q18a_abi_recon -- reconnaissance of the STATIC engine ABI surface
#
# Question(s): docs/instrumented_experiments/2026-07-13-abi-surface-probe.md
#              (companion to q13/q13b -- the static API surface, NOT live state).
#              Settles, on a few representative targets, which deeper
#              introspection veins actually yield data in BC's SWIG build:
#                1. method -> C symbol name        (im_func.__name__)
#                2. method signatures via docstring (im_func.__doc__)   <- the prize
#                3. data-member tables              (cls.__getmethods__)
#                4. Appc.globals namespace          (engine globals/sentinels)
#                5. flat dir(Appc) C-function table (superset of App)
#                6. real inheritance tree           (cls.__bases__)
# Needs combat state? NO -- static surface, run once at the boot menu.
# Output:      game/BCProbe_q18a.cfg, section [BCProbe_q18a]
#
# Run in the -TestMode REPL with:  execfile('q18a_abi_recon.py')
###############################################################################
#
# PYTHON 1.5 CONSTRAINTS -- read docs/instrumented_experiments/console-probe-workflow.md
#   No "import X as Y" / no f-strings / no True/False (use 1/0) /
#   "except E, e:" (comma) / print is a STATEMENT / only App.g_kConfigMapping
#   writes to disk. This recon output is small, so per-line print is FINE here.
#
###############################################################################

import App
import sys

# Appc is the raw SWIG module the App shim wraps. It is imported by App.py, so
# it is already in sys.modules; import it here to introspect it directly.
_Appc = None
try:
    import Appc
    _Appc = Appc
except:
    _Appc = None

_cfg      = App.g_kConfigMapping
_SECTION  = "BCProbe_q18a"
_CFG_FILE = "BCProbe_q18a.cfg"
_log = []

# representative targets -- a ship, a tube, an energy weapon, a data-struct.
_CLASSES = ["ShipClass", "TorpedoTube", "EnergyWeapon", "TorpedoAmmoType",
            "ObjectClass", "NiPoint3"]
# a few methods to probe deeply (class, method)
_METHODS = [("ShipClass", "GetHull"), ("TorpedoTube", "Fire"),
            ("EnergyWeapon", "GetMaxCharge"), ("ObjectClass", "GetName")]

def _exc_name(e):
    try:
        return e.__class__.__name__
    except AttributeError:
        return str(type(e))

def _record(label, value):
    line = "%s = %s" % (str(label), str(value))
    _log.append(line)
    print line

def _section(title):
    bar = "-- " + str(title) + " " + ("-" * max(1, 60 - len(str(title))))
    _log.append(bar)
    print bar

def _safe(obj, name, default):
    try:
        return getattr(obj, name)
    except:
        return default

def _flush():
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

# === PROBE BODY ================================================================

try:
    _section("environment")
    _record("python_version", sys.version)
    _record("Appc_importable", _Appc is not None)

    # -- VEIN 5: flat dir(Appc) C-function table -----------------------------
    _section("VEIN 5 - flat dir(Appc)")
    if _Appc is not None:
        _dApp = []
        _dAppc = []
        try:
            _dApp = dir(App)
        except:
            _dApp = []
        try:
            _dAppc = dir(_Appc)
        except:
            _dAppc = []
        _record("len_dir_App", len(_dApp))
        _record("len_dir_Appc", len(_dAppc))
        # names in Appc but not App (raw functions the shadow layer hides)
        _appset = {}
        for _n in _dApp:
            _appset[_n] = 1
        _onlyc = []
        for _n in _dAppc:
            if not _appset.has_key(_n):
                _onlyc.append(_n)
        _record("count_Appc_only", len(_onlyc))
        _onlyc.sort()
        _record("Appc_only_sample", _onlyc[:25])
    else:
        _record("Appc", "NOT importable -- veins 4/5 unavailable")

    # -- VEIN 4: Appc.globals namespace --------------------------------------
    _section("VEIN 4 - Appc.globals")
    _glob = _safe(_Appc, "globals", None)
    if _glob is not None:
        _dg = []
        try:
            _dg = dir(_glob)
        except:
            _dg = []
        _record("dir_globals_count", len(_dg))
        _dg.sort()
        _record("dir_globals", _dg)
    else:
        _record("Appc.globals", "absent")

    # -- VEINS 1,2,6 + 3: per-class deep introspection -----------------------
    for _cname in _CLASSES:
        _section("class " + _cname)
        _cls = _safe(App, _cname, None)
        if _cls is None:
            _record(_cname, "absent from App")
            continue
        # VEIN 6: inheritance
        _bases = _safe(_cls, "__bases__", ())
        _bn = []
        try:
            for _b in _bases:
                _bn.append(_safe(_b, "__name__", "?"))
        except:
            pass
        _record(_cname + ".__bases__", _bn)
        _record(_cname + ".__doc__", _safe(_cls, "__doc__", None))
        # VEIN 3: data-member tables
        _gm = _safe(_cls, "__getmethods__", None)
        _sm = _safe(_cls, "__setmethods__", None)
        if _gm is not None:
            try:
                _k = _gm.keys(); _k.sort()
                _record(_cname + ".__getmethods__ (readable members)", _k)
            except:
                _record(_cname + ".__getmethods__", "present, unreadable")
        else:
            _record(_cname + ".__getmethods__", "none (pure-method class)")
        if _sm is not None:
            try:
                _k = _sm.keys(); _k.sort()
                _record(_cname + ".__setmethods__ (writable members)", _k)
            except:
                pass

    # -- VEINS 1,2: method -> C symbol + signature docstring -----------------
    for _pair in _METHODS:
        _cn = _pair[0]; _mn = _pair[1]
        _section("method " + _cn + "." + _mn)
        _cls = _safe(App, _cn, None)
        if _cls is None:
            _record("class", "absent")
            continue
        _m = _safe(_cls, _mn, None)
        if _m is None:
            _record(_cn + "." + _mn, "absent")
            continue
        # unbound method -> im_func = the backing Appc builtin
        _f = _safe(_m, "im_func", _m)
        _record(_mn + ".im_func.__name__ (C symbol)", _safe(_f, "__name__", "?"))
        # THE PRIZE: does the docstring carry a signature?
        _record(_mn + ".im_func.__doc__ (signature?)", _safe(_f, "__doc__", None))
        # also try the raw Appc.<Class>_<method> directly
        if _Appc is not None:
            _raw = _safe(_Appc, _cn + "_" + _mn, None)
            if _raw is not None:
                _record("Appc." + _cn + "_" + _mn + ".__doc__", _safe(_raw, "__doc__", None))

    _flush()
    print "done (q18a recon)"

except Exception, _err:
    _record("FATAL", "%s: %s" % (_exc_name(_err), str(_err)))
    _flush()
    print "done (fatal, q18a)"

# === END PROBE BODY ============================================================
