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


def _valid_target(player):
    """The player's current target if it is a real, non-self object."""
    get = getattr(player, "GetTarget", None)
    if get is None:
        return None
    tgt = get()
    if tgt is None or tgt is player:
        return None
    return tgt


def _valid_subsystem(target):
    """The locked subsystem if present and not destroyed, else None."""
    get = getattr(target, "GetTargetSubsystem", None)
    if get is None:
        return None
    sub = get()
    if sub is None:
        return None
    is_destroyed = getattr(sub, "IsDestroyed", None)
    if is_destroyed is not None and is_destroyed():
        return None
    return sub


def target_aim_point(player):
    """World point the tracking camera should orbit, or None if no valid
    target. Subsystem world position when a valid subsystem is locked,
    otherwise the target's hull centre."""
    target = _valid_target(player)
    if target is None:
        return None
    sub = _valid_subsystem(target)
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
    sub = _valid_subsystem(target)
    subtarget = None
    if sub is not None:
        w = subsystem_world_position(sub, target)
        subtarget = (w.x, w.y, w.z)
    return TargetReticlePayload(
        visible=True,
        ship_center=(centre.x, centre.y, centre.z),
        ship_radius=float(radius),
        subtarget_pos=subtarget,
    )
