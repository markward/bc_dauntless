"""Rotate rule: damaged ships fall back. Pure: no App imports."""
import math

from engine.wings import dials
from engine.wings.assess import dist


def fallback_flags(member_views, prev, now, exclude):
    views = list(member_views)
    n = len(views)
    cap = 0 if n <= 1 else min(
        n - 1, max(1, math.floor(dials.get("rotate_cap_frac") * n)))
    out = {v.name: None for v in views}
    keep = []
    for v in views:
        since = prev.get(v.name)
        if since is None or v.name in exclude:
            continue
        if v.shield >= dials.get("rotate_in_shield") \
                or now - since >= dials.get("rotate_max_s"):
            continue
        keep.append(v)
    keep.sort(key=lambda v: (v.shield, v.name))
    chosen = keep[:cap]
    for v in chosen:
        out[v.name] = prev[v.name]
    room = cap - len(chosen)
    if room > 0:
        fresh = [v for v in views
                 if v.name not in exclude and prev.get(v.name) is None
                 and v.shield < dials.get("rotate_out_shield")
                 and v.hull >= dials.get("desperate_hull")]
        fresh.sort(key=lambda v: (v.shield, v.name))
        for v in fresh[:room]:
            out[v.name] = now
    return out


def fallback_point(anchor_pos, enemy_centroid, gather_gu):
    d = dist(anchor_pos, enemy_centroid)
    if d <= 1e-9:
        return tuple(anchor_pos)
    return tuple(a + (a - c) / d * gather_gu
                 for a, c in zip(anchor_pos, enemy_centroid))
