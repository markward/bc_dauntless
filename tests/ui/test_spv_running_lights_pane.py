"""SPV running-lights pane, Python side (spec 2026-10-22-spv-running-lights
S3.1, S3.2, S3.6, S5): the `RunningLightsPaneMixin` staging model, the
"Running Lights" group + "+ Add" rows appended to the subsystem list, the
`rl/select` / `rl/toggle_group` actions, undo, Save routing and the Physical
tab's light entries.

Fixture: the `spv_test_fixtures` `_Ship` pattern plus a property set holding
two placed `BlinkingLightProperty` entries ("Port Nav", "Star Nav")."""
import json

import pytest

import App
from engine.appc.math import TGPoint3
from engine.appc.properties import TGModelPropertySet
from engine.ui.ship_property_viewer import OrbitCamera
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel
from tests.ui import spv_test_fixtures as fx

_PORT = {"name": "Port Nav", "position": (-1.0, 0.5, 0.0),
         "color": (1.0, 0.0, 0.0), "radius": 0.5, "period": 2.0,
         "duration": 0.5}
_STAR = {"name": "Star Nav", "position": (1.0, 0.5, 0.0),
         "color": (0.0, 1.0, 0.0), "radius": 0.5, "period": 2.0,
         "duration": 0.5}
_BOW = {"name": "Bow Nav", "position": (0.0, 2.0, 0.25),
        "color": (1.0, 1.0, 1.0), "radius": 1.0, "period": 3.0,
        "duration": 0.0}


def _light(spec):
    p = App.BlinkingLightProperty_Create(spec["name"])
    pt = TGPoint3()
    pt.SetXYZ(*spec["position"])
    p.SetPosition(pt)
    p.SetColor(App.TGColorA(*(spec["color"] + (1.0,))))
    p.SetRadius(spec["radius"])
    p.SetPeriod(spec["period"])
    p.SetDuration(spec["duration"])
    return p


class _LitShip(fx._Ship):
    def __init__(self, lights=()):
        super().__init__()
        self._pset = TGModelPropertySet()
        for spec in lights:
            self._pset.AddToSet("Scene Root", _light(spec))

    def GetPropertySet(self):
        return self._pset


class _Target:
    def __init__(self):
        self.calls = []

    def write(self, leaf, edits):
        self.calls.append((leaf, list(edits)))


@pytest.fixture
def make_panel(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    target = _Target()
    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: target)
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship",
                        lambda s: fx.UNRIGGED_LEAF)
    monkeypatch.setattr(
        mod, "build_descriptors",
        lambda ship: [dict(fx._DESCRIPTORS[0],
                           properties=dict(fx._DESCRIPTORS[0]["properties"]))])

    def _make(lights=(_PORT, _STAR)):
        ship = _LitShip(lights)
        p = ShipPropertyViewerPanel(ship_getter=lambda: ship)
        p.open()
        p.camera = OrbitCamera((0.0, 0.0, 0.0), 10.0, 0.0, 0.0)
        p._undo_stack.clear()
        return p
    _make.target = target
    return _make


def _payload(p):
    p._last_pushed = None
    js = p.render_payload()
    return json.loads(js[len("setShipPropertyViewer("):-2])


def _group(rows):
    groups = [r for r in rows if r.get("kind") == "rl_group"]
    return groups[0] if groups else None


def _light_names(p):
    g = _group(p._subsystem_rows())
    return [c["name"] for c in g["children"]] if g else []


def test_rows_append_group_and_add_row(make_panel):
    p = make_panel()
    rows = p._subsystem_rows()
    group, add = rows[-2], rows[-1]
    assert group["kind"] == "rl_group"
    assert group["name"] == "Running Lights"
    assert group["expanded"] is False
    assert [c["name"] for c in group["children"]] == ["Port Nav", "Star Nav"]
    port = group["children"][0]
    assert port["kind"] == "running_light"
    assert port["spec"] == _PORT
    assert port["dirty"] is False and port["chosen"] is False
    assert add == {"kind": "rl_add", "name": "+ Add"}
    for r in (group, add, *group["children"]):
        assert "index" not in r


def test_no_group_row_without_lights(make_panel):
    p = make_panel(lights=())
    rows = p._subsystem_rows()
    assert rows[-1] == {"kind": "rl_add", "name": "+ Add"}
    assert _group(rows) is None


def test_stage_remove_hides_light_from_rows_and_physical(make_panel):
    p = make_panel()
    p._last_pushed = ("stale",)
    p._rl_stage("Port Nav", None)
    assert p._last_pushed is None
    assert _light_names(p) == ["Star Nav"]
    keys = [e["key"] for e in p._physical_entries()]
    assert "light:Port Nav" not in keys
    assert "light:Star Nav" in keys
    # A pending ADD appears in the rows and on the Physical tab.
    p._rl_stage("Bow Nav", dict(_BOW))
    assert _light_names(p) == ["Star Nav", "Bow Nav"]
    bow = [e for e in p._physical_entries() if e["key"] == "light:Bow Nav"]
    assert len(bow) == 1
    assert bow[0]["kind"] == "running_light"
    assert bow[0]["point"] == _BOW["position"]
    assert bow[0]["index"] is None
    # The staged light row is dirty; the untouched one is not.
    g = _group(p._subsystem_rows())
    assert {c["name"]: c["dirty"] for c in g["children"]} == {
        "Star Nav": False, "Bow Nav": True}


def test_physical_entry_keeps_baked_parent(make_panel):
    p = make_panel()
    p._physical_lights[0]["physical_parent"] = "left wing"
    entry = [e for e in p._physical_entries()
             if e["key"] == "light:Port Nav"][0]
    assert entry["baked"] == "left wing"
    assert entry["point"] == _PORT["position"]


