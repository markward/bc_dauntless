# engine/appc/shockwaves.py
"""Warp-core breach shockwave registry.

A transient, age-driven world-VFX registry mirroring engine/appc/hit_vfx.py.
warp_core_breach.detonate spawns one shockwave at the warp core's world
position; host_loop ages the registry each tick and pushes render_data() to the
renderer via host.set_shockwaves(...). The native ShockwavePass draws a
camera-facing ring + core flash whose size/animation derive from (max_radius,
age, lifetime).

See docs/superpowers/specs/2026-06-20-warp-core-breach-shockwave-design.md.
"""

SHOCKWAVE_LIFETIME = 1.4   # seconds — total ring/flash lifetime (was 0.7;
                           # doubled to run the expansion at ~50% speed)

_active: list[dict] = []


def _center_xyz(center):
    """Accept a TGPoint3-like (.x/.y/.z) or a 3-tuple; return (x, y, z) floats."""
    if hasattr(center, "x"):
        return (float(center.x), float(center.y), float(center.z))
    return (float(center[0]), float(center[1]), float(center[2]))


def spawn(center_world, max_radius_gu, lifetime, pSet=None) -> None:
    """Register a shockwave centered at `center_world` (world space) that
    expands to `max_radius_gu` over `lifetime` seconds.

    `pSet` is the set `center_world` is local to (the breaching ship's); the
    render feed drops a shockwave outside the viewed frame and expresses one
    inside it in the viewed set's coordinates. None: in no frame, not drawn."""
    _active.append({
        "center": _center_xyz(center_world),
        "set": pSet,
        "max_radius": float(max_radius_gu),
        "age": 0.0,
        "lifetime": float(lifetime),
    })


def advance(dt: float) -> None:
    """Age every shockwave by dt; drop those that have reached their lifetime."""
    dt = float(dt)
    survivors = []
    for entry in _active:
        new_age = entry["age"] + dt
        if new_age < entry["lifetime"]:
            entry["age"] = new_age
            survivors.append(entry)
    _active[:] = survivors


def render_data() -> list:
    """Return [{"world_center": (cx,cy,cz), "max_radius": r, "age": a,
    "lifetime": l, "set": pSet}, ...] -- the native set_shockwaves binding's
    py::dict keys (the set_torpedoes / set_hit_vfx idiom) plus the birth set,
    which host_loop._build_shockwave_render_data consumes and strips."""
    return [
        {
            "world_center": entry["center"],
            "set": entry["set"],
            "max_radius": entry["max_radius"],
            "age": entry["age"],
            "lifetime": entry["lifetime"],
        }
        for entry in _active
    ]


def reset() -> None:
    """Clear the registry (mission swap / test teardown)."""
    _active.clear()
