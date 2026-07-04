"""Subsystem glow-dimming driver (impulse, sensors, warp).

Pure mapping logic (state classification, edge tracking, dim/flicker mapping,
warp-pod enumeration) plus a thin per-ship orchestration object that registers
glow regions at construction and pushes state each frame. The C++ side owns the
region geometry and the shader attenuation; this module only decides *when* and
*how* a region dims. See
docs/superpowers/specs/2026-06-10-subsystem-glow-dimming-design.md.

Impulse glow volumes are driven by BAKED hardpoint data: each impulse pod's
property template carries indexed GlowRegion* fields (authored in hardpoint
files or engine/appc/hardpoint_overrides.py — see README "Information for
modders"). All state VFX (dim, flicker, throttle gain) operate on whatever
regions the hardpoint defines. The hardpoint is the single source of truth: a
pod that bakes nothing gets no impulse glow VFX at all (there is no in-engine
derivation fallback).
"""

import logging
import math

from engine.appc.properties import read_indexed_setter_args

_log = logging.getLogger(__name__)

HEALTHY = "healthy"
DISABLED = "disabled"
DESTROYED = "destroyed"

# Capsule axis for warp nacelles: ship-forward is model +Y (column-vector).
WARP_AXIS = (0.0, 1.0, 0.0)

# Impulse exhaust faces point aft = model -Y. The shader gates the impulse
# brightening to faces whose normal points this way, so only the aft engine
# faces glow (not the whole sphere around the hardpoint). The volume itself
# comes from the hardpoint's baked GlowRegion* fields (no in-engine default).
IMPULSE_AFT_AXIS = (0.0, -1.0, 0.0)

# Impulse-glow power/speed scaling (Mark's "sell the movement" pass). Driven by
# the *commanded* impulse throttle (player notch / AI speed setpoint), NOT
# measured velocity, so warp/collision/drift never brighten the engines. All
# tunable here with no rebuild; biased slightly strong (calibrate up then down).
GAIN_IDLE = 1.0      # powered but stopped -> base glow (matches legacy brightness)
GAIN_MAX = 2.0       # full throttle -> 2x brighter (feeds HDR bloom)
PULSE_FREQ_HZ = 0.4  # slow throb rate
PULSE_AMP = 0.15     # peak pulse fraction at full throttle (scales with speed)
# Time constant (s) for easing the commanded throttle, so stepping between
# impulse notches ramps the glow smoothly instead of jumping. Larger = slower.
IMPULSE_EASE_TAU = 0.35


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def commanded_impulse_frac(ship, throttle_override=None) -> float:
    """Commanded impulse throttle as a 0..1 fraction.

    `throttle_override` (the player's notch fraction, supplied by the host loop)
    wins when given. Otherwise derive from the AI speed setpoint
    (`GetSpeedSetpoint()[0]`) over the impulse subsystem's max speed. Returns 0.0
    when there is no command or no usable max speed (never divides by zero). This
    is the *commanded* throttle, so it excludes warp/collision/drift velocity.
    """
    if throttle_override is not None:
        return _clamp01(float(throttle_override))
    sp = ship.GetSpeedSetpoint() if hasattr(ship, "GetSpeedSetpoint") else None
    if not sp:
        return 0.0
    commanded = abs(float(sp[0]))
    ies = (ship.GetImpulseEngineSubsystem()
           if hasattr(ship, "GetImpulseEngineSubsystem") else None)
    max_speed = float(ies.GetMaxSpeed()) if ies is not None else 0.0
    if max_speed <= 0.0:
        return 0.0
    return _clamp01(commanded / max_speed)


def impulse_gain(frac: float, now: float, powered: bool) -> float:
    """Glow brightness gain for the impulse region.

    Unpowered / disabled / destroyed -> 1.0 (no boost; the dim state machine owns
    those). Powered -> base ramps GAIN_IDLE..GAIN_MAX with commanded throttle,
    times a slow pulse whose amplitude grows with speed (steady at rest).
    """
    if not powered:
        return 1.0
    frac = _clamp01(frac)
    base = GAIN_IDLE + (GAIN_MAX - GAIN_IDLE) * frac
    amp = PULSE_AMP * frac
    pulse = 1.0 + amp * math.sin(2.0 * math.pi * PULSE_FREQ_HZ * now)
    return base * pulse


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


