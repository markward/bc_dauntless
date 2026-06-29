###############################################################################
# q04_shield_bleedthrough.py
#
# Question: Q4 from 2026-06-29-weapon-exchange-console-probe.md.
#   Does the weapon path bleed SOME FRACTION to hull even while the facing
#   shield is up, or does it use a STRICT CASCADE (100% to face until face
#   hits zero, then 100% to hull)?
#
#   q03 saw 715 shield + 180 hull (80/20) over 35 sec with no face going
#   to zero -- AMBIGUOUS between (a) 20% bleed-through fraction and (b) a
#   face briefly hit zero mid-window.  q04 disambiguates by RESETTING ALL
#   FACES TO FULL right before the fire window, so a face going to zero
#   becomes implausibly hard.
#
# ==== OPERATOR PROCEDURE -- 5 STEPS ==========================================
#
#   1.  Quick Battle.  Pick any hostile ship.  TAB to lock target.
#       Fly to about 5 km from target (HUD range readout).  Face it.
#
#   2.  PAUSE  (press P)
#
#   3.  execfile('q04_shield_bleedthrough.py')      <-- PRE pass.
#       The probe will reset every face of the target to full, snapshot,
#       and tell you what to do next.
#
#   4.  UNPAUSE (P).  HOLD FIRE for about 3 seconds.  PAUSE (P).
#       (Anything from 1 to 30 sec is fine; we just don't want to fire
#       long enough for a face to actually deplete, which takes >100 sec
#       at point-blank against most ships.)
#
#   5.  execfile('q04_shield_bleedthrough.py')      <-- POST pass.
#       Probe diffs and reports BLEED-THROUGH or STRICT CASCADE.
#
# Output: game/BCProbe_q04.cfg
###############################################################################

import App
import sys

_cfg = App.g_kConfigMapping
_SECTION = "BCProbe_q04"
_CFG_FILE = "BCProbe_q04.cfg"
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

# --- snapshot helper --------------------------------------------------------

