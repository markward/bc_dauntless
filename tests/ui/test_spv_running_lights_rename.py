"""SPV running lights: renaming a light (follow-up 2026-10-23 on spec
docs/superpowers/specs/2026-10-22-spv-running-lights-design.md).

A light may be renamed when it was added this session, when Dauntless code
created it (a stock leaf's attach-queued name), or when the ship's hardpoints
are a mod's own file. Any other stock light is a template from the game's own
hardpoint file -- keyed by name -- and stays locked. `rl/edit` with a new
`spec.name` stages the rename; Save emits `(original, "__rename_light__",
new)` before the light's spec edit.

Built on the pane fixture (`make_panel`: one subsystem "Sub", two baked
lights "Port Nav" / "Star Nav" on a stock leaf)."""
import json

import pytest

from engine.appc import attach_templates, override_routing
from tests.ui import spv_test_fixtures as fx
from tests.ui.test_spv_running_lights_pane import (  # noqa: F401 (fixture)
    _BOW, _PORT, _STAR, _group, _light_names, _payload, make_panel)

_VERB = "__running_light__"
_LOCK = "Named in the game's hardpoint file"


@pytest.fixture
def attached(monkeypatch):
    """The stock leaf's attach-queued names: "Port Nav" was created by
    Dauntless, "Star Nav" is the game's own template."""
    monkeypatch.setattr(attach_templates, "_attached",
                        {fx.UNRIGGED_LEAF: {"Port Nav"}})


def _edit(p, name, spec):
    return p.dispatch_event("rl/edit:" + json.dumps({"name": name, "spec": spec}))


def _rename(p, old, new, spec=None):
    base = dict(spec if spec is not None else p._rl_spec(old))
    base["name"] = new
    return _edit(p, old, base)


def _rows(p):
    return {c["name"]: c for c in _group(_payload(p)["subsystems"])["children"]}


def _save(p, make):
    assert p.dispatch_event("save") is True
    return make.target.calls[-1][1]


# --- which lights are renameable ----------------------------------------------

def test_renameable_flag_and_lock_reason_in_the_payload(make_panel, attached):
    p = make_panel()
    rows = _rows(p)
    assert rows["Port Nav"]["renameable"] is True
    assert "rename_lock_reason" not in rows["Port Nav"]
    assert rows["Star Nav"]["renameable"] is False
    assert rows["Star Nav"]["rename_lock_reason"] == _LOCK
    # A light added this session is always renameable.
    p._rl_stage("Bow Nav", dict(_BOW))
    assert _rows(p)["Bow Nav"]["renameable"] is True


def test_every_light_of_a_mod_file_is_renameable(make_panel, monkeypatch,
                                                 tmp_path):
    import engine.ui.ship_property_viewer_panel as mod
    target = override_routing.ModHardpointFileTarget(str(tmp_path / "x.py"))
    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: target)
    monkeypatch.setattr(attach_templates, "_attached", {})
    p = make_panel()
    assert {n: r["renameable"] for n, r in _rows(p).items()} == {
        "Port Nav": True, "Star Nav": True}


def test_the_stock_target_does_not_rename_any_light():
    assert override_routing.HardpointOverridesFileTarget.renames_any_light is False
    assert override_routing.ModHardpointFileTarget.renames_any_light is True


# --- staging ------------------------------------------------------------------

def test_rename_a_pending_add_rekeys_it(make_panel, attached):
    p = make_panel()
    p._rl_stage("Bow Nav", dict(_BOW))
    p._rl_stage("Keel Nav", dict(_BOW, name="Keel Nav"))
    assert _rename(p, "Bow Nav", "Fore Nav") is True
    assert list(p._pending_running_light) == ["Fore Nav", "Keel Nav"]
    assert p._pending_running_light["Fore Nav"]["name"] == "Fore Nav"
    assert p._pending_rl_renames == {}
    assert _light_names(p) == ["Port Nav", "Star Nav", "Fore Nav", "Keel Nav"]


def test_rename_a_baked_light_is_one_change(make_panel, attached):
    p = make_panel()
    assert _rename(p, "Port Nav", "Bow Light") is True
    assert p._pending_rl_renames == {"Bow Light": "Port Nav"}
    assert p._pending_running_light == {}
    # Same place in the list, under the new name.
    assert _light_names(p) == ["Bow Light", "Star Nav"]
    assert p._rl_spec("Bow Light") == dict(_PORT, name="Bow Light")
    data = _payload(p)
    assert data["pending_count"] == 1
    assert data["pending"] == [{"name": "Bow Light", "count": 1}]
    assert _rows(p)["Bow Light"]["dirty"] is True
    assert _rows(p)["Bow Light"]["renameable"] is True


def test_rename_with_a_spec_change_counts_both(make_panel, attached):
    p = make_panel()
    assert _rename(p, "Port Nav", "Bow Light",
                   dict(_PORT, color=(0.0, 0.0, 1.0))) is True
    assert p._pending_running_light["Bow Light"]["color"] == (0.0, 0.0, 1.0)
    assert {"name": "Bow Light", "count": 2} in _payload(p)["pending"]