def impulse_engines(impulse_subsystem):
    """Per-engine pods to glow-boost.

    The parent `ImpulseEngineSubsystem` is a *category* node sitting near the
    saucer centre; the real engines (Port/Star/Center) are attached as its
    children (ships.py SetupProperties Pass 5), exactly like warp nacelles.
    Return the children when present, else the aggregator itself, else [].
    """
    if impulse_subsystem is None:
        return []
    n = impulse_subsystem.GetNumChildSubsystems()
    if n > 0:
        return [impulse_subsystem.GetChildSubsystem(i) for i in range(n)]
    return [impulse_subsystem]


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


def baked_glow_regions(prop) -> list:
    """Raw baked GlowRegion entries from a property template's data-bag.

    Indexed 0..N; iteration stops at the first index with no
    ``SetGlowRegionShape(i, ...)`` call. Returns [] for None/unbaked props.
    """
    if prop is None:
        return []
    out = []
    i = 0
    while True:
        shape = read_indexed_setter_args(prop, "GlowRegionShape", i)
        if shape is None:
            return out
        out.append({
            "index": i,
            "shape": shape[0],
            "position": read_indexed_setter_args(prop, "GlowRegionPosition", i),
            "axis": read_indexed_setter_args(prop, "GlowRegionAxis", i),
            "radius": read_indexed_setter_args(prop, "GlowRegionRadius", i),
            "extent": read_indexed_setter_args(prop, "GlowRegionExtent", i),
            "scale": read_indexed_setter_args(prop, "GlowRegionScale", i),
        })
        i += 1


def resolve_baked_region(raw: dict, default_pos):
    """Normalize one raw baked entry to a renderer op, or None if unusable.

    Ops: ('sphere', center, radius)
         ('cylinder', center, unit_axis, radius, length)  # centre pre-shifted
                                                          # by the aft extent
    Position defaults to the pod's hardpoint position. Shape names are
    case-insensitive. 'Box' is authored-valid but has no renderer shape yet —
    treated as unusable (caller warns + falls back) until Box rendering lands.
    """
    shape = str(raw.get("shape", "")).lower()
    pos = raw.get("position") or default_pos
    if pos is None or len(pos) != 3:
        return None
    if shape == "sphere":
        r = raw.get("radius")
        if not r or float(r[0]) <= 0.0:
            return None
        return ("sphere", tuple(pos), float(r[0]))
    if shape == "cylinder":
        axis, r, extent = raw.get("axis"), raw.get("radius"), raw.get("extent")
        if axis is None or len(axis) != 3 or not r or float(r[0]) <= 0.0 \
                or extent is None or len(extent) != 2:
            return None
        aft, fore = float(extent[0]), float(extent[1])
        norm = math.sqrt(sum(float(a) * float(a) for a in axis))
        if fore <= aft or norm <= 0.0:
            return None
        u = tuple(float(a) / norm for a in axis)
        center = tuple(float(p) + u[k] * aft for k, p in enumerate(pos))
        return ("cylinder", center, u, float(r[0]), fore - aft)
    return None