def _snap(player, target, sh, n_faces):
    snap = {}
    snap['frame']     = App.g_kSystemWrapper.GetUpdateNumber()
    snap['game_time'] = App.g_kUtopiaModule.GetGameTime()
    snap['faces']     = []
    s = 0.0
    i = 0
    while i < n_faces:
        v = _call("sh.GetCurShields(%d)" % i, sh, "GetCurShields", (i,))
        if v is None:
            v = -1.0
        snap['faces'].append(v)
        if v > 0:
            s = s + v
        i = i + 1
    snap['shield_total'] = s
    try:
        snap['hull'] = target.GetHull().GetCondition()
    except:
        snap['hull'] = -1.0
    try:
        pp = player.GetWorldLocation()
        tp = target.GetWorldLocation()
        dx = tp.x - pp.x; dy = tp.y - pp.y; dz = tp.z - pp.z
        snap['range'] = (dx*dx + dy*dy + dz*dz) ** 0.5
    except:
        snap['range'] = -1.0
    return snap

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

    _missing = None
    if _player is None: _missing = "player"
    elif _target is None: _missing = "target (TAB to lock a hostile ship)"
    elif _sh is None: _missing = "shields"

    if _missing is not None:
        _record("ABORT", "missing %s -- check setup and rerun" % _missing)
        _flush()
        _banner("ABORTED -- " + _missing)
    else:
        _n_faces = _sh.GetNumShields()
        _has_pre = globals().has_key('_q04_pre')

        if not _has_pre:
            # =============================================================
            # PRE -- reset every face to its max, snapshot
            # =============================================================
            _section("PRE pass")
            _record("player", _player.GetName())
            _record("target", _target.GetName())
            _record("num_shield_faces", _n_faces)

            # Reset each face to its OWN max (faces can have different maxes).
            _maxes = []
            i = 0
            while i < _n_faces:
                m = _call("sh.GetMaxShields(%d)" % i, _sh, "GetMaxShields", (i,))
                if m is None:
                    m = 0.0
                _maxes.append(m)
                _call("sh.SetCurShields(%d)" % i, _sh, "SetCurShields", (i, m))
                i = i + 1
            _record("face_maxes", _maxes)

            _pre = _snap(_player, _target, _sh, _n_faces)
            _record("pre.frame", _pre['frame'])
            _record("pre.game_time", _pre['game_time'])
            _record("pre.faces (should match face_maxes)", _pre['faces'])
            _record("pre.shield_total", _pre['shield_total'])
            _record("pre.hull", _pre['hull'])
            _record("pre.range", _pre['range'])

            globals()['_q04_pre'] = _pre
            _flush()

            _banner("PRE COMPLETE -- ALL SHIELD FACES RESET TO MAX")
            print ""
            print "NEXT STEPS (in this order):"
            print "  4a. Press P to UNPAUSE the game."
            print "  4b. HOLD FIRE for about 3 seconds (1-30 sec OK)."
            print "  4c. Press P to PAUSE again."
            print "  5.  execfile('q04_shield_bleedthrough.py')"
            print ""

        else:
            # =============================================================
            # POST -- snapshot, diff, conclude
            # =============================================================
            _section("POST pass")
            _pre = globals()['_q04_pre']

            _post = _snap(_player, _target, _sh, _n_faces)
            _record("post.frame", _post['frame'])
            _record("post.game_time", _post['game_time'])
            _record("post.faces", _post['faces'])
            _record("post.shield_total", _post['shield_total'])
            _record("post.hull", _post['hull'])
            _record("post.range", _post['range'])

            _section("diffs")
            d_gt   = _post['game_time'] - _pre['game_time']
            d_sht  = _pre['shield_total'] - _post['shield_total']
            d_hull = _pre['hull'] - _post['hull']
            _record("d_game_time", d_gt)
            _record("d_shield_total", d_sht)
            _record("d_hull", d_hull)

            _any_zero = 0
            _zero_faces = []
            i = 0
            while i < _n_faces:
                df = _pre['faces'][i] - _post['faces'][i]
                _record("face_%d  pre=%.2f  post=%.2f  delta" % (
                            i, _pre['faces'][i], _post['faces'][i]),
                        "%.3f" % df)
                if _post['faces'][i] <= 0.01:
                    _any_zero = 1
                    _zero_faces.append(i)
                i = i + 1

            _section("Q4 finding")
            _delivered = d_sht + d_hull
            if d_gt <= 0:
                conclusion = "INCONCLUSIVE -- no game-time elapsed (did you unpause?)"
            elif _delivered <= 1.0:
                conclusion = ("INCONCLUSIVE -- no damage delivered "
                              "(d_shield=%.3f d_hull=%.3f). Were you in arc/range?"
                              % (d_sht, d_hull))
            elif d_hull <= 0.5:
                # Hull untouched.  Either strict cascade with no face depleted,
                # OR bleed-through but rate so low no hull damage measurable.
                conclusion = ("STRICT CASCADE plausible -- hull untouched. "
                              "Face deltas were %.3f total, hull stayed flat."
                              % d_sht)
            elif _any_zero:
                conclusion = ("AMBIGUOUS -- face(s) %s went to zero during the "
                              "fire window. Strict cascade COULD explain the "
                              "%.3f hull damage. Rerun with a shorter fire "
                              "burst." % (_zero_faces, d_hull))
            else:
                # Hull moved, NO face depleted -> bleed-through fraction
                frac = d_hull / _delivered
                conclusion = ("BLEED-THROUGH FRACTION = %.1f%%  "
                              "(d_shield=%.3f, d_hull=%.3f, no face depleted)."
                              " The weapon path applies ~%.0f%% to facing "
                              "shield and ~%.0f%% straight to hull "
                              "REGARDLESS of shield state."
                              % (100.0 * frac, d_sht, d_hull,
                                 100.0 * (1.0 - frac), 100.0 * frac))
            _record("Q4 CONCLUSION", conclusion)

            del globals()['_q04_pre']
            _flush()

            _banner("Q4 RESULT")
            print ""
            print "  " + conclusion
            print ""
            print "Run:  uv run python tools/probes/collect.py q04"
            print ""

except:
    _record("FATAL",
            "exc_type=%s exc_value=%s"
            % (str(sys.exc_type), str(sys.exc_value)))
    _flush()
    _banner("PROBE CRASHED -- see FATAL line above")

print "done"
