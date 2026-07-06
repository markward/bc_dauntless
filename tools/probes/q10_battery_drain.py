###############################################################################
# q10_battery_drain.py
#
# Question(s): Q1-Q4 from docs/instrumented_experiments/2026-07-06-battery-drain-order.md
#   Q1 Does the backup battery drain while main > 0?
#   Q2 Measured drain rates (main / backup) pre-tractor vs tractor-held.
#   Q3 Do the sliders move during the run? (AdjustPower throttling)
#   Q4 After releasing tractor + green alert, does main refill before backup?
#
# Needs combat state? NO -- operator sets up state by script call.
#   However: tractor engagement requires a LIVE TARGET.
#   Start Quick Battle first so a target ship is available in-space.
#   The script sets red alert and boosts sliders; operator engages the tractor
#   manually via the in-game UI (or keys) AFTER calling setup(), then calls
#   sample() every ~5 seconds.
#
# Output: game/BCProbe_q10.cfg, section [BCProbe_q10]
#
# Sampling workflow (no timer -- timer-based probes unproven in this workflow):
#   execfile('q10_battery_drain.py')   -- defines setup/sample/finish
#   setup()                            -- sets red alert, all sliders 1.25
#                                     -- prints initial state snapshot
#   # operator engages tractor via UI
#   sample()                           -- call every 5-10 s to record state
#   sample()
#   ...                                -- continue while drain is interesting
#   # operator releases tractor + switches to green alert
#   sample()                           -- post-release recharge phase
#   sample()
#   finish()                           -- flush all rows to BCProbe_q10.cfg
#
# Run in the -TestMode REPL with:  execfile('q10_battery_drain.py')
###############################################################################
#
# PYTHON 1.5 CONSTRAINTS
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
_SECTION = "BCProbe_q10"
_CFG_FILE = "BCProbe_q10.cfg"
_log = []
_samples = []

# --------------------------------------------------------------------------
# Helpers (identical contract to _template.py)
# --------------------------------------------------------------------------

def _exc_name(e):
    try:
        return e.__class__.__name__
    except AttributeError:
        return str(type(e))

def _record(label, value):
    line = "%s = %s" % (str(label), str(value))
    _log.append(line)
    print line

def _try(label, fn, args):
    try:
        return apply(fn, args)
    except:
        _record(label + " FAILED",
                "exc_type=%s exc_value=%s" % (str(sys.exc_type), str(sys.exc_value)))
        return None

def _call(label, obj, name, args):
    try:
        return apply(getattr(obj, name), args)
    except:
        _record(label + " FAILED",
                "exc_type=%s exc_value=%s" % (str(sys.exc_type), str(sys.exc_value)))
        return None

def _quiet_call(obj, name, args):
    # Like _call but swallows failures silently (no FAILED line). Used for
    # optional readings whose absence we don't care about.
    try:
        return apply(getattr(obj, name), args)
    except:
        return None

def _section(title):
    bar = "-- " + str(title) + " " + ("-" * max(1, 60 - len(str(title))))
    _log.append(bar)
    print bar

def _join(parts, sep):
    # Python 1.5 has no str.join method and no guaranteed string module in
    # this static build -- hand-roll the join with + and a while loop.
    s = ""
    i = 0
    while i < len(parts):
        if i > 0:
            s = s + sep
        s = s + parts[i]
        i = i + 1
    return s

def _flush():
    n = len(_log)
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, _log[i])
    _cfg.SetIntValue(_SECTION, "n", n)
    try:
        _cfg.SaveConfigFile(_CFG_FILE)
        print "wrote " + _CFG_FILE + " with %d lines" % n
    except Exception, _e:
        print "save FAILED: " + str(_e)
    # Scrub immediately -- single-threaded, no race window with the game.
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, "")
    _cfg.SetIntValue(_SECTION, "n", 0)

