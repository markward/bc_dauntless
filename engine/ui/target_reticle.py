"""Single source of truth for subsystem-target focus: the tracking-camera
look-at point and the on-screen reticle payload. Pure Python (no GL/CEF).

See docs/superpowers/specs/2026-06-09-subsystem-target-reticle-and-camera-design.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from engine.appc.subsystems import subsystem_world_position


@dataclass
class TargetReticlePayload:
    visible: bool = False
    ship_center: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    ship_radius: float = 0.0
    subtarget_pos: Optional[Tuple[float, float, float]] = None
    bar_alignment: float = 0.0   # [-1,+1]: +1 target fore, -1 aft, 0 abeam


def _valid_target(player):
    """The player's current target if it is a real, non-self object."""
    get = getattr(player, "GetTarget", None)
    if get is None:
        return None
    tgt = get()
    if tgt is None or tgt is player:
        return None
    return tgt


def _valid_subsystem(ship):
    """The subsystem ``ship`` has locked, if present and not destroyed, else
    None. BC stores the subsystem lock on the *firing* ship (the player), set
    via ``player.SetTargetSubsystem`` — see engine/ui/target_list_view.py and
    engine/appc/ships.py:GetTargetSubsystem. The locked subsystem instance
    itself belongs to the *target* ship, so resolve its world position against
    the target, not against ``ship``."""
    get = getattr(ship, "GetTargetSubsystem", None)
    if get is None:
        return None
    sub = get()
    if sub is None:
        return None
    is_destroyed = getattr(sub, "IsDestroyed", None)
    if is_destroyed is not None and is_destroyed():
        return None
    return sub


class _PoseView:
    """Minimal target-pose stand-in exposing GetWorldLocation/Rotation, so the
    aim-point math anchors on a supplied (render-interpolated) pose instead of
    the live one. Used only to feed subsystem_world_position."""
    __slots__ = ("_loc", "_rot")

    def __init__(self, loc, rot):
        self._loc = loc
        self._rot = rot

    def GetWorldLocation(self):
        return self._loc

    def GetWorldRotation(self):
        return self._rot


def target_aim_point(player, pose_of=None):
    """World point the tracking camera should orbit, or None if no valid
    target. Subsystem world position when the player has a valid subsystem
    locked, otherwise the target's hull centre.

    `pose_of(obj) -> (loc, rot)` optionally supplies the render-interpolated
    target pose so the aim point tracks exactly what the renderer draws (the
    smooth-motion fix). The subsystem mount and hull centre both rigidly follow
    the target, so anchoring on the interpolated pose interpolates the aim
    point too. When None, the live pose is read directly."""
    target = _valid_target(player)
    if target is None:
        return None
    sub = _valid_subsystem(player)
    if pose_of is not None:
        t_loc, t_rot = pose_of(target)
        if sub is not None:
            return subsystem_world_position(sub, _PoseView(t_loc, t_rot))
        return t_loc
    if sub is not None:
        return subsystem_world_position(sub, target)
    return target.GetWorldLocation()


def build_target_reticle(player) -> TargetReticlePayload:
    """Describe what the reticle pass should draw this frame."""
    target = _valid_target(player)
    if target is None:
        return TargetReticlePayload(visible=False)
    centre = target.GetWorldLocation()
    radius = target.GetRadius()
    sub = _valid_subsystem(player)
    subtarget = None
    if sub is not None:
        w = subsystem_world_position(sub, target)
        subtarget = (w.x, w.y, w.z)
    bar_alignment = 0.0
    rot = player.GetWorldRotation() if hasattr(player, "GetWorldRotation") else None
    pc = player.GetWorldLocation() if hasattr(player, "GetWorldLocation") else None
    if rot is not None and pc is not None:
        fwd = rot.GetCol(1)                       # ship forward in world space
        dx, dy, dz = centre.x - pc.x, centre.y - pc.y, centre.z - pc.z
        dlen = (dx * dx + dy * dy + dz * dz) ** 0.5
        if dlen > 1e-6:
            dot = (fwd.x * dx + fwd.y * dy + fwd.z * dz) / dlen
            bar_alignment = max(-1.0, min(1.0, dot))
    return TargetReticlePayload(
        visible=True,
        ship_center=(centre.x, centre.y, centre.z),
        ship_radius=float(radius),
        subtarget_pos=subtarget,
        bar_alignment=bar_alignment,
    )
