"""Ship running lights: BlinkingLightProperty -> render specs + per-frame level.

Pure (no host calls). The host loop sends `lights_for` once per ship at spawn
and `level_for` every frame; the C++ RunningLightPass does placement and blink.
Spec: docs/superpowers/specs/2026-10-14-ship-running-lights-design.md. Read its
§3 before "fixing" any behaviour here back toward BC: BC's own timing is a
~9 Hz flicker and its statics are invisible, and both departures are rulings.
"""
import zlib
from dataclasses import dataclass


@dataclass(frozen=True)
class RunningLightSpec:
    pos: tuple        # body frame, GU, unscaled (emitter-light convention)
    rgb: tuple        # colour alpha is dropped, as BC does
    size: float       # the property's Radius; scaled by the size dial in C++
    period: float
    duration: float   # <= 0 means a static (always-on) light

    def as_tuple(self) -> tuple:
        return (self.pos[0], self.pos[1], self.pos[2],
                self.rgb[0], self.rgb[1], self.rgb[2],
                self.size, self.period, self.duration)


def lights_for(ship) -> list:
    """The ship's running lights in property-set order. A light that was never
    placed (no SetPosition) is skipped rather than drawn at the hull origin."""
    import App
    get_set = getattr(ship, "GetPropertySet", None)
    pset = get_set() if get_set is not None else None
    if pset is None:
        return []
    out = []
    for prop in pset.GetPropertiesByType(App.CT_BLINKING_LIGHT_PROPERTY):
        pos = prop.GetPosition()
        if pos is None:
            continue
        c = prop.GetColor()
        out.append(RunningLightSpec(
            pos=(float(pos.x), float(pos.y), float(pos.z)),
            rgb=(float(c.r), float(c.g), float(c.b)),
            size=float(prop.GetRadius()),
            period=float(prop.GetPeriod()),
            duration=float(prop.GetDuration())))
    return out


def phase_for(ship) -> float:
    """Seconds in [0, 1000), stable per ship name. One ship's blinkers share
    it (they flash together); the C++ side takes it modulo each period."""
    name = str(ship.GetName() or "")
    return (zlib.crc32(name.encode("utf-8")) / 2.0 ** 32) * 1000.0


def level_for(ship, cloak_frac: float, now: float, phase: float) -> float:
    """Brightness in [0, 1]: alive x power-plant state x (1 - cloak)."""
    if ship.IsDying() or ship.IsDead():
        return 0.0
    from engine.appc import subsystem_glow
    from engine.appc.light_emitters import emitter_flicker
    get_power = getattr(ship, "GetPowerSubsystem", None)
    power = get_power() if get_power is not None else None
    state = subsystem_glow.glow_state(power)
    if state == subsystem_glow.DESTROYED:
        return 0.0
    level = emitter_flicker(now, phase) if state == subsystem_glow.DISABLED else 1.0
    frac = min(1.0, max(0.0, float(cloak_frac)))
    return level * (1.0 - frac)
