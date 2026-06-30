###############################################################################
# q09_range_falloff.py
#
# Question (bonus, not in original runbook): what curve converts player-to-
# target range to delivered weapon damage?
#
# Why it matters: engine/host_loop.py:_phaser_damage_for_tick currently
# assumes a LINEAR (1 - d/MaxDamageDistance) falloff.  q03 hinted weapons
# deliver non-zero damage even beyond MaxDamageDistance, so the curve is
# probably not a hard linear cap.  This probe samples DPS at multiple
# ranges so we can fit the real curve.
#
# Method: multi-sample accumulator.  Operator runs the probe at several
# ranges; each PRE/fire/POST cycle appends (range, dps) to a global list,
# and the probe prints the accumulated curve after each sample.
#
# ==== OPERATOR PROCEDURE =====================================================
#
#   ONE-TIME SETUP:
#   1.  Quick Battle.  TAB-lock a hostile ship.  Open the dev console.
#   2.  execfile('setup_disable_target.py')   <-- target won't move/shoot
#
#   PER-SAMPLE (repeat 3-5 times at DIFFERENT ranges):
#   3.  Fly to a known range (read off the HUD readout).  Face the target.
#       Recommended ranges: ~2 km, ~5 km, ~8 km, ~15 km, ~25 km.
#       (60 GU = 10.5 km is MaxDamageDistance for Galaxy phaser bank 0.)
#   4.  PAUSE (P)
#   5.  execfile('q09_range_falloff.py')      <-- PRE: snapshots, resets
#                                                  shields, FULL intensity.
#   6.  UNPAUSE, FIRE ~3 sec, PAUSE.
#   7.  execfile('q09_range_falloff.py')      <-- POST: appends sample,
#                                                  prints curve so far.
#
#   When done sampling, the cfg file at game/BCProbe_q09.cfg contains the
#   full list of (range, dps) samples.  Run:
#       uv run python tools/probes/collect.py q09
#
# Output: game/BCProbe_q09.cfg
###############################################################################

import App
import sys

_cfg = App.g_kConfigMapping
_SECTION = "BCProbe_q09"
_CFG_FILE = "BCProbe_q09.cfg"
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

# --- helpers ----------------------------------------------------------------

def _range_player_target(player, target):
    try:
        pp = player.GetWorldLocation()
        tp = target.GetWorldLocation()
        dx = tp.x - pp.x; dy = tp.y - pp.y; dz = tp.z - pp.z
        return (dx*dx + dy*dy + dz*dz) ** 0.5
    except:
        return -1.0

def _reset_shields(sh, n_faces):
    i = 0
    while i < n_faces:
        m = _quiet_call(sh, "GetMaxShields", (i,))
        if m is None: m = 0.0
        _quiet_call(sh, "SetCurShields", (i, m))
        i = i + 1

def _shield_total(sh, n_faces):
    s = 0.0
    i = 0
    while i < n_faces:
        v = _quiet_call(sh, "GetCurShields", (i,))
        if v is not None and v > 0: s = s + v
        i = i + 1
    return s

def _hull_condition(target):
    try: return target.GetHull().GetCondition()
    except: return -1.0

def _print_table(samples):
    """Print the running curve.  Each sample is (range_gu, dps, raw, gt)."""
    print ""
    print "  samples so far:  range(GU)   range(km)   DPS(shield+hull)   raw / sec"
    for r_gu, dps, raw, gt in samples:
        r_km = r_gu * 0.175
        print "    %8.2f    %8.2f    %10.2f    %.1f / %.2f" % (
                r_gu, r_km, dps, raw, gt)
    print ""

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
    elif _target is None: _missing = "target (TAB to lock a hostile)"
    elif _sh is None: _missing = "shields"
    elif _ws is None: _missing = "player phaser system"

    if _missing is not None:
        _record("ABORT", "missing %s" % _missing)
        _flush()
        _banner("ABORTED -- " + _missing)
    else:
        _n_faces = _sh.GetNumShields()
        _has_pre = globals().has_key('_q09_pre')

        if not _has_pre:
            # =============================================================
            # PRE pass
            # =============================================================
            _section("PRE pass -- range falloff sample")
            _record("player", _player.GetName())
            _record("target", _target.GetName())

            # FULL intensity (max signal)
            _call("ws.SetPowerLevel(PP_HIGH)", _ws,
                  "SetPowerLevel", (App.PhaserSystem.PP_HIGH,))

            # Reset all shield faces to max (each sample starts clean)
            _reset_shields(_sh, _n_faces)

            r_gu = _range_player_target(_player, _target)
            _record("range_GU", r_gu)
            _record("range_km", r_gu * 0.175)
            _record("shield_total_pre", _shield_total(_sh, _n_faces))
            _record("hull_pre", _hull_condition(_target))

            _pre = {
                'game_time': App.g_kUtopiaModule.GetGameTime(),
                'range_gu':  r_gu,
                'shield':    _shield_total(_sh, _n_faces),
                'hull':      _hull_condition(_target),
            }
            globals()['_q09_pre'] = _pre
            _flush()

            _banner("PRE COMPLETE -- range %.2f GU (%.2f km)" %
                    (r_gu, r_gu * 0.175))
            print ""
            print "NEXT: UNPAUSE (P), HOLD FIRE ~3 sec, PAUSE (P), run again."
            print ""

        else:
            # =============================================================
            # POST pass -- append sample, print accumulated curve
            # =============================================================
            _section("POST pass -- recording sample")
            _pre = globals()['_q09_pre']

            d_gt = App.g_kUtopiaModule.GetGameTime() - _pre['game_time']
            d_shield = _pre['shield'] - _shield_total(_sh, _n_faces)
            d_hull = _pre['hull'] - _hull_condition(_target)
            raw = d_shield + d_hull
            dps = 0.0
            if d_gt > 0: dps = raw / d_gt

            _record("d_game_time", d_gt)
            _record("d_shield", d_shield)
            _record("d_hull", d_hull)
            _record("raw_damage_total", raw)
            _record("DPS", dps)

            # Append to accumulator
            samples = globals().get('_q09_samples')
            if samples is None:
                samples = []
            samples.append((_pre['range_gu'], dps, raw, d_gt))
            globals()['_q09_samples'] = samples

            _section("accumulated samples")
            i = 0
            while i < len(samples):
                r_gu, dps_i, raw_i, gt_i = samples[i]
                _record("sample[%d]  range_GU=%.2f  range_km=%.2f" % (
                            i, r_gu, r_gu * 0.175),
                        "DPS=%.2f  raw=%.1f  t=%.2f"
                        % (dps_i, raw_i, gt_i))
                i = i + 1

            del globals()['_q09_pre']
            _flush()

            _banner("SAMPLE %d RECORDED (range %.2f km, DPS %.1f)" %
                    (len(samples), _pre['range_gu'] * 0.175, dps))
            _print_table(samples)
            print "TO ADD ANOTHER SAMPLE:"
            print "  - Fly to a different range"
            print "  - P, execfile('q09_range_falloff.py'), P, fire, P, execfile(...)"
            print ""
            print "WHEN DONE:"
            print "  uv run python tools/probes/collect.py q09"
            print ""

except:
    _record("FATAL",
            "exc_type=%s exc_value=%s"
            % (str(sys.exc_type), str(sys.exc_value)))
    _flush()
    _banner("PROBE CRASHED -- see FATAL line above")

print "done"
