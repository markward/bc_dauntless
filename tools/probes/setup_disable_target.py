###############################################################################
# setup_disable_target.py  --  NOT a probe, a TEST-CONDITION HELPER.
#
# Disables the locked target's engines and weapons so you can position your
# ship at leisure and run q05a vs q05b (or any other A/B test) without the
# target flying off or firing back to pollute the measurements.
#
# What it does:
#   - target.GetImpulseEngineSubsystem().SetCondition(0)
#   - target.GetWarpEngineSubsystem().SetCondition(0)
#   - target.GetPhaserSystem().SetCondition(0)
#   - target.GetTorpedoSystem().SetCondition(0)
#   - target.GetPulseWeaponSystem().SetCondition(0)   (if present)
#
# Hull, shields, sensors, power, etc. are NOT touched -- shields still need
# to be resettable by the probes, hull still needs to be readable.
#
# Run as many times as you like; idempotent.  Effect persists until the
# target dies, you change target, or you start a new battle.
#
# ==== OPERATOR PROCEDURE =====================================================
#
#   1. Quick Battle, TAB to lock the target you want to test against.
#   2. PAUSE  (P)   -- prevents the target from moving while we zero its engines
#   3. execfile('setup_disable_target.py')
#   4. Now position your ship freely.  Target is a sitting duck.
#   5. Run q05a / q05b / etc. as normal.
###############################################################################

import App
import sys

def _quiet_call(obj, name, args):
    try:
        return apply(getattr(obj, name), args)
    except:
        return None

_player = _quiet_call(App, "Game_GetCurrentPlayer", ())
_raw = None
if _player is not None:
    _raw = _quiet_call(_player, "GetTarget", ())
_target = None
if _raw is not None:
    _target = _quiet_call(App, "ShipClass_Cast", (_raw,))

if _target is None:
    print "ABORT: no ShipClass target.  TAB-lock a hostile ship and retry."
else:
    print "Target: %s" % _quiet_call(_target, "GetName", ())

    _DISABLE = (
        ("GetImpulseEngineSubsystem",  "impulse engines"),
        ("GetWarpEngineSubsystem",     "warp engines"),
        ("GetPhaserSystem",            "phasers"),
        ("GetTorpedoSystem",           "torpedoes"),
        ("GetPulseWeaponSystem",       "pulse weapons"),
    )

    for getter_name, label in _DISABLE:
        sub = _quiet_call(_target, getter_name, ())
        if sub is None:
            print "  - %s : not present" % label
            continue
        before = _quiet_call(sub, "GetCondition", ())
        result = _quiet_call(sub, "SetCondition", (0.0,))
        after = _quiet_call(sub, "GetCondition", ())
        if after is not None and after <= 0.01:
            print "  - %s : DISABLED (%s -> %s)" % (label, before, after)
        else:
            print "  - %s : tried (cond %s -> %s)" % (label, before, after)

    print ""
    print "Target should now be helpless.  Position your ship and run q05a/q05b."

# Defensive cleanup: don't leave the helpers in the REPL namespace.
del _quiet_call, _player, _raw, _target
