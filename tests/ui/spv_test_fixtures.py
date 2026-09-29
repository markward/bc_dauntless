"""Shared SPV edit-target test fixtures: one panel carrying a target of
every kind at once (subsystem mount, Sphere/Cylinder/Box lights, point/strip/
cone emitters, part "wing" anchor + poses, decal "top"), the `make_panel`
fixture that builds it, the `_SELECT` event per case, and the observation
helpers (`_r`, `_staged`, `_diff`, ...).

Used by the characterisation suite
(`tests/ui/test_spv_edit_target_characterisation.py`, which holds the
recorded expectations) and the adapter unit tests
(`tests/unit/test_spv_edit_targets.py`). Import `make_panel` into a test
module to use the fixture.
"""
import dataclasses

import pytest

from engine.appc.math import TGMatrix3, TGPoint3
from engine.ui import decal_editor
from engine.ui.ship_property_viewer import OrbitCamera
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
