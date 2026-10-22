"""SPV Physical tab, Python side (physical-parents spec section 7): the
`physical` payload (parts, groups, AUTO/SET rows, missing-part groups first),
the `physical/*` actions (tab, move, reset, move_all, reset_all), their undo
steps, the live preview overlay, Cancel, Save and the save-confirm tally.

Fixture mirrors tests/ui/test_ship_property_viewer_panel_part.py: a
Bird-of-Prey-shaped descriptor list, the model's part nodes set after open(),
and `part_severance.part_for_mount` patched so AUTO placement is a table.
"""
import json

import pytest

import App
from engine.appc import part_severance, physical_parents
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.properties import TGModelProperty, TGModelPropertySet
from engine.ui.ship_property_viewer import OrbitCamera
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel

_LEAF = "spvphysicaltest"

_PARTS = ["birdofprey", "left wing", "right wing outer", "head"]

# Body-frame mount -> the part the geometric rule (part_for_mount) answers.
_AUTO = {
    (-0.6, -0.5, 0.0): "left wing",
    (0.6, -0.5, 0.0): "right wing outer",
    (-0.9, -0.3, 0.0): "left wing",
    (0.9, -0.3, 0.0): "right wing outer",
    (0.0, 0.5, 0.0): "birdofprey",
    (-0.2, 0.1, 0.0): "left wing",
    (0.2, 0.1, 0.0): "right wing outer",
}


def _descriptor(name, pos, baked=None):
    return {
        "name": name, "kind": "subsystem", "icon_id": 1,
        "properties": {"position": pos, "radius": 0.3},
        "world_pos": pos, "parent_index": None,
        "light": False, "light_region": None, "emitters": [],
        "physical_parent": baked,
    }


def _bop_descriptors():
    return [
        _descriptor("Impulse Engines", (-0.6, -0.5, 0.0)),
        _descriptor("Warp Engines", (0.6, -0.5, 0.0)),
        _descriptor("Port Warp", (-0.9, -0.3, 0.0)),
        _descriptor("Star Warp", (0.9, -0.3, 0.0)),
        _descriptor("Sensor Array", (0.0, 0.5, 0.0)),
    ]


def _light(name, pos, parent=None):
    p = App.BlinkingLightProperty_Create(name)
    pt = TGPoint3()
    pt.SetXYZ(*pos)
    p.SetPosition(pt)
    p.SetPhysicalParent(parent)
    return p


class _Sub:
    def GetPosition(self):
        return (0.0, 0.0, 0.0)

    def GetProperty(self):
        return None

    def GetNumChildSubsystems(self):
        return 0


class _Ship:
    def __init__(self, lights=()):
        self._hull = _Sub()
        self._articulation_leaf = _LEAF
        self._articulation_poses = {}
        self._pset = TGModelPropertySet()
        for p in lights:
            self._pset.AddToSet("Scene Root", p)

    def GetHull(self):
        return self._hull

    def GetSensorSubsystem(self):
        return self._hull

    def GetWorldLocation(self):
        return TGPoint3(0.0, 0.0, 0.0)

    def GetWorldRotation(self):
        return TGMatrix3()

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
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: _LEAF)
    monkeypatch.setattr(
        part_severance, "part_for_mount",
        lambda leaf, point, iid=None: _AUTO.get(tuple(point)))

    def _make(descriptors=None, parts=None, lights=()):
        descs = descriptors if descriptors is not None else _bop_descriptors()
        monkeypatch.setattr(mod, "build_descriptors",
                            lambda ship: [dict(d) for d in descs])
        ship = _Ship(lights)
        p = ShipPropertyViewerPanel(ship_getter=lambda: ship)
        p.open()
        p._model_part_nodes = [
            {"name": n, "parent": "Scene Root", "candidate": True,
             "bounds_min": (0.0, 0.0, 0.0), "bounds_max": (1.0, 1.0, 1.0)}
            for n in (parts if parts is not None else _PARTS)]
        p.camera = OrbitCamera((0.0, 0.0, 0.0), 10.0, 0.0, 0.0)
        p._undo_stack.clear()
        return p
    make = _make
    make.target = target
    return make


def _payload(p):
    p._last_pushed = None
    js = p.render_payload()
    prefix = "setShipPropertyViewer("
    assert js.startswith(prefix) and js.endswith(");")
    return json.loads(js[len(prefix):-2])


def _physical(p):
    return _payload(p)["physical"]


