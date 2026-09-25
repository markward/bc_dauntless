"""One way to compare positions across sets (system-frames spec §1).

A set belongs to exactly one FRAME. A mapped region (a set its region module
created, which apply_map marked) is in its star system's frame, anchored at
the region's anchor_gu. Every other set -- Starbase 12, a mission's own set,
the warp transit set, the bridge, QuickBattle, and a set that merely carries a
region's NAME but was never mapped -- is its own one-set frame with a zero
anchor.

Positions stay set-local everywhere BC can see them. Engine code converts only
when it compares, and the primitive is offset_between(set_a, set_b): add it to
a point in b's set-local coordinates to express that point in a's. Same set
-> zero, so same-set results are byte-identical to comparing raw numbers.
Different frames -> None: they never interact. An object in no set has no
frame and interacts with nothing.

No cache: anchor_of() is a dict lookup returning an immutable tuple, and a
set's frame can change exactly once, when the region hook marks it mapped
after BC's Initialize() -- a cache would have to know that; a lookup does not.
"""
from __future__ import annotations

import math
from typing import NamedTuple

_ZERO = (0.0, 0.0, 0.0)


class Frame(NamedTuple):
    key: tuple
    anchor_gu: tuple


def frame_of(pSet):
    from engine.appc.sets import SetClass
    if not isinstance(pSet, SetClass):
        return None
    from engine.systems import region_hooks, resolve
    if region_hooks.is_mapped(pSet):
        name = pSet.GetName()
        anchor = resolve.anchor_of(name)
        system = resolve.system_of(name)
        if anchor is not None and system is not None:
            return Frame(("system", system), tuple(float(c) for c in anchor))
    return Frame(("set", pSet), _ZERO)


def containing_set(obj):
    from engine.core.ids import implements
    if obj is None or not implements(obj, "GetContainingSet"):
        return None
    return obj.GetContainingSet()


def frame_of_object(obj):
    return frame_of(containing_set(obj))


def offset_between(set_a, set_b):
    fa, fb = frame_of(set_a), frame_of(set_b)
    if fa is None or fb is None or fa.key != fb.key:
        return None
    if set_a is set_b:
        return _ZERO
    return tuple(b - a for a, b in zip(fa.anchor_gu, fb.anchor_gu))


def in_view(view, pSet, x, y, z):
    """(x, y, z) of a point in pSet's set-local coordinates, expressed in the
    VIEWED set's -- or None when pSet is not in the viewed frame (a left-behind
    set of another system, an object in no set) or nothing is viewed.

    Same set: the point itself, untouched, so the renderer sees exactly the
    numbers it saw before frames existed."""
    off = offset_between(view, pSet)
    if off is None:
        return None
    if off == _ZERO:
        return (x, y, z)
    return (x + off[0], y + off[1], z + off[2])


# ── The floating render origin (spec §5) ────────────────────────────────────
#
# The renderer draws the Space pass in RENDER space: view coordinates minus
# one render origin -- the exterior camera eye, in the viewed set's
# coordinates, held in double. host_loop sets it once per frame BEFORE any
# feed is built (and pushes it to native, which subtracts it from every
# Space-pass instance's double translation); every Space-pass position then
# crosses into the renderer through to_render. At origin (0,0,0) render space
# IS view space, and to_render hands back in_view's own tuple.

_render_origin = _ZERO


def set_render_origin(view_xyz) -> None:
    global _render_origin
    _render_origin = tuple(float(c) for c in view_xyz)


def render_origin() -> tuple:
    return _render_origin


def reset_render_origin() -> None:
    """Back to (0,0,0): mission swap, tests."""
    global _render_origin
    _render_origin = _ZERO


def view_to_render(p):
    """A point ALREADY in view coordinates, minus the render origin; None
    stays None. The one subtraction every Space-pass feed goes through (via
    to_render when the point is still set-local)."""
    if p is None:
        return None
    o = _render_origin
    if o == _ZERO:
        return p
    return (p[0] - o[0], p[1] - o[1], p[2] - o[2])


def render_to_view(p):
    """Inverse of view_to_render: a render-space point back in view
    coordinates."""
    if p is None:
        return None
    o = _render_origin
    if o == _ZERO:
        return p
    return (p[0] + o[0], p[1] + o[1], p[2] + o[2])


