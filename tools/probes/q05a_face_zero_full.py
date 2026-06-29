###############################################################################
# q05a_face_zero_full.py
#
# Question: Q5 from 2026-06-29-weapon-exchange-console-probe.md, FULL
#   intensity variant.  With the facing shield pre-set to 0 AND phasers at
#   FULL power (PP_HIGH, "max hull damage"), where does a weapon hit go --
#   100% hull, proportional hull/subsystem, or some other split?
#
#   Companion probe: q05b_face_zero_light.py runs the same experiment at
#   LIGHT intensity (PP_LOW, "max subsystem damage").  Run BOTH and compare.
#
# Design choices:
#   - Set ALL faces to 0 (not just face_0).  Face indices vary by ship
#     class/orientation; this guarantees the facing shield is depleted
#     regardless of which way the target points.
#   - Set PhaserSystem.SetPowerLevel(PP_HIGH) explicitly so we KNOW the
#     intensity mode; don't rely on whatever the operator last set.
#
# ==== OPERATOR PROCEDURE -- 5 STEPS ==========================================
#
#   1.  Quick Battle.  Pick any hostile ship.  TAB to lock target.
#       Fly to about 5 km from target (HUD range readout).  Face it.
#
#   2.  PAUSE  (press P)
#
#   3.  execfile('q05a_face_zero_full.py')          <-- PRE pass.
#       Sets your phasers to FULL intensity, snapshots subsystem
#       conditions, drops all target shields to 0.
#
#   4.  UNPAUSE (P).  HOLD FIRE for about 3 seconds.  PAUSE (P).
#       IMPORTANT: do this PROMPTLY -- shields regenerate on unpause.
#
#   5.  execfile('q05a_face_zero_full.py')          <-- POST pass.
#       Probe diffs and reports where damage went (hull, which subsystems).
#
# Output: game/BCProbe_q05a.cfg
###############################################################################

import App
import sys

_cfg = App.g_kConfigMapping
_SECTION = "BCProbe_q05a"
_CFG_FILE = "BCProbe_q05a.cfg"
_INTENSITY_LABEL = "FULL (PP_HIGH)"
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
    """Like _call but silent on failure -- for subsystem getters that may not
    exist on every ship class (e.g. a Galaxy has no cloak)."""
    try:
        return apply(getattr(obj, name), args)
    except:
        return None

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

def _banner(text):
    print ""
    print "=========================================================="
    print text
    print "=========================================================="

# --- subsystem enumeration -------------------------------------------------

_SUB_GETTERS = (
    ("GetPowerSubsystem",          "power"),
    ("GetSensorSubsystem",         "sensors"),
    ("GetImpulseEngineSubsystem",  "impulse"),
    ("GetWarpEngineSubsystem",     "warp"),
    ("GetTorpedoSystem",           "torpedoes"),
    ("GetPhaserSystem",            "phasers"),
    ("GetPulseWeaponSystem",       "pulse"),
    ("GetTractorBeamSystem",       "tractor"),
    ("GetRepairSubsystem",         "repair"),
    ("GetCloakingSubsystem",       "cloak"),
)

def _delta(pre, post):
    """Return pre - post for two values that might be None."""
    if pre is None or post is None:
        return None
    try:
        return pre - post
    except:
        return None

def _snapshot_one_sub(sub, label):
    """Return a dict of every condition/damage signal we can read off a
    ShipSubsystem.  None values are kept so deltas show NULL clearly."""
    return {
        'label':         label,
        'condition':     _quiet_call(sub, "GetCondition", ()),
        'max_condition': _quiet_call(sub, "GetMaxCondition", ()),
        'cond_pct':      _quiet_call(sub, "GetConditionPercentage", ()),
        'combined_pct':  _quiet_call(sub, "GetCombinedConditionPercentage", ()),
        'damage':        _quiet_call(sub, "GetDamage", ()),
        'num_children':  _quiet_call(sub, "GetNumChildSubsystems", ()),
    }

def _walk_subsystem(sub, label, out, depth):
    """Append (depth, snapshot) for sub and its children recursively."""
    out.append((depth, _snapshot_one_sub(sub, label)))
    n = _quiet_call(sub, "GetNumChildSubsystems", ())
    if n is None or n <= 0:
        return
    i = 0
    while i < n:
        child = _quiet_call(sub, "GetChildSubsystemIndex", (i,))
        if child is None:
            i = i + 1
            continue
        child_name = _quiet_call(child, "GetName", ())
        if child_name is None:
            child_name = "child_%d" % i
        _walk_subsystem(child, label + "/" + str(child_name), out, depth + 1)
        i = i + 1

def _enumerate_subsystem_conditions(target):
    """Return a list of (depth, snap_dict) covering EVERY subsystem on the
    target -- top-level parents AND their children.  q05v1 only walked the
    parents; the user observed damage spreading to subsystems in gameplay
    that the parent-only walk missed, so the live damage signal is almost
    certainly on the leaves."""
    out = []
    for getter_name, label in _SUB_GETTERS:
        sub = _quiet_call(target, getter_name, ())
        if sub is None:
            continue
        _walk_subsystem(sub, label, out, 0)
    return out

