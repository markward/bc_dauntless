###############################################################################
# q06_lock_shielded.py
#
# Question: Q6 from 2026-06-29-weapon-exchange-console-probe.md.
#   With shields at FULL and a deliberate subsystem lock set, does any
#   damage bleed through the shield to the locked subsystem?
#
#   q03/q04 proved STRICT CASCADE without a lock -- shields absorb everything
#   until a face hits zero.  Q6 asks: does a subsystem lock CHANGE that?
#
# Companion probes: q07a (face@0 + lock, FULL) and q07b (face@0 + lock, LIGHT)
# answer the second half of the lock question -- does the lock change
# WHICH subsystem takes damage vs the default sensors routing seen in q05.
#
# Lock strategy: try power, repair, impulse, warp.  Skip sensors (the
# observed default-routing target in q05) so we can distinguish lock
# behaviour from default behaviour.
#
# ==== OPERATOR PROCEDURE -- 5 STEPS ==========================================
#
#   1.  Quick Battle.  TAB to lock a hostile.  Fly to ~5 km.  Face it.
#       (You DO need a Tab-lock on the ship; the probe sets the *subsystem*
#       lock for you.)
#
#   2.  PAUSE  (press P)
#
#   3.  execfile('q06_lock_shielded.py')             <-- PRE pass.
#       Disables target engines/weapons, resets shields to max, sets
#       phaser intensity to FULL, locks a subsystem on the target.
#
#   4.  UNPAUSE (P).  HOLD FIRE for about 3 seconds.  PAUSE (P).
#
#   5.  execfile('q06_lock_shielded.py')             <-- POST pass.
#       Reports whether the locked subsystem took damage through the shield.
#
# Output: game/BCProbe_q06.cfg
###############################################################################

import App
import sys

_cfg = App.g_kConfigMapping
_SECTION = "BCProbe_q06"
_CFG_FILE = "BCProbe_q06.cfg"
_INTENSITY_LABEL = "FULL (PP_HIGH)"
_log = []

def _exc_name(e):
    try: return e.__class__.__name__
    except AttributeError: return str(type(e))

def _record(label, value):
    line = "%s = %s" % (str(label), str(value))
    _log.append(line)
    print line

def _section(title):
    bar = "-- " + str(title) + " " + ("-" * max(1, 60 - len(str(title))))
    _log.append(bar)
    print bar

def _try(label, fn, args):
    try: return apply(fn, args)
    except:
        _record(label + " FAILED",
                "exc_type=%s exc_value=%s" % (str(sys.exc_type), str(sys.exc_value)))
        return None

def _call(label, obj, name, args):
    try: return apply(getattr(obj, name), args)
    except:
        _record(label + " FAILED",
                "exc_type=%s exc_value=%s" % (str(sys.exc_type), str(sys.exc_value)))
        return None

def _quiet_call(obj, name, args):
    try: return apply(getattr(obj, name), args)
    except: return None

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

def _delta(pre, post):
    if pre is None or post is None: return None
    try: return pre - post
    except: return None

# --- subsystem walker (same as q05) ----------------------------------------

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

def _snapshot_one_sub(sub, label):
    return {
        'label':         label,
        'condition':     _quiet_call(sub, "GetCondition", ()),
        'cond_pct':      _quiet_call(sub, "GetConditionPercentage", ()),
        'combined_pct':  _quiet_call(sub, "GetCombinedConditionPercentage", ()),
        'damage':        _quiet_call(sub, "GetDamage", ()),
    }

def _walk_subsystem(sub, label, out):
    out.append(_snapshot_one_sub(sub, label))
    n = _quiet_call(sub, "GetNumChildSubsystems", ())
    if n is None or n <= 0: return
    i = 0
    while i < n:
        child = _quiet_call(sub, "GetChildSubsystemIndex", (i,))
        if child is not None:
            child_name = _quiet_call(child, "GetName", ())
            if child_name is None: child_name = "child_%d" % i
            _walk_subsystem(child, label + "/" + str(child_name), out)
        i = i + 1

def _enumerate_subs(target):
    out = []
    for getter_name, label in _SUB_GETTERS:
        sub = _quiet_call(target, getter_name, ())
        if sub is None: continue
        _walk_subsystem(sub, label, out)
    return out

# --- lock pickers -----------------------------------------------------------

# Try these in order; sensors LAST because it's the no-lock default routing.
_LOCK_CANDIDATES = (
    ("GetPowerSubsystem",          "power"),
    ("GetRepairSubsystem",         "repair"),
    ("GetImpulseEngineSubsystem",  "impulse"),
    ("GetWarpEngineSubsystem",     "warp"),
    ("GetSensorSubsystem",         "sensors"),
)

