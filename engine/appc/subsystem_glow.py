"""Subsystem glow-dimming driver (impulse, sensors, warp).

Pure mapping logic (state classification, edge tracking, dim/flicker mapping,
warp-pod enumeration) plus a thin per-ship orchestration object that registers
glow regions at construction and pushes state each frame. The C++ side owns the
region geometry and the shader attenuation; this module only decides *when* and
*how* a region dims. See
docs/superpowers/specs/2026-06-10-subsystem-glow-dimming-design.md.
"""

HEALTHY = "healthy"
DISABLED = "disabled"
DESTROYED = "destroyed"

# Capsule axis for warp nacelles: ship-forward is model +Y (column-vector).
WARP_AXIS = (0.0, 1.0, 0.0)


def glow_state(sub) -> str:
    """Three-state classification. Destroyed dominates disabled; None=healthy."""
    if sub is None:
        return HEALTHY
    if sub.IsDestroyed():
        return DESTROYED
    if sub.IsDisabled():
        return DISABLED
    return HEALTHY


def dim_and_flicker(state) -> tuple:
    """(dim_target, flicker) pushed to the shader for a state.

    healthy   -> (1.0, 0.0)  region is inert (edge_time -1 also set)
    disabled  -> (0.0, 1.0)  continuous flicker (shader ignores dim_target)
    destroyed -> (0.0, 0.0)  blow-out then settle to 0 (off)
    """
    if state == DISABLED:
        return (0.0, 1.0)
    if state == DESTROYED:
        return (0.0, 0.0)
    return (1.0, 0.0)


def glow_edge(prev_state, cur_state, prev_time, now) -> float:
    """Game-time of the most recent state-change edge.

    -1.0 while healthy; `now` whenever the state changes to a different
    non-healthy state (healthy->disabled, healthy->destroyed, disabled->
    destroyed); otherwise keep prev_time (same non-healthy state persists).
    """
    if cur_state == HEALTHY:
        return -1.0
    if cur_state != prev_state:
        return now
    return prev_time


def warp_pods(warp_subsystem):
    """Per-nacelle pods to drive: children, else [aggregator], else []."""
    if warp_subsystem is None:
        return []
    n = warp_subsystem.GetNumChildSubsystems()
    if n > 0:
        return [warp_subsystem.GetChildSubsystem(i) for i in range(n)]
    return [warp_subsystem]


def _position_tuple(sub):
    """Body-frame (x, y, z) of a subsystem's hardpoint, or None."""
    if sub is None or not hasattr(sub, "GetPosition"):
        return None
    p = sub.GetPosition()
    if p is None:
        return None
    return (p.GetX(), p.GetY(), p.GetZ())


def _radius(sub) -> float:
    """Hardpoint radius in game units (default 1.0 if unspecified)."""
    if hasattr(sub, "GetRadius"):
        r = sub.GetRadius()
        if r:
            return float(r)
    return 1.0


class ShipGlowController:
    """Per-ship: register glow regions once, push state each frame.

    Capsule region per warp pod (elongated nacelles); sphere region for the
    impulse engine and the sensor array (compact spots). Holds
    (subsystem, region_index, prev_state, edge_time) per region. `renderer` is
    engine.renderer (injected for testability).
    """

    def __init__(self, renderer, instance_id, ship):
        self._r = renderer
        self._iid = instance_id
        self._regions = []  # dicts: sub, idx, prev, etime

        # Warp nacelles -> capsule regions (fit the elongated shape).
        for pod in warp_pods(ship.GetWarpEngineSubsystem()):
            pos = _position_tuple(pod)
            if pos is None:
                continue
            idx = self._r.compute_capsule_region(
                instance_id, pos, WARP_AXIS, _radius(pod))
            if idx < 0:
                continue
            self._regions.append(
                {"sub": pod, "idx": idx, "prev": HEALTHY, "etime": -1.0})

        # Impulse + sensors -> sphere regions (compact hardpoint spots).
        for sub in (ship.GetImpulseEngineSubsystem(),
                    ship.GetSensorSubsystem()):
            pos = _position_tuple(sub)
            if pos is None:
                continue
            idx = self._r.add_sphere_region(instance_id, pos, _radius(sub))
            if idx < 0:
                continue
            self._regions.append(
                {"sub": sub, "idx": idx, "prev": HEALTHY, "etime": -1.0})

    def update(self, now: float) -> None:
        """Read each region's live state and push dim/edge/flicker for `now`."""
        for reg in self._regions:
            state = glow_state(reg["sub"])
            etime = glow_edge(reg["prev"], state, reg["etime"], now)
            dim, flick = dim_and_flicker(state)
            self._r.set_glow_region_dim(self._iid, reg["idx"], dim, etime, flick)
            reg["prev"] = state
            reg["etime"] = etime
