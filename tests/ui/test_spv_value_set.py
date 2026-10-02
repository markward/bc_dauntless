"""Typed values in the SPV Move / Rotate / Scale rows.

A typed value must do EXACTLY what the steppers do when clicked until the row
reads that value -- so each *_set is pinned equal to the matching *_nudge on
every edit-target kind (returned, staged change, undo entries), using the
characterisation fixture.

Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md S5.2
"""
import json

import pytest

from tests.ui.spv_test_fixtures import (  # noqa: F401  (make_panel: fixture)
    CASES, _diff, _select, _staged, _use_tool, make_panel)


def _run(make_panel, case, tool, action):
    p = make_panel()
    _select(p, case)
    _use_tool(p, tool)
    before, n = _staged(p, case), len(p._undo_stack)
    ok = p.dispatch_event(action)
    return (ok, _diff(before, _staged(p, case)), len(p._undo_stack) - n)


def _shown(make_panel, case, tool):
    """The values the row displays, read the way the JS gets them."""
    p = make_panel()
    _select(p, case)
    _use_tool(p, tool)
    if tool == "transform":
        tc = p.transform_coords()
        return None if tc is None else [tc["x"], tc["y"], tc["z"]]
    vals = p.scale_values() if tool == "scale" else p.rotate_values()
    return None if vals is None else [f["value"] for f in vals["fields"]]


@pytest.mark.parametrize("case", CASES)
def test_coord_set_equals_the_nudge(make_panel, case):
    nudged = _run(make_panel, case, "transform", 'coord_nudge:{"axis": 0, "delta": 1.0}')
    shown = _shown(make_panel, case, "transform")
    value = (shown[0] + 1.0) if shown else 1.0
    got = _run(make_panel, case, "transform",
               "coord_set:" + json.dumps({"axis": 0, "value": value}))
    assert got == nudged


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("k", [0, 1, 2])
def test_scale_set_equals_the_nudge(make_panel, case, k):
    nudged = _run(make_panel, case, "scale", 'scale_nudge:{"index": %d, "delta": 0.1}' % k)
    shown = _shown(make_panel, case, "scale")
    value = (shown[k] + 0.1) if shown and k < len(shown) else 0.1
    got = _run(make_panel, case, "scale",
               "scale_set:" + json.dumps({"index": k, "value": value}))
    assert got == nudged


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("k", [0, 1, 2])
def test_rotate_set_equals_the_nudge(make_panel, case, k):
    nudged = _run(make_panel, case, "rotate", 'rotate_nudge:{"axis": %d, "delta": 10.0}' % k)
    shown = _shown(make_panel, case, "rotate")
    value = (shown[k] + 10.0) if shown and k < len(shown) else 10.0
    got = _run(make_panel, case, "rotate",
               "rotate_set:" + json.dumps({"axis": k, "value": value}))
    assert got == nudged


def test_rotate_set_is_relative_to_the_accumulator(make_panel):
    p = make_panel()
    _select(p, "light_cylinder")
    _use_tool(p, "rotate")
    p.dispatch_event('rotate_nudge:{"axis": 0, "delta": 20.0}')
    calls = []
    t = p._rotate_edit_target()
    orig = type(t).rotate_nudge
    type(t).rotate_nudge = lambda self, i, d: calls.append((i, d))
    try:
        p.dispatch_event('rotate_set:{"axis": 0, "value": 30.0}')
    finally:
        type(t).rotate_nudge = orig
    assert calls == [(0, pytest.approx(10.0))]


@pytest.mark.parametrize("action", [
    "coord_set:not json",
    'coord_set:{"axis": 3, "value": 1.0}',
    'coord_set:{"axis": 0}',
    'coord_set:{"axis": 0, "value": NaN}',
    'coord_set:{"axis": 0, "value": Infinity}',
    'coord_set:{"axis": 0, "value": "abc"}',
    'scale_set:{"index": 9, "value": 1.0}',
    'scale_set:{"index": 0, "value": NaN}',
    'rotate_set:{"axis": 7, "value": 1.0}',
    'rotate_set:{"axis": 0, "value": -Infinity}',
])
def test_malformed_sets_are_rejected_and_change_nothing(make_panel, action):
    p = make_panel()
    _select(p, "light_box")
    tool = {"coord": "transform", "scale": "scale", "rotate": "rotate"}[action.split("_")[0]]
    _use_tool(p, tool)
    before, n = _staged(p, "light_box"), len(p._undo_stack)
    assert p.dispatch_event(action) is False
    assert _diff(before, _staged(p, "light_box")) == _diff(before, before)
    assert len(p._undo_stack) == n


@pytest.mark.parametrize("case", CASES)
def test_a_locked_mount_refuses_typed_values(make_panel, case):
    """Typed values honour the same lock as the steppers and gizmo."""
    from engine.appc import articulation
    p = make_panel()
    _select(p, case)
    _use_tool(p, "transform")
    articulation.set_dev_override("red")
    try:
        locked = p._current_target_is_locked_mount()
        before = _staged(p, case)
        results = [p.dispatch_event(a) for a in (
            'coord_set:{"axis": 0, "value": 5.0}',
            'scale_set:{"index": 0, "value": 5.0}',
            'rotate_set:{"axis": 0, "value": 5.0}')]
        changed = _diff(before, _staged(p, case)) != _diff(before, before)
    finally:
        articulation.set_dev_override(None)
    if locked:
        assert not any(results) and not changed
