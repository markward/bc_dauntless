"""Warp-nacelle glow dimming driver.

Pure mapping logic (dim targets, disable-edge tracking, pod enumeration)
plus a thin per-ship orchestration object that registers capsules at
construction and pushes dim state each frame. The C++ side owns the capsule
geometry and the shader attenuation; this module only decides *when* and
*how dark* (see docs/superpowers/specs/2026-06-10-warp-nacelle-glow-dimming-design.md).
"""

# Faint residual so a disabled nacelle reads as a dark ember, not a hole.
DISABLED_RESIDUAL = 0.08

# Capsule axis: ship-forward is model +Y under the column-vector convention.
NACELLE_AXIS = (0.0, 1.0, 0.0)


def dim_target(disabled: bool) -> float:
    """Glow multiplier target for a pod: full when healthy, residual when off."""
    return DISABLED_RESIDUAL if disabled else 1.0


def disable_edge(prev_disabled: bool, now_disabled: bool,
                 prev_time: float, now: float) -> float:
    """Track the game-time of the most recent healthy->disabled edge.

    Returns now on a falling edge, the prior stamp while still disabled, and
    -1.0 while healthy. The shader uses this to time the flicker.
    """
    if not now_disabled:
        return -1.0
    if not prev_disabled:        # falling edge
        return now
    return prev_time             # still disabled — keep original stamp


def warp_pods(warp_subsystem):
    """Return the per-nacelle pods to drive.

    Prefers the aggregator's child pods (Galaxy: Port/Star Warp). If the
    aggregator has no children, treats the aggregator itself as a single pod.
    None -> empty list.
    """
    if warp_subsystem is None:
        return []
    n = warp_subsystem.GetNumChildSubsystems()
    if n > 0:
        return [warp_subsystem.GetChildSubsystem(i) for i in range(n)]
    return [warp_subsystem]


def _is_disabled(pod) -> bool:
    """True when the pod is disabled or destroyed (live condition)."""
    return bool(pod.IsDisabled()) or bool(pod.IsDestroyed())


def _pod_position(pod):
    """Body-frame (x, y, z) of the pod's hardpoint, or None."""
    if not hasattr(pod, "GetPosition"):
        return None
    p = pod.GetPosition()
    if p is None:
        return None
    return (p.GetX(), p.GetY(), p.GetZ())


def _pod_radius(pod) -> float:
    """Hardpoint radius in game units (default 1.0 if unspecified)."""
    if hasattr(pod, "GetRadius"):
        r = pod.GetRadius()
        if r:
            return float(r)
    return 1.0


class WarpGlowController:
    """Per-ship: register capsules once, push dim state each frame.

    Holds (pod, region_index, prev_disabled, disable_time) per nacelle.
    `renderer` is engine.renderer (injected for testability).
    """

    def __init__(self, renderer, instance_id, warp_subsystem):
        self._r = renderer
        self._iid = instance_id
        self._regions = []  # list of dicts: pod, idx, prev_disabled, dtime
        for pod in warp_pods(warp_subsystem):
            pos = _pod_position(pod)
            if pos is None:
                continue
            idx = self._r.compute_nacelle_region(
                instance_id, pos, NACELLE_AXIS, _pod_radius(pod))
            if idx < 0:
                continue
            self._regions.append(
                {"pod": pod, "idx": idx, "prev": False, "dtime": -1.0})

    def update(self, now: float) -> None:
        """Read each pod's live condition and push the dim state for `now`."""
        for reg in self._regions:
            disabled = _is_disabled(reg["pod"])
            dtime = disable_edge(reg["prev"], disabled, reg["dtime"], now)
            self._r.set_nacelle_dim(
                self._iid, reg["idx"], dim_target(disabled), dtime)
            reg["prev"] = disabled
            reg["dtime"] = dtime