def test_chained_rename_collapses_and_rename_back_drops_it(make_panel, attached):
    p = make_panel()
    assert _rename(p, "Port Nav", "Bow Light") is True
    assert _rename(p, "Bow Light", "Third") is True
    assert p._pending_rl_renames == {"Third": "Port Nav"}
    assert _light_names(p) == ["Third", "Star Nav"]
    assert _rename(p, "Third", "Port Nav") is True
    assert p._pending_rl_renames == {}
    assert p._pending_running_light == {}
    assert _light_names(p) == ["Port Nav", "Star Nav"]
    assert _payload(p)["pending_count"] == 0


def test_rename_onto_a_taken_name_is_refused(make_panel, attached):
    p = make_panel()
    for taken in ("Star Nav", "Sub"):
        assert _rename(p, "Port Nav", taken) is False
        assert "already exists" in p._rl_error
    assert p._pending_rl_renames == {} and p._pending_running_light == {}
    assert p._undo_stack == []
    # Padding around its own name is not a rename.
    assert _rename(p, "Port Nav", "  Port Nav ") is True
    assert p._pending_rl_renames == {}


def test_rename_to_a_non_ascii_name_is_refused(make_panel, attached):
    p = make_panel()
    assert _rename(p, "Port Nav", "Bug Ünïcode") is False
    assert "plain letters, numbers and punctuation" in p._rl_error
    assert p._pending_rl_renames == {} and p._pending_running_light == {}


def test_rename_onto_a_name_the_file_still_holds_is_refused(make_panel,
                                                            attached):
    """A name staged for removal, or renamed away, is still in the file
    until Save: neither writer can free and retake it in one save."""
    p = make_panel()
    p._rl_stage("Bow Nav", dict(_BOW))
    assert p.dispatch_event('rl/remove:{"name": "Star Nav"}') is True
    assert _rename(p, "Bow Nav", "Star Nav") is False
    assert "removed or renamed" in p._rl_error
    assert _rename(p, "Port Nav", "Fore Nav") is True
    assert _rename(p, "Bow Nav", "Port Nav") is False
    assert "removed or renamed" in p._rl_error
    # ...but a light may always go back to its own original name.
    assert _rename(p, "Fore Nav", "Port Nav") is True
    assert p._pending_rl_renames == {}


def test_rename_of_a_locked_light_is_refused(make_panel, attached):
    p = make_panel()
    assert _rename(p, "Star Nav", "Renamed") is False
    assert p._rl_error == _LOCK
    assert p._pending_rl_renames == {} and p._pending_running_light == {}
    assert _light_names(p) == ["Port Nav", "Star Nav"]
    # Its other fields still edit under the fixed name.
    assert _edit(p, "Star Nav", dict(_STAR, radius=1.0)) is True
    assert p._pending_running_light["Star Nav"]["radius"] == 1.0


def test_physical_parent_and_selection_follow_the_rename(make_panel, attached):
    p = make_panel()
    assert p.dispatch_event('rl/select:{"name": "Port Nav"}') is True
    p._pending_physical["Port Nav"] = "wing"
    assert _rename(p, "Port Nav", "Bow Light") is True
    assert p._pending_physical == {"Bow Light": "wing"}
    assert p._rl_selected == "Bow Light"
    assert p._active_transform_target() == ("running_light", "Bow Light")
    assert _rows(p)["Bow Light"]["chosen"] is True


def test_baked_parent_shows_on_the_renamed_light(make_panel, attached):
    p = make_panel()
    p._physical_lights[0]["physical_parent"] = "left wing"
    assert _rename(p, "Port Nav", "Bow Light") is True
    entry = p._physical_entry("light:Bow Light")
    assert p._physical_committed(entry) == "left wing"
    assert p._physical_explicit(entry) == "left wing"
    assert p._pending_physical == {}


def test_undo_restores_the_old_name(make_panel, attached):
    p = make_panel()
    assert p.dispatch_event('rl/select:{"name": "Port Nav"}') is True
    assert _rename(p, "Port Nav", "Bow Light") is True
    assert p.dispatch_event("undo") is True
    assert _light_names(p) == ["Port Nav", "Star Nav"]
    assert p._pending_rl_renames == {}


def test_remove_a_renamed_light_removes_the_original(make_panel, attached):
    p = make_panel()
    assert _rename(p, "Port Nav", "Bow Light") is True
    assert p.dispatch_event('rl/remove:{"name": "Bow Light"}') is True
    assert p._pending_rl_renames == {}
    assert p._pending_running_light == {"Port Nav": None}
    assert _light_names(p) == ["Star Nav"]


def test_open_and_close_drop_staged_renames(make_panel, attached):
    p = make_panel()
    assert _rename(p, "Port Nav", "Bow Light") is True
    p.close()
    p.open()
    assert p._pending_rl_renames == {}
    assert _light_names(p) == ["Port Nav", "Star Nav"]