def _shield_total(sh, n_faces):
    s = 0.0
    i = 0
    while i < n_faces:
        v = _quiet_call(sh, "GetCurShields", (i,))
        if v is not None and v > 0:
            s = s + v
        i = i + 1
    return s

def _face_list(sh, n_faces):
    out = []
    i = 0
    while i < n_faces:
        v = _quiet_call(sh, "GetCurShields", (i,))
        if v is None:
            v = -1.0
        out.append(v)
        i = i + 1
    return out

def _hull_condition(target):
    try:
        return target.GetHull().GetCondition()
    except:
        return -1.0

def _range_player_target(player, target):
    try:
        pp = player.GetWorldLocation()
        tp = target.GetWorldLocation()
        dx = tp.x - pp.x; dy = tp.y - pp.y; dz = tp.z - pp.z
        return (dx*dx + dy*dy + dz*dz) ** 0.5
    except:
        return -1.0

# === MAIN ====================================================================

try:
    _player = _try("Game_GetCurrentPlayer", App.Game_GetCurrentPlayer, ())
    _raw = None
    if _player is not None:
        _raw = _call("player.GetTarget", _player, "GetTarget", ())
    _target = None
    if _raw is not None:
        _target = _try("ShipClass_Cast", App.ShipClass_Cast, (_raw,))
    _sh = None
    if _target is not None:
        _sh = _call("target.GetShields", _target, "GetShields", ())
    _ws = None
    if _player is not None:
        _ws = _call("player.GetPhaserSystem", _player, "GetPhaserSystem", ())

    _missing = None
    if _player is None: _missing = "player"
    elif _target is None: _missing = "target (TAB to lock a hostile ship)"
    elif _sh is None: _missing = "shields"
    elif _ws is None: _missing = "player phaser system"

    # Note: GetTargetSubsystem() returns non-None even with no in-game lock --
    # appears to be the default body/hull target.  We log it but don't abort.
    # Watch for a subsystem name change in q06/q07 if a deliberate lock matters.
    _locked_sub = None
    if _missing is None:
        _locked_sub = _quiet_call(_player, "GetTargetSubsystem", ())

    if _missing is not None:
        _record("ABORT", _missing)
        _flush()
        _banner("ABORTED -- " + _missing)
    else:
        _n_faces = _sh.GetNumShields()
        _has_pre = globals().has_key('_q05a_pre')

        if not _has_pre:
            # =============================================================
            # PRE pass
            # =============================================================
            _section("PRE pass -- intensity " + _INTENSITY_LABEL)
            _record("player", _player.GetName())
            _record("target", _target.GetName())
            _record("intensity_target", _INTENSITY_LABEL)
            _record("num_shield_faces", _n_faces)
            _record("range", _range_player_target(_player, _target))
            _record("targetSubsystem (any default value)", _locked_sub)
            if _locked_sub is not None:
                _record("targetSubsystem.GetName",
                        _quiet_call(_locked_sub, "GetName", ()))

            # Set phaser intensity to FULL (max hull damage).
            _call("ws.SetPowerLevel(PP_HIGH)", _ws,
                  "SetPowerLevel", (App.PhaserSystem.PP_HIGH,))
            _record("intensity_after_set",
                    _call("ws.GetPowerLevel", _ws, "GetPowerLevel", ()))

            _subs_pre = _enumerate_subsystem_conditions(_target)
            _section("subsystems present on target (depth/name : cond / combined% / damage)")
            for depth, snap in _subs_pre:
                _record("pre[%d] %s" % (depth, snap['label']),
                        "cond=%s combined%%=%s damage=%s n_child=%s"
                        % (snap['condition'], snap['combined_pct'],
                           snap['damage'], snap['num_children']))
            _record("subsystem_count (incl. children)", len(_subs_pre))

            _hull_pre = _hull_condition(_target)
            _record("pre.hull", _hull_pre)

            _section("dropping ALL shield faces to 0")
            i = 0
            while i < _n_faces:
                _call("sh.SetCurShields(%d, 0)" % i, _sh, "SetCurShields", (i, 0.0))
                i = i + 1
            _faces_pre = _face_list(_sh, _n_faces)
            _record("pre.faces (should be all 0)", _faces_pre)
            _record("pre.shield_total", _shield_total(_sh, _n_faces))

            _pre = {
                'frame':      App.g_kSystemWrapper.GetUpdateNumber(),
                'game_time':  App.g_kUtopiaModule.GetGameTime(),
                'subs':       _subs_pre,
                'hull':       _hull_pre,
                'faces':      _faces_pre,
            }
            globals()['_q05a_pre'] = _pre
            _flush()

            _banner("PRE COMPLETE -- intensity " + _INTENSITY_LABEL +
                    ", shields at 0")
            print ""
            print "NEXT STEPS (do these PROMPTLY -- shields regen on unpause):"
            print "  4a. Press P to UNPAUSE."
            print "  4b. HOLD FIRE for about 3 seconds."
            print "  4c. Press P to PAUSE."
            print "  5.  execfile('q05a_face_zero_full.py')"
            print ""

        else:
            # =============================================================
            # POST pass
            # =============================================================
            _section("POST pass -- intensity " + _INTENSITY_LABEL)
            _pre = globals()['_q05a_pre']

            d_gt = App.g_kUtopiaModule.GetGameTime() - _pre['game_time']
            _record("d_game_time", d_gt)
            _record("intensity_during_run",
                    _call("ws.GetPowerLevel", _ws, "GetPowerLevel", ()))

            _subs_post = _enumerate_subsystem_conditions(_target)
            _post_by_label = {}
            for depth, snap in _subs_post:
                _post_by_label[snap['label']] = snap

            _section("subsystem deltas (any signal change = damage detected)")
            sub_deltas = []  # list of (label, condition_delta) for compatibility
            for depth, pre_snap in _pre['subs']:
                label = pre_snap['label']
                post_snap = _post_by_label.get(label)
                if post_snap is None:
                    continue
                # Try every condition signal we have
                d_cond = _delta(pre_snap['condition'], post_snap['condition'])
                d_combined = _delta(pre_snap['combined_pct'],
                                    post_snap['combined_pct'])
                d_damage = _delta(post_snap['damage'], pre_snap['damage'])  # damage GROWS
                _safe_d = 0.0
                if d_cond is not None:
                    _safe_d = d_cond
                sub_deltas.append((label, _safe_d))
                if (d_cond and d_cond > 0.001) or \
                   (d_combined and d_combined > 0.001) or \
                   (d_damage and d_damage > 0.001):
                    _record("CHANGED %s" % label,
                            "d_cond=%s d_combined%%=%s d_damage=%s"
                            % (d_cond, d_combined, d_damage))

            d_hull = _pre['hull'] - _hull_condition(_target)
            _record("d_hull", d_hull)

            _section("face deltas (started at 0)")
            faces_post = _face_list(_sh, _n_faces)
            d_face_sum = 0.0
            i = 0
            while i < _n_faces:
                d = _pre['faces'][i] - faces_post[i]
                d_face_sum = d_face_sum + d
                _record("face_%d  pre=%.2f  post=%.2f  delta" % (
                            i, _pre['faces'][i], faces_post[i]),
                        "%.3f" % d)
                i = i + 1
            _record("face_delta_sum (negative = regen)", d_face_sum)

            _section("Q5 finding (FULL intensity)")
            # Sum damage growth across all subsystems (parents + children).
            # GetDamage() is the canonical "damage taken" counter -- it
            # accumulates regardless of condition rollup quirks.
            total_sub_damage = 0.0
            top_sub = None
            top_sub_d = 0.0
            for depth, pre_snap in _pre['subs']:
                label = pre_snap['label']
                post_snap = _post_by_label.get(label)
                if post_snap is None:
                    continue
                d = _delta(post_snap['damage'], pre_snap['damage'])  # damage grows
                if d is None or d <= 0:
                    continue
                total_sub_damage = total_sub_damage + d
                if d > top_sub_d:
                    top_sub_d = d
                    top_sub = label

            if d_gt <= 0:
                conclusion = "INCONCLUSIVE -- no game-time elapsed (did you unpause?)"
            elif d_hull <= 0.5 and total_sub_damage <= 0.5:
                conclusion = ("INCONCLUSIVE -- no damage delivered. "
                              "Shields regen'd before fire? face_delta_sum=%.3f."
                              % d_face_sum)
            elif total_sub_damage <= 0.5 and d_hull > 0.5:
                conclusion = ("FULL INTENSITY -> HULL-ONLY.  "
                              "d_hull=%.3f, total sub damage=%.3f. "
                              "Damage routes purely to hull, no spread "
                              "to subsystems."
                              % (d_hull, total_sub_damage))
            elif total_sub_damage > 0.5 and d_hull > 0.5:
                sub_pct = 100.0 * total_sub_damage / (total_sub_damage + d_hull)
                conclusion = ("FULL INTENSITY -> HULL+SUBSYSTEMS SPLIT.  "
                              "hull=%.3f (%.0f%%), sub total=%.3f (%.0f%%).  "
                              "Top subsystem: %s (-%.3f)."
                              % (d_hull, 100.0 - sub_pct,
                                 total_sub_damage, sub_pct,
                                 top_sub, top_sub_d))
            else:
                conclusion = ("FULL INTENSITY -> SUBSYSTEM-ONLY?  "
                              "d_hull=%.3f, total sub=%.3f. Inspect data."
                              % (d_hull, total_sub_damage))
            _record("Q5 FULL CONCLUSION", conclusion)

            del globals()['_q05a_pre']
            _flush()

            _banner("Q5a RESULT (FULL intensity)")
            print ""
            print "  " + conclusion
            print ""
            print "Next: run q05b for LIGHT intensity:"
            print "    execfile('q05b_face_zero_light.py')"
            print "Then: uv run python tools/probes/collect.py q05"
            print ""

except:
    _record("FATAL",
            "exc_type=%s exc_value=%s"
            % (str(sys.exc_type), str(sys.exc_value)))
    _flush()
    _banner("PROBE CRASHED -- see FATAL line above")

print "done"
