"""Characterisation suite: every SPV editing tool x every kind of edit target,
pinned against the code BEFORE the edit-target refactor (plan
docs/superpowers/plans/2026-09-29-spv-edit-target-refactor.md, Task 1; spec
docs/superpowers/specs/2026-09-29-spv-edit-target-refactor-design.md S2).

Every expected value below is a LITERAL, recorded once from the pre-refactor
code. Nothing here recomputes an expectation through the code under test: a
scenario runs the product, `_r` rounds what it observed to 9 decimals, and
the result is compared with the literal. If a later task changes one of these
literals, that is a behaviour change and must be recorded as one -- the only
planned ones are the decal Copy/Paste/Mirror gaps pinned here (Task 6).

One panel carries a target of every kind at once, so cross-kind Copy/Paste
and Pipette run between real targets on the same panel:

    descriptor 0  "Sub"          subsystem mount (sphere)
    descriptor 1  "SphereLight"  light volume, Sphere
    descriptor 2  "CylLight"     light volume, Cylinder
    descriptor 3  "BoxLight"     light volume, Box
    descriptor 4  "Emitters"     emitters j=0 point, j=1 strip, j=2 cone
    part "wing"                  Anchor + Red Alert / Warp Transformations
    decal "top"                  one placement in the (active) Decals pane

The Decals pane is entered for EVERY case, so a decal is always selectable
(it is only selectable while the pane is active). No mount/part code path
reads `_decals_active` except through `_decal_target()`, which is None unless
a decal is selected.
"""
import dataclasses
import json
import math

import pytest

from engine.appc.math import TGMatrix3, TGPoint3
from engine.ui import decal_editor
from engine.ui import ship_property_viewer as spv
from engine.ui.ship_property_viewer import OrbitCamera, gizmo_length
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel

UNRIGGED_LEAF = "spvcharacterisationtest"

CASES = ["subsystem", "light_sphere", "light_cylinder", "light_box",
         "emitter_point", "emitter_strip", "emitter_cone",
         "part_anchor", "part_pose", "decal"]

# ── the fixture ship ─────────────────────────────────────────────────────────

_BASE_REGION = {
    "position": (0.0, 0.0, 0.0), "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
    "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25),
    "orientation": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
}


def _region(**kw):
    r = dict(_BASE_REGION)
    r.update(kw)
    return r


def _descriptor(name, pos, radius, light_region=None, emitters=()):
    return {
        "name": name, "kind": "subsystem", "icon_id": 1,
        "properties": {"position": pos, "radius": radius},
        "world_pos": pos, "parent_index": None,
        "light": light_region is not None,
        "light_region": light_region or _region(shape="Sphere"),
        "emitters": [dict(e) for e in emitters],
    }


_DESCRIPTORS = [
    _descriptor("Sub", (0.5, 1.0, -0.25), 0.3),
    _descriptor("SphereLight", (0.0, 0.0, 0.0), 0.4, _region(
        shape="Sphere", position=(0.2, -0.4, 0.1), radius=(0.35,))),
    _descriptor("CylLight", (0.0, 0.0, 0.0), 0.4, _region(
        shape="Cylinder", position=(-0.3, 0.6, 0.2), axis=(0.6, -0.8, 0.0),
        radius=(0.2,), extent=(-0.5, 1.5))),
    _descriptor("BoxLight", (0.0, 0.0, 0.0), 0.4, _region(
        shape="Box", position=(0.7, -0.2, 0.4), scale=(0.3, 0.5, 0.2),
        orientation=((0.6, 0.8, 0.0), (0.0, 0.0, 1.0)))),
    _descriptor("Emitters", (0.0, 0.0, 0.0), 0.4, emitters=[
        {"kind": "point", "position": (0.1, 0.2, 0.3), "axis": (0.0, -1.0, 0.0),
         "length": 1.0, "radius": 0.4, "color": (1.0, 0.5, 0.25),
         "intensity": 2.0},
        {"kind": "strip", "position": (-0.5, 0.25, 0.0),
         "axis": (0.28, -0.96, 0.0), "length": 1.5, "radius": 0.15,
         "color": (0.2, 0.4, 1.0), "intensity": 1.5},
        {"kind": "cone", "position": (0.3, -0.6, 0.15),
         "axis": (-0.8, -0.6, 0.0), "up": (0.0, 0.0, 1.0), "length": 0.8,
         "radius": 0.25, "radius_y": 0.15, "color": (1.0, 1.0, 0.0),
         "intensity": 3.0},
    ]),
]

_PART_NODES = [{"name": "wing", "parent": "Scene Root", "candidate": True,
                "bounds_min": (-1.0, -0.5, -0.5), "bounds_max": (-0.1, 0.5, 0.5)}]

_WING = {"anchor": (-0.4, 0.2, 0.1), "transition": 2.0,
         "poses": {"red": (0.05, 0.0, -0.02, 10.0, 5.0, -15.0),
                   "warp": (0.0, 0.1, 0.0, 0.0, 20.0, 0.0)},
         "break": None}

# A chirality-OK placement ((u x v) . n < 0), 2:1 like the default aspect.
_TOP = decal_editor.Placement(
    name="top", origin=(-20.0, 30.0, 50.0), u_axis=(40.0, 0.0, 0.0),
    v_axis=(0.0, -20.0, 0.0), normal=(0.0, 0.0, 1.0), depth=2.0,
    shape="amb saucer:0")

_SELECT = {
    "subsystem": "select_pin:0",
    "light_sphere": "select_light:1",
    "light_cylinder": "select_light:2",
    "light_box": "select_light:3",
    "emitter_point": 'select_emitter:{"i": 4, "j": 0}',
    "emitter_strip": 'select_emitter:{"i": 4, "j": 1}',
    "emitter_cone": 'select_emitter:{"i": 4, "j": 2}',
    "part_anchor": 'part/select_node:{"name": "wing", "kind": "anchor"}',
    "part_pose": 'part/select_node:{"name": "wing", "kind": "red"}',
    "decal": "decal-select:top",
}


class _FakeSubsystem:
    def GetPosition(self):
        return (0.0, 0.0, 0.0)

    def GetProperty(self):
        return None

    def GetNumChildSubsystems(self):
        return 0


class _Ship:
    """An unrigged hull at the world origin, identity rotation: world ==
    body for every hardpoint gizmo."""

    def __init__(self):
        self._hull = _FakeSubsystem()
        self._articulation_leaf = UNRIGGED_LEAF
        self._articulation_poses = {}

    def GetHull(self):
        return self._hull

    def GetSensorSubsystem(self):
        return self._hull

    def GetWorldLocation(self):
        return TGPoint3(0.0, 0.0, 0.0)

    def GetWorldRotation(self):
        return TGMatrix3()


