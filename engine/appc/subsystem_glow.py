"""Subsystem glow-dimming driver (impulse, sensors, warp).

Pure mapping logic (state classification, edge tracking, dim/flicker mapping,
warp-pod enumeration) plus a thin per-ship orchestration object that registers
glow regions at construction and pushes state each frame. The C++ side owns the
region geometry and the shader attenuation; this module only decides *when* and
*how* a region dims. See
docs/superpowers/specs/2026-06-10-subsystem-glow-dimming-design.md.
"""

import math

HEALTHY = "healthy"
DISABLED = "disabled"
DESTROYED = "destroyed"

# Capsule axis for warp nacelles: ship-forward is model +Y (column-vector).
WARP_AXIS = (0.0, 1.0, 0.0)

# Impulse-glow power/speed scaling (Mark's "sell the movement" pass). Driven by
# the *commanded* impulse throttle (player notch / AI speed setpoint), NOT
# measured velocity, so warp/collision/drift never brighten the engines. All
# tunable here with no rebuild; biased slightly strong (calibrate up then down).
GAIN_IDLE = 1.0      # powered but stopped -> base glow (matches legacy brightness)
GAIN_MAX = 4.0       # full throttle -> ~4x brighter (feeds HDR bloom)
PULSE_FREQ_HZ = 0.4  # slow throb rate
PULSE_AMP = 0.15     # peak pulse fraction at full throttle (scales with speed)


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _is_on(sub) -> bool:
    """Powered? Default True when the sub has no power model (region exists)."""
    if sub is None or not hasattr(sub, "IsOn"):
        return True
    return bool(sub.IsOn())


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
        self._ship = ship
        self._regions = []  # dicts: sub, idx, prev, etime, boost

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

        # Impulse + sensors -> sphere regions (compact hardpoint spots).
        # Only the impulse region is power/speed-brightened ("boost").
        for sub, boost in ((ship.GetImpulseEngineSubsystem(), True),
                           (ship.GetSensorSubsystem(), False)):
            pos = _position_tuple(sub)
            if pos is None:
                continue
            idx = self._r.add_sphere_region(instance_id, pos, _radius(sub))
            if idx < 0:
                continue
            self._regions.append(
                {"sub": sub, "idx": idx, "prev": HEALTHY, "etime": -1.0,
                 "boost": boost})

    def update(self, now: float, throttle_frac=None) -> None:
        """Push dim/edge/flicker each frame; brighten the impulse region by
        commanded throttle (+ slow pulse). `throttle_frac` is the player's notch
        fraction from the host loop; None -> derive from the AI speed setpoint."""
        for reg in self._regions:
            sub = reg["sub"]
            state = glow_state(sub)
            etime = glow_edge(reg["prev"], state, reg["etime"], now)
            dim, flick = dim_and_flicker(state)
            self._r.set_glow_region_dim(self._iid, reg["idx"], dim, etime, flick)
            reg["prev"] = state
            reg["etime"] = etime
            if reg["boost"]:
                powered = (state == HEALTHY) and _is_on(sub)
                frac = (commanded_impulse_frac(self._ship, throttle_frac)
                        if powered else 0.0)
                gain = impulse_gain(frac, now, powered)
                self._r.set_glow_region_gain(self._iid, reg["idx"], gain)