# --- Save ---------------------------------------------------------------------

def test_save_emits_the_rename_before_the_spec_edit(make_panel, attached):
    p = make_panel()
    edited = dict(_PORT, name="Bow Light", color=(0.0, 0.0, 1.0))
    assert _rename(p, "Port Nav", "Bow Light", edited) is True
    edits = _save(p, make_panel)
    rename = ("Port Nav", "__rename_light__", "Bow Light")
    spec = ("Bow Light", _VERB, {"spec": edited, "new": False})
    assert rename in edits and spec in edits
    assert edits.index(rename) < edits.index(spec)
    # Renames precede every other hardpoint edit (a parent set for the new
    # name must not exist before the rename).
    assert edits.index(rename) == 0
    assert p._pending_rl_renames == {}
    assert _light_names(p) == ["Bow Light", "Star Nav"]
    assert _rows(p)["Bow Light"]["dirty"] is False
    # The saved overlay survives a reopen, and the light stays renameable.
    p.close()
    p.open()
    assert _light_names(p) == ["Bow Light", "Star Nav"]
    assert _rows(p)["Bow Light"]["renameable"] is True
    assert _rename(p, "Bow Light", "Fourth") is True
    assert p._pending_rl_renames == {"Fourth": "Bow Light"}
    edits = _save(p, make_panel)
    assert edits[0] == ("Bow Light", "__rename_light__", "Fourth")
    assert _light_names(p) == ["Fourth", "Star Nav"]


def test_renamed_light_stays_renameable_when_the_leaf_rerecords(make_panel,
                                                                attached):
    """Another build of the leaf after the saved rename (an NPC of the same
    class) re-records the attach queue under the NEW name only; the viewed
    ship still has the old name baked."""
    p = make_panel()
    assert _rename(p, "Port Nav", "Bow Light") is True
    _save(p, make_panel)
    attach_templates._attached[fx.UNRIGGED_LEAF] = {"Bow Light"}
    p.close()
    p.open()
    row = _rows(p)["Bow Light"]
    assert row["renameable"] is True
    assert "rename_lock_reason" not in row
    # The game's own template stays locked.
    assert _rows(p)["Star Nav"]["renameable"] is False


def test_save_pure_rename_has_no_spec_edit(make_panel, attached):
    p = make_panel()
    assert _rename(p, "Port Nav", "Bow Light") is True
    assert _save(p, make_panel) == [("Port Nav", "__rename_light__", "Bow Light")]


def test_save_renamed_pending_add_is_just_created(make_panel, attached):
    p = make_panel()
    p._rl_stage("Bow Nav", dict(_BOW))
    assert _rename(p, "Bow Nav", "Fore Nav") is True
    assert _save(p, make_panel) == [("Fore Nav", _VERB, {
        "spec": dict(_BOW, name="Fore Nav"), "new": True})]


def test_save_moves_an_explicit_parent_to_the_new_name(make_panel, attached):
    p = make_panel()
    p._physical_lights[0]["physical_parent"] = "left wing"
    assert _rename(p, "Port Nav", "Bow Light") is True
    edits = _save(p, make_panel)
    unset = ("Port Nav", "__unset__", "SetPhysicalParent")
    move = ("Bow Light", "SetPhysicalParent", ("left wing",))
    assert unset in edits and move in edits
    assert edits.index(unset) > 0 and edits.index(move) > 0
    entry = p._physical_entry("light:Bow Light")
    assert p._physical_committed(entry) == "left wing"
    # A later light under the old name does not inherit the parent.
    p._rl_stage("Port Nav", dict(_PORT))
    assert p._physical_committed(p._physical_entry("light:Port Nav")) is None


def test_save_a_staged_parent_is_not_overridden_by_the_move(make_panel,
                                                            attached):
    p = make_panel()
    p._physical_lights[0]["physical_parent"] = "left wing"
    assert _rename(p, "Port Nav", "Bow Light") is True
    p._pending_physical["Bow Light"] = "nacelle"
    edits = _save(p, make_panel)
    assert ("Bow Light", "SetPhysicalParent", ("nacelle",)) in edits
    assert ("Bow Light", "SetPhysicalParent", ("left wing",)) not in edits
    entry = p._physical_entry("light:Bow Light")
    assert p._physical_committed(entry) == "nacelle"


def test_save_rename_then_a_new_light_under_the_old_name(make_panel, attached):
    p = make_panel()
    assert _rename(p, "Port Nav", "Bow Light") is True
    p._rl_stage("Port Nav", dict(_PORT, radius=2.0))
    assert _rows(p)["Port Nav"]["renameable"] is True
    edits = _save(p, make_panel)
    assert edits.index(("Port Nav", "__rename_light__", "Bow Light")) < edits.index(
        ("Port Nav", _VERB, {"spec": dict(_PORT, radius=2.0), "new": True}))
    assert _light_names(p) == ["Bow Light", "Star Nav", "Port Nav"]