# --------------------------------------------------------------------------
# Power accessors  (all via _call -- SWIG-wrapped objects)
# --------------------------------------------------------------------------

def _get_player():
    return _try("Game_GetCurrentPlayer", App.Game_GetCurrentPlayer, ())

def _power_snapshot(label):
    """Append one labelled snapshot row to _log and return a summary string."""
    p = _get_player()
    if p is None:
        _record(label + ".error", "no player")
        return
    pwr = _call(label + ".GetPowerSubsystem", p, "GetPowerSubsystem", ())
    if pwr is None:
        _record(label + ".error", "no PowerSubsystem")
        return

    main   = _call(label + ".main",   pwr, "GetMainBatteryPower",   ())
    backup = _call(label + ".backup", pwr, "GetBackupBatteryPower", ())
    output = _call(label + ".output", pwr, "GetPowerOutput",        ())
    avail  = _call(label + ".avail",  pwr, "GetAvailablePower",     ())
    disp   = _call(label + ".disp",   pwr, "GetPowerDispensed",     ())
    # GetPowerWanted needs an arg we don't have; not one of Q1-Q4, so read it
    # quietly and let it be None (renders as 0.0) rather than spamming FAILED.
    wanted = _quiet_call(pwr, "GetPowerWanted",        ())
    mcon   = _call(label + ".mcon",   pwr, "GetMainConduitCapacity", ())
    bcon   = _call(label + ".bcon",   pwr, "GetBackupConduitCapacity", ())
    condpct = _call(label + ".condpct", pwr, "GetConditionPercentage", ())

    gt = _call(label + ".gt", App.g_kUtopiaModule, "GetGameTime", ())

    # 7 slider subsystems (read via PoweredSubsystem.GetPowerPercentageWanted).
    # Build BOTH the labelled list (_sliders, for the human snapshot) and the
    # bare-value list (_svals, for the compact row) in one pass -- Python 1.5
    # has no str.split, so we must never reconstruct values from the labels.
    _sliders = []
    _svals = []
    for _sname, _getter in (
            ("impulse", "GetImpulseEngineSubsystem"),
            ("warp",    "GetWarpEngineSubsystem"),
            ("shields", "GetShields"),
            ("phasers", "GetPhaserSystem"),
            ("torps",   "GetTorpedoSystem"),
            ("pulse",   "GetPulseWeaponSystem"),
            ("sensors", "GetSensorSubsystem"),
    ):
        _sub = _call(label + "." + _sname, p, _getter, ())
        if _sub is None:
            _sliders.append(_sname + "=NA")
            _svals.append("NA")
        else:
            _pct = _call(label + "." + _sname + ".pct", _sub,
                         "GetPowerPercentageWanted", ())
            if _pct is None:
                _sliders.append(_sname + "=NA")
                _svals.append("NA")
            else:
                _sliders.append("%s=%.2f" % (_sname, _pct))
                _svals.append("%.2f" % _pct)

    # Tractor IsFiring
    _trac_str = "NA"
    try:
        _tbs = p.GetTractorBeamSystem()
        if _tbs is not None:
            _n = _tbs.GetNumChildSubsystems()
            _firing = 0
            _i = 0
            while _i < _n:
                _w = _tbs.GetWeapon(_i)
                if _w is not None:
                    if _w.IsFiring():
                        _firing = 1
                _i = _i + 1
            _trac_str = "%d" % _firing
    except:
        _trac_str = "ERR"

    _record(label + ".snapshot",
            "gt=%.2f main=%.1f backup=%.1f output=%.1f avail=%.1f "
            "disp=%.1f wanted=%.1f mcon=%.1f bcon=%.1f condpct=%.3f "
            "tractor=%s sliders=[%s]" % (
                (gt or 0.0), (main or 0.0), (backup or 0.0),
                (output or 0.0), (avail or 0.0), (disp or 0.0),
                (wanted or 0.0), (mcon or 0.0), (bcon or 0.0),
                (condpct or 0.0), _trac_str,
                _join(_sliders, " ")
            ))

    # Also record per-sample row for the collect.py-parseable section
    # (_svals was built alongside _sliders above -- no splitting needed.)
    _samples.append(
        "%.2f %.1f %.1f %.1f %.1f %.1f %.1f %.1f %.1f %.3f %s %s" % (
            (gt or 0.0), (main or 0.0), (backup or 0.0),
            (output or 0.0), (avail or 0.0), (disp or 0.0),
            (wanted or 0.0), (mcon or 0.0), (bcon or 0.0),
            (condpct or 0.0), _trac_str,
            _join(_svals, " ")
        )
    )