def _act(p, verb, **arg):
    return p.dispatch_event("physical/%s:%s" % (verb, json.dumps(arg)))


def _group(phys, part):
    return next(g for g in phys["groups"] if g["part"] == part)


def _row(phys, name):
    for g in phys["groups"]:
        for r in g["rows"]:
            if r["name"] == name:
                return g["part"], r
    raise AssertionError("no row %r" % name)


def _baked(p, name):
    d = next(d for d in p._descriptors if d["name"] == name)
    return physical_parents.explicit_parent(
        _LEAF, physical_parents.PropRef(name, d.get("physical_parent")))


# ---------------------------------------------------------------------------


def test_physical_groups_auto_rows_by_part(make_panel):
    p = make_panel()
    phys = _physical(p)
    assert phys["tab"] == "functional"
    assert phys["parts"] == _PARTS
    assert [g["part"] for g in phys["groups"]] == _PARTS
    assert all(g["missing"] is False for g in phys["groups"])
    names = {g["part"]: [r["name"] for r in g["rows"]] for g in phys["groups"]}
    assert names == {
        "birdofprey": ["Sensor Array"],
        "left wing": ["Impulse Engines", "Port Warp"],
        "right wing outer": ["Warp Engines", "Star Warp"],
        "head": [],
    }
    _part, row = _row(phys, "Impulse Engines")
    assert row == {"key": "sub:0", "name": "Impulse Engines",
                   "kind": "subsystem", "source": "auto",
                   "chosen": False, "index": 0}


def test_move_sets_and_regroups(make_panel):
    p = make_panel()
    assert _act(p, "move", key="sub:0", part="birdofprey") is True
    phys = _physical(p)
    part, row = _row(phys, "Impulse Engines")
    assert part == "birdofprey"
    assert row["source"] == "set"
    assert p._pending_physical == {"Impulse Engines": "birdofprey"}
    assert _baked(p, "Impulse Engines") == "birdofprey"   # preview overlay
    # A physical edit never marks the Functional row dirty.
    assert not any(r.get("dirty") for r in _payload(p)["subsystems"])


def test_move_to_current_auto_part_confirms(make_panel):
    p = make_panel()
    assert _act(p, "move", key="sub:0", part="left wing") is True
    part, row = _row(_physical(p), "Impulse Engines")
    assert (part, row["source"]) == ("left wing", "set")
    assert p._pending_physical == {"Impulse Engines": "left wing"}


def test_move_on_a_set_row_to_its_own_part_is_a_no_op(make_panel):
    descs = _bop_descriptors()
    descs[0]["physical_parent"] = "birdofprey"
    p = make_panel(descs)
    assert _act(p, "move", key="sub:0", part="birdofprey") is True
    assert p._pending_physical == {}
    assert p._undo_stack == []


def test_move_to_an_unknown_part_is_refused(make_panel):
    p = make_panel()
    assert _act(p, "move", key="sub:0", part="no such part") is False
    assert _act(p, "move", key="sub:99", part="head") is False
    assert p._pending_physical == {}


def test_reset_to_auto(make_panel):
    descs = _bop_descriptors()
    descs[3]["physical_parent"] = "birdofprey"      # Star Warp baked SET
    p = make_panel(descs)
    part, row = _row(_physical(p), "Star Warp")
    assert (part, row["source"]) == ("birdofprey", "set")
    assert _act(p, "reset", key="sub:3") is True
    assert p._pending_physical == {"Star Warp": None}
    part, row = _row(_physical(p), "Star Warp")
    assert (part, row["source"]) == ("right wing outer", "auto")
    assert _baked(p, "Star Warp") is None


def test_reset_on_an_auto_row_is_inert(make_panel):
    p = make_panel()
    assert _act(p, "reset", key="sub:0") is True
    assert p._pending_physical == {}
    assert p._undo_stack == []


