"""Large field rocks as avoidance obstacles (rock-promotion spec §4).

NPCs steer round every large near-band rock -- promoted or not -- through
the native camera-independent query. Only for the viewed set (the field's
anchor is known only there). Promoted rocks are set objects already, so
their keys are left out. Never raises.
"""
from __future__ import annotations


def near(pSet, centre_view, radius_gu, r=None) -> list:
    try:
        from engine.systems import frames
        if pSet is None or pSet is not frames.viewing_set():
            return []
        from engine.rocks import far_tier, far_dials, promotion
        system, anchor = far_tier.frame_for(pSet)
        if r is None:
            from engine import renderer as r
        if not r.far_enabled():
            return []
        c = tuple(a + p for a, p in zip(anchor, centre_view))
        skip = set(promotion.promoted())
        out = []
        for h in r.rockfield_query_large(c, float(radius_gu),
                                         float(far_dials.get("near_large_r_min"))):
            if h["key"] in skip:
                continue
            p = h["pos"]
            out.append((p[0] - anchor[0], p[1] - anchor[1], p[2] - anchor[2],
                        float(h["radius"])))
        return out
    except Exception as e:
        from engine import dev_mode
        dev_mode.log_swallowed("field obstacles", e)
        return []
