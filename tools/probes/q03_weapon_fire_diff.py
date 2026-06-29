###############################################################################
# q03_weapon_fire_diff.py
#
# Question(s): Q-D2..Q-D7 and Q-C1..Q-C2 from the weapon-exchange runbook --
# what does a REAL weapon hit do?  Where does the damage land?  What's the
# discharge rate in chg/sec and chg/frame?
#
# Strategy: q02 proved AddDamage bypasses shields (= explosion/collision path,
# not weapon path).  To find the weapon path we do a CONTROLLED-FIRE DIFF:
# snapshot state, let bank 0 fire normally for ~1 sec, snapshot again.  The
# diff is the routing.
#
# IMPORTANT -- PURELY OBSERVATIONAL.  An earlier version of this probe
# triggered fire via Weapon.SetFiring(1) / WeaponSystem.StartFiring()
# programmatically and CRASHED THE GAME on unpause (bypassing the normal
# target-acquisition pipeline left the engine in a half-initialised state).
# This version mutates *nothing*; the operator presses the fire key.
#
# TWO-PASS probe (BC's game loop is single-threaded with Python -- while a
# probe is running the game is frozen, so we can't sleep-fire-sleep in one
# call):
#
#   1. Quick Battle, Tab-lock a hostile, get within ~60 GU (= 10.5 km),
#      face bank 0 at the target.
#   2. PAUSE (P).
#   3. execfile('q03_weapon_fire_diff.py')   <-- PRE: snapshots state.
#   4. Unpause (P), HOLD FIRE for ~1 sec, pause (P).
#   5. execfile('q03_weapon_fire_diff.py')   <-- POST: snapshots, diffs,
#                                                 writes cfg.
#
# Output: game/BCProbe_q03.cfg (POST pass only).
###############################################################################

import App
import sys

_cfg = App.g_kConfigMapping
_SECTION = "BCProbe_q03"
_CFG_FILE = "BCProbe_q03.cfg"
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

# --- snapshot helper --------------------------------------------------------