def test_missing_group_first_and_bulk_actions(make_panel):
    descs = _bop_descriptors()
    descs[1]["physical_parent"] = "left wing01"
    descs[3]["physical_parent"] = "left wing01"
    p = make_panel(descs)
    phys = _physical(p)
    first = phys["groups"][0]
    assert (first["part"], first["missing"]) == ("left wing01", True)
    assert [r["name"] for r in first["rows"]] == ["Warp Engines", "Star Warp"]
    assert all(r["source"] == "set" for r in first["rows"])
    assert [g["part"] for g in phys["groups"][1:]] == _PARTS
    assert "left wing01" not in phys["parts"]

    assert _act(p, "move_all", missing="left wing01",
                part="right wing outer") is True
    phys = _physical(p)
    assert not any(g["missing"] for g in phys["groups"])
    rows = _group(phys, "right wing outer")["rows"]
    assert [(r["name"], r["source"]) for r in rows] == [
        ("Warp Engines", "set"), ("Star Warp", "set")]
    # Only rows explicitly on the missing name were touched.
    assert p._pending_physical == {"Warp Engines": "right wing outer",
                                   "Star Warp": "right wing outer"}

    p.undo()
    assert _act(p, "reset_all", missing="left wing01") is True
    phys = _physical(p)
    assert not any(g["missing"] for g in phys["groups"])
    assert p._pending_physical == {"Warp Engines": None, "Star Warp": None}
    for name in ("Warp Engines", "Star Warp"):
        part, row = _row(phys, name)
        assert (part, row["source"]) == ("right wing outer", "auto")


def test_move_all_is_one_undo_step(make_panel):
    descs = _bop_descriptors()
    descs[1]["physical_parent"] = "left wing01"
    descs[3]["physical_parent"] = "left wing01"
    p = make_panel(descs)
    assert _act(p, "move", key="sub:4", part="head") is True
    depth = len(p._undo_stack)
    assert _act(p, "move_all", missing="left wing01", part="birdofprey") is True
    assert len(p._undo_stack) == depth + 1
    assert p.dispatch_event("undo") is True
    assert p._pending_physical == {"Sensor Array": "head"}
    assert _baked(p, "Warp Engines") == "left wing01"
    assert _baked(p, "Star Warp") == "left wing01"
    assert _physical(p)["groups"][0]["part"] == "left wing01"

    assert _act(p, "reset_all", missing="left wing01") is True
    assert len(p._undo_stack) == depth + 1
    assert p.dispatch_event("undo") is True
    assert _baked(p, "Warp Engines") == "left wing01"
    assert _baked(p, "Star Warp") == "left wing01"


def test_cancel_drops_pending_preview(make_panel):
    descs = _bop_descriptors()
    descs[3]["physical_parent"] = "right wing outer"
    p = make_panel(descs)
    assert _act(p, "move", key="sub:3", part="birdofprey") is True
    assert _act(p, "move", key="sub:0", part="birdofprey") is True
    assert _baked(p, "Star Warp") == "birdofprey"
    assert p.dispatch_event("cancel") is True
    assert physical_parents.explicit_parent(
        _LEAF, physical_parents.PropRef("Star Warp", "right wing outer")) \
        == "right wing outer"
    assert physical_parents.explicit_parent(
        _LEAF, physical_parents.PropRef("Impulse Engines", None)) is None
    assert p._pending_physical == {}


def test_save_emits_edits_and_tally(make_panel):
    descs = _bop_descriptors()
    descs[3]["physical_parent"] = "right wing outer"
    p = make_panel(descs)
    _act(p, "move", key="sub:0", part="birdofprey")
    _act(p, "reset", key="sub:3")
    assert p._pending_edits() == [{"name": "Impulse Engines", "count": 1},
                                  {"name": "Star Warp", "count": 1}]
    assert _payload(p)["pending_count"] == 2
    assert p.dispatch_event("save") is True
    leaf, edits = make_panel.target.calls[-1]
    assert leaf == _LEAF
    assert sorted(e for e in edits if "SetPhysicalParent" in e) == sorted([
        ("Impulse Engines", "SetPhysicalParent", ("birdofprey",)),
        ("Star Warp", "__unset__", "SetPhysicalParent"),
    ])
    assert p._pending_physical == {}
    assert p._saved_physical == {"Impulse Engines": "birdofprey",
                                 "Star Warp": None}
    assert p._pending_edits() == []
    # Saved choices keep driving the session until the next ship build.
    assert _baked(p, "Impulse Engines") == "birdofprey"
    assert _baked(p, "Star Warp") is None
    part, row = _row(_physical(p), "Impulse Engines")
    assert (part, row["source"]) == ("birdofprey", "set")