def to_render(view, pSet, x, y, z):
    """(x, y, z) of a point in pSet's set-local coordinates, in RENDER space
    (in_view minus the render origin) -- or None exactly when in_view is None
    (another frame, nothing viewed)."""
    return view_to_render(in_view(view, pSet, x, y, z))


def view_offset(pSet):
    """offset_between(viewing_set(), pSet) when it is a real shift, else
    None: add it to a point in pSet's set-local coordinates to express it in
    VIEW coordinates -- the frame the renderer's instance translations (and
    so the mesh queries) are in. shifted(p, view_offset(s)) goes there,
    shifted(p, view_offset(s), -1) comes back. None for the viewed set itself
    (the point untouched), and for a set outside the viewed frame, whose
    instances host_loop pushes in their own set coordinates."""
    if pSet is None:
        return None
    off = offset_between(viewing_set(), pSet)
    if off is None or off == _ZERO:
        return None
    return off


def shifted(p, off, sign=1.0):
    """TGPoint3 `p` moved by sign*off, as a new TGPoint3 -- or `p` ITSELF when
    `off` is zero or None, so a same-set comparison runs exactly the old
    arithmetic on the same objects.

    `off` is offset_between(set_a, set_b): sign=+1 takes a point in b's
    set-local coordinates into a's, sign=-1 takes a point in a's back to b's
    (a ray trace against b's mesh, a hit point on b's hull)."""
    if off is None or off == _ZERO:
        return p
    from engine.appc.math import TGPoint3
    return TGPoint3(p.x + sign * off[0], p.y + sign * off[1], p.z + sign * off[2])


def _xyz(obj):
    p = obj.GetWorldLocation()
    return (p.x, p.y, p.z)


def local_in(set_a, obj):
    off = offset_between(set_a, containing_set(obj))
    if off is None:
        return None
    x, y, z = _xyz(obj)
    return (x + off[0], y + off[1], z + off[2])


def same_frame(a, b) -> bool:
    return offset_between(containing_set(a), containing_set(b)) is not None


def system_position(obj):
    f = frame_of_object(obj)
    if f is None:
        return None
    x, y, z = _xyz(obj)
    return (f.key, x + f.anchor_gu[0], y + f.anchor_gu[1], z + f.anchor_gu[2])


def system_distance(a, b) -> float:
    pb = local_in(containing_set(a), b)
    if pb is None:
        return math.inf
    return math.dist(_xyz(a), pb)


# "No `view` given": the aggregators that take an optional view keyword
# (host_loop._aggregate_planets, lens_flare.aggregate_lens_flares_for_renderer)
# default to this, so view=None can mean "nothing is viewed" (-> empty).
UNSCOPED = object()


def is_space_scene(pSet) -> bool:
    """True for a set the WORLD scene can show; False for the bridge and for
    interior/comm rooms.

    BC builds the two non-space kinds one way each: the main bridge is a
    BridgeSet (LoadBridge.py: App.BridgeSet_Create(), registered as
    "bridge"), and every other room -- EngineeringSet, DBridgeSet,
    FedOutpostSet_Graff, LiuSet, ... -- comes from MissionLib.SetupBridgeSet,
    which calls SetBackgroundModel (the only SDK caller of it). That is the
    same line host_loop._realize_comm_sets draws when it picks the comm rooms
    out of g_kSetManager (skip "bridge", take sets with a background model).
    """
    from engine.appc.sets import SetClass
    if not isinstance(pSet, SetClass):
        return False
    from engine.appc.bridge_set import BridgeSet
    if isinstance(pSet, BridgeSet):
        return False
    import App
    if App.g_kSetManager._sets.get("bridge") is pSet:
        return False
    return pSet.GetBackgroundModelNIF() is None


def viewing_set():
    """The set the world scene is drawn in: the explicit rendered set when it
    is a space scene (an in-space cutscene), else the player's set.

    Cutscenes end with CameraScriptActions.ChangeRenderedSet("bridge")
    (E6M1, E6M2, E7M1, E8M1, ...) and only a warp arrival resets it, so the
    explicit rendered set is routinely the bridge while the player flies in
    tactical view; that must not blank the world scene."""
    import App
    s = App.g_kSetManager.get_explicit_rendered_set()
    if s is not None and is_space_scene(s):
        return s
    from engine.appc.ship_iter import active_set
    return active_set()
