###############################################################################
# q08_lock_rear_subsystem.py
#
# Question: Q7 disambiguation -- does player.SetTargetSubsystem() actually
#   redirect weapon fire?
#
#   q07a (lock=power, fire from front, FULL) saw damage go to sensors anyway
#   -- but the operator noted that sensors is forward-mounted on Galaxy and
#   the impact is geometric.  Locking a non-impact-area subsystem (power)
#   while firing forward isn't a clean test.
#
#   q08 locks IMPULSE ENGINES (rear-mounted on Galaxy and most ships) while
#   firing from in front.  If damage redirects to impulse, the lock works.
#   If damage still goes to forward subsystems (sensors), the lock is inert.
#
# Important setup difference from q07a:
#   - q07a used setup_disable_target.py-style disabling, which zeros impulse
#     so it can't show damage.
#   - q08 disables ONLY weapons (phasers, torpedoes, pulse) so impulse stays
#     intact at non-zero condition and CAN register damage if hit.
#   - Target may drift slowly on impulse, but the 3-sec fire window limits it.
#
# ==== OPERATOR PROCEDURE -- 5 STEPS ==========================================
#
#   1.  Quick Battle.  TAB to lock a hostile (Galaxy or similar -- impulse
#       engines rear-mounted).  Fly to ~5 km.  Face it directly.
#
#   2.  PAUSE  (P)
#
#   3.  execfile('q08_lock_rear_subsystem.py')      <-- PRE pass.
#       Disables target weapons (NOT engines), drops shields to 0, sets
#       FULL intensity, locks the rear-mounted impulse engines.
#
#   4.  UNPAUSE (P).  HOLD FIRE for about 3 seconds.  PAUSE (P).
#       (Target may drift slightly on impulse -- that's fine, just keep
#       firing.)
#
#   5.  execfile('q08_lock_rear_subsystem.py')      <-- POST pass.
#       Reports whether damage redirected to the locked impulse engines.
#
# Output: game/BCProbe_q08.cfg
###############################################################################

import App
import sys

_cfg = App.g_kConfigMapping
_SECTION = "BCProbe_q08"
_CFG_FILE = "BCProbe_q08.cfg"
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

# --- subsystem walker ------------------------------------------------------

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

# --- target-disable (WEAPONS ONLY -- engines stay intact) ------------------

_DISABLE_LIST = (
    ("GetPhaserSystem",     "phasers"),
    ("GetTorpedoSystem",    "torpedoes"),
    ("GetPulseWeaponSystem", "pulse"),
)

def _disable_target_weapons(target):
    n = 0
    for getter, label in _DISABLE_LIST:
        sub = _quiet_call(target, getter, ())
        if sub is None: continue
        _quiet_call(sub, "SetCondition", (0.0,))
        n = n + 1
    return n

# --- pick a rear-mounted lockable subsystem --------------------------------

# Impulse first (rear on Galaxy/most Federation ships); warp next (also rear).
# Both must be non-disabled (condition > 0) to be a meaningful lock target.
_REAR_CANDIDATES = (
    ("GetImpulseEngineSubsystem",  "impulse"),
    ("GetWarpEngineSubsystem",     "warp"),
)

def _pick_rear_lock(target):
    """Returns (sub, label) of the first present + non-disabled rear-mounted
    subsystem; or (None, None).

    Note: we deliberately do NOT check IsTargetable() -- on the Galaxy-1
    that flag returns 0 for impulse AND warp even when both are intact
    (probably means 'offered in the in-game subsystem-target dialog'
    rather than 'can be set via SetTargetSubsystem').  q07 proved
    SetTargetSubsystem accepts whatever we give it; the readback after
    SetTargetSubsystem is the real test of whether the lock stuck."""
    for getter, label in _REAR_CANDIDATES:
        sub = _quiet_call(target, getter, ())
        if sub is None: continue
        cond = _quiet_call(sub, "GetCondition", ())
        if cond is None or cond <= 0.0: continue  # already destroyed
        return (sub, label)
    return (None, None)

# --- shields ---------------------------------------------------------------