def test_running_lights_listed(make_panel):
    lights = [_light("Port Nav", (-0.2, 0.1, 0.0)),
              _light("Star Nav", (0.2, 0.1, 0.0), parent="birdofprey"),
              App.BlinkingLightProperty_Create("Unplaced")]   # no position
    p = make_panel(lights=lights)
    phys = _physical(p)
    part, row = _row(phys, "Port Nav")
    assert part == "left wing"
    assert row == {"key": "light:Port Nav", "name": "Port Nav",
                   "kind": "running_light", "source": "auto",
                   "chosen": False, "index": None}
    part, row = _row(phys, "Star Nav")
    assert (part, row["source"]) == ("birdofprey", "set")
    # Lights follow the descriptor rows in a group.
    assert [r["name"] for r in _group(phys, "birdofprey")["rows"]] == [
        "Sensor Array", "Star Nav"]
    with pytest.raises(AssertionError):
        _row(phys, "Unplaced")

    assert _act(p, "move", key="light:Port Nav", part="head") is True
    assert p._pending_physical == {"Port Nav": "head"}
    part, row = _row(_physical(p), "Port Nav")
    assert (part, row["source"]) == ("head", "set")


def test_physical_actions_allowed_under_pose_lock(make_panel, monkeypatch):
    p = make_panel()
    monkeypatch.setattr(p, "_mount_lock_state_and_reason",
                        lambda: (True, "posed"))
    assert p.dispatch_event('set_radius:{"i":0,"value":0.9}') is False
    assert _act(p, "move", key="sub:0", part="birdofprey") is True
    assert _act(p, "reset", key="sub:0") is True
    assert _act(p, "tab", tab="physical") is True
    assert p._systems_tab == "physical"


def test_tab_switch_is_not_an_edit(make_panel):
    p = make_panel()
    assert _act(p, "tab", tab="physical") is True
    assert p._systems_tab == "physical"
    assert _physical(p)["tab"] == "physical"
    assert p._pending_edits() == []
    assert p._undo_stack == []
    assert _act(p, "tab", tab="bogus") is False
    assert p._systems_tab == "physical"
    assert _act(p, "tab", tab="functional") is True
    assert _physical(p)["tab"] == "functional"


def test_auto_grouping_ignores_an_unsaved_position(make_panel, monkeypatch):
    """A staged (dragged) position never reaches the sim, so an Auto row
    stays where the committed mount puts it -- and a drag never feeds a new
    point per frame to the model query."""
    seen = []

    def fake(leaf, point, iid=None):
        seen.append(tuple(point))
        return _AUTO.get(tuple(point))
    monkeypatch.setattr(part_severance, "part_for_mount", fake)
    p = make_panel()
    p.set_subsystem_position(0, (0.2, 0.1, 0.0))       # staged, unsaved
    part, _row_ = _row(_physical(p), "Impulse Engines")
    assert part == "left wing"
    assert (0.2, 0.1, 0.0) not in seen
    p._saved_pos[0] = (0.9, -0.3, 0.0)                 # saved this session
    part, _row_ = _row(_physical(p), "Impulse Engines")
    assert part == "right wing outer"


def test_chosen_follows_the_selected_subsystem(make_panel):
    p = make_panel()
    assert p.dispatch_event("select_pin:2") is True
    _part, row = _row(_physical(p), "Port Warp")
    assert row["chosen"] is True
    _part, row = _row(_physical(p), "Impulse Engines")
    assert row["chosen"] is False


def test_selected_pin_resolves_through_its_physical_parent(make_panel,
                                                           monkeypatch):
    from engine.appc import articulation
    seen = []

    def fake(ship, point, part=None, *, authored=True, prop=None):
        seen.append(prop)
        return point
    monkeypatch.setattr(articulation, "part_transform_point", fake)
    descs = _bop_descriptors()
    descs[1]["physical_parent"] = "birdofprey"
    p = make_panel(descs)
    p._effective_world_pos(1)
    assert seen[-1] == physical_parents.PropRef("Warp Engines", "birdofprey")


def test_build_descriptors_carries_baked_physical_parent(monkeypatch):
    import engine.ui.ship_property_viewer as spv

    class _S:
        def __init__(self, name, parent):
            self._prop = TGModelProperty(name)
            self._prop.SetPhysicalParent(parent)
            self._name = name

        def GetName(self):
            return self._name

        def GetPosition(self):
            return TGPoint3(0.0, 1.0, 0.0)

        def GetProperty(self):
            return self._prop

    class _NoProp(_S):
        def GetProperty(self):
            return None

    subs = [_S("Impulse Engines", "birdofprey"), _S("Port Warp", None),
            _NoProp("Abstract", None)]
    monkeypatch.setattr(spv, "_icon_id_for", lambda sub: 2)
    monkeypatch.setattr(spv, "_iter_subsystems", lambda ship: subs)
    descs = spv.build_descriptors(_Ship())
    assert [d["physical_parent"] for d in descs] == ["birdofprey", None, None]


