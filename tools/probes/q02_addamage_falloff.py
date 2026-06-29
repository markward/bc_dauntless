###############################################################################
# q02_addamage_falloff.py
#
# Question(s): Q1, Q3 from 2026-06-29-weapon-exchange-console-probe.md.
#   Q1 - Anchor: at the target centre, does AddDamage(node, r, D) deliver D?
#   Q3 - Routing: does AddDamage subtract from facing shield, or hit hull?
#   Q2 (position falloff) is DEFERRED -- AddDamage takes a scene node, not a
#       TGPoint3 (the SDK's pEmitPos name is misleading; Effects.py:691
#       literally says "INVALID NiAVObject wrapper").  Position can't be
#       varied by mutating coords -- needs different sub-nodes at different
#       ship locations.  See q03 once written.
#
#   This probe instead sweeps the RADIUS parameter at a fixed node (target
#   centre) to see whether splash radius affects delivered damage.
#
# Needs combat state? YES -- Quick Battle, Tab-lock a *hostile ship* before
#                     running.
# Output: game/BCProbe_q02.cfg, section [BCProbe_q02]
#
# Run: execfile('q02_addamage_falloff.py')
###############################################################################

import App
import sys

_cfg = App.g_kConfigMapping
_SECTION = "BCProbe_q02"
_CFG_FILE = "BCProbe_q02.cfg"
_log = []

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

def _flush():
    n = len(_log)
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, _log[i])
    _cfg.SetIntValue(_SECTION, "n", n)
    try:
        _cfg.SaveConfigFile(_CFG_FILE)
        print "wrote " + _CFG_FILE + " with %d lines" % n
    except:
        print "save FAILED"
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, "")
    _cfg.SetIntValue(_SECTION, "n", 0)

def _try(label, fn, args):
    """Call fn(*args). Bare except catches Python 1.5 string exceptions too."""
    try:
        return apply(fn, args)
    except:
        _record(label + " FAILED",
                "exc_type=%s exc_value=%s" % (str(sys.exc_type), str(sys.exc_value)))
        return None

def _call(label, obj, name, args):
    """Resolve obj.<name> and call with args.  Use this for object methods --
    SWIG attribute lookup itself can raise when the wrapper exposes only a
    base class.  _try(label, obj.method, args) evaluates obj.method BEFORE
    _try is called, so the lookup error escapes the safety net."""
    try:
        return apply(getattr(obj, name), args)
    except:
        _record(label + " FAILED",
                "exc_type=%s exc_value=%s" % (str(sys.exc_type), str(sys.exc_value)))
        return None

# === PROBE BODY ================================================================

