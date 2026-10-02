"""Shared setup for the "Far Tier" developer preview missions.

Places the player at an exact point facing an exact target (a placement made
with the SDK's own AlignToVectors), and points the / L O dial keys at the
"far" group, so tuning starts on the first press.
"""
import math

import App
import MissionLib


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def aimed_placement(name, set_name, eye, target):
    """A placement at `eye` (set coordinates) whose forward points at `target`,
    with up as close to set +Z as the forward allows."""
    fwd = _unit(tuple(t - e for t, e in zip(target, eye)))
    up_ref = (0.0, 0.0, 1.0) if abs(fwd[2]) < 0.99 else (0.0, 1.0, 0.0)
    right = _unit(_cross(fwd, up_ref))
    up = _cross(right, fwd)
    p = App.PlacementObject_Create(name, set_name, None)
    p.SetTranslateXYZ(*eye)
    kf = App.TGPoint3()
    kf.SetXYZ(*fwd)
    ku = App.TGPoint3()
    ku.SetXYZ(*up)
    p.AlignToVectors(kf, ku)
    p.UpdateNodeOnly()
    return p


def create_aimed_player(pSet, eye, target):
    aimed_placement("Far Tier View", pSet.GetName(), eye, target)
    return MissionLib.CreatePlayerShip("Galaxy", pSet, "player", "Far Tier View")


def start_on_far_dials(dial="haze_brightness"):
    """/ L O act on the "rock fields" group, with `dial` selected."""
    try:
        from engine import dev_dial_groups
        if dev_dial_groups.set_active("rock fields"):
            while dev_dial_groups.selected() != dial:
                dev_dial_groups.cycle_dial()
    except Exception:
        pass