# --------------------------------------------------------------------------
# Public interface for the operator
# --------------------------------------------------------------------------

def setup():
    """Set red alert, all seven sliders to 1.25, and take the first snapshot.
    Call this once BEFORE engaging the tractor."""
    _section("setup")
    _record("info", "setting RED_ALERT + all sliders to 1.25")

    p = _get_player()
    if p is None:
        _record("setup.error", "no player -- start Quick Battle first")
        return

    # Red alert
    try:
        p.SetAlertLevel(App.ShipClass.RED_ALERT)
        _record("alert", "RED_ALERT set")
    except Exception, _e:
        _record("alert.FAILED", "%s: %s" % (_exc_name(_e), str(_e)))

    # Boost all powered subsystem sliders to 1.25
    for _sname, _getter in (
            ("impulse", "GetImpulseEngineSubsystem"),
            ("warp",    "GetWarpEngineSubsystem"),
            ("shields", "GetShields"),
            ("phasers", "GetPhaserSystem"),
            ("torps",   "GetTorpedoSystem"),
            ("pulse",   "GetPulseWeaponSystem"),
            ("sensors", "GetSensorSubsystem"),
    ):
        try:
            _sub = getattr(p, _getter)()
            if _sub is not None:
                _sub.SetPowerPercentageWanted(1.25)
                _record("slider." + _sname, "set to 1.25")
            else:
                _record("slider." + _sname, "subsystem not found")
        except Exception, _e:
            _record("slider." + _sname + ".FAILED",
                    "%s: %s" % (_exc_name(_e), str(_e)))

    _section("baseline snapshot (pre-tractor)")
    _power_snapshot("t0")
    _record("instruction",
            "now engage tractor via UI, then call sample() every 5-10 s")
    print "setup done -- engage tractor, then call sample() periodically"


def sample():
    """Take one power snapshot. Call this every 5-10 s while the scenario runs."""
    _n = len(_samples)
    _power_snapshot("s%d" % _n)
    print "sample %d recorded" % _n


def finish():
    """Flush all recorded data to BCProbe_q10.cfg then scrub the singleton."""
    _section("sample rows (compact -- one per sample() call)")
    _record("sample_fields",
            "game_time main backup output avail disp wanted mcon bcon "
            "condpct tractor impulse warp shields phasers torps pulse sensors")
    _j = 0
    for _row in _samples:
        _record("sample_%d" % _j, _row)
        _j = _j + 1
    _record("sample_count", len(_samples))
    _flush()
    print "finish done -- run: uv run python tools/probes/collect.py q10"


# --------------------------------------------------------------------------
# On execfile: register and print instructions
# --------------------------------------------------------------------------

try:
    _section("environment")
    _record("python_version", sys.version)
    _record("frame", App.g_kSystemWrapper.GetUpdateNumber())
    _record("game_time", App.g_kUtopiaModule.GetGameTime())
    _record("instructions",
            "call setup() -> engage tractor -> sample() x N -> "
            "release tractor + green alert -> sample() x N -> finish()")

except Exception, _err:
    _record("FATAL", "%s: %s" % (_exc_name(_err), str(_err)))
    _flush()

print "q10_battery_drain loaded -- call setup() to begin"
