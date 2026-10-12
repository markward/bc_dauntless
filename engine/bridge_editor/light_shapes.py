"""Lights with size (spec 2026-10-08-bridge-emitters §16.2): an object's
front rectangle, and the strip / panel rectangles cut from it. Pure Python;
the geometry comes from host_io.bridge_mesh_geometry. Nothing here is
stored: the file holds only parameters, so a light follows its object
through mesh fixes and shape-diff edits."""
import math
from dataclasses import dataclass
from typing import Optional, Tuple

Vec = Tuple[float, float, float]

ROOM_UP: Vec = (0.0, 0.0, 1.0)      # renderer::kBridgeUp
STRIP_WIDTH = 0.5                   # bridge units; an engine constant, not edited
NO_FACING = 0.05                    # normal sum below this x area: a closed shape
VERTICAL_DEG = 25.0                 # facing this close to +-Z: a ceiling / floor piece


def _add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _mul(a, k): return (a[0] * k, a[1] * k, a[2] * k)
def _dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _len(a): return math.sqrt(_dot(a, a))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a) -> Optional[Vec]:
    n = _len(a)
    return _mul(a, 1.0 / n) if n > 1e-9 else None


def _horizontal(a) -> Optional[Vec]:
    return _unit((a[0], a[1], 0.0))


@dataclass(frozen=True)
class Frame:
    right: Vec
    up: Vec
    facing: Vec
    centre: Vec      # the object's box centre, world
    half: Vec        # half-extents along (right, up, facing)


@dataclass(frozen=True)
class Rect:
    centre: Vec
    half_u: Vec
    half_v: Vec      # cross(half_u, half_v) points where it emits

    @property
    def normal(self) -> Vec:
        return _unit(_cross(self.half_u, self.half_v)) or (0.0, 0.0, 0.0)


def frame(vertices, normal_sum, area, eye) -> Optional[Frame]:
    """The object's frame: facing = its area-weighted normal; up = room up
    without its facing part; right = up x facing (the viewer's right, seen
    from the front). A closed shape (normals cancel) faces the eye; a piece
    within VERTICAL_DEG of +-Z tops on its edge farther from the eye."""
    if not vertices:
        return None
    lo = [min(v[i] for v in vertices) for i in range(3)]
    hi = [max(v[i] for v in vertices) for i in range(3)]
    mid = tuple((lo[i] + hi[i]) / 2.0 for i in range(3))
    n = tuple(float(c) for c in normal_sum)
    if area > 0.0 and _len(n) >= NO_FACING * area:
        facing = _unit(n)
    else:
        facing = _horizontal(_sub(eye, mid)) or (0.0, -1.0, 0.0)
    if abs(_dot(facing, ROOM_UP)) > math.cos(math.radians(VERTICAL_DEG)):
        hint = _horizontal(_sub(mid, eye)) or (0.0, 1.0, 0.0)
    else:
        hint = ROOM_UP
    up = _unit(_sub(hint, _mul(facing, _dot(hint, facing))))
    if up is None:          # cannot happen for the hints above; keep a frame anyway
        up = _unit(_cross(facing, (1.0, 0.0, 0.0))) or (0.0, 1.0, 0.0)
    right = _cross(up, facing)
    axes = (right, up, facing)
    proj = [[_dot(v, a) for a in axes] for v in vertices]
    plo = [min(p[i] for p in proj) for i in range(3)]
    phi = [max(p[i] for p in proj) for i in range(3)]
    centre = (0.0, 0.0, 0.0)
    for i in range(3):
        centre = _add(centre, _mul(axes[i], (plo[i] + phi[i]) / 2.0))
    half = tuple((phi[i] - plo[i]) / 2.0 for i in range(3))
    return Frame(right, up, facing, centre, half)


def _front(fr) -> Vec:
    return _add(fr.centre, _mul(fr.facing, fr.half[2]))


def strip_rect(fr, edge, start=0.0, end=1.0, offset=0.0) -> Rect:
    """That edge of the front rectangle, cut to [start, end] (0 = the left /
    bottom end), moved out along facing by `offset`, STRIP_WIDTH wide. It
    faces the box centre with its along-edge part removed: perpendicular to
    the edge, toward the centre on average."""
    hr, hu, _hf = fr.half
    if edge in ("top", "bottom"):
        axis, span = fr.right, hr
        across = _mul(fr.up, hu if edge == "top" else -hu)
    else:
        axis, span = fr.up, hu
        across = _mul(fr.right, hr if edge == "right" else -hr)
    mid = (start + end) / 2.0
    c = _add(_add(_front(fr), across), _mul(axis, span * (2.0 * mid - 1.0)))
    c = _add(c, _mul(fr.facing, offset))
    to_centre = _sub(fr.centre, c)
    n = _unit(_sub(to_centre, _mul(axis, _dot(to_centre, axis)))) or fr.facing
    width = _cross(n, axis)
    return Rect(c, _mul(axis, span * (end - start)), _mul(width, STRIP_WIDTH / 2.0))


def panel_rect(fr, x=(0.0, 1.0), y=(0.0, 1.0), offset=0.0) -> Rect:
    """The x by y span of the front rectangle (0 = left / bottom), moved out
    along facing by `offset`, facing out."""
    hr, hu, hf = fr.half
    c = _add(fr.centre, _mul(fr.facing, hf + offset))
    c = _add(c, _mul(fr.right, hr * (x[0] + x[1] - 1.0)))
    c = _add(c, _mul(fr.up, hu * (y[0] + y[1] - 1.0)))
    return Rect(c, _mul(fr.right, hr * (x[1] - x[0])), _mul(fr.up, hu * (y[1] - y[0])))


def light_rect(light, fr) -> Rect:
    off = float(light.get("offset", 0.0))
    if light.get("shape") == "strip":
        return strip_rect(fr, light["edge"], float(light.get("start", 0.0)),
                          float(light.get("end", 1.0)), off)
    x = light.get("x", (0.0, 1.0))
    y = light.get("y", (0.0, 1.0))
    return panel_rect(fr, (float(x[0]), float(x[1])), (float(y[0]), float(y[1])), off)