try:
    _section("environment")
    _record("frame", App.g_kSystemWrapper.GetUpdateNumber())
    _record("game_time", App.g_kUtopiaModule.GetGameTime())

    _player = _try("Game_GetCurrentPlayer", App.Game_GetCurrentPlayer, ())
    if _player is None:
        _record("ABORT", "no player -- start Quick Battle")
    else:
        _record("player", _call("player.GetName", _player, "GetName", ()))

        _raw = _call("player.GetTarget", _player, "GetTarget", ())
        if _raw is None:
            _record("ABORT", "no target -- press Tab to lock a hostile ship")
            _target = None
        else:
            _section("target identity")
            _record("raw target.repr", repr(_raw))
            _record("raw target.GetName", _call("GetName", _raw, "GetName", ()))

            # GetTarget() returns ObjectClass* -- downcast to expose the ship
            # subclass methods (GetShields, GetHull, AddDamage).
            _target = _try("ShipClass_Cast", App.ShipClass_Cast, (_raw,))
            if _target is None:
                _target = _try("DamageableObject_Cast",
                               App.DamageableObject_Cast, (_raw,))
                _record("cast", "DamageableObject")
            else:
                _record("cast", "ShipClass")
            if _target is None:
                _target = _raw
                _record("cast", "FAILED -- using raw ObjectClass")
            else:
                _record("downcast target.repr", repr(_target))

        if _target is None:
            _sh = None
        else:
            _sh = _call("target.GetShields", _target, "GetShields", ())
            if _sh is None:
                _record("ABORT",
                        "target has no working GetShields -- "
                        "Tab to a different (hostile) ship and rerun")
            else:
                _section("setup")
                _n_faces = _call("sh.GetNumShields", _sh, "GetNumShields", ())
                _max_face = _call("sh.GetMaxShields(0)", _sh, "GetMaxShields", (0,))
                _record("num_shield_faces", _n_faces)
                _record("max_shield_face0", _max_face)

                # Phaser bank 0 metadata -- needs EnergyWeapon downcast because
                # GetWeapon(i) returns a base wrapper; GetMaxDamageDistance is
                # only on EnergyWeapon (App.py:6435).
                _ws = _call("player.GetPhaserSystem", _player, "GetPhaserSystem", ())
                _R = 60.0  # Galaxy-style default if we can't read it
                if _ws is not None:
                    _w_raw = _call("ws.GetWeapon(0)", _ws, "GetWeapon", (0,))
                    if _w_raw is not None:
                        _w0 = _try("EnergyWeapon_Cast",
                                   App.EnergyWeapon_Cast, (_w_raw,))
                        if _w0 is None:
                            _w0 = _w_raw
                            _record("weapon cast", "FAILED -- using raw")
                        else:
                            _record("weapon cast", "EnergyWeapon")
                        _mdd = _call("w0.GetMaxDamageDistance", _w0,
                                     "GetMaxDamageDistance", ())
                        if _mdd is not None and _mdd > 0:
                            _R = _mdd
                        _record("phaser0.MaxDamage",
                                _call("GetMaxDamage", _w0, "GetMaxDamage", ()))
                        _record("phaser0.MaxDamageDistance (R)", _R)
                else:
                    _record("phaser0", "no GetPhaserSystem -- using R=%.1f" % _R)

                # --- helpers (capture closures over the in-scope live objects) ---
                def _shield_total():
                    s = 0.0
                    i = 0
                    while i < _n_faces:
                        try:
                            s = s + _sh.GetCurShields(i)
                        except:
                            pass
                        i = i + 1
                    return s

                def _hull():
                    try:
                        return _target.GetHull().GetCondition()
                    except:
                        return -1.0

                def _reset_shields():
                    i = 0
                    while i < _n_faces:
                        try:
                            _sh.SetCurShields(i, _max_face)
                        except:
                            pass
                        i = i + 1

                # AddDamage takes a _p_NiAVObject. GetNode() returns NiNode
                # which SWIG's strict type check rejects.  GetNiObject()
                # (App.py:3806) returns an NiAVObjectPtr directly -- this is
                # the call site that satisfies the type check.
                _node = _call("target.GetNiObject", _target, "GetNiObject", ())
                _record("target.GetNiObject", _node)
                if _node is None:
                    _record("ABORT", "no NiAVObject -- can't call AddDamage")
                else:
                    def _hit(radius, damage):
                        _target.AddDamage(_node, radius, damage)

                    _section("baseline")
                    _reset_shields()
                    _record("shield_total_after_reset", _shield_total())
                    _record("hull", _hull())

                    # Sweep radius at the target's centre node.
                    _DAMAGE = 1000.0
                    _RADII = [0.1, 1.0, 5.0, _R * 0.5, _R, _R * 2.0]

                    _section("radius sweep (DAMAGE=%.1f, node=centre)" % _DAMAGE)
                    _record("columns",
                            "radius shield_pre shield_post shield_d  "
                            "hull_pre hull_post hull_d")

                    _hits = []
                    i = 0
                    while i < len(_RADII):
                        rad = _RADII[i]
                        _reset_shields()
                        sp = _shield_total()
                        hp = _hull()
                        try:
                            _hit(rad, _DAMAGE)
                            sa = _shield_total()
                            ha = _hull()
                            row = (rad, sp, sa, sp - sa, hp, ha, hp - ha)
                            _hits.append(row)
                            _record("hit r=%.2f" % rad,
                                    "%8.3f -> %8.3f  d=%8.3f   %7.3f -> %7.3f  d=%7.3f"
                                    % (sp, sa, sp - sa, hp, ha, hp - ha))
                        except:
                            _record("hit r=%.2f FAILED" % rad,
                                    "exc_type=%s exc_value=%s"
                                    % (str(sys.exc_type), str(sys.exc_value)))
                        i = i + 1

                    _section("analysis")
                    if _hits:
                        # Q1: pick the radius=1.0 row as the "centre anchor"
                        if len(_hits) > 1:
                            anchor = _hits[1]
                        else:
                            anchor = _hits[0]
                        delivered_anchor = anchor[3] + anchor[6]
                        _record("Q1 delivered_at_r=%.2f" % anchor[0],
                                delivered_anchor)
                        _record("Q1 requested_damage", _DAMAGE)
                        if delivered_anchor > 0:
                            _record("Q1 anchor_ratio",
                                    delivered_anchor / _DAMAGE)

                        # Q3: at anchor radius, where did the damage land?
                        csd = anchor[3]
                        chd = anchor[6]
                        if csd > 0 and chd <= 0:
                            q3 = "shields-only (csd=%.3f, chd=%.3f)" % (csd, chd)
                        elif csd <= 0 and chd > 0:
                            q3 = "BYPASSES shields (csd=%.3f, chd=%.3f)" % (csd, chd)
                        elif csd > 0 and chd > 0:
                            q3 = "splits to both (csd=%.3f, chd=%.3f)" % (csd, chd)
                        else:
                            q3 = "no delivery (csd=%.3f, chd=%.3f)" % (csd, chd)
                        _record("Q3 routing", q3)

                        _record("Q2 status",
                                "DEFERRED -- AddDamage takes a node not a "
                                "position; q03 needed for distance sweep")

except:
    _record("FATAL outer",
            "exc_type=%s exc_value=%s" % (str(sys.exc_type), str(sys.exc_value)))

# === END PROBE BODY ============================================================

_flush()
print "done"
