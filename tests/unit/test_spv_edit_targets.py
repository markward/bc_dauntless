"""`edit_target_for` / `ShipPropertyViewerPanel._edit_target()` -- the per-kind
Move-tool adapters (plan docs/superpowers/plans/2026-09-29-spv-edit-target-
refactor.md, Task 2; spec S3-4). Built on the Task 1 characterisation panel,
which carries a target of every kind at once."""
from engine.ui.spv_edit_targets import (
    EmitterTarget, LightTarget, MountTarget, PartAnchorTarget, PartPoseTarget,
    edit_target_for)
from tests.ui.spv_test_fixtures import (  # noqa: F401  (make_panel: fixture)
    _SELECT, _diff, _r, _staged, make_panel)


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


# Scale tool (plan Task 3) ----------------------------------------------------

def test_scale_kind_matches_characterised_scale_payload(make_panel):
    """`scale_kind()` is the (kind, fields) tuple `scale_values` has always
    been built from -- pinned against the characterisation suite's record."""
    from tests.ui.test_spv_edit_target_characterisation import (
        EXPECTED_PAYLOADS)
    p = make_panel()
    for case in ("subsystem", "light_sphere", "light_cylinder", "light_box",
                 "emitter_point", "emitter_strip", "emitter_cone"):
        assert p.dispatch_event(_SELECT[case]) is True
        kind, fields = p._edit_target().scale_kind()
        want = EXPECTED_PAYLOADS[case][2]
        assert isinstance(fields, list), case
        assert (kind, _r(fields)) == (want["kind"], want["fields"]), case


def test_part_targets_have_no_scale(make_panel):
    p = make_panel()
    for case in ("part_anchor", "part_pose"):
        assert p.dispatch_event(_SELECT[case]) is True
        t = p._edit_target()
        assert t.scale_spec() is None, case
        assert t.scale_kind() == ("none", []), case


def test_scale_spec_and_get_scale_on_a_box_light(make_panel):
    p = make_panel()
    assert p.dispatch_event(_SELECT["light_box"]) is True
    t = p._edit_target()
    assert t.scale_spec()["kind"] == "xyz"
    assert t.get_scale() == (0.3, 0.5, 0.2)
    t.set_scale_field(1, 0.9)
    assert t.get_scale() == (0.3, 0.9, 0.2)


# Rotate tool (plan Task 4) ---------------------------------------------------

def test_rotate_kind_matches_characterised_clipboard_tag(make_panel):
    """`rotate_kind()` is today's rotate-clipboard tag, per case -- pinned
    against the characterisation suite's record."""
    from tests.ui.test_spv_edit_target_characterisation import (
        EXPECTED_CLIP_TAGS)
    p = make_panel()
    for case in ("subsystem", "light_sphere", "light_cylinder", "light_box",
                 "emitter_point", "emitter_strip", "emitter_cone",
                 "part_anchor", "part_pose"):
        assert p.dispatch_event(_SELECT[case]) is True
        assert p._edit_target().rotate_kind() == EXPECTED_CLIP_TAGS[case][2], case


def test_cylinder_light_and_strip_emitter_share_cylinder_axis(make_panel):
    p = make_panel()
    for case in ("light_cylinder", "emitter_strip"):
        assert p.dispatch_event(_SELECT[case]) is True
        t = p._edit_target()
        assert t.rotate_kind() == "cylinder_axis", case
        assert t.rotate_spec()["clipboard_kind"] == "cylinder_axis", case


def test_non_rotating_targets_have_no_rotate_spec(make_panel):
    p = make_panel()
    for case in ("light_sphere", "emitter_point", "subsystem", "part_anchor"):
        assert p.dispatch_event(_SELECT[case]) is True
        t = p._edit_target()
        assert t.rotate_spec() is None, case
        assert t.rotate_kind() is None, case


