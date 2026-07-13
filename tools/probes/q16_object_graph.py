###############################################################################
# q16_object_graph -- the live space-side object + subsystem graph.
#
# Question(s): docs/instrumented_experiments/2026-07-13-object-graph-probe.md
#              Q16-1 rendered-set object roster, Q16-2 per-ship subsystem tree,
#              Q16-3 Galaxy-vs-Galaxy symmetry oracle, Q16-4 GetAllSets,
#              Q16-5 cast-ladder coverage (UNKNOWN objects).
# Needs combat state? Needs a loaded scenario (A = Galaxy vs Galaxy QB;
#              B = E1M1 checkpoints). Dump from the EXTERIOR/tactical view so the
#              rendered set is the space set (bridge view -> empty roster).
# Output:      game/BCProbe_q16_<scenario>.cfg  (<scenario> = A / B / unknown)
#
# One-shot execfile() probe -- pure read of live state, no handlers:
#   execfile('q16_object_graph.py')
#
# REQUIRES probe_harness.py in game/ (push.py copies it alongside). Reuses the
# harness's hardened set-walk (iter_set_objids -- objid-advance + circular
# dedup, from q14), describe() cast ladder, scenario_tag(), and buffer-only,
# 180-char-capped flush.
#
# PYTHON 1.5 CONSTRAINTS -- see console-probe-workflow.md
#   No "import X as Y" / no f-strings / no True/False / "except E, e:" /
#   print is a statement / dict.has_key() not "in" / keep cfg lines short.
###############################################################################

import App
import sys
import string
import probe_harness
_h = probe_harness              # no "import X as Y" in Python 1.5

_CHUNK = 0
_MAX_SUBS = 500                 # guard on the subsystem walk

# Subsystem cast ladder, MOST-SPECIFIC first (a TorpedoTube also casts to
# ShipSubsystem -- we want the specific label). Extends the harness's object
# ladder with the subsystem-type factories confirmed in App.py.
_SUB_CASTS = [
    ("TorpedoTube",            "TorpedoTube_Cast"),
    ("TorpedoSystem",          "TorpedoSystem_Cast"),
    ("PhaserBank",             "PhaserBank_Cast"),
    ("PhaserSystem",           "PhaserSystem_Cast"),
    ("PulseWeapon",            "PulseWeapon_Cast"),
    ("PulseWeaponSystem",      "PulseWeaponSystem_Cast"),
    ("HullClass",              "HullClass_Cast"),
    ("ShieldClass",            "ShieldClass_Cast"),
    ("ImpulseEngineSubsystem", "ImpulseEngineSubsystem_Cast"),
    ("WarpEngineSubsystem",    "WarpEngineSubsystem_Cast"),
    ("SensorSubsystem",        "SensorSubsystem_Cast"),
    ("CloakingSubsystem",      "CloakingSubsystem_Cast"),
    ("RepairSubsystem",        "RepairSubsystem_Cast"),
    ("TractorBeamSystem",      "TractorBeamSystem_Cast"),
    ("PowerSubsystem",         "PowerSubsystem_Cast"),
    ("PoweredSubsystem",       "PoweredSubsystem_Cast"),
    ("WeaponSystem",           "WeaponSystem_Cast"),
    ("ShipSubsystem",          "ShipSubsystem_Cast"),
]

# Getters attempted on every subsystem; only non-None results are emitted, so
# this self-selects to whatever the engine actually exposes for that type.
_GENERIC_GETTERS = [
    ("cond",     "GetCondition"),
    ("maxcond",  "GetMaxCondition"),
    ("disabled", "GetDisabled"),
    ("power",    "GetPower"),
    ("maxpower", "GetMaxPower"),
    ("curmaxspeed", "GetCurMaxSpeed"),
]

_diag = {}          # last _collect_subsystems diagnostics (ct_ok / iter_ok)


def _pos(obj):
    v = _h._safe(obj, "GetWorldLocation", ())
    if v is None:
        return "pos=?"
    try:
        return "pos=(%.1f,%.1f,%.1f)" % (v.x, v.y, v.z)
    except:
        return "pos=?"


def _subtype(pSub):
    """Return (label, cast_pointer). The cast pointer matters: type-specific
    getters (GetMaxReady on a TorpedoTube) live on the cast type, not the base
    ShipSubsystem wrapper the iterator hands back -- calling them on the base
    silently returns None (the same q11 gotcha, one level down)."""
    for pair in _SUB_CASTS:
        c = _h._cast(pair[1], pSub)
        if c:
            return (pair[0], c)
    return ("UNKNOWN", None)


def _subprops(pSub, stype):
    props = []
    nc = _h._safe(pSub, "GetNumChildSubsystems", ())
    if nc is not None:
        props.append("nchild=%s" % str(nc))
    for g in _GENERIC_GETTERS:
        v = _h._safe(pSub, g[1], ())
        if v is not None:
            props.append("%s=%s" % (g[0], str(v)))
    if stype == "TorpedoTube":
        for g in [("maxready", "GetMaxReady"), ("numready", "GetNumReady"),
                  ("reload", "GetReloadDelay"), ("immediate", "GetImmediateDelay")]:
            v = _h._safe(pSub, g[1], ())
            if v is not None:
                props.append("%s=%s" % (g[0], str(v)))
    return props


