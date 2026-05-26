"""Pure projection math for the sensor disc.

Reads player + contact world-space pose, returns the disc-relative
(x, y, alt, heading) tuple, or None if the contact is outside disc
range. Lives separate from the panel so it's testable in isolation.

Convention (matches engine/appc/ships.py:153-157):
  - World axes: X = right, Y = forward, Z = up.
  - Model forward = R.GetCol(1); model right = R.GetCol(0);
    model up = R.GetCol(2).
  - Disc coords normalised to [-1, +1]: +y = player forward,
    +x = player right.
  - Altitude normalised by range_m, clipped to [-1, +1].
  - Heading in radians: 0 = same heading as player; positive = clockwise
    looking down (toward player's right).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from engine.appc.math import TGPoint3, TGMatrix3


@dataclass(frozen=True)
class Contact:
    x: float          # disc-plane x, normalised [-1, +1]
    y: float          # disc-plane y, normalised [-1, +1]
    alt: float        # altitude, normalised then clipped to [-1, +1]
    heading: float    # radians, relative to player forward


def project_contact(
    player_pos: TGPoint3,
    player_rot: TGMatrix3,
    target_pos: TGPoint3,
    target_rot: TGMatrix3,
    range_m: float,
) -> Optional[Contact]:
    if range_m <= 0.0:
        return None

    # Delta in world space.
    dx = target_pos.x - player_pos.x
    dy = target_pos.y - player_pos.y
    dz = target_pos.z - player_pos.z

    # Player basis vectors in world space (columns of the rotation matrix).
    right   = player_rot.GetCol(0)
    forward = player_rot.GetCol(1)
    up      = player_rot.GetCol(2)

    # Decompose the delta into the player frame.
    proj_right   = dx * right.x   + dy * right.y   + dz * right.z
    proj_forward = dx * forward.x + dy * forward.y + dz * forward.z
    proj_up      = dx * up.x      + dy * up.y      + dz * up.z

    # Disc-plane distance (ignores altitude — altitude is the stem).
    plane_sq = proj_right * proj_right + proj_forward * proj_forward
    if plane_sq > range_m * range_m:
        return None  # outside disc → contact hidden, matches stock BC

    inv_range = 1.0 / range_m
    x = proj_right   * inv_range
    y = proj_forward * inv_range

    # Altitude — clip to [-1, +1] so very high/low contacts don't fly
    # off the panel. The disc filter above only gates the planar
    # distance; a contact directly above the player at range_m * 2
    # should still render at the disc centre with a max-length stem.
    alt = max(-1.0, min(1.0, proj_up * inv_range))

    # Heading — target forward projected onto the player's (right, forward)
    # plane, expressed as an angle from player forward.
    tgt_fwd = target_rot.GetCol(1)
    tgt_in_right   = tgt_fwd.x * right.x   + tgt_fwd.y * right.y   + tgt_fwd.z * right.z
    tgt_in_forward = tgt_fwd.x * forward.x + tgt_fwd.y * forward.y + tgt_fwd.z * forward.z
    heading = math.atan2(tgt_in_right, tgt_in_forward)

    return Contact(x=x, y=y, alt=alt, heading=heading)