def _pick_lock_subsystem(target):
    """Returns (subsystem_instance, label) of the first targetable, present
    subsystem on the target from _LOCK_CANDIDATES; or (None, None)."""
    for getter, label in _LOCK_CANDIDATES:
        sub = _quiet_call(target, getter, ())
        if sub is None: continue
        ok = _quiet_call(sub, "IsTargetable", ())
        if ok is None or ok == 0: continue
        return (sub, label)
    return (None, None)

# --- target-disable (mirrors setup_disable_target) -------------------------

_DISABLE_LIST = (
    ("GetImpulseEngineSubsystem", "impulse"),
    ("GetWarpEngineSubsystem",    "warp"),
    ("GetPhaserSystem",           "phasers"),
    ("GetTorpedoSystem",          "torpedoes"),
    ("GetPulseWeaponSystem",      "pulse"),
)

def _disable_target_combat(target):
    n_disabled = 0
    for getter, label in _DISABLE_LIST:
        sub = _quiet_call(target, getter, ())
        if sub is None: continue
        _quiet_call(sub, "SetCondition", (0.0,))
        n_disabled = n_disabled + 1
    return n_disabled

# --- shields ---------------------------------------------------------------

def _reset_shields(sh, n_faces):
    i = 0
    while i < n_faces:
        m = _quiet_call(sh, "GetMaxShields", (i,))
        if m is None: m = 0.0
        _quiet_call(sh, "SetCurShields", (i, m))
        i = i + 1

def _face_list(sh, n_faces):
    out = []
    i = 0
    while i < n_faces:
        v = _quiet_call(sh, "GetCurShields", (i,))
        if v is None: v = -1.0
        out.append(v)
        i = i + 1
    return out

def _shield_total(sh, n_faces):
    s = 0.0
    for v in _face_list(sh, n_faces):
        if v > 0: s = s + v
    return s

def _hull_condition(target):
    try: return target.GetHull().GetCondition()
    except: return -1.0