def _collect_subsystems(pShip):
    """Every subsystem on the ship, dedup'd by objid. The ship iterator
    (StartGetSubsystemMatch/GetNextSubsystemMatch/End) yields the matched set;
    we then child-walk each via GetChildSubsystem to catch nested subsystems
    (e.g. tubes under the torpedo system) the flat match may not include."""
    seen = {}
    result = []
    # Guard the constant separately so iter_ok can distinguish "constant missing"
    # from "method failed".
    ct = None
    try:
        ct = App.CT_SHIP_SUBSYSTEM
    except:
        ct = None
    it = None
    if ct is not None:
        it = _h._safe(pShip, "StartGetSubsystemMatch", (ct,))
    _diag["ct_ok"] = (ct is not None)
    _diag["iter_ok"] = (it is not None)
    if it is not None:
        sub = _h._safe(pShip, "GetNextSubsystemMatch", (it,))
        guard = 0
        while sub is not None and guard < _MAX_SUBS:
            oid = _h._safe(sub, "GetObjID", ())
            if oid is None or not seen.has_key(oid):
                if oid is not None:
                    seen[oid] = 1
                result.append(sub)
            sub = _h._safe(pShip, "GetNextSubsystemMatch", (it,))
            guard = guard + 1
        _h._safe(pShip, "EndGetSubsystemMatch", (it,))
    # child-walk (dedup) to catch nested subsystems
    i = 0
    while i < len(result) and len(result) < _MAX_SUBS:
        nc = _h._safe(result[i], "GetNumChildSubsystems", ())
        n = 0
        if nc is not None:
            try:
                n = int(nc)
            except:
                n = 0
        for k in range(n):
            child = _h._safe(result[i], "GetChildSubsystem", (k,))
            if child is not None:
                oid = _h._safe(child, "GetObjID", ())
                if oid is None or not seen.has_key(oid):
                    if oid is not None:
                        seen[oid] = 1
                    result.append(child)
        i = i + 1
    return result


# === PROBE BODY ================================================================

try:
    tag = _h.scenario_tag()
    _h.configure("BCProbe_q16_" + tag, "BCProbe_q16_" + tag + ".cfg")

    _h.section("provenance")
    for _ln in _h.provenance():
        _h.emit(_ln)

    pSet = None
    try:
        pSet = App.g_kSetManager.GetRenderedSet()
    except:
        pSet = None

    # Q16-4 -- all sets (best-effort; record the repr, don't risk iterating)
    _h.section("sets")
    _h.record("all_sets", _h._safe(App.g_kSetManager, "GetAllSets", ()))

    # Q16-1 -- object roster of the rendered set (hardened set-walk)
    _h.section("objects (rendered set)")
    objs = _h.iter_set_objids(pSet)
    _h.record("n_objects", len(objs))
    ships = []
    idx = 0
    for pair in objs:
        obj = pair[1]
        _h.emit("o%03d = %s %s" % (idx, _h.describe(obj), _pos(obj)))
        # Set iteration hands back BASE ObjectClass wrappers; type-specific
        # methods (StartGetSubsystemMatch) need the CAST ShipClass pointer, so
        # store the cast result -- not the base wrapper (q11 gotcha #4).
        pShipCast = _h._cast("ShipClass_Cast", obj)
        if pShipCast:
            ships.append(pShipCast)
        idx = idx + 1
    _h.record("n_ships", len(ships))

    # Q16-2 / Q16-3 -- per-ship subsystem tree (identity first, props after, so
    # the 180-char cap trims props not identity). Two Galaxies -> diff off-box.
    for pShip in ships:
        nm = _h._safe(pShip, "GetName", ())
        oid = _h._safe(pShip, "GetObjID", ())
        subs = _collect_subsystems(pShip)
        _h.section("ship '%s' objid=%s subsystems (%d) ct_ok=%s iter_ok=%s"
                   % (str(nm), str(oid), len(subs),
                      str(_diag.get("ct_ok")), str(_diag.get("iter_ok"))))
        sidx = 0
        for sub in subs:
            tinfo = _subtype(sub)
            stype = tinfo[0]
            pTyped = tinfo[1]                 # cast pointer for type-specific getters
            if pTyped is None:
                pTyped = sub
            sname = _h._safe(sub, "GetName", ())
            par = _h._safe(sub, "GetParentSubsystem", ())
            parname = "-"
            if par is not None:
                pn = _h._safe(par, "GetName", ())
                if pn is not None:
                    parname = str(pn)
            props = _subprops(pTyped, stype)
            _h.emit("ss%03d %s name='%s' parent='%s' %s"
                    % (sidx, stype, str(sname), parname, string.join(props, " ")))
            sidx = sidx + 1

    _n = _h.line_count()
    _h.section("summary")
    _h.record("data_lines", _n)
    if _CHUNK:
        _h.flush_chunked()
    else:
        _h.flush()
    _h.echo("q16 done (scenario=%s, %d objects, %d ships, %d lines)"
            % (tag, len(objs), len(ships), _h.line_count()))

except Exception, _err:
    _h.record("FATAL", "%s: %s" % (_h.exc_name(_err), str(_err)))
    _h.echo("FATAL: %s: %s" % (_h.exc_name(_err), str(_err)))
    _h.flush()

# === END PROBE BODY ============================================================
