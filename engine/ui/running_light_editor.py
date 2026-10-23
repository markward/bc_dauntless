"""Pure helpers for the SPV running-light editor (no host calls)."""
import math

DEFAULT_COLOR = (1.0, 1.0, 1.0)
DEFAULT_RADIUS = 1.0
DEFAULT_PERIOD = 3.0
DEFAULT_DURATION = 0.5
RADIUS_RANGE = (0.1, 5.0)
PERIOD_RANGE = (0.5, 10.0)
DURATION_MIN = 0.1
STEADY_PERIOD = 3.0


def default_name(taken):
    n = 1
    while "Running Light %d" % n in taken:
        n += 1
    return "Running Light %d" % n


def _first_free(base, taken):
    n = 2
    while "%s %d" % (base, n) in taken:
        n += 1
    return "%s %d" % (base, n)


def mirror_name(name, taken):
    head, sep, rest = name.partition(" ")
    swap = {"Port": "Star", "Star": "Port", "Starboard": "Port"}.get(head)
    if swap is None:
        return _first_free(name, taken)
    swapped = swap + sep + rest
    if swapped in taken:
        return _first_free(swapped, taken)
    return swapped


def _num(value, what):
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a number" % what)
    if not math.isfinite(f):
        raise ValueError("%s must be a finite number" % what)
    return f


def validate_spec(spec, taken):
    name = str(spec.get("name", "")).strip()
    if not name:
        raise ValueError("Name must not be empty")
    # Printable ASCII only: the writers quote names with json.dumps, whose
    # \uXXXX escapes Python 1.5 (stock BC) reads literally -- the game would
    # see a different name than ours.
    if not all(" " <= c <= "~" for c in name):
        raise ValueError("Light names must use plain letters, numbers and "
                         "punctuation")
    if name in taken:
        raise ValueError("A light or other ship property named '%s' already exists" % name)
    position = tuple(_num(v, "Position") for v in spec["position"])
    color = tuple(_num(v, "Colour") for v in spec["color"])
    if len(position) != 3 or len(color) != 3:
        raise ValueError("Position and colour need three components")
    radius = _num(spec["radius"], "Radius")
    duration = _num(spec.get("duration", 0.0), "Duration")
    if "period" in spec and spec["period"] is not None:
        period = _num(spec["period"], "Period")
    else:
        period = STEADY_PERIOD
    if not RADIUS_RANGE[0] <= radius <= RADIUS_RANGE[1]:
        raise ValueError("Radius must be between %g and %g" % RADIUS_RANGE)
    for c in color:
        if not 0.0 <= c <= 1.0:
            raise ValueError("Colour components must be between 0 and 1")
    if duration > 0:
        if not PERIOD_RANGE[0] <= period <= PERIOD_RANGE[1]:
            raise ValueError("Period must be between %g and %g" % PERIOD_RANGE)
        if not DURATION_MIN <= duration <= period:
            raise ValueError("Duration must be between %g and the period"
                             % DURATION_MIN)
    else:
        duration = 0.0
    return {"name": name, "position": position, "color": color,
            "radius": radius, "period": period, "duration": duration}


def spec_from_property(prop):
    p = prop.GetPosition()
    c = prop.GetColor()
    return {"name": prop.GetName(),
            "position": (float(p.x), float(p.y), float(p.z)),
            "color": (float(c.r), float(c.g), float(c.b)),
            "radius": float(prop.GetRadius()),
            "period": float(prop.GetPeriod()),
            "duration": float(prop.GetDuration())}
