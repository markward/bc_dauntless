"""SPV running lights: the live preview and its restore on close (spec
docs/superpowers/specs/2026-10-22-spv-running-lights-design.md S3.5).

While the viewer is open the effective lights are pushed to native for the
SPV instance (`engine.renderer.set_running_lights`, monkeypatched here) --
only when the tuple list changed. Closing hands (ship, iid) to the injected
`on_running_lights_closed` callback, which puts the spawn lights back.

Built on the Task 7 pane fixture's ship and lights ("Port Nav", "Star Nav")."""
import json

import pytest

import engine.renderer
from engine.appc import running_lights
from engine.ui.ship_property_viewer import OrbitCamera
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel
from tests.ui import spv_test_fixtures as fx
from tests.ui.test_spv_running_lights_pane import _BOW, _PORT, _STAR, _LitShip

_IID = 42


class _NamedShip(_LitShip):
    def GetName(self):
        return "USS Preview"


def _tuple(spec):
    return (tuple(spec["position"]) + tuple(spec["color"])
            + (spec["radius"], spec["period"], spec["duration"]))


@pytest.fixture
def pushes(monkeypatch):
    calls = []
    monkeypatch.setattr(engine.renderer, "set_running_lights",
                        lambda iid, lights, phase: calls.append(
                            (iid, [tuple(l) for l in lights], phase)))
    return calls


@pytest.fixture
def make_panel(monkeypatch, pushes):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: None)
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship",
                        lambda s: fx.UNRIGGED_LEAF)
    monkeypatch.setattr(
        mod, "build_descriptors",
        lambda ship: [dict(fx._DESCRIPTORS[0],
                           properties=dict(fx._DESCRIPTORS[0]["properties"]))])

    def _make(lights=(_PORT, _STAR)):
        ship = _NamedShip(lights)
        closed = []
        p = ShipPropertyViewerPanel(
            ship_getter=lambda: ship, iid_getter=lambda: _IID,
            on_running_lights_closed=lambda s, iid: closed.append((s, iid)))
        p.closed = closed
        p.ship = ship
        p.open()
        p.camera = OrbitCamera((0.0, 0.0, 0.0), 10.0, 0.0, 0.0)
        return p
    return _make


def _edit(p, name, **changes):
    spec = dict(p._rl_spec(name), **changes)
    spec.pop("name")
    return p.dispatch_event("rl/edit:" + json.dumps(
        {"name": name, "spec": spec}))


def test_open_pushes_effective_lights(make_panel, pushes):
    p = make_panel()
    assert pushes == [(_IID, [_tuple(_PORT), _tuple(_STAR)],
                       running_lights.phase_for(p.ship))]


def test_edit_repushes_once(make_panel, pushes):
    p = make_panel()
    del pushes[:]
    assert _edit(p, "Port Nav", color=[0.0, 0.0, 1.0]) is True
    assert _edit(p, "Port Nav", color=[0.0, 0.0, 1.0]) is True
    assert len(pushes) == 1
    iid, lights, _ = pushes[0]
    assert iid == _IID
    assert lights[0][3:6] == (0.0, 0.0, 1.0)
    assert lights[1] == _tuple(_STAR)


def test_unchanged_dispatch_pushes_nothing(make_panel, pushes):
    p = make_panel()
    del pushes[:]
    p.dispatch_event("rl/toggle_group")
    assert pushes == []


def test_remove_last_light_pushes_empty(make_panel, pushes):
    p = make_panel(lights=(_BOW,))
    del pushes[:]
    assert p.dispatch_event('rl/remove:{"name": "Bow Nav"}') is True
    assert pushes == [(_IID, [], running_lights.phase_for(p.ship))]


def test_undo_repushes(make_panel, pushes):
    p = make_panel()
    _edit(p, "Port Nav", color=[0.0, 0.0, 1.0])
    del pushes[:]
    p.undo()
    assert [l for _, l, _ in pushes] == [[_tuple(_PORT), _tuple(_STAR)]]


def test_close_calls_restore_callback(make_panel, pushes):
    p = make_panel()
    p.close()
    assert p.closed == [(p.ship, _IID)]
    # ...once: the cache is cleared, and a closed panel pushes nothing.
    del pushes[:]
    p.close()
    p.dispatch_event("rl/toggle_group")
    assert p.closed == [(p.ship, _IID)]
    assert pushes == []


def test_reopen_pushes_again(make_panel, pushes):
    p = make_panel()
    p.close()
    del pushes[:]
    p.open()
    assert len(pushes) == 1


def test_no_iid_pushes_nothing_and_close_restores_nothing(monkeypatch,
                                                          make_panel, pushes):
    p = make_panel()
    p.close()
    del p.closed[:]
    del pushes[:]
    p._iid_getter = lambda: None
    p.open()
    p.close()
    assert pushes == []
    assert p.closed == []


def test_placing_click_pushes_the_new_light(monkeypatch, make_panel, pushes):
    """`_rl_click` runs from pick_at, outside dispatch_event."""
    from engine.ui import spv_running_lights_pane as rl_mod
    monkeypatch.setattr(rl_mod, "instance_scale", lambda ship: 1.0)
    p = make_panel()
    p._decal_hull_hit = lambda x, y, viewport: ((0.0, 3.0, 0.0),
                                                (0.0, 0.0, 1.0), None)
    spec = dict(_BOW)
    spec.pop("position")
    p.dispatch_event("rl/place_begin:" + json.dumps(spec))
    del pushes[:]
    p.pick_at(100.0, 100.0, (0, 0, 800, 600))
    assert len(pushes) == 1
    assert [l[3:] for l in pushes[0][1]] == [
        _tuple(s)[3:] for s in (_PORT, _STAR, _BOW)]


def test_preview_iids_while_previewing(make_panel):
    p = make_panel()
    assert p.running_light_preview_iids() == (_IID,)
    p.close()
    assert p.running_light_preview_iids() == ()


def test_mission_swap_forgets_preview_without_callback(make_panel, pushes):
    """The swap destroys the instance: never restore onto a dead (or reused)
    iid at the later close."""
    p = make_panel()
    p.on_mission_swap()
    assert p.running_light_preview_iids() == ()
    p.close()
    assert p.closed == []