# ---------------------------------------------------------------------------
# Save reaches the LIVE ship: the property objects themselves are updated,
# so the preview overlay carries pending edits only and nothing that clears
# it (another ship opened, close, Cancel) can undo a save.
# ---------------------------------------------------------------------------


class _LiveSub:
    def __init__(self, name, pos, parent=None):
        self._name = name
        self._pos = TGPoint3(*pos)
        self._prop = TGModelProperty(name)
        self._prop.SetPhysicalParent(parent)

    def GetName(self):
        return self._name

    def GetPosition(self):
        return self._pos

    def GetProperty(self):
        return self._prop


@pytest.fixture
def live(monkeypatch):
    """Live subsystems behind the BoP descriptors, by name, walked by
    `ship_property_viewer._iter_subsystems` as build_descriptors walks them."""
    import engine.ui.ship_property_viewer as spv
    subs = {}

    def _install(descs):
        subs.clear()
        for d in descs:
            subs[d["name"]] = _LiveSub(d["name"], d["properties"]["position"],
                                       d.get("physical_parent"))
        monkeypatch.setattr(spv, "_iter_subsystems",
                            lambda ship: list(subs.values()))
        return subs
    return _install


def _live_parent(subs, name):
    return subs[name].GetProperty().GetPhysicalParent()


def test_save_applies_to_live_property(make_panel, live):
    descs = _bop_descriptors()
    subs = live(descs)
    p = make_panel(descs)
    _act(p, "move", key="sub:0", part="birdofprey")
    assert _live_parent(subs, "Impulse Engines") is None    # pending only
    assert p.dispatch_event("save") is True
    assert _live_parent(subs, "Impulse Engines") == "birdofprey"
    assert _live_parent(subs, "Warp Engines") is None       # untouched


def test_saved_choice_survives_overlay_clear(make_panel, live):
    descs = _bop_descriptors()
    subs = live(descs)
    p = make_panel(descs)
    _act(p, "move", key="sub:0", part="birdofprey")
    assert p.dispatch_event("save") is True
    physical_parents.clear_preview()
    assert physical_parents.explicit_parent(
        _LEAF, subs["Impulse Engines"].GetProperty()) == "birdofprey"
    # The panel's own rows read the saved value too, overlay or not.
    part, row = _row(_physical(p), "Impulse Engines")
    assert (part, row["source"]) == ("birdofprey", "set")


def test_saved_reset_sets_live_none(make_panel, live):
    descs = _bop_descriptors()
    descs[3]["physical_parent"] = "birdofprey"
    subs = live(descs)
    p = make_panel(descs)
    _act(p, "reset", key="sub:3")
    assert p.dispatch_event("save") is True
    assert _live_parent(subs, "Star Warp") is None
    physical_parents.clear_preview()
    part, row = _row(_physical(p), "Star Warp")
    assert (part, row["source"]) == ("right wing outer", "auto")


def test_overlay_holds_only_pending_after_save(make_panel, live):
    descs = _bop_descriptors()
    live(descs)
    p = make_panel(descs)
    _act(p, "move", key="sub:0", part="birdofprey")
    assert p.dispatch_event("save") is True
    assert physical_parents._preview.get(_LEAF) is None
    _act(p, "move", key="sub:1", part="head")
    assert physical_parents._preview.get(_LEAF) == {"Warp Engines": "head"}
    assert p.dispatch_event("cancel") is True
    assert physical_parents._preview.get(_LEAF) is None


def test_failed_save_applies_nothing(make_panel, live, monkeypatch):
    descs = _bop_descriptors()
    subs = live(descs)
    p = make_panel(descs)

    def boom(leaf, edits):
        raise OSError("disk full")
    monkeypatch.setattr(make_panel.target, "write", boom)
    _act(p, "move", key="sub:0", part="birdofprey")
    assert p.dispatch_event("save") is True
    assert _live_parent(subs, "Impulse Engines") is None
    assert p._pending_physical == {"Impulse Engines": "birdofprey"}
    assert p._saved_physical == {}


def test_saved_running_light_applies_to_its_property(make_panel):
    lights = [_light("Port Nav", (-0.2, 0.1, 0.0))]
    p = make_panel(lights=lights)
    _act(p, "move", key="light:Port Nav", part="head")
    assert p.dispatch_event("save") is True
    assert lights[0].GetPhysicalParent() == "head"