def _snap(player, target, sh, n_faces, w0):
    snap = {}
    snap['frame']     = App.g_kSystemWrapper.GetUpdateNumber()
    snap['game_time'] = App.g_kUtopiaModule.GetGameTime()
    snap['real_time'] = App.g_kUtopiaModule.GetRealTime()
    snap['charge']    = _call("w0.GetChargeLevel", w0, "GetChargeLevel", ())
    snap['can_fire']  = _call("w0.CanFire", w0, "CanFire", ())
    snap['is_firing'] = _call("w0.IsFiring", w0, "IsFiring", ())
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
        dx = tp.x - pp.x
        dy = tp.y - pp.y
        dz = tp.z - pp.z
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
    _ws = None
    if _player is not None:
        _ws = _call("player.GetPhaserSystem", _player, "GetPhaserSystem", ())
    _w0 = None
    if _ws is not None:
        _w_raw = _call("ws.GetWeapon(0)", _ws, "GetWeapon", (0,))
        if _w_raw is not None:
            _w0 = _try("EnergyWeapon_Cast", App.EnergyWeapon_Cast, (_w_raw,))

    _missing = None
    if _player is None: _missing = "player"
    elif _target is None: _missing = "target (Tab-lock a hostile ship)"
    elif _sh is None: _missing = "shields"
    elif _w0 is None: _missing = "bank 0"

    if _missing is not None:
        _record("ABORT", "missing %s -- check setup and rerun" % _missing)
        _flush()
    else:
        _n_faces = _sh.GetNumShields()
        _has_pre = globals().has_key('_q03_pre')

        if not _has_pre:
            # =============================================================
            # PRE pass -- snapshot ONLY.  Do not mutate engine state.
            # =============================================================
            _section("PRE pass (observational, no state changes)")
            _record("player", _player.GetName())
            _record("target", _target.GetName())

            _pre = _snap(_player, _target, _sh, _n_faces, _w0)
            _record("pre.frame", _pre['frame'])
            _record("pre.game_time", _pre['game_time'])
            _record("pre.real_time", _pre['real_time'])
            _record("pre.charge", _pre['charge'])
            _record("pre.max_charge",
                    _call("w0.GetMaxCharge", _w0, "GetMaxCharge", ()))
            _record("pre.can_fire", _pre['can_fire'])
            _record("pre.is_firing", _pre['is_firing'])
            _record("pre.shield_total", _pre['shield_total'])
            _record("pre.faces", _pre['faces'])
            _record("pre.hull", _pre['hull'])
            _record("pre.range", _pre['range'])

            globals()['_q03_pre'] = _pre
            _record("status",
                    "PRE saved.  Unpause, HOLD FIRE KEY ~1 sec, pause, rerun me.")
            _flush()

        else:
            # =============================================================
            # POST pass -- snapshot, diff against saved PRE
            # =============================================================
            _section("POST pass")
            _pre = globals()['_q03_pre']

            _post = _snap(_player, _target, _sh, _n_faces, _w0)
            _record("post.frame", _post['frame'])
            _record("post.game_time", _post['game_time'])
            _record("post.real_time", _post['real_time'])
            _record("post.charge", _post['charge'])
            _record("post.shield_total", _post['shield_total'])
            _record("post.faces", _post['faces'])
            _record("post.hull", _post['hull'])
            _record("post.range", _post['range'])

            _section("diffs")
            d_frame = _post['frame'] - _pre['frame']
            d_gt    = _post['game_time'] - _pre['game_time']
            d_rt    = _post['real_time'] - _pre['real_time']
            d_chg   = _pre['charge'] - _post['charge']
            d_sht   = _pre['shield_total'] - _post['shield_total']
            d_hull  = _pre['hull'] - _post['hull']

            _record("d_frame", d_frame)
            _record("d_game_time", d_gt)
            _record("d_real_time", d_rt)
            _record("d_charge", d_chg)
            _record("d_shield_total", d_sht)
            _record("d_hull", d_hull)
            i = 0
            while i < _n_faces:
                _record("d_face_%d" % i,
                        _pre['faces'][i] - _post['faces'][i])
                i = i + 1

            _section("findings")
            _delivered = d_sht + d_hull
            if d_frame <= 0:
                _record("note",
                        "no frames elapsed -- did you unpause? rerun: P, fire, P.")
            elif _delivered <= 1.0:
                _record("note",
                        "no damage delivered -- target out of arc / range / "
                        "shields recharged faster than we drained them. "
                        "(d_shield=%.3f d_hull=%.3f d_chg=%.3f)"
                        % (d_sht, d_hull, d_chg))
            else:
                if d_sht > 0.5 and d_hull <= 0.5:
                    routing = "SHIELDS-ONLY (weapon path routes through shields)"
                elif d_sht <= 0.5 and d_hull > 0.5:
                    routing = "BYPASSES SHIELDS (same primitive as AddDamage)"
                elif d_sht > 0.5 and d_hull > 0.5:
                    routing = ("SPLITS shield+hull (%.0f%% shield / %.0f%% hull) -- "
                               "either bleed-through fraction or face depleted mid-window"
                               % (100.0 * d_sht / _delivered,
                                  100.0 * d_hull / _delivered))
                else:
                    routing = "no damage detected"
                _record("WEAPON PATH ROUTING", routing)

                if d_gt > 0:
                    _record("DPS shield (game time)", d_sht / d_gt)
                    _record("DPS hull   (game time)", d_hull / d_gt)
                    _record("DPS total  (game time)", _delivered / d_gt)
                if d_rt > 0 and d_gt > 0:
                    _record("real/game time ratio", d_rt / d_gt)

                # Charge measurement caveat: d_charge often 0 because the
                # bank fully recharges between PRE and POST snapshots.  For
                # discharge rate use an approach-1 per-tick polling snippet
                # (see tools/charge_logger.py).
                if d_chg <= 0.5:
                    _record("charge_note",
                            "d_charge=%.3f -- bank likely fully recharged "
                            "between PRE and POST snapshots; discharge rate "
                            "needs per-tick polling (approach 1)." % d_chg)
                elif d_gt > 0:
                    _record("discharge_rate (chg / s game time, lower bound)",
                            d_chg / d_gt)

            del globals()['_q03_pre']
            _flush()

except:
    _record("FATAL",
            "exc_type=%s exc_value=%s"
            % (str(sys.exc_type), str(sys.exc_value)))
    _flush()

print "done"
