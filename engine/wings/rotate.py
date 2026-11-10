"""Rotate rule: damaged ships fall back. Pure: no App imports."""
import math

from engine.wings import dials
from engine.wings.assess import dist


def weak_face(v) -> float:
    """The weakest shield face, the side being hit. A view built without
    one (tests, enemy snapshots) reads its mean."""
    return v.shield if v.weak_face is None else v.weak_face


def reason(name, v, hull_state) -> str:
    """Why `name` is falling back, for the log: its one hull fall-back, or
    a downed shield face."""
    return "hull" if (hull_state or {}).get(name) == "active" else "shields"


def fallback_flags(member_views, prev, now, exclude, cooldown=None,
                   hull_state=None):
    """Fall-back start times (name -> since, or None).

    Out when the weakest shield face is under rotate_out_shield, or, once
    per ship, when the hull is under rotate_out_hull; never with the hull
    under desperate_hull (Phase A's ram/flee owns that ship). Back when the
    weakest face reaches rotate_in_shield, except a hull fall-back, which
    holds to rotate_max_s; every fall-back ends at rotate_max_s.

    `cooldown` (name -> time) and `hull_state` (name -> "active" while a
    hull fall-back runs, "spent" after) are caller-owned state, updated in
    place. A fall-back ended by the rotate_max_s timeout bars a new one
    until now + rotate_max_s. Shield-recovery returns set no cooldown."""
    if cooldown is None:
        cooldown = {}
    if hull_state is None:
        hull_state = {}
    views = list(member_views)
    n = len(views)
    cap = 0 if n <= 1 else min(
        n - 1, max(1, math.floor(dials.get("rotate_cap_frac") * n)))
    out = {v.name: None for v in views}
    keep = []
    for v in views:
        since = prev.get(v.name)
        if since is None or v.name in exclude:
            if hull_state.get(v.name) == "active":
                hull_state[v.name] = "spent"
            continue
        on_hull = hull_state.get(v.name) == "active"
        if not on_hull and weak_face(v) >= dials.get("rotate_in_shield"):
            continue
        if now - since >= dials.get("rotate_max_s"):
            cooldown[v.name] = now + dials.get("rotate_max_s")
            if on_hull:
                hull_state[v.name] = "spent"
            continue
        keep.append(v)
    keep.sort(key=lambda v: (weak_face(v), v.hull, v.name))
    chosen = keep[:cap]
    for v in chosen:
        out[v.name] = prev[v.name]
    for v in keep[cap:]:
        if hull_state.get(v.name) == "active":
            hull_state[v.name] = "spent"
    room = cap - len(chosen)
    if room > 0:
        out_shield = dials.get("rotate_out_shield")
        out_hull = dials.get("rotate_out_hull")
        fresh = []
        for v in views:
            if (v.name in exclude or prev.get(v.name) is not None
                    or now < cooldown.get(v.name, -1.0)
                    or v.hull < dials.get("desperate_hull")):
                continue
            if weak_face(v) < out_shield:
                fresh.append((v, False))
            elif v.hull < out_hull and v.name not in hull_state:
                fresh.append((v, True))
        fresh.sort(key=lambda f: (weak_face(f[0]), f[0].hull, f[0].name))
        for v, on_hull in fresh[:room]:
            out[v.name] = now
            if on_hull:
                hull_state[v.name] = "active"
    return out


def fallback_point(anchor_pos, enemy_centroid, gather_gu):
    d = dist(anchor_pos, enemy_centroid)
    if d <= 1e-9:
        return tuple(anchor_pos)
    return tuple(a + (a - c) / d * gather_gu
                 for a, c in zip(anchor_pos, enemy_centroid))