def test_get_rotation_is_what_rotate_copy_stores(make_panel):
    """`(rotate_kind(), get_rotation())` is exactly the rotate clipboard
    entry `rotate_copy` writes, for every rotating kind."""
    for case in ("light_cylinder", "light_box", "emitter_strip",
                 "emitter_cone", "part_pose"):
        p = make_panel()
        assert p.dispatch_event(_SELECT[case]) is True
        if p.active_tool != "rotate":
            p.dispatch_event("set_tool:rotate")
        t = p._edit_target()
        assert p.dispatch_event("rotate_copy") is True
        assert p._rotate_clipboard == (t.rotate_kind(), t.get_rotation()), case


def test_set_rotation_round_trips_a_pose(make_panel):
    p = make_panel()
    assert p.dispatch_event(_SELECT["part_pose"]) is True
    t = p._edit_target()
    t.set_rotation((5.0, 10.0, -15.0))
    assert t.get_rotation() == (5.0, 10.0, -15.0)


# Pipette and Mirror Element (plan Task 5) ------------------------------------

_KEYS = {"subsystem": ("subsystem", 0), "light_sphere": ("light", 1),
         "light_cylinder": ("light", 2), "light_box": ("light", 3),
         "emitter_point": ("emitter", 4, 0), "emitter_strip": ("emitter", 4, 1),
         "emitter_cone": ("emitter", 4, 2)}

# Staged-spec key the characterisation suite records -> pipette field.
_FIELD_OF = {"position": "position", "axis": "rotation", "up": "rotation",
             "orientation": "rotation", "radius": "scale", "radius_y": "scale",
             "length": "scale", "extent": "scale", "scale": "scale",
             "color": "colour", "intensity": "colour"}


def test_pipette_fields_from_matches_characterised_pipette(make_panel):
    """For every ordered pair of hardpoint cases, the fields the adapter
    says it copies are exactly the ones the characterisation suite saw
    change, in the order ("position", "rotation", "scale", "colour")."""
    from engine.ui.spv_edit_targets import edit_target_for_key
    from tests.ui.test_spv_edit_target_characterisation import EXPECTED_PIPETTE
    order = ("position", "rotation", "scale", "colour")
    p = make_panel()
    for tgt in _KEYS:
        for src in _KEYS:
            if src == tgt:
                continue
            changed, _armed = EXPECTED_PIPETTE[tgt][1][src]
            want = {_FIELD_OF[k] for k in changed}
            got = edit_target_for_key(p, _KEYS[tgt]).pipette_fields_from(
                edit_target_for_key(p, _KEYS[src]))
            assert set(got) == want, (src, tgt)
            assert list(got) == [f for f in order if f in got], (src, tgt)


def test_part_targets_take_no_pipette_fields(make_panel):
    from engine.ui.spv_edit_targets import edit_target_for_key
    p = make_panel()
    src = edit_target_for_key(p, _KEYS["subsystem"])
    for key in (("part_anchor", "wing"), ("part_pose", "wing", "red")):
        assert edit_target_for_key(p, key).pipette_fields_from(src) == ()


def test_mirror_is_mirror_element(make_panel):
    """`EditTarget.mirror()` is the whole Mirror Element: position x-flip
    plus the rotation mirror -- pinned against the characterisation
    record of `mirror_element`."""
    from tests.ui.test_spv_edit_target_characterisation import (
        EXPECTED_MIRRORS)
    for case in ("subsystem", "light_sphere", "light_cylinder", "light_box",
                 "emitter_point", "emitter_strip", "emitter_cone",
                 "part_anchor", "part_pose"):
        p = make_panel()
        assert p.dispatch_event(_SELECT[case]) is True
        before = _staged(p, case)
        p._edit_target().mirror()
        assert _diff(before, _staged(p, case)) == EXPECTED_MIRRORS[case][2][1], case


def test_grab_allowed_defaults_true_for_non_decal_kinds(make_panel):
    """Only a decal restricts which gizmo handles grab; every other kind
    takes any handle under every tool."""
    from engine.ui.spv_edit_targets import edit_target_for_key
    p = make_panel()
    for key in (("subsystem", 0), ("light", 1), ("emitter", 4, 2),
                ("part_anchor", "wing"), ("part_pose", "wing", "red")):
        t = edit_target_for_key(p, key)
        for tool in ("transform", "rotate", "scale"):
            assert all(t.grab_allowed(tool, h) for h in range(3)), (key, tool)
