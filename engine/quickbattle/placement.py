"""Deterministic group placement around the player. Pure: plain tuples in GU.

Spec §4.4: axes from the player's columns (stbd = GetCol(0), fore = GetCol(1),
dorsal = GetCol(2); right-handed); anchor = player + axis * distance (centre to
centre); line abreast across the lateral axis, slots 0, +1, -1, +2, -2 packed
by radii plus MARGIN_GU; rows of ROW_SIZE, each further row one row-gap further
along the axis. No randomness.
"""
from __future__ import annotations

MARGIN_GU = 2.0
ROW_SIZE = 5

_AXIS = {"starboard": (0, 1.0), "port": (0, -1.0), "fore": (1, 1.0),
         "aft": (1, -1.0), "dorsal": (2, 1.0), "ventral": (2, -1.0)}


def _scale(v, k):
    return (v[0] * k, v[1] * k, v[2] * k)


def _add(*vs):
    return (sum(v[0] for v in vs), sum(v[1] for v in vs), sum(v[2] for v in vs))


def axis_for(direction, cols):
    i, sign = _AXIS[direction]
    return _scale(cols[i], sign)


def lateral_for(direction, cols):
    return cols[1] if direction in ("port", "starboard") else cols[0]


def faces_player(allegiance) -> bool:
    return allegiance == "enemy"


def slot_offsets(radii) -> list:
    """Lateral offset per ship of one row, in input order. Slot k>0 alternates
    +, -; each side packs outward: prev offset + prev radius + this radius + margin."""
    out = [0.0] * len(radii)
    if not radii:
        return out
    edge = {1: (0.0, radii[0]), -1: (0.0, radii[0])}   # side -> (last offset, last radius)
    for i in range(1, len(radii)):
        side = 1 if i % 2 == 1 else -1
        last_off, last_r = edge[side]
        off = abs(last_off) + last_r + radii[i] + MARGIN_GU
        out[i] = side * off
        edge[side] = (out[i], radii[i])
    return out


def group_positions(player_pos, cols, direction, distance_gu, radii) -> list:
    axis = axis_for(direction, cols)
    lat = lateral_for(direction, cols)
    out = []
    depth = float(distance_gu)
    prev_row_max = None
    for start in range(0, len(radii), ROW_SIZE):
        row = radii[start:start + ROW_SIZE]
        if prev_row_max is not None:
            depth += prev_row_max + max(row) + MARGIN_GU
        for off in slot_offsets(row):
            out.append(_add(player_pos, _scale(axis, depth), _scale(lat, off)))
        prev_row_max = max(row)
    return out


def escort_positions(player_pos, cols, player_radius, radii) -> list:
    """Escorts line abreast with the player as slot 0."""
    offs = slot_offsets([player_radius] + list(radii))[1:]
    return [_add(player_pos, _scale(cols[0], off)) for off in offs]