def baked_region_ops(prop, default_pos, pod_name="") -> list:
    """Resolved renderer ops for a property's baked regions.

    Unusable entries (malformed, unsupported shape, or values that don't even
    coerce to numbers — hardpoints are modder-supplied) are dropped with one
    warning each and can never raise; an empty result simply means no glow
    VFX for this pod.
    """
    ops = []
    for raw in baked_glow_regions(prop):
        try:
            op = resolve_baked_region(raw, default_pos)
        except Exception:  # noqa: BLE001 - bad authored values must not raise
            op = None
        if op is None:
            _log.warning(
                "glow region %s[%d] (%r) skipped: malformed or unsupported "
                "shape", pod_name, raw["index"], raw.get("shape"))
            continue
        ops.append(op)
    return ops


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
        self._ship = ship
        self._regions = []  # dicts: sub, idx, prev, etime, boost
        self._eased_frac = 0.0    # smoothed commanded throttle (0..1)
        self._last_now = None     # game-time of the previous update (for dt)

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
                {"sub": pod, "idx": idx, "prev": HEALTHY, "etime": -1.0,
                 "boost": False})

        # Impulse engines -> regions BAKED in the pod's hardpoint property
        # (GlowRegion* fields; see baked_region_ops). The hardpoint is the
        # single source of truth: a pod that bakes nothing gets NO impulse
        # glow VFX (no in-engine derivation). Every baked region on an
        # impulse pod is a boost region: dim/flicker AND the throttle gain
        # all drive the authored volume. The shader still gates the gain to
        # aft-facing faces (IMPULSE_AFT_AXIS) so only the exhaust faces
        # brighten. Sensor array -> a plain (non-boost) sphere.
        for pod in impulse_engines(ship.GetImpulseEngineSubsystem()):
            pos = _position_tuple(pod)
            if pos is None:
                continue
            prop = pod.GetProperty() if hasattr(pod, "GetProperty") else None
            for op in baked_region_ops(prop, pos,
                                       getattr(pod, "GetName", str)()):
                if op[0] == "sphere":
                    idx = self._r.add_sphere_region(instance_id, op[1], op[2])
                else:  # cylinder
                    idx = self._r.add_cylinder_region(
                        instance_id, op[1], op[2], op[3], op[4])
                if idx < 0:
                    continue
                self._regions.append(
                    {"sub": pod, "idx": idx, "prev": HEALTHY,
                     "etime": -1.0, "boost": True})

        _sensor = ship.GetSensorSubsystem()
        _spos = _position_tuple(_sensor)
        if _spos is not None:
            _sidx = self._r.add_sphere_region(instance_id, _spos, _radius(_sensor))
            if _sidx >= 0:
                self._regions.append(
                    {"sub": _sensor, "idx": _sidx, "prev": HEALTHY,
                     "etime": -1.0, "boost": False})

    def update(self, now: float, throttle_frac=None) -> None:
        """Push dim/edge/flicker each frame; brighten the impulse region by the
        (time-eased) commanded throttle + slow pulse. `throttle_frac` is the
        player's notch fraction from the host loop; None -> derive from the AI
        speed setpoint."""
        # Ease the commanded throttle so stepping between impulse notches ramps
        # the glow smoothly rather than jumping. "Powered up" = commanded
        # throttle, NOT the subsystem IsOn() (ImpulseEngineSubsystem never gets
        # turned on -> IsOn() is always False).
        target = commanded_impulse_frac(self._ship, throttle_frac)
        if self._last_now is None or now < self._last_now:
            self._eased_frac = target   # snap on first frame / after a reset
        else:
            dt = now - self._last_now
            alpha = (1.0 - math.exp(-dt / IMPULSE_EASE_TAU)
                     if IMPULSE_EASE_TAU > 0.0 else 1.0)
            self._eased_frac += (target - self._eased_frac) * alpha
        self._last_now = now

        for reg in self._regions:
            sub = reg["sub"]
            state = glow_state(sub)
            etime = glow_edge(reg["prev"], state, reg["etime"], now)
            dim, flick = dim_and_flicker(state)
            self._r.set_glow_region_dim(self._iid, reg["idx"], dim, etime, flick)
            reg["prev"] = state
            reg["etime"] = etime
            if reg["boost"]:
                # Gate only on health; the dim state machine owns disabled/
                # destroyed. Eased frac drives brightness: 0 at full-stop ->
                # GAIN_IDLE (no visible change), up to GAIN_MAX at full throttle.
                active = (state == HEALTHY)
                frac = self._eased_frac if active else 0.0
                gain = impulse_gain(frac, now, active)
                self._r.set_glow_region_gain(self._iid, reg["idx"], gain,
                                             IMPULSE_AFT_AXIS)