def _face_list(sh, n_faces):
    out = []
    i = 0
    while i < n_faces:
        v = _quiet_call(sh, "GetCurShields", (i,))
        if v is None: v = -1.0
        out.append(v)
        i = i + 1
    return out

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
        _has_pre = globals().has_key('_q08_pre')

        if not _has_pre:
            # =============================================================
            # PRE pass
            # =============================================================
            _section("PRE pass -- intensity " + _INTENSITY_LABEL +
                     ", lock = rear-mounted subsystem")
            _record("player", _player.GetName())
            _record("target", _target.GetName())

            # Disable target weapons ONLY (NOT engines -- impulse needs to
            # be intact so it can register damage when locked)
            n = _disable_target_weapons(_target)
            _record("target weapons disabled", n)

            # Set FULL intensity
            _call("ws.SetPowerLevel(PP_HIGH)", _ws,
                  "SetPowerLevel", (App.PhaserSystem.PP_HIGH,))
            _record("intensity_after_set",
                    _call("ws.GetPowerLevel", _ws, "GetPowerLevel", ()))

            # Drop shields to 0
            i = 0
            while i < _n_faces:
                _quiet_call(_sh, "SetCurShields", (i, 0.0))
                i = i + 1
            _faces_pre = _face_list(_sh, _n_faces)
            _record("pre.faces (should be all 0)", _faces_pre)

            # Pick a rear-mounted lockable subsystem
            _lock_sub, _lock_label = _pick_rear_lock(_target)
            if _lock_sub is None:
                _record("ABORT",
                        "no rear-mounted lockable subsystem found "
                        "(impulse/warp both unavailable or destroyed)")
                _flush()
                _banner("ABORTED -- no rear lock available")
            else:
                _record("lock_choice", _lock_label)
                _record("locked sub pre-condition",
                        _quiet_call(_lock_sub, "GetCondition", ()))
                _call("player.SetTargetSubsystem", _player,
                      "SetTargetSubsystem", (_lock_sub,))
                _readback = _call("player.GetTargetSubsystem",
                                   _player, "GetTargetSubsystem", ())
                _record("lock readback",
                        _quiet_call(_readback, "GetName", ()))

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
                    'game_time': App.g_kUtopiaModule.GetGameTime(),
                    'subs':      _subs_pre,
                    'hull':      _hull_pre,
                    'faces':     _faces_pre,
                    'lock_label': _lock_label,
                }
                globals()['_q08_pre'] = _pre
                _flush()

                _banner("PRE COMPLETE -- locked rear subsystem: " + _lock_label)
                print ""
                print "NEXT STEPS (PROMPTLY -- shields regen on unpause):"
                print "  4a. Press P to UNPAUSE."
                print "  4b. HOLD FIRE for about 3 seconds."
                print "  4c. Press P to PAUSE."
                print "  5.  execfile('q08_lock_rear_subsystem.py')"
                print ""

        else:
            # =============================================================
            # POST pass
            # =============================================================
            _section("POST pass")
            _pre = globals()['_q08_pre']
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

            _section("Q7-disambiguation finding (locked = %s, FULL)" %
                     _pre['lock_label'])

            # Find top-damaged subsystem
            total_sub_damage = 0.0
            top_sub = None
            top_sub_d = 0.0
            for pre_snap in _pre['subs']:
                label = pre_snap['label']
                post_snap = _post_by_label.get(label)
                if post_snap is None: continue
                d = _delta(post_snap['damage'], pre_snap['damage'])
                if d is None or d <= 0: continue
                total_sub_damage = total_sub_damage + d
                if d > top_sub_d:
                    top_sub_d = d
                    top_sub = label

            locked_took = (locked_d_damage is not None and locked_d_damage > 0.001) \
                       or (locked_d_combined is not None and locked_d_combined > 0.001)

            if d_gt <= 0:
                conclusion = "INCONCLUSIVE -- no game-time elapsed"
            elif d_hull <= 0.5 and total_sub_damage <= 0.5:
                conclusion = "INCONCLUSIVE -- no damage delivered"
            elif locked_took and top_sub == _pre['lock_label']:
                conclusion = ("LOCK REDIRECTS FIRE.  Damage routed to LOCKED "
                              "rear sub '%s' (-%s damage).  This OVERTURNS "
                              "the q07 'lock inert' reading -- Q7 reopens."
                              % (_pre['lock_label'], locked_d_damage))
            elif locked_took:
                conclusion = ("PARTIAL REDIRECT.  Locked rear sub '%s' took "
                              "some (-%s) but the top sub was '%s' (-%.3f). "
                              "The lock has SOME effect but doesn't dominate."
                              % (_pre['lock_label'], locked_d_damage,
                                 top_sub, top_sub_d))
            elif top_sub is not None:
                conclusion = ("LOCK IS INERT.  Locked rear sub '%s' was "
                              "untouched (d_damage=0). Damage went to '%s' "
                              "(-%.3f) -- a forward-mounted subsystem, same "
                              "as q07.  Confirms the lock truly does not "
                              "redirect weapon fire."
                              % (_pre['lock_label'], top_sub, top_sub_d))
            else:
                conclusion = "AMBIGUOUS -- inspect data above"
            _record("Q7 DISAMBIGUATION", conclusion)

            del globals()['_q08_pre']
            _flush()

            _banner("Q7 DISAMBIGUATION RESULT")
            print ""
            print "  " + conclusion
            print ""
            print "Run:  uv run python tools/probes/collect.py q08"
            print ""

except:
    _record("FATAL",
            "exc_type=%s exc_value=%s"
            % (str(sys.exc_type), str(sys.exc_value)))
    _flush()
    _banner("PROBE CRASHED -- see FATAL line above")

print "done"