def test_select_running_light_clears_other_selections(make_panel):
    p = make_panel()
    assert p.dispatch_event("select_pin:0") is True
    assert p.selected_index == 0
    p._decal_selected = "top"
    p._selected_light_index = 0
    p._selected_emitter = (0, 0)
    assert p.dispatch_event('rl/select:{"name": "Port Nav"}') is True
    assert p._rl_selected == "Port Nav"
    assert p.selected_index is None
    assert p._selected_light_index is None
    assert p._selected_emitter is None
    assert p._decal_selected is None
    from engine.ui import ship_property_viewer as spv
    assert spv.selected_part_node() is None
    assert spv.selected_model_part() is None
    assert p._active_transform_target() == ("running_light", "Port Nav")
    g = _group(p._subsystem_rows())
    assert [c["chosen"] for c in g["children"]] == [True, False]
    # Any other select takes the selection off the light.
    assert p.dispatch_event("select_pin:0") is True
    assert p._rl_selected is None
    assert p._active_transform_target() == ("subsystem", 0)


def test_select_unknown_light_is_refused(make_panel):
    p = make_panel()
    assert p.dispatch_event('rl/select:{"name": "Nope"}') is False
    assert p.dispatch_event("rl/select:not json") is False
    assert p._rl_selected is None


def test_deselect_clears_running_light_selection(make_panel):
    p = make_panel()
    assert p.dispatch_event('rl/select:{"name": "Star Nav"}') is True
    assert p.dispatch_event("deselect") is True
    assert p._rl_selected is None


def test_toggle_group_flips_expanded(make_panel):
    p = make_panel()
    assert p.dispatch_event("rl/toggle_group") is True
    assert _group(p._subsystem_rows())["expanded"] is True
    assert p.dispatch_event("rl/toggle_group") is True
    assert _group(p._subsystem_rows())["expanded"] is False


def test_undo_restores_running_light_staging(make_panel):
    p = make_panel()
    before = p._snapshot_pending()
    p._rl_stage("Port Nav", None)
    assert p._snapshot_pending() != before
    p._undo_stack.append(before)
    assert p.dispatch_event("undo") is True
    assert p._pending_running_light == {}
    assert _light_names(p) == ["Port Nav", "Star Nav"]


def test_save_routes_running_light_edits(make_panel):
    p = make_panel()
    edited = dict(_STAR, color=(0.0, 0.5, 1.0))
    p._rl_stage("Port Nav", None)
    p._rl_stage("Star Nav", edited)
    p._rl_stage("Bow Nav", dict(_BOW))
    assert p.dispatch_event("save") is True
    assert len(make_panel.target.calls) == 1
    leaf, edits = make_panel.target.calls[0]
    assert leaf == fx.UNRIGGED_LEAF
    assert sorted(edits, key=lambda e: e[0]) == [
        ("Bow Nav", "__running_light__", {"spec": _BOW, "new": True}),
        ("Port Nav", "__running_light__", {"spec": None, "new": False}),
        ("Star Nav", "__running_light__", {"spec": edited, "new": False}),
    ]
    assert p._pending_running_light == {}
    assert p._saved_running_light == {"Port Nav": None, "Star Nav": edited,
                                      "Bow Nav": _BOW}
    # The saved overlay keeps driving the rows, which are no longer dirty.
    g = _group(p._subsystem_rows())
    assert [(c["name"], c["dirty"]) for c in g["children"]] == [
        ("Star Nav", False), ("Bow Nav", False)]
    assert p._rl_spec("Star Nav") == edited
    # The overlay survives a reopen of the same ship.
    p.close()
    p.open()
    assert _light_names(p) == ["Star Nav", "Bow Nav"]


def test_unsaved_add_then_remove_writes_nothing(make_panel):
    p = make_panel()
    p._rl_stage("Bow Nav", dict(_BOW))
    p._rl_stage("Bow Nav", None)
    assert p._pending_running_light == {}
    assert _light_names(p) == ["Port Nav", "Star Nav"]


def test_open_and_close_drop_staged_lights(make_panel):
    p = make_panel()
    p._rl_stage("Port Nav", None)
    p.dispatch_event('rl/select:{"name": "Star Nav"}')
    p.close()
    assert p._pending_running_light == {}
    assert p._rl_selected is None
    p.open()
    assert _light_names(p) == ["Port Nav", "Star Nav"]


def test_pending_count_and_confirm_list_include_lights(make_panel):
    p = make_panel()
    p._rl_stage("Port Nav", None)
    p._rl_stage("Bow Nav", dict(_BOW))
    data = _payload(p)
    assert data["pending_count"] == 2
    assert {"name": "Port Nav", "count": 1} in data["pending"]
    assert {"name": "Bow Nav", "count": 1} in data["pending"]
    assert p._rl_dirty_names() == ["Port Nav", "Bow Nav"]


def test_payload_carries_running_light_rows(make_panel):
    p = make_panel()
    data = _payload(p)
    group = [r for r in data["subsystems"] if r.get("kind") == "rl_group"]
    assert len(group) == 1
    port = group[0]["children"][0]
    assert port["name"] == "Port Nav"
    assert port["spec"] == json.loads(json.dumps(_PORT))
    assert data["subsystems"][-1] == {"kind": "rl_add", "name": "+ Add"}


def test_payload_repushes_after_stage(make_panel):
    p = make_panel()
    _payload(p)
    assert p.render_payload() is None
    p._rl_stage("Port Nav", None)
    assert p.render_payload() is not None