# === MAIN ===================================================================

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

    if _missing is not None:
        _record("ABORT", "missing %s" % _missing)
        _flush()
        _banner("ABORTED -- " + _missing)
    else:
        _n_faces = _sh.GetNumShields()
        _has_pre = globals().has_key('_q06_pre')

        if not _has_pre:
            # =============================================================
            # PRE pass
            # =============================================================
            _section("PRE pass -- intensity " + _INTENSITY_LABEL)
            _record("player", _player.GetName())
            _record("target", _target.GetName())

            # Disable target combat capability (engines + weapons)
            n = _disable_target_combat(_target)
            _record("target subsystems disabled", n)

            # Set phaser intensity to FULL
            _call("ws.SetPowerLevel(PP_HIGH)", _ws,
                  "SetPowerLevel", (App.PhaserSystem.PP_HIGH,))
            _record("intensity_after_set",
                    _call("ws.GetPowerLevel", _ws, "GetPowerLevel", ()))

            # Reset all shield faces to max
            _reset_shields(_sh, _n_faces)
            _faces_pre = _face_list(_sh, _n_faces)
            _record("pre.faces (should be at max)", _faces_pre)
            _record("pre.shield_total", _shield_total(_sh, _n_faces))

            # Pick and set the lock target
            _lock_sub, _lock_label = _pick_lock_subsystem(_target)
            if _lock_sub is None:
                _record("ABORT", "no targetable subsystem found on target")
                _flush()
                _banner("ABORTED -- no lockable subsystem")
            else:
                _record("lock_choice", _lock_label)
                _call("player.SetTargetSubsystem", _player,
                      "SetTargetSubsystem", (_lock_sub,))
                _readback = _call("player.GetTargetSubsystem",
                                   _player, "GetTargetSubsystem", ())
                _record("lock readback",
                        _quiet_call(_readback, "GetName", ()))

                # Snapshot subsystems
                _subs_pre = _enumerate_subs(_target)
                _section("subsystems snapshot (PRE)")
                for snap in _subs_pre:
                    _record("pre %s" % snap['label'],
                            "cond=%s combined%%=%s damage=%s"
                            % (snap['condition'], snap['combined_pct'],
                               snap['damage']))

                _hull_pre = _hull_condition(_target)
                _record("pre.hull", _hull_pre)

                _pre = {
                    'frame':     App.g_kSystemWrapper.GetUpdateNumber(),
                    'game_time': App.g_kUtopiaModule.GetGameTime(),
                    'subs':      _subs_pre,
                    'hull':      _hull_pre,
                    'faces':     _faces_pre,
                    'lock_label': _lock_label,
                }
                globals()['_q06_pre'] = _pre
                _flush()

                _banner("PRE COMPLETE -- shields at max, lock = " + _lock_label)
                print ""
                print "NEXT STEPS:"
                print "  4a. Press P to UNPAUSE."
                print "  4b. HOLD FIRE for about 3 seconds."
                print "  4c. Press P to PAUSE."
                print "  5.  execfile('q06_lock_shielded.py')"
                print ""

        else:
            # =============================================================
            # POST pass
            # =============================================================
            _section("POST pass")
            _pre = globals()['_q06_pre']
            _record("lock_was", _pre['lock_label'])

            d_gt = App.g_kUtopiaModule.GetGameTime() - _pre['game_time']
            _record("d_game_time", d_gt)

            _subs_post = _enumerate_subs(_target)
            _post_by_label = {}
            for snap in _subs_post:
                _post_by_label[snap['label']] = snap

            _section("subsystem deltas (any non-zero = damage detected)")
            locked_d_damage = None
            locked_d_combined = None
            for pre_snap in _pre['subs']:
                label = pre_snap['label']
                post_snap = _post_by_label.get(label)
                if post_snap is None: continue
                d_cond = _delta(pre_snap['condition'], post_snap['condition'])
                d_combined = _delta(pre_snap['combined_pct'],
                                    post_snap['combined_pct'])
                d_damage = _delta(post_snap['damage'], pre_snap['damage'])
                if (d_cond and d_cond > 0.001) or \
                   (d_combined and d_combined > 0.001) or \
                   (d_damage and d_damage > 0.001):
                    _record("CHANGED %s" % label,
                            "d_cond=%s d_combined%%=%s d_damage=%s"
                            % (d_cond, d_combined, d_damage))
                if label == _pre['lock_label']:
                    locked_d_damage = d_damage
                    locked_d_combined = d_combined

            d_hull = _pre['hull'] - _hull_condition(_target)
            _record("d_hull", d_hull)

            _section("face deltas (started at max)")
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
            _record("face_delta_sum", d_face_sum)

            _section("Q6 finding")
            # Check whether any face went to 0
            any_face_zero = 0
            i = 0
            while i < _n_faces:
                if faces_post[i] <= 0.01:
                    any_face_zero = 1
                i = i + 1

            locked_took_damage = 0
            if locked_d_damage is not None and locked_d_damage > 0.001:
                locked_took_damage = 1
            if locked_d_combined is not None and locked_d_combined > 0.001:
                locked_took_damage = 1

            if d_gt <= 0:
                conclusion = "INCONCLUSIVE -- no game-time elapsed"
            elif d_face_sum <= 0.5:
                conclusion = ("INCONCLUSIVE -- no shield damage delivered. "
                              "Out of arc, target dead, or fire didn't happen.")
            elif any_face_zero:
                conclusion = ("AMBIGUOUS -- a face went to 0 mid-window so "
                              "ANY subsequent hull/subsystem damage could be "
                              "from cascade, not lock-bleed-through.  Rerun "
                              "with shorter fire burst.")
            elif d_hull <= 0.5 and not locked_took_damage:
                conclusion = ("NO LOCK BLEED-THROUGH.  Shields absorbed "
                              "everything (face_sum=%.3f); hull=%.3f; "
                              "locked sub '%s' was untouched.  The lock "
                              "does NOT bypass shields."
                              % (d_face_sum, d_hull, _pre['lock_label']))
            elif locked_took_damage:
                conclusion = ("LOCK BLEED-THROUGH DETECTED.  Locked sub "
                              "'%s' took damage (d_damage=%s, "
                              "d_combined%%=%s) DESPITE shields holding "
                              "(face_sum=%.3f, no face depleted).  The "
                              "lock DOES bleed damage through shields."
                              % (_pre['lock_label'], locked_d_damage,
                                 locked_d_combined, d_face_sum))
            else:
                conclusion = ("AMBIGUOUS -- hull moved (%.3f) but locked "
                              "sub untouched, no face depleted.  Inspect data."
                              % d_hull)
            _record("Q6 CONCLUSION", conclusion)

            del globals()['_q06_pre']
            _flush()

            _banner("Q6 RESULT")
            print ""
            print "  " + conclusion
            print ""
            print "Run:  uv run python tools/probes/collect.py q06"
            print ""

except:
    _record("FATAL",
            "exc_type=%s exc_value=%s"
            % (str(sys.exc_type), str(sys.exc_value)))
    _flush()
    _banner("PROBE CRASHED -- see FATAL line above")

print "done"