@pytest.fixture
def make_panel(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(
        mod, "build_descriptors",
        lambda ship: [dict(d, emitters=[dict(e) for e in d["emitters"]],
                           properties=dict(d["properties"]))
                      for d in _DESCRIPTORS])
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda s: UNRIGGED_LEAF)

    def _make():
        ship = _Ship()
        p = ShipPropertyViewerPanel(ship_getter=lambda: ship)
        p.open()
        p._model_part_nodes = [dict(n) for n in _PART_NODES]
        p._saved_part["wing"] = dict(_WING, poses=dict(_WING["poses"]))
        p.camera = OrbitCamera((0.0, 0.0, 0.0), 10.0, 0.0, 0.0)
        assert p.dispatch_event("decal-pane") is True
        p._decal_working = [_TOP]
        p._decal_baseline = [_TOP]
        p._undo_stack.clear()
        return p
    return _make


# ── helpers ──────────────────────────────────────────────────────────────────

def _r(v):
    """Observed value -> comparable literal: floats rounded to 9 places,
    sequences to tuples, a Placement to its field dict."""
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        return round(v, 9) + 0.0
    if dataclasses.is_dataclass(v):
        return _r(dataclasses.asdict(v))
    if isinstance(v, dict):
        return {k: _r(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return tuple(_r(x) for x in v)
    raise TypeError(type(v))


def _select(p, case):
    assert p.dispatch_event(_SELECT[case]) is True, case


def _use_tool(p, tool):
    """set_tool TOGGLES, so only dispatch it when the tool is not already
    active. (Selecting a part Anchor/State node switches to Move itself.)"""
    if p.active_tool != tool:
        assert p.dispatch_event("set_tool:" + tool) is True


def _staged(p, case):
    """The effective (staged, else saved, else baked) value the case edits."""
    if case == "subsystem":
        return _r({"position": p._effective_pos(0),
                   "radius": p._effective_radius(0, 0.3)})
    if case.startswith("light_"):
        return _r(p._effective_light(
            {"light_sphere": 1, "light_cylinder": 2, "light_box": 3}[case]))
    if case.startswith("emitter_"):
        return _r(p._effective_emitter(
            4, {"emitter_point": 0, "emitter_strip": 1, "emitter_cone": 2}[case]))
    if case.startswith("part_"):
        return _r(p._effective_part("wing"))
    return _r(p._decal_working[p._decal_index("top")])


def _diff(before, after):
    """What changed from `before` to `after` (two `_staged` dicts): the new
    value of every changed key, recursing into nested dicts (a part's
    `poses`), so a literal names only what an action touched."""
    out = {}
    for k in sorted(set(before) | set(after)):
        b, a = before.get(k), after.get(k)
        if b != a:
            out[k] = (_diff(b, a) if isinstance(b, dict) and isinstance(a, dict)
                      else a)
    return out


def _changed_fields(before, after):
    return tuple(sorted(k for k in set(before) | set(after)
                        if before.get(k) != after.get(k)))


def _payloads(p, case):
    """(transform_coords, rotate_values, scale_values), each under its tool."""
    out = []
    for tool, fn in (("transform", p.transform_coords),
                     ("rotate", p.rotate_values),
                     ("scale", p.scale_values)):
        _use_tool(p, tool)
        out.append(_r(fn()))
    return tuple(out)


# ── scenarios (each runs the product; the tests compare with literals) ────────

def _scenario_payloads(make_panel, case):
    p = make_panel()
    _select(p, case)
    return _payloads(p, case)


def _scenario_action(make_panel, case, tool, action):
    """Select `case`, activate `tool`, dispatch `action`: (returned, what
    changed in the staged value, undo entries pushed)."""
    p = make_panel()
    _select(p, case)
    _use_tool(p, tool)
    before, n = _staged(p, case), len(p._undo_stack)
    ok = p.dispatch_event(action)
    return (ok, _diff(before, _staged(p, case)), len(p._undo_stack) - n)


def _scenario_clip_tag(make_panel, case, tool, verb):
    p = make_panel()
    _select(p, case)
    _use_tool(p, tool)
    p.dispatch_event(verb + "_copy")
    clip = {"coord": p._coord_clipboard, "scale": p._scale_clipboard,
            "rotate": p._rotate_clipboard}[verb]
    return None if clip is None else clip[0]


def _scenario_paste_matrix(make_panel, tool, verb):
    """{src: the targets (other cases) whose staged value a Paste of src's
    Copy changes}. A target missing from the tuple refused the paste."""
    applied = {src: () for src in CASES}
    for src in CASES:
        for tgt in CASES:
            if src == tgt:
                continue
            p = make_panel()
            _select(p, src)
            _use_tool(p, tool)
            p.dispatch_event(verb + "_copy")
            _select(p, tgt)
            _use_tool(p, tool)
            before = _staged(p, tgt)
            p.dispatch_event(verb + "_paste")
            if _staged(p, tgt) != before:
                applied[src] += (tgt,)
    return applied


def _scenario_pipette(make_panel, tgt):
    """(armed, {src: (changed fields of tgt, still armed)})."""
    p = make_panel()
    _select(p, tgt)
    p.dispatch_event("pipette")
    armed = p._pipette_armed
    picks = {}
    for src in CASES:
        if src == tgt:
            continue
        p = make_panel()
        _select(p, tgt)
        p.dispatch_event("pipette")
        before = _staged(p, tgt)
        p.dispatch_event(_SELECT[src])
        picks[src] = (_changed_fields(before, _staged(p, tgt)),
                      p._pipette_armed)
    return armed, picks


def _scenario_drag(make_panel, case, kind):
    """One gizmo drag through the panel's own begin/apply/end: (what changed
    in the staged value, undo entries pushed)."""
    p = make_panel()
    _select(p, case)
    before, n = _staged(p, case), len(p._undo_stack)
    if kind == "axis":
        _use_tool(p, "transform")
        p._begin_axis_drag(0, 1.0)
        p._apply_axis_drag(1.25)
    elif kind == "scale":
        _use_tool(p, "scale")
        L = gizmo_length(p.camera)
        p._begin_scale_drag(1, L)
        p._apply_scale_drag(1.5 * L)
    else:
        _use_tool(p, "rotate")
        p._begin_ring_drag(2, 0.0)
        p._apply_ring_drag_angle(math.radians(30.0))
    p._end_axis_drag()
    return (_diff(before, _staged(p, case)), len(p._undo_stack) - n)


def _scenario_noop_drags(make_panel, case):
    """Undo entries pushed by gestures that move nothing, per drag kind:
    (grab + release with no apply, grab + one apply AT the grab value)."""
    out = []
    for kind in ("axis", "scale", "ring"):
        for apply_once in (False, True):
            p = make_panel()
            _select(p, case)
            n = len(p._undo_stack)
            L = gizmo_length(p.camera)
            if kind == "axis":
                _use_tool(p, "transform")
                p._begin_axis_drag(0, 1.0)
                if apply_once:
                    p._apply_axis_drag(1.0)
            elif kind == "scale":
                _use_tool(p, "scale")
                p._begin_scale_drag(1, L)
                if apply_once:
                    p._apply_scale_drag(L)
            else:
                _use_tool(p, "rotate")
                p._begin_ring_drag(2, 0.0)
                if apply_once:
                    p._apply_ring_drag_angle(0.0)
            p._end_axis_drag()
            out.append(len(p._undo_stack) - n)
    return tuple(out)


def _scenario_pose_states(make_panel):
    """A part pose's Move and Rotate panels as the State node switches
    red -> warp -> red, with a Rotate X +10 edit made under red first."""
    p = make_panel()
    seen = []

    def _look(state):
        assert p.dispatch_event(
            'part/select_node:{"name": "wing", "kind": "%s"}' % state) is True
        _use_tool(p, "transform")
        coords = p.transform_coords()
        _use_tool(p, "rotate")
        rot = p.rotate_values()
        seen.append((state, _r((coords["x"], coords["y"], coords["z"])),
                     _r(tuple(f["value"] for f in rot["fields"]))))

    _look("red")
    assert p.dispatch_event('rotate_nudge:{"axis": 0, "delta": 10.0}') is True
    _look("red")
    _look("warp")
    _look("red")
    return seen


def _scenario_lock(make_panel, case):
    """A real mouse press on the Move gizmo's X handle, unlocked and then
    under the 'K' dev override forcing Red Alert (which the fixture's wing
    pose articulates, so mount editing locks): (unlocked press consumed,
    axis grabbed, target is a locked mount, locked coord nudge returned,
    locked press consumed, axis grabbed, undo entries pushed, anything
    staged changed)."""
    from engine.appc import articulation
    p = make_panel()
    _select(p, case)
    _use_tool(p, "transform")
    g = p._active_gizmo()
    tip = tuple(g["origin"][k] + g["axes"][0][k] * g["length"] * 0.5
                for k in range(3))
    x, y, _depth, visible = spv.project(tip, p.camera, (800, 600))
    assert visible

    def _press():
        consumed = p._handle_gizmo_input(x, y, True, False, 1.0,
                                         lambda: (800, 600))
        grabbed = p._axis_drag
        p._handle_gizmo_input(x, y, False, False, 1.0, lambda: (800, 600))
        return consumed, grabbed

    unlocked = _press()
    articulation.set_dev_override("red")
    try:
        before, n = _staged(p, case), len(p._undo_stack)
        locked = p._current_target_is_locked_mount()
        nudged = p.dispatch_event('coord_nudge:{"axis": 0, "delta": 1.0}')
        pressed = _press()
        pushed = len(p._undo_stack) - n
        changed = _diff(before, _staged(p, case))
    finally:
        articulation.set_dev_override(None)
    return unlocked + (locked, nudged) + pressed + (pushed, bool(changed))


# ── literals (recorded from the pre-refactor code) ───────────────────────────

EXPECTED_BASELINE = {'subsystem': {'position': (0.5, 1.0, -0.25), 'radius': 0.3},
 'light_sphere': {'position': (0.2, -0.4, 0.1),
                  'axis': (0.0, -1.0, 0.0),
                  'radius': (0.35,),
                  'extent': (0.0, 2.0),
                  'scale': (0.25, 0.25, 0.25),
                  'orientation': ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
                  'shape': 'Sphere'},
 'light_cylinder': {'position': (-0.3, 0.6, 0.2),
                    'axis': (0.6, -0.8, 0.0),
                    'radius': (0.2,),
                    'extent': (-0.5, 1.5),
                    'scale': (0.25, 0.25, 0.25),
                    'orientation': ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
                    'shape': 'Cylinder'},
 'light_box': {'position': (0.7, -0.2, 0.4),
               'axis': (0.0, -1.0, 0.0),
               'radius': (0.25,),
               'extent': (0.0, 2.0),
               'scale': (0.3, 0.5, 0.2),
               'orientation': ((0.6, 0.8, 0.0), (0.0, 0.0, 1.0)),
               'shape': 'Box'},
 'emitter_point': {'kind': 'point',
                   'position': (0.1, 0.2, 0.3),
                   'axis': (0.0, -1.0, 0.0),
                   'length': 1.0,
                   'radius': 0.4,
                   'color': (1.0, 0.5, 0.25),
                   'intensity': 2.0},
 'emitter_strip': {'kind': 'strip',
                   'position': (-0.5, 0.25, 0.0),
                   'axis': (0.28, -0.96, 0.0),
                   'length': 1.5,
                   'radius': 0.15,
                   'color': (0.2, 0.4, 1.0),
                   'intensity': 1.5},
 'emitter_cone': {'kind': 'cone',
                  'position': (0.3, -0.6, 0.15),
                  'axis': (-0.8, -0.6, 0.0),
                  'up': (0.0, 0.0, 1.0),
                  'length': 0.8,
                  'radius': 0.25,
                  'radius_y': 0.15,
                  'color': (1.0, 1.0, 0.0),
                  'intensity': 3.0},
 'part_anchor': {'anchor': (-0.4, 0.2, 0.1),
                 'transition': 2.0,
                 'poses': {'red': (0.05, 0.0, -0.02, 10.0, 5.0, -15.0),
                           'warp': (0.0, 0.1, 0.0, 0.0, 20.0, 0.0)},
                 'break': None},
 'part_pose': {'anchor': (-0.4, 0.2, 0.1),
               'transition': 2.0,
               'poses': {'red': (0.05, 0.0, -0.02, 10.0, 5.0, -15.0),
                         'warp': (0.0, 0.1, 0.0, 0.0, 20.0, 0.0)},
               'break': None},
 'decal': {'name': 'top',
           'origin': (-20.0, 30.0, 50.0),
           'u_axis': (40.0, 0.0, 0.0),
           'v_axis': (0.0, -20.0, 0.0),
           'normal': (0.0, 0.0, 1.0),
           'depth': 2.0,
           'shape': 'amb saucer:0',
           'mask': ''}}

EXPECTED_PAYLOADS = {'subsystem': ({'x': 0.5,
                'y': 1.0,
                'z': -0.25,
                'has_clipboard': False,
                'can_paste': False},
               None,
               {'kind': 'radius',
                'fields': ({'label': 'Radius', 'value': 0.3},),
                'has_clipboard': False,
                'can_paste': False}),
 'light_sphere': ({'x': 0.2,
                   'y': -0.4,
                   'z': 0.1,
                   'has_clipboard': False,
                   'can_paste': False},
                  None,
                  {'kind': 'radius',
                   'fields': ({'label': 'Radius', 'value': 0.35},),
                   'has_clipboard': False,
                   'can_paste': False}),
 'light_cylinder': ({'x': -0.3,
                     'y': 0.6,
                     'z': 0.2,
                     'has_clipboard': False,
                     'can_paste': False},
                    {'fields': ({'label': 'X', 'value': 0.0},
                                {'label': 'Y', 'value': 0.0},
                                {'label': 'Z', 'value': 0.0}),
                     'has_clipboard': False,
                     'can_paste': False},
                    {'kind': 'radius_length',
                     'fields': ({'label': 'Radius', 'value': 0.2},
                                {'label': 'Length', 'value': 2.0}),
                     'has_clipboard': False,
                     'can_paste': False}),
 'light_box': ({'x': 0.7,
                'y': -0.2,
                'z': 0.4,
                'has_clipboard': False,
                'can_paste': False},
               {'fields': ({'label': 'X', 'value': 0.0},
                           {'label': 'Y', 'value': 0.0},
                           {'label': 'Z', 'value': 0.0}),
                'has_clipboard': False,
                'can_paste': False},
               {'kind': 'xyz',
                'fields': ({'label': 'X', 'value': 0.3},
                           {'label': 'Y', 'value': 0.5},
                           {'label': 'Z', 'value': 0.2}),
                'has_clipboard': False,
                'can_paste': False}),
 'emitter_point': ({'x': 0.1,
                    'y': 0.2,
                    'z': 0.3,
                    'has_clipboard': False,
                    'can_paste': False},
                   None,
                   {'kind': 'radius',
                    'fields': ({'label': 'Radius', 'value': 0.4},),
                    'has_clipboard': False,
                    'can_paste': False}),
 'emitter_strip': ({'x': -0.5,
                    'y': 0.25,
                    'z': 0.0,
                    'has_clipboard': False,
                    'can_paste': False},
                   {'fields': ({'label': 'X', 'value': 0.0},
                               {'label': 'Y', 'value': 0.0},
                               {'label': 'Z', 'value': 0.0}),
                    'has_clipboard': False,
                    'can_paste': False},
                   {'kind': 'radius_length',
                    'fields': ({'label': 'Radius', 'value': 0.15},
                               {'label': 'Length', 'value': 1.5}),
                    'has_clipboard': False,
                    'can_paste': False}),
 'emitter_cone': ({'x': 0.3,
                   'y': -0.6,
                   'z': 0.15,
                   'has_clipboard': False,
                   'can_paste': False},
                  {'fields': ({'label': 'X', 'value': 0.0},
                              {'label': 'Y', 'value': 0.0},
                              {'label': 'Z', 'value': 0.0}),
                   'has_clipboard': False,
                   'can_paste': False},
                  {'kind': 'radius_xy_length',
                   'fields': ({'label': 'Radius X', 'value': 0.25},
                              {'label': 'Radius Y', 'value': 0.15},
                              {'label': 'Length', 'value': 0.8}),
                   'has_clipboard': False,
                   'can_paste': False}),
 'part_anchor': ({'x': -0.4,
                  'y': 0.2,
                  'z': 0.1,
                  'has_clipboard': False,
                  'can_paste': False},
                 None,
                 None),
 'part_pose': ({'x': -0.277202571,
                'y': 0.273605884,
                'z': 0.147565802,
                'has_clipboard': False,
                'can_paste': False},
               {'fields': ({'label': 'X', 'value': 10.0},
                           {'label': 'Y', 'value': 5.0},
                           {'label': 'Z', 'value': -15.0}),
                'has_clipboard': False,
                'can_paste': False},
               None),
 'decal': ({'x': 0.0,
            'y': 20.0,
            'z': 50.0,
            'has_clipboard': False,
            'can_paste': False,
            'decal': True,
            'step_scale': 100.0},
           {'fields': ({'label': 'Roll', 'value': 0.0},),
            'has_clipboard': False,
            'can_paste': False,
            'decal': True},
           {'kind': 'decal',
            'fields': ({'label': 'Width', 'value': 40.0, 'step_scale': 100.0},
                       {'label': 'Depth', 'value': 2.0, 'step_scale': 10.0}),
            'has_clipboard': False,
            'can_paste': False,
            'decal': True})}

EXPECTED_COORD_NUDGE = {'subsystem': (True, {'position': (1.5, 1.0, -0.25)}, 1),
 'light_sphere': (True, {'position': (1.2, -0.4, 0.1)}, 1),
 'light_cylinder': (True, {'position': (0.7, 0.6, 0.2)}, 1),
 'light_box': (True, {'position': (1.7, -0.2, 0.4)}, 1),
 'emitter_point': (True, {'position': (1.1, 0.2, 0.3)}, 1),
 'emitter_strip': (True, {'position': (0.5, 0.25, 0.0)}, 1),
 'emitter_cone': (True, {'position': (1.3, -0.6, 0.15)}, 1),
 'part_anchor': (True, {'anchor': (0.6, 0.2, 0.1)}, 1),
 'part_pose': (True,
               {'poses': {'red': (1.05, 0.0, -0.02, 10.0, 5.0, -15.0)}},
               1),
 'decal': (True, {'origin': (-19.0, 30.0, 50.0)}, 1)}

EXPECTED_ROTATE_NUDGE = {'subsystem': ((False, {}, 0), (False, {}, 0), (False, {}, 0)),
 'light_sphere': ((False, {}, 0), (False, {}, 0), (False, {}, 0)),
 'light_cylinder': ((True, {'axis': (0.6, -0.787846202, -0.138918542)}, 1),
                    (True, {'axis': (0.590884652, -0.8, -0.104188907)}, 1),
                    (True, {'axis': (0.729803194, -0.683657296, 0.0)}, 1)),
 'light_box': ((True,
                {'orientation': ((0.6, 0.787846202, 0.138918542),
                                 (0.0, -0.173648178, 0.984807753))},
                1),
               (True,
                {'orientation': ((0.590884652, 0.8, -0.104188907),
                                 (0.173648178, 0.0, 0.984807753))},
                1),
               (True,
                {'orientation': ((0.45196611, 0.892035109, 0.0),
                                 (0.0, 0.0, 1.0))},
                1)),
 'emitter_point': ((False, {}, 0), (False, {}, 0), (False, {}, 0)),
 'emitter_strip': ((True, {'axis': (0.28, -0.945415443, -0.166702251)}, 1),
                   (True, {'axis': (0.275746171, -0.96, -0.04862149)}, 1),
                   (True, {'axis': (0.442448421, -0.896793953, 0.0)}, 1)),
 'emitter_cone': ((True,
                   {'axis': (-0.8, -0.590884652, -0.104188907),
                    'up': (0.0, -0.173648178, 0.984807753)},
                   1),
                  (True,
                   {'axis': (-0.787846202, -0.6, 0.138918542),
                    'up': (0.173648178, 0.0, 0.984807753)},
                   1),
                  (True, {'axis': (-0.683657296, -0.729803194, 0.0)}, 1)),
 'part_anchor': ((False, {}, 0), (False, {}, 0), (False, {}, 0)),
 'part_pose': ((True,
                {'poses': {'red': (0.054238013,
                                   0.025636901,
                                   -0.049051906,
                                   20.0,
                                   5.0,
                                   -15.0)}},
                1),
               (True,
                {'poses': {'red': (0.016216853,
                                   0.009052167,
                                   -0.084633192,
                                   10.0,
                                   15.0,
                                   -15.0)}},
                1),
               (True,
                {'poses': {'red': (0.092540221,
                                   0.060974818,
                                   -0.02,
                                   10.0,
                                   5.0,
                                   -5.0)}},
                1)),
 'decal': ((True,
            {'origin': (-21.432636837, 26.375113977, 50.0),
             'u_axis': (39.39231012, 6.945927107, 0.0),
             'v_axis': (3.472963553, -19.69615506, 0.0)},
            1),
           (False, {}, 0),
           (False, {}, 0))}

EXPECTED_SCALE_NUDGE = {'subsystem': ((True, {'radius': 0.4}, 1), (False, {}, 0), (False, {}, 0)),
 'light_sphere': ((True, {'radius': (0.45,)}, 1),
                  (False, {}, 0),
                  (False, {}, 0)),
 'light_cylinder': ((True, {'radius': (0.3,)}, 1),
                    (True, {'extent': (-0.525, 1.575)}, 1),
                    (False, {}, 0)),
 'light_box': ((True, {'scale': (0.4, 0.5, 0.2)}, 1),
               (True, {'scale': (0.3, 0.6, 0.2)}, 1),
               (True, {'scale': (0.3, 0.5, 0.3)}, 1)),
 'emitter_point': ((True, {'radius': 0.5}, 1), (False, {}, 0), (False, {}, 0)),
 'emitter_strip': ((True, {'radius': 0.25}, 1),
                   (True, {'length': 1.6}, 1),
                   (False, {}, 0)),
 'emitter_cone': ((True, {'radius': 0.35}, 1),
                  (True, {'radius_y': 0.25}, 1),
                  (True, {'length': 0.9}, 1)),
 'part_anchor': ((False, {}, 0), (False, {}, 0), (False, {}, 0)),
 'part_pose': ((False, {}, 0), (False, {}, 0), (False, {}, 0)),
 'decal': ((True,
            {'origin': (-20.05, 30.025, 50.0),
             'u_axis': (40.1, 0.0, 0.0),
             'v_axis': (0.0, -20.05, 0.0)},
            1),
           (True, {'depth': 2.1}, 1),
           (False, {}, 0))}

EXPECTED_CLIP_TAGS = {'subsystem': ('mount', 'radius', None),
 'light_sphere': ('mount', 'radius', None),
 'light_cylinder': ('mount', 'radius_length', 'cylinder_axis'),
 'light_box': ('mount', 'xyz', 'box_orientation'),
 'emitter_point': ('mount', 'radius', None),
 'emitter_strip': ('mount', 'radius_length', 'cylinder_axis'),
 'emitter_cone': ('mount', 'radius_xy_length', 'cone_orientation'),
 'part_anchor': ('part_anchor', None, None),
 'part_pose': ('part_pose', None, 'pose_euler'),
 'decal': (None, None, None)}

EXPECTED_COORD_PASTE = {'subsystem': ('light_sphere',
               'light_cylinder',
               'light_box',
               'emitter_point',
               'emitter_strip',
               'emitter_cone'),
 'light_sphere': ('subsystem',
                  'light_cylinder',
                  'light_box',
                  'emitter_point',
                  'emitter_strip',
                  'emitter_cone'),
 'light_cylinder': ('subsystem',
                    'light_sphere',
                    'light_box',
                    'emitter_point',
                    'emitter_strip',
                    'emitter_cone'),
 'light_box': ('subsystem',
               'light_sphere',
               'light_cylinder',
               'emitter_point',
               'emitter_strip',
               'emitter_cone'),
 'emitter_point': ('subsystem',
                   'light_sphere',
                   'light_cylinder',
                   'light_box',
                   'emitter_strip',
                   'emitter_cone'),
 'emitter_strip': ('subsystem',
                   'light_sphere',
                   'light_cylinder',
                   'light_box',
                   'emitter_point',
                   'emitter_cone'),
 'emitter_cone': ('subsystem',
                  'light_sphere',
                  'light_cylinder',
                  'light_box',
                  'emitter_point',
                  'emitter_strip'),
 'part_anchor': (),
 'part_pose': (),
 'decal': ()}

EXPECTED_SCALE_PASTE = {'subsystem': ('light_sphere', 'emitter_point'),
 'light_sphere': ('subsystem', 'emitter_point'),
 'light_cylinder': ('emitter_strip',),
 'light_box': (),
 'emitter_point': ('subsystem', 'light_sphere'),
 'emitter_strip': ('light_cylinder',),
 'emitter_cone': (),
 'part_anchor': (),
 'part_pose': (),
 'decal': ()}

EXPECTED_ROTATE_PASTE = {'subsystem': (),
 'light_sphere': (),
 'light_cylinder': ('emitter_strip',),
 'light_box': (),
 'emitter_point': (),
 'emitter_strip': ('light_cylinder',),
 'emitter_cone': (),
 'part_anchor': (),
 'part_pose': (),
 'decal': ()}

EXPECTED_MIRRORS = {'subsystem': ((True, {'position': (-0.5, 1.0, -0.25)}, 1),
               (True, {}, 0),
               (True, {'position': (-0.5, 1.0, -0.25)}, 1)),
 'light_sphere': ((True, {'position': (-0.2, -0.4, 0.1)}, 1),
                  (True, {}, 0),
                  (True, {'position': (-0.2, -0.4, 0.1)}, 1)),
 'light_cylinder': ((True, {'position': (0.3, 0.6, 0.2)}, 1),
                    (True, {'axis': (-0.6, -0.8, 0.0)}, 1),
                    (True,
                     {'axis': (-0.6, -0.8, 0.0), 'position': (0.3, 0.6, 0.2)},
                     1)),
 'light_box': ((True, {'position': (-0.7, -0.2, 0.4)}, 1),
               (True, {'orientation': ((-0.6, 0.8, 0.0), (0.0, 0.0, 1.0))}, 1),
               (True,
                {'orientation': ((-0.6, 0.8, 0.0), (0.0, 0.0, 1.0)),
                 'position': (-0.7, -0.2, 0.4)},
                1)),
 'emitter_point': ((True, {'position': (-0.1, 0.2, 0.3)}, 1),
                   (True, {}, 0),
                   (True, {'position': (-0.1, 0.2, 0.3)}, 1)),
 'emitter_strip': ((True, {'position': (0.5, 0.25, 0.0)}, 1),
                   (True, {'axis': (-0.28, -0.96, 0.0)}, 1),
                   (True,
                    {'axis': (-0.28, -0.96, 0.0),
                     'position': (0.5, 0.25, 0.0)},
                    1)),
 'emitter_cone': ((True, {'position': (-0.3, -0.6, 0.15)}, 1),
                  (True, {'axis': (0.8, -0.6, 0.0)}, 1),
                  (True,
                   {'axis': (0.8, -0.6, 0.0), 'position': (-0.3, -0.6, 0.15)},
                   1)),
 'part_anchor': ((True, {'anchor': (0.4, 0.2, 0.1)}, 1),
                 (True, {}, 0),
                 (True, {'anchor': (0.4, 0.2, 0.1)}, 1)),
 'part_pose': ((True,
                {'poses': {'red': (0.604405141,
                                   0.0,
                                   -0.02,
                                   10.0,
                                   5.0,
                                   -15.0)}},
                1),
               (True,
                {'poses': {'red': (0.165395009,
                                   0.206267328,
                                   0.049724594,
                                   10.0,
                                   -5.0,
                                   15.0)}},
                1),
               (True,
                {'poses': {'red': (0.71980015,
                                   0.206267328,
                                   0.049724594,
                                   10.0,
                                   -5.0,
                                   15.0)}},
                1)),
 'decal': ((True, {}, 0), (True, {}, 0), (True, {}, 0))}

EXPECTED_PIPETTE = {'subsystem': (True,
               {'light_sphere': (('position', 'radius'), False),
                'light_cylinder': (('position',), False),
                'light_box': (('position',), False),
                'emitter_point': (('position', 'radius'), False),
                'emitter_strip': (('position',), False),
                'emitter_cone': (('position',), False),
                'part_anchor': ((), False),
                'part_pose': ((), False),
                'decal': ((), False)}),
 'light_sphere': (True,
                  {'subsystem': (('position', 'radius'), False),
                   'light_cylinder': (('position',), False),
                   'light_box': (('position',), False),
                   'emitter_point': (('position', 'radius'), False),
                   'emitter_strip': (('position',), False),
                   'emitter_cone': (('position',), False),
                   'part_anchor': ((), False),
                   'part_pose': ((), False),
                   'decal': ((), False)}),
 'light_cylinder': (True,
                    {'subsystem': (('position',), False),
                     'light_sphere': (('position',), False),
                     'light_box': (('position',), False),
                     'emitter_point': (('position',), False),
                     'emitter_strip': (('axis',
                                        'extent',
                                        'position',
                                        'radius'),
                                       False),
                     'emitter_cone': (('position',), False),
                     'part_anchor': ((), False),
                     'part_pose': ((), False),
                     'decal': ((), False)}),
 'light_box': (True,
               {'subsystem': (('position',), False),
                'light_sphere': (('position',), False),
                'light_cylinder': (('position',), False),
                'emitter_point': (('position',), False),
                'emitter_strip': (('position',), False),
                'emitter_cone': (('position',), False),
                'part_anchor': ((), False),
                'part_pose': ((), False),
                'decal': ((), False)}),
 'emitter_point': (True,
                   {'subsystem': (('position', 'radius'), False),
                    'light_sphere': (('position', 'radius'), False),
                    'light_cylinder': (('position',), False),
                    'light_box': (('position',), False),
                    'emitter_strip': (('color', 'intensity', 'position'),
                                      False),
                    'emitter_cone': (('color', 'intensity', 'position'),
                                     False),
                    'part_anchor': ((), False),
                    'part_pose': ((), False),
                    'decal': ((), False)}),
 'emitter_strip': (True,
                   {'subsystem': (('position',), False),
                    'light_sphere': (('position',), False),
                    'light_cylinder': (('axis',
                                        'length',
                                        'position',
                                        'radius'),
                                       False),
                    'light_box': (('position',), False),
                    'emitter_point': (('color', 'intensity', 'position'),
                                      False),
                    'emitter_cone': (('color', 'intensity', 'position'),
                                     False),
                    'part_anchor': ((), False),
                    'part_pose': ((), False),
                    'decal': ((), False)}),
 'emitter_cone': (True,
                  {'subsystem': (('position',), False),
                   'light_sphere': (('position',), False),
                   'light_cylinder': (('position',), False),
                   'light_box': (('position',), False),
                   'emitter_point': (('color', 'intensity', 'position'),
                                     False),
                   'emitter_strip': (('color', 'intensity', 'position'),
                                     False),
                   'part_anchor': ((), False),
                   'part_pose': ((), False),
                   'decal': ((), False)}),
 'part_anchor': (False,
                 {'subsystem': ((), False),
                  'light_sphere': ((), False),
                  'light_cylinder': ((), False),
                  'light_box': ((), False),
                  'emitter_point': ((), False),
                  'emitter_strip': ((), False),
                  'emitter_cone': ((), False),
                  'part_pose': ((), False),
                  'decal': ((), False)}),
 'part_pose': (False,
               {'subsystem': ((), False),
                'light_sphere': ((), False),
                'light_cylinder': ((), False),
                'light_box': ((), False),
                'emitter_point': ((), False),
                'emitter_strip': ((), False),
                'emitter_cone': ((), False),
                'part_anchor': ((), False),
                'decal': ((), False)}),
 'decal': (False,
           {'subsystem': ((), False),
            'light_sphere': ((), False),
            'light_cylinder': ((), False),
            'light_box': ((), False),
            'emitter_point': ((), False),
            'emitter_strip': ((), False),
            'emitter_cone': ((), False),
            'part_anchor': ((), False),
            'part_pose': ((), False)})}

EXPECTED_DRAGS = {'subsystem': (({'position': (0.75, 1.0, -0.25)}, 1),
               ({'radius': 0.45}, 1),
               ({}, 0)),
 'light_sphere': (({'position': (0.45, -0.4, 0.1)}, 1),
                  ({'radius': (0.525,)}, 1),
                  ({}, 0)),
 'light_cylinder': (({'position': (-0.05, 0.6, 0.2)}, 1),
                    ({'extent': (-0.75, 2.25)}, 1),
                    ({'axis': (0.919615242, -0.392820323, 0.0)}, 1)),
 'light_box': (({'position': (0.95, -0.2, 0.4)}, 1),
               ({'scale': (0.3, 0.75, 0.2)}, 1),
               ({'orientation': ((0.119615242, 0.992820323, 0.0),
                                 (0.0, 0.0, 1.0))},
                1)),
 'emitter_point': (({'position': (0.35, 0.2, 0.3)}, 1),
                   ({'radius': 0.6}, 1),
                   ({}, 0)),
 'emitter_strip': (({'position': (-0.25, 0.25, 0.0)}, 1),
                   ({'length': 2.25}, 1),
                   ({'axis': (0.722487113, -0.691384388, 0.0)}, 1)),
 'emitter_cone': (({'position': (0.55, -0.6, 0.15)}, 1),
                  ({'radius': 0.375}, 1),
                  ({'axis': (-0.392820323, -0.919615242, 0.0)}, 1)),
 'part_anchor': (({'anchor': (-0.15, 0.2, 0.1)}, 1), ({}, 0), ({}, 0)),
 'part_pose': (({'poses': {'red': (0.3, 0.0, -0.02, 10.0, 5.0, -15.0)}}, 1),
               ({}, 0),
               ({'poses': {'red': (0.14296611,
                                   0.200257523,
                                   -0.02,
                                   10.0,
                                   5.0,
                                   15.0)}},
                1)),
 'decal': (({'origin': (5.0, 30.0, 50.0)}, 1),
           ({'depth': 3.0,
             'origin': (-30.0, 35.0, 50.0),
             'u_axis': (60.0, 0.0, 0.0),
             'v_axis': (0.0, -30.0, 0.0)},
            1),
           ({'origin': (-22.320508076, 18.660254038, 50.0),
             'u_axis': (34.641016151, 20.0, 0.0),
             'v_axis': (10.0, -17.320508076, 0.0)},
            1))}

EXPECTED_NOOP_DRAG_UNDO = {'subsystem': (0, 1, 0, 1, 0, 0),
 'light_sphere': (0, 1, 0, 1, 0, 0),
 'light_cylinder': (0, 1, 0, 1, 0, 1),
 'light_box': (0, 1, 0, 1, 0, 1),
 'emitter_point': (0, 1, 0, 1, 0, 0),
 'emitter_strip': (0, 1, 0, 1, 0, 1),
 'emitter_cone': (0, 1, 0, 1, 0, 1),
 'part_anchor': (0, 1, 0, 0, 0, 0),
 'part_pose': (0, 1, 0, 0, 0, 1),
 'decal': (0, 0, 0, 0, 0, 0)}

EXPECTED_POSE_STATES = [('red', (-0.277202571, 0.273605884, 0.147565802), (10.0, 5.0, -15.0)),
 ('red', (-0.277202571, 0.273605884, 0.147565802), (20.0, 5.0, -15.0)),
 ('warp', (-0.341675034, 0.3, 0.230777319), (0.0, 20.0, 0.0)),
 ('red', (-0.277202571, 0.273605884, 0.147565802), (20.0, 5.0, -15.0))]

EXPECTED_LOCK = {'subsystem': (True, 0, True, False, False, None, 0, False),
 'light_sphere': (True, 0, True, False, False, None, 0, False),
 'light_cylinder': (True, 0, True, False, False, None, 0, False),
 'light_box': (True, 0, True, False, False, None, 0, False),
 'emitter_point': (True, 0, True, False, False, None, 0, False),
 'emitter_strip': (True, 0, True, False, False, None, 0, False),
 'emitter_cone': (True, 0, True, False, False, None, 0, False),
 'part_anchor': (True, 0, False, True, True, 0, 1, True),
 'part_pose': (True, 0, False, True, True, 0, 1, True),
 'decal': (True, 0, False, True, True, 0, 1, True)}


# ── the tests ────────────────────────────────────────────────────────────────

def test_the_fixture_baseline(make_panel):
    """What every case starts as, before any tool touches it."""
    p = make_panel()
    assert {c: _staged(p, c) for c in CASES} == EXPECTED_BASELINE


# Move / Rotate / Scale panels ------------------------------------------------

@pytest.mark.parametrize("case", CASES)
def test_the_three_tool_payloads(make_panel, case):
    """(transform_coords, rotate_values, scale_values), whole dicts, each
    read under its own tool. None = that tool has no panel for the kind."""
    assert _scenario_payloads(make_panel, case) == EXPECTED_PAYLOADS[case]


@pytest.mark.parametrize("case", CASES)
def test_coord_nudge_x_plus_one(make_panel, case):
    """(returned, what changed, undo entries) after coord_nudge x +1."""
    got = _scenario_action(make_panel, case, "transform",
                           'coord_nudge:{"axis": 0, "delta": 1.0}')
    assert got == EXPECTED_COORD_NUDGE[case]


@pytest.mark.parametrize("case", CASES)
def test_rotate_nudge_each_field(make_panel, case):
    """rotate_nudge +10 on axis 0, 1, 2 (each from a fresh panel)."""
    got = tuple(_scenario_action(
        make_panel, case, "rotate",
        'rotate_nudge:{"axis": %d, "delta": 10.0}' % k) for k in range(3))
    assert got == EXPECTED_ROTATE_NUDGE[case]


@pytest.mark.parametrize("case", CASES)
def test_scale_nudge_each_field(make_panel, case):
    """scale_nudge +0.1 on index 0, 1, 2 (each from a fresh panel)."""
    got = tuple(_scenario_action(
        make_panel, case, "scale",
        'scale_nudge:{"index": %d, "delta": 0.1}' % k) for k in range(3))
    assert got == EXPECTED_SCALE_NUDGE[case]


# Copy / Paste ----------------------------------------------------------------

@pytest.mark.parametrize("case", CASES)
def test_clipboard_tags(make_panel, case):
    """The kind tag each Copy writes: (coord, scale, rotate). None = Copy
    wrote nothing (the decal gap: it has no clipboard at all)."""
    got = tuple(_scenario_clip_tag(make_panel, case, tool, verb)
                for tool, verb in (("transform", "coord"), ("scale", "scale"),
                                   ("rotate", "rotate")))
    assert got == EXPECTED_CLIP_TAGS[case]


def test_coord_paste_matrix(make_panel):
    assert _scenario_paste_matrix(make_panel, "transform", "coord") \
        == EXPECTED_COORD_PASTE


def test_scale_paste_matrix(make_panel):
    assert _scenario_paste_matrix(make_panel, "scale", "scale") \
        == EXPECTED_SCALE_PASTE


def test_rotate_paste_matrix(make_panel):
    assert _scenario_paste_matrix(make_panel, "rotate", "rotate") \
        == EXPECTED_ROTATE_PASTE


# Mirror ----------------------------------------------------------------------

@pytest.mark.parametrize("case", CASES)
def test_mirrors(make_panel, case):
    """(coord_mirror, rotate_mirror, mirror_element), each from a fresh
    panel: (returned, what changed, undo entries). The decal row is the
    Mirror gap: every mirror returns True and changes nothing."""
    got = tuple(_scenario_action(make_panel, case, tool, action)
                for tool, action in (("transform", "coord_mirror"),
                                     ("rotate", "rotate_mirror"),
                                     ("transform", "mirror_element")))
    assert got == EXPECTED_MIRRORS[case]


# Pipette ---------------------------------------------------------------------

@pytest.mark.parametrize("case", CASES)
def test_pipette(make_panel, case):
    """(arms on this target, {source: (target fields changed, still
    armed)}). A part node or a decal never arms; picking a part node or a
    decal as the SOURCE is not a pick (it disarms and selects it)."""
    assert _scenario_pipette(make_panel, case) == EXPECTED_PIPETTE[case]


# Gizmo drags -----------------------------------------------------------------

@pytest.mark.parametrize("case", CASES)
def test_one_drag_of_each_kind(make_panel, case):
    """Axis drag X +0.25, scale drag handle 1 x1.5, ring drag 2 +30 deg:
    (what changed, undo entries) -- exactly one entry when anything moved."""
    got = tuple(_scenario_drag(make_panel, case, kind)
                for kind in ("axis", "scale", "ring"))
    assert got == EXPECTED_DRAGS[case]


# Review Focus 3: undo per gesture ---------------------------------------------

@pytest.mark.parametrize("case", CASES)
def test_undo_entries_for_gestures_that_move_nothing(make_panel, case):
    """(axis, scale, ring) x (grab+release, grab+apply-at-grab+release).
    A grab and release pushes none. An apply AT the grab value re-stages an
    identical value into a pending dict that was empty, which the snapshot
    compare counts as a change -- pinned as it is (see the task report)."""
    assert _scenario_noop_drags(make_panel, case) \
        == EXPECTED_NOOP_DRAG_UNDO[case]


# Review Focus 2: locked mounts -------------------------------------------------

@pytest.mark.parametrize("case", CASES)
def test_a_locked_mount_refuses_a_nudge_and_a_grab(make_panel, case):
    """Unlocked, a press on the X handle grabs axis 0. Under the 'K' lock a
    subsystem/light/emitter refuses both the coord nudge and the press; a
    part node or a decal is never a locked mount."""
    assert _scenario_lock(make_panel, case) == EXPECTED_LOCK[case]


# Review Focus 1: selection switching -------------------------------------------

def test_switching_selection_between_kinds_updates_all_three_payloads(
        make_panel):
    """Each hop shows exactly the payloads a fresh selection of that case
    shows, and exactly one of (hardpoint/part target, decal) is live."""
    p = make_panel()
    chain = ["decal", "light_sphere", "decal", "part_pose", "decal",
             "light_box", "emitter_cone", "part_anchor", "subsystem",
             "part_pose", "light_cylinder", "decal", "emitter_strip",
             "emitter_point", "decal"]
    for case in chain:
        _select(p, case)
        assert _payloads(p, case) == EXPECTED_PAYLOADS[case], case
        if case == "decal":
            assert p._decal_selected == "top"
            assert p._active_transform_target() is None
        else:
            assert p._decal_selected is None
            assert p._active_transform_target() is not None


# Review Focus 4: pose-state switching ------------------------------------------

def test_a_part_pose_shows_each_states_own_values(make_panel):
    """(state, Move panel xyz, Rotate panel xyz) as the State node goes
    red -> (Rotate X +10) -> red -> warp -> red: warp shows warp's values,
    and red keeps its edit."""
    assert _scenario_pose_states(make_panel) == EXPECTED_POSE_STATES


# Box -> Box rotate paste (fix round 1) -----------------------------------------

def _scenario_box_to_box_rotate_paste(make_panel):
    """Light 3 (Box A, forward (0.6, 0.8, 0)) copies; light 1, re-shaped as
    a second Box B with a different basis (saved this session, so nothing
    is pending before the paste), pastes: (returned, B's staged (forward,
    up), undo entries)."""
    p = make_panel()
    p._saved_light[1] = _region(
        shape="Box", position=(0.2, -0.4, 0.1), scale=(0.3, 0.3, 0.3),
        orientation=((0.0, 0.0, 1.0), (1.0, 0.0, 0.0)))
    _select(p, "light_box")
    _use_tool(p, "rotate")
    assert p.dispatch_event("rotate_copy") is True
    assert p.dispatch_event("select_light:1") is True
    n = len(p._undo_stack)
    ok = p.dispatch_event("rotate_paste")
    return (ok, _r(p._pending_light[1]["orientation"]),
            len(p._undo_stack) - n)


def test_box_to_box_rotate_paste(make_panel):
    """The `box_orientation` branch of rotate_paste: B takes A's
    re-orthonormalised forward and up (not swapped), one undo entry."""
    assert _scenario_box_to_box_rotate_paste(make_panel) == (
        True, ((0.6, 0.8, 0.0), (0.0, 0.0, 1.0)), 1)


# Cone mirror with a tilted up (Task 5 review carry) -----------------------------

def _tilted_up_cone_panel(make_panel):
    """The fixture panel with emitter 4/2 (the cone) saved this session with
    an `up` whose X is non-zero, orthonormal to its axis (-0.8, -0.6, 0):
    the base cone's up (0, 0, 1) has x = 0, so it cannot see a sign error
    in mirroring up."""
    p = make_panel()
    lst = [dict(e) for e in _DESCRIPTORS[4]["emitters"]]
    lst[2] = dict(lst[2], up=(0.48, -0.64, 0.6))
    p._saved_emitter[4] = lst
    return p


def test_mirrors_of_a_cone_whose_up_has_nonzero_x(make_panel):
    """(rotate_mirror, mirror_element) on the tilted-up cone: both negate
    X of axis AND up; mirror_element also flips position X. One undo each."""
    got = tuple(_scenario_action(lambda: _tilted_up_cone_panel(make_panel),
                                 "emitter_cone", tool, action)
                for tool, action in (("rotate", "rotate_mirror"),
                                     ("transform", "mirror_element")))
    assert got == (
        (True, {'axis': (0.8, -0.6, 0.0), 'up': (-0.48, -0.64, 0.6)}, 1),
        (True, {'axis': (0.8, -0.6, 0.0), 'position': (-0.3, -0.6, 0.15),
                'up': (-0.48, -0.64, 0.6)}, 1))
