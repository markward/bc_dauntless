"""`edit_target_for` / `ShipPropertyViewerPanel._edit_target()` -- the per-kind
Move-tool adapters (plan docs/superpowers/plans/2026-09-29-spv-edit-target-
refactor.md, Task 2; spec S3-4). Built on the Task 1 characterisation panel,
which carries a target of every kind at once."""
from engine.ui.spv_edit_targets import (
    EmitterTarget, LightTarget, MountTarget, PartAnchorTarget, PartPoseTarget,
    edit_target_for)
from tests.ui.test_spv_edit_target_characterisation import (  # noqa: F401
    _SELECT, make_panel)


def test_edit_target_for_maps_each_active_target(make_panel):
    p = make_panel()
    for case, cls, key in [
        ("subsystem", MountTarget, ("subsystem", 0)),
        ("light_sphere", LightTarget, ("light", 1)),
        ("emitter_cone", EmitterTarget, ("emitter", 4, 2)),
        ("part_anchor", PartAnchorTarget, ("part_anchor", "wing")),
        ("part_pose", PartPoseTarget, ("part_pose", "wing", "red")),
    ]:
        assert p.dispatch_event(_SELECT[case]) is True
        t = p._edit_target()
        assert isinstance(t, cls) and t.key == key, case
        e = edit_target_for(p)
        assert type(e) is cls and e.key == key, case


def test_no_selection_has_no_edit_target(make_panel):
    p = make_panel()
    assert p._edit_target() is None
    assert edit_target_for(p) is None


def test_coord_kind_tags_unchanged(make_panel):
    p = make_panel()
    for case, tag in [
        ("subsystem", "mount"), ("light_box", "mount"),
        ("emitter_point", "mount"),
        ("part_anchor", "part_anchor"), ("part_pose", "part_pose"),
    ]:
        assert p.dispatch_event(_SELECT[case]) is True
        assert p._edit_target().coord_kind() == tag, case


def test_edit_target_is_not_cached_across_pose_state(make_panel):
    p = make_panel()
    assert p.dispatch_event(
        'part/select_node:{"name": "wing", "kind": "red"}') is True
    a = p._edit_target()
    assert p.dispatch_event(
        'part/select_node:{"name": "wing", "kind": "warp"}') is True
    b = p._edit_target()
    assert a.key[2] == "red" and b.key[2] == "warp"
    assert a is not b


def test_position_matches_panel_transform_coords(make_panel):
    p = make_panel()
    for case in ("subsystem", "light_cylinder", "emitter_strip",
                 "part_anchor", "part_pose"):
        assert p.dispatch_event(_SELECT[case]) is True
        if p.active_tool != "transform":
            p.dispatch_event("set_tool:transform")
        c = p.transform_coords()
        assert p._edit_target().position() == (c["x"], c["y"], c["z"]), case


def test_locked_follows_mount_editing_for_mounts_only(make_panel, monkeypatch):
    p = make_panel()
    monkeypatch.setattr(p, "_mount_editing_enabled", lambda: False)
    for case, locked in [("subsystem", True), ("light_sphere", True),
                         ("emitter_point", True), ("part_anchor", False)]:
        p._selected_emitter = None
        p._selected_light_index = None
        p.selected_index = None
        if case == "subsystem":
            p.selected_index = 0
        elif case == "light_sphere":
            p._selected_light_index = 1
        elif case == "emitter_point":
            p._selected_emitter = (4, 0)
        else:
            assert p.dispatch_event(_SELECT[case]) is True
        assert p._edit_target().locked is locked, case
        assert p._current_target_is_locked_mount() is locked, case
