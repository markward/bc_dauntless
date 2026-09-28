"""What a star system looks like from the viewed set (spec §4).

A PURE function of the viewed set: every non-star body of its system, placed
in the viewed set's local coordinates (body.position_gu - anchor(view)). The
renderer diffs its instances against this list; there is no cache to supersede
and nothing to sweep -- the reference branch's two-source design died of that.
The star is not here: the viewed set's own Sun object already sits at the map
star (apply_map) and draws through the sun pass.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CelestialBody:
    key: tuple
    name: str
    model: str
    radius_gu: float
    position: tuple


def draw_list(view) -> tuple:
    from engine.systems import frames, resolve
    f = frames.frame_of(view)
    if f is None or f.key[0] != "system":
        return ()
    m = resolve.map_of(f.key[1])
    if m is None:
        return ()
    ax, ay, az = f.anchor_gu
    out = []
    for b in m.bodies:
        if b.orbits is None:
            continue
        x, y, z = b.position_gu
        out.append(CelestialBody(
            key=(m.system, b.owner_region or "", b.name),
            name=b.name, model=b.appearance.model,
            radius_gu=float(b.radius_gu),
            position=(x - ax, y - ay, z - az)))
    return tuple(out)
