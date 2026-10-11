"""Bridge Editor dev panel (spec 2026-10-08-bridge-emitters §4, §7, §8)."""
import json

import pytest

from engine.bridge_editor import lighting_doc as ld
from engine.ui import bridge_emitters_panel as bep

HASH = "0123456789abcdef"
INFO = {
    "source": "/abs/Dbridge.NIF", "content_hash": HASH,
    "meshes": [
        {"mesh": 0, "block": 3, "name": "floor", "node_chain": ["Scene Root"],
         "textures": [], "material": 0},
        {"mesh": 1, "block": 7, "name": "redalertpanel",
         "node_chain": ["Scene Root", "Red On GlowAlpha"],
         "textures": ["redalertpanel.tga"], "material": 1,
         "maps": {"roughness": True, "metalness": False, "normal": False}},
        # Stock DBridge: every shape is unnamed; the owning node names it.
        {"mesh": 2, "block": 11, "name": "",
         "node_chain": ["", "Gamma", "wall side pnls 11"],
         "textures": ["Map 20.tga"], "material": 2},
    ],
}
POSE = ((0.0, 0.0, 50.0), (0.0, 1.0, 50.0), (0.0, 0.0, 1.0), 0.785398)


class FakeIO:
    """`layers` = the meshes stacked front-to-back under the cursor."""

    def __init__(self, hit_mesh=1):
        self.layers = [hit_mesh]
        self.highlights = []
        self.traces = []

    @property
    def hit_mesh(self):
        return self.layers[0] if self.layers else None

    @hit_mesh.setter
    def hit_mesh(self, mesh):
        self.layers = [] if mesh is None else [mesh]

    def model_identity(self, iid):
        return INFO

    def ray_trace_mesh_pick(self, iid, origin, direction, max_dist, exclude=()):
        self.traces.append((origin, direction, tuple(exclude)))
        mesh = next((m for m in self.layers if m not in exclude), None)
        if mesh is None:
            return None
        return ((0, 10, 50), (0, -1, 0), 10.0, mesh, 0)

    def set_bridge_highlight(self, iid, selected, hover):
        self.highlights.append((iid, selected, hover))


class FakeKeys:
    MOUSE_BUTTON_LEFT, MOUSE_BUTTON_RIGHT = 0, 1
    KEY_W, KEY_S, KEY_A, KEY_D, KEY_Q, KEY_E = 10, 11, 12, 13, 14, 15
    KEY_LEFT_SHIFT, KEY_RIGHT_SHIFT, KEY_LEFT_ALT, KEY_RIGHT_ALT = 20, 21, 22, 23


class FakeH:
    keys = FakeKeys

    def __init__(self):
        self.buttons = set()
        self.held = set()
        self.cursor = (400.0, 300.0)
        self.delta = (0.0, 0.0)
        self.locked = []
        self.scroll = 0.0

    def consume_scroll_y(self):
        v, self.scroll = self.scroll, 0.0
        return v

    def mouse_button_state(self, b):
        return b in self.buttons

    def key_state(self, k):
        return k in self.held

    def cursor_pos(self):
        return self.cursor

    def framebuffer_size(self):
        return (1600, 1200)

    def window_size(self):
        return (800, 600)          # dsf 2

    def consume_mouse_delta(self):
        d, self.delta = self.delta, (0.0, 0.0)
        return d

    def set_cursor_locked(self, on):
        self.locked.append(bool(on))


class FakeHDsf1(FakeH):
    """Same as FakeH but window_size == framebuffer_size (dsf 1), so the
    dock's CSS-pixel width maps 1:1 onto framebuffer pixels."""

    def window_size(self):
        return self.framebuffer_size()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(ld.paths, "game_asset_dirs", lambda rel: [tmp_path / "stock" / rel])
    monkeypatch.setattr(ld.paths, "project_asset_root", lambda: tmp_path)
    t = [0.0]
    io = FakeIO()
    p = bep.BridgeEmittersPanel(pose_provider=lambda: POSE,
                                instance_provider=lambda: "iid",
                                in_bridge_provider=lambda: True,
                                clock=lambda: t[0], io=io)
    return p, io, FakeH(), t, tmp_path


def click(p, h, xy, alt=False):
    h.cursor = xy
    if alt:
        h.held.add(FakeKeys.KEY_LEFT_ALT)
    h.buttons.add(FakeKeys.MOUSE_BUTTON_LEFT)
    p.handle_input(h)
    h.buttons.discard(FakeKeys.MOUSE_BUTTON_LEFT)
    p.handle_input(h)
    h.held.discard(FakeKeys.KEY_LEFT_ALT)


def payload(p):
    js = p.render_payload()
    assert js.startswith("setBridgeEmitters(") and js.endswith(");")
    return json.loads(js[len("setBridgeEmitters("):-2])


class FakeRuntime:
    def __init__(self):
        self.pushes = []

    def push(self, doc, matched=None):
        self.pushes.append((json.dumps(doc, sort_keys=True), dict(matched or {})))
        return []


@pytest.fixture
def env_rt(env):
    p, io, h, t, tmp = env
    rt = FakeRuntime()
    p._runtime = rt
    return p, io, h, t, tmp, rt


def test_material_edit_pushes_overrides_and_requests_capture(env_rt):
    p, io, h, t, tmp, rt = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material-new")
    p.dispatch_event("finish:metalness:0.8")
    doc, matched = rt.pushes[-1]
    assert '"metalness": 0.8' in doc
    assert matched.get("7:redalertpanel") == 1


def test_map_wins_and_is_reported(env_rt):
    p, io, h, *_ = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material-new")
    mat = payload(p)["selected"]["material_data"]["finish"]
    assert mat["roughness"]["source"] == "map"
    assert mat["metalness"]["source"] == "default"


def test_light_add_places_at_the_hit_facing_the_normal(env_rt):
    p, io, h, *_ = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("light-add")
    light = payload(p)["selected"]["lights"][0]
    assert light["position"] == [0, 10, 50]       # FakeIO's hit point
    assert light["direction"] == [0, -1, 0]       # FakeIO's hit normal
    assert (light["inner_deg"], light["outer_deg"], light["range"], light["intensity"]) == (30, 60, 200, 2000)


def test_light_aim_uses_the_fly_camera_forward(env_rt):
    p, io, h, *_ = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("light-add")
    p.dispatch_event("light-aim:0")
    d = payload(p)["selected"]["lights"][0]["direction"]
    assert abs(d[1] - 1.0) < 1e-6                 # POSE looks along +Y


def test_light_fields_clamp_and_keep_inner_le_outer(env_rt):
    p, io, h, *_ = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("light-add")
    p.dispatch_event("light:0:inner_deg:80")        # above outer 60 -> outer follows
    light = payload(p)["selected"]["lights"][0]
    assert light["inner_deg"] == 80 and light["outer_deg"] == 80
    p.dispatch_event("light:0:range:-5")
    assert payload(p)["selected"]["lights"][0]["range"] > 0


def test_light_remove_and_undo_both_push(env_rt):
    p, io, h, t, tmp, rt = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("light-add")
    n = len(rt.pushes)
    p.dispatch_event("light-remove:0")
    assert payload(p)["selected"]["lights"] == []
    p.dispatch_event("undo")
    assert payload(p)["selected"]["lights"] != []
    assert len(rt.pushes) == n + 2


def test_saved_lights_validate(env_rt):
    p, io, h, t, tmp, rt = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("light-add")
    p.dispatch_event("save")
    saved = json.loads((tmp / "bridge_lighting" / f"{HASH}.json").read_text())
    assert saved["objects"]["7:redalertpanel"]["lights"][0]["range"] == 200


class FakeConstantWarningRuntime:
    """A runtime whose push() always reports the SAME warning -- pins that a
    persistent condition (too many spot lights, a non-finite value) is shown
    once, not re-announced and concatenated on every later edit."""
    def __init__(self, warning):
        self._warning = warning

    def push(self, doc, matched=None):
        return [self._warning]


class FakeToggleWarningRuntime:
    def __init__(self):
        self.on = True

    def push(self, doc, matched=None):
        return ["too many bridge lights"] if self.on else []


def test_push_warnings_replace_not_accumulate(env):
    p, io, h, *_ = env
    p._runtime = FakeConstantWarningRuntime("too many bridge lights")
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material-new")
    p.dispatch_event("finish:metalness:0.1")
    p.dispatch_event("finish:metalness:0.2")
    p.dispatch_event("finish:metalness:0.3")
    status = payload(p)["status"]
    assert status.count("too many bridge lights") == 1


def test_push_warnings_disappear_once_a_later_push_stops_reporting_them(env):
    p, io, h, *_ = env
    rt = FakeToggleWarningRuntime()
    p._runtime = rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material-new")
    assert "too many bridge lights" in payload(p)["status"]
    rt.on = False
    p.dispatch_event("finish:metalness:0.1")
    assert "too many bridge lights" not in payload(p)["status"]


def test_light_field_noop_pushes_no_undo_entry(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("light-add")
    n = len(p._undo)
    p.dispatch_event("light:0:inner_deg:30")        # already 30 (the default) -> no-op
    assert len(p._undo) == n
    assert payload(p)["selected"]["lights"][0]["inner_deg"] == 30


def test_closed_panel_has_no_camera_and_hides(env):
    p, *_ = env
    assert p.camera_pose() is None
    assert payload(p)["visible"] is False


def test_open_seeds_the_fly_camera_from_the_bridge_camera(env):
    p, io, h, *_ = env
    p.open()
    p.handle_input(h)
    eye, target, up, fov = p.camera_pose()
    assert eye == POSE[0]
    assert abs(target[1] - 1.0) < 1e-6


def test_click_selects_and_highlights_the_shape(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    st = payload(p)
    assert st["selected"]["key"] == "7:redalertpanel"
    assert st["selected"]["node_chain"] == ["Scene Root", "Red On GlowAlpha"]
    assert st["selected"]["textures"] == ["redalertpanel.tga"]
    assert st["selected"]["display_name"] == "redalertpanel"
    assert st["hover"] == "redalertpanel"
    assert io.highlights[-1] == ("iid", 1, 1)


def test_pick_uses_the_fly_camera_pose(env):
    p, io, h, t, _ = env
    p.open()
    p.handle_input(h)
    h.held.add(FakeKeys.KEY_LEFT_SHIFT)
    h.held.add(FakeKeys.KEY_W)
    p.handle_input(h)                      # Shift edge: lock
    t[0] = 1.0
    p.handle_input(h)                      # fly 1 s forward
    h.buttons.clear(); h.held.clear()
    p.handle_input(h)
    click(p, h, (800.0, 600.0))
    origin = io.traces[-1][0]
    assert origin[1] > 1.0                 # traced from where we flew to (eye started at y = 0)


def test_click_over_the_dock_does_not_pick(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))                       # select mesh 1: the dock shows
    io.layers = [0]
    # dsf 2: the dock covers the right DOCK_CSS_PX*2 = 720 framebuffer pixels
    # (x >= 880). x=1000 is inside that *scaled* dock but OUTSIDE the
    # unscaled 360 band -- pins the `* dsf` factor.
    click(p, h, (1000.0, 300.0))
    assert payload(p)["selected"]["key"] == "7:redalertpanel"
    # dsf 1: the dock is only 360 px wide, so x=1000 reaches the 3D view.
    click(p, FakeHDsf1(), (1000.0, 300.0))
    assert payload(p)["selected"]["key"] == "3:floor"


def test_with_nothing_selected_the_dock_area_picks(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (1000.0, 300.0))                      # no dock without a selection
    assert payload(p)["selected"]["key"] == "7:redalertpanel"


def test_click_over_the_bar_does_not_pick(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (100.0, 50.0))                        # dsf 2: the bar is 1120 x 128
    assert payload(p)["selected"] is None


def test_clicking_empty_space_deselects(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    io.layers = []
    click(p, h, (400.0, 300.0))
    assert payload(p)["selected"] is None


def test_drag_is_not_a_click(env):
    p, io, h, *_ = env
    p.open()
    h.cursor = (400.0, 300.0)
    h.buttons.add(FakeKeys.MOUSE_BUTTON_LEFT)
    p.handle_input(h)
    h.cursor = (450.0, 300.0)
    p.handle_input(h)
    h.buttons.clear()
    p.handle_input(h)
    assert payload(p)["selected"] is None


def test_alt_click_picks_the_surface_behind(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    io.layers = [1, 0]                      # mesh 0 lies behind mesh 1
    click(p, h, (400.0, 300.0), alt=True)
    assert io.traces[-1][2] == (1,)
    assert payload(p)["selected"]["key"] == "3:floor"


def test_first_alt_click_at_a_fresh_spot_skips_the_front_surface(env):
    # The selection (mesh 1) is unrelated to what is under the cursor now
    # (mesh 2 in front of mesh 0): seeding the exclusion with the selection
    # returned the FRONT surface. The first Alt+click must step past it.
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    assert payload(p)["selected"]["key"] == "7:redalertpanel"
    io.layers = [2, 0]
    click(p, h, (600.0, 300.0), alt=True)
    assert payload(p)["selected"]["key"] == "3:floor"


def test_repeated_alt_clicks_at_one_spot_step_deeper(env):
    p, io, h, *_ = env
    p.open()
    io.layers = [2, 0, 1]
    click(p, h, (600.0, 300.0), alt=True)
    assert payload(p)["selected"]["key"] == "3:floor"
    click(p, h, (601.0, 300.0), alt=True)
    assert payload(p)["selected"]["key"] == "7:redalertpanel"


def test_an_unnamed_shape_keys_on_its_block_and_displays_its_node(env):
    p, io, h, *_ = env
    p.open()
    io.layers = [2]
    click(p, h, (400.0, 300.0))
    st = payload(p)
    assert st["selected"]["key"] == "11:"
    assert st["selected"]["name"] == ""
    assert st["selected"]["display_name"] == "(node) wall side pnls 11"
    assert st["selected"]["textures"] == ["Map 20.tga"]
    assert st["hover"] == "(node) wall side pnls 11"


def test_an_unnamed_shape_round_trips_through_save_and_revert(env):
    p, io, h, t, tmp = env
    p.open()
    io.layers = [2]
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material-new")
    p.dispatch_event("finish:metalness:0.75")
    p.dispatch_event("save")
    saved = json.loads((tmp / "bridge_lighting" / f"{HASH}.json").read_text())
    assert saved["objects"]["11:"] == {"block": 11, "name": "", "material": "Map 20 2"}
    assert saved["materials"]["Map 20 2"] == {"metalness": 0.75, "texture": "map 20.tga"}
    p.dispatch_event("finish:metalness:0.1")
    p.dispatch_event("revert")
    st = payload(p)
    assert st["status"] == ""                 # loaded cleanly, matched, no warning
    assert st["selected"]["material_data"]["finish"]["metalness"] == {"value": 0.75, "source": "material"}
    p.close()                                 # a fresh session reads it back too
    p.open()
    click(p, h, (400.0, 300.0))
    assert payload(p)["selected"]["material_data"]["finish"]["metalness"]["value"] == 0.75


def test_material_override_edit_and_sources(env):
    # mesh 1 (redalertpanel) has a roughness MAP (see test_map_wins_and_is_reported
    # for that case) -- metalness has no map, so it still exercises the plain
    # default -> override -> clear flow.
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material-new")
    st = payload(p)["selected"]["material_data"]["finish"]
    assert st == {"roughness": {"value": 1.0, "source": "map"},
                  "metalness": {"value": 0.0, "source": "default"}}
    assert p.dispatch_event("finish:metalness:0.35")
    st = payload(p)
    assert st["selected"]["material_data"]["finish"]["metalness"] == {"value": 0.35, "source": "material"}
    assert st["dirty"] is True
    assert p.dispatch_event("finish-clear:metalness")
    assert payload(p)["selected"]["material_data"]["finish"]["metalness"]["source"] == "default"


def test_material_value_is_clamped_and_garbage_ignored(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material-new")
    p.dispatch_event("finish:metalness:7")
    assert payload(p)["selected"]["material_data"]["finish"]["metalness"]["value"] == 1.0
    assert p.dispatch_event("finish:metalness:abc") is True    # handled, no change
    assert payload(p)["selected"]["material_data"]["finish"]["metalness"]["value"] == 1.0
    assert p.dispatch_event("finish:shine:0.5") is True
    assert "shine" not in payload(p)["selected"]["material_data"]["finish"]


def test_undo_restores_the_previous_document(env):
    # metalness, not roughness: mesh 1 has a roughness MAP (see
    # test_map_wins_and_is_reported), which always reports "map" regardless
    # of any stored override.
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material-new")
    p.dispatch_event("finish:metalness:0.2")
    p.dispatch_event("finish:metalness:0.4")
    p.dispatch_event("undo")
    assert payload(p)["selected"]["material_data"]["finish"]["metalness"]["value"] == 0.2
    p.dispatch_event("undo")
    assert payload(p)["selected"]["material_data"]["finish"]["metalness"]["source"] == "default"


def test_save_writes_the_project_file_and_revert_reloads(env):
    # metalness: mesh 1's roughness MAP always reports "map" (its stored
    # value never surfaces in the live state -- see test_map_wins_and_is_reported),
    # so the round-trip-through-value check needs the unmapped channel.
    p, io, h, t, tmp = env
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material-new")
    p.dispatch_event("finish:metalness:0.25")
    p.dispatch_event("save")
    path = tmp / "bridge_lighting" / f"{HASH}.json"
    saved = json.loads(path.read_text())
    assert saved["materials"][saved["objects"]["7:redalertpanel"]["material"]] == {
        "metalness": 0.25, "texture": "redalertpanel.tga"}
    assert payload(p)["dirty"] is False
    p.dispatch_event("finish:metalness:0.9")
    p.dispatch_event("revert")
    assert payload(p)["selected"]["material_data"]["finish"]["metalness"]["value"] == 0.25


def test_save_is_refused_when_the_file_failed_to_load(env):
    p, io, h, t, tmp = env
    (tmp / "bridge_lighting").mkdir()
    bad = tmp / "bridge_lighting" / f"{HASH}.json"
    bad.write_text("{broken")
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material-new")
    st = payload(p)
    assert st["can_save"] is False
    assert st["status"]
    p.dispatch_event("finish:roughness:0.5")
    p.dispatch_event("save")
    assert bad.read_text() == "{broken"


def test_close_while_flying_unlocks_cursor_and_clears_highlight(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    h.held.add(FakeKeys.KEY_LEFT_SHIFT)
    p.handle_input(h)
    assert h.locked[-1] is True
    p.dispatch_event("close")
    assert h.locked[-1] is False
    assert io.highlights[-1] == (None, -1, -1)
    assert p.camera_pose() is None
    assert p.is_open() is False


def test_outside_the_bridge_view_the_panel_says_so_and_does_nothing(env):
    p, io, h, *_ = env
    p._in_bridge = lambda: False
    p.open()
    click(p, h, (400.0, 300.0))
    st = payload(p)
    assert st["in_bridge"] is False and st["selected"] is None
    assert p.camera_pose() is None


def test_a_swapped_bridge_reattaches_and_drops_the_selection(env):
    p, io, h, *_ = env
    iid = ["iid"]
    p._iid = lambda: iid[0]
    p.open()
    click(p, h, (400.0, 300.0))
    assert payload(p)["selected"] is not None
    iid[0] = "other"
    p.handle_input(h)
    assert payload(p)["selected"] is None
    assert io.highlights[-1][0] == "other"


def test_esc_closes(env):
    p, *_ = env
    p.open()
    p.handle_key_esc()
    assert p.is_open() is False


def test_leaving_the_bridge_while_flying_unlocks_the_cursor(env):
    p, io, h, *_ = env
    p.open()
    p.handle_input(h)
    h.held.add(FakeKeys.KEY_LEFT_SHIFT)
    p.handle_input(h)                      # Shift edge: lock
    assert h.locked[-1] is True
    p._in_bridge = lambda: False
    p.handle_input(h)                      # the view leaves the bridge mid-fly
    assert h.locked[-1] is False


def test_the_instance_vanishing_while_flying_unlocks_the_cursor(env):
    p, io, h, *_ = env
    iid = ["iid"]
    p._iid = lambda: iid[0]
    p.open()
    p.handle_input(h)
    h.held.add(FakeKeys.KEY_LEFT_SHIFT)
    p.handle_input(h)                      # Shift edge: lock
    assert h.locked[-1] is True
    iid[0] = None
    p.handle_input(h)                      # the instance disappears mid-fly
    assert h.locked[-1] is False


def test_revert_without_an_instance_does_not_raise(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    assert payload(p)["selected"] is not None
    p._iid = lambda: None
    assert p.dispatch_event("revert") is True
    # Must not raise: _attach_reload has no instance to re-attach to, so it
    # must leave _info (and therefore the document/selection) intact rather
    # than nulling it out and leaving render_payload's _can_save() to index
    # into None.
    st = payload(p)
    assert st["selected"] is not None


# ── Final-review fix wave, finding 6: closing the editor with UNSAVED edits
# must not leave them rendered (they would stay until the editor reopened or
# the bridge reloaded). close() re-pushes the last saved/loaded document.

def test_close_with_unsaved_edits_repushes_the_saved_doc(env_rt):
    p, io, h, t, tmp, rt = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    loaded = rt.pushes[-1]                       # the attach push: the loaded doc
    p.dispatch_event("material-new")
    p.dispatch_event("finish:metalness:0.8")
    assert '"metalness": 0.8' in rt.pushes[-1][0]
    p.close()
    assert rt.pushes[-1] == loaded


def test_close_after_save_repushes_the_saved_not_the_loaded_doc(env_rt):
    p, io, h, t, tmp, rt = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material-new")
    p.dispatch_event("finish:metalness:0.8")
    p.dispatch_event("save")
    saved = rt.pushes[-1]
    p.dispatch_event("finish:metalness:0.3")
    p.close()
    assert rt.pushes[-1] == saved
    assert '"metalness": 0.8' in rt.pushes[-1][0]


def test_close_with_nothing_unsaved_pushes_nothing(env_rt):
    p, io, h, t, tmp, rt = env_rt
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material-new")
    p.dispatch_event("finish:metalness:0.8")
    p.dispatch_event("save")
    n = len(rt.pushes)
    p.close()
    assert len(rt.pushes) == n


# ── Object / Material tabs, five states, Shift fly (spec §13) ──────────────

def _sel(env_rt):
    p, io, h, *_, rt = env_rt
    p.open()
    click(p, h, (400.0, 300.0))          # mesh 1, block 7 "redalertpanel"
    return p, h, rt


def test_nothing_selected_hides_the_dock_payload(env_rt):
    p, io, h, *_ , rt = env_rt
    p.open()
    st = payload(p)
    assert st["selected"] is None and st["state"] == "green" and st["playing"] is True


def test_material_new_link_duplicate_and_library(env_rt):
    p, h, rt = _sel(env_rt)
    p.dispatch_event("material-new")
    sel = payload(p)["selected"]
    assert sel["material"] == "redalertpanel 2"
    assert sel["library"] == [{"name": "redalertpanel 2", "used_by": 1, "texture": False}]
    assert sel["linked"] is True
    p.dispatch_event("material-duplicate")
    assert payload(p)["selected"]["material"] == "redalertpanel 2 copy"
    p.dispatch_event("material-link:redalertpanel 2")
    p.dispatch_event("material-rename:alcove")
    assert payload(p)["selected"]["material"] == "alcove"
    p.dispatch_event("material-link:")
    assert payload(p)["selected"]["material"] is None


def test_an_unlinked_object_edits_its_texture_material(env_rt):
    """Each TGA is a material (Mark 2026-10-11): with no link, the Material
    tab is the texture's material -- made on the first edit, never a link."""
    p, h, rt = _sel(env_rt)
    sel = payload(p)["selected"]
    assert sel["material"] is None and sel["linked"] is False
    assert sel["texture_material"] == "redalertpanel"
    assert (sel["material_data"]["name"], sel["material_data"]["kind"]) == ("redalertpanel", "texture")
    p.dispatch_event("finish:roughness:0.2")
    assert "7:redalertpanel" not in p._doc["objects"]          # no link made
    assert p._doc["textures"] == {"redalertpanel.tga": "redalertpanel"}
    assert p._doc["materials"]["redalertpanel"] == {"roughness": 0.2, "texture": "redalertpanel.tga"}
    p.dispatch_event("tab:material")
    p.dispatch_event("state:red")
    p.dispatch_event("mod-add:emitter")
    sel = payload(p)["selected"]
    assert sel["material"] == "redalertpanel" and sel["material_data"]["used_by"] == 1
    assert sel["material_data"]["modifiers"][0]["scope"] == ["red"]   # the preview state
    assert {"name": "redalertpanel", "used_by": 1, "texture": True} in sel["library"]


def test_duplicate_splits_one_object_off_its_texture_material(env_rt):
    p, h, rt = _sel(env_rt)
    p.dispatch_event("finish:roughness:0.2")
    p.dispatch_event("material-duplicate")
    sel = payload(p)["selected"]
    assert (sel["material"], sel["linked"]) == ("redalertpanel copy", True)
    assert p._doc["materials"]["redalertpanel copy"] == {"roughness": 0.2,
                                                         "texture": "redalertpanel.tga"}
    p.dispatch_event("material-link:")                          # back to the texture's
    assert payload(p)["selected"]["material"] == "redalertpanel"


def test_rename_of_a_texture_material_keeps_the_texture_on_it(env_rt):
    p, h, rt = _sel(env_rt)
    p.dispatch_event("material-rename:red panels")              # before any edit: makes it
    assert p._doc["textures"] == {"redalertpanel.tga": "red panels"}
    assert payload(p)["selected"]["material"] == "red panels"


def test_finish_source_reports_map_material_default(env_rt):
    p, h, rt = _sel(env_rt)
    p.dispatch_event("material-new")
    p.dispatch_event("finish:metalness:0.8")
    fin = payload(p)["selected"]["material_data"]["finish"]
    assert fin["roughness"]["source"] == "map"           # mesh 1 has a roughness map
    assert fin["metalness"] == {"value": 0.8, "source": "material"}


def test_every_edit_is_one_undo_step(env_rt):
    p, h, rt = _sel(env_rt)
    p.dispatch_event("material-new")
    n = len(p._undo)
    p.dispatch_event("fade:0.5")                         # same as default? sets it: one step
    p.dispatch_event("fade:0.5")                         # unchanged: none
    assert len(p._undo) == n + 1
    p.dispatch_event("undo")
    assert "fade_s" not in p._doc["materials"]["redalertpanel 2"]


def test_lights_are_indexed(env_rt):
    p, h, rt = _sel(env_rt)
    p.dispatch_event("light-add")
    p.dispatch_event("light-add")
    p.dispatch_event("light:1:intensity:-5")
    lights = payload(p)["selected"]["lights"]
    assert len(lights) == 2 and lights[1]["intensity"] == 0.0
    p.dispatch_event("light-remove:0")
    assert len(payload(p)["selected"]["lights"]) == 1


def test_state_and_expand_are_not_document_edits(env_rt):
    p, h, rt = _sel(env_rt)
    n = len(p._undo)
    p.dispatch_event("state:offline")
    p.dispatch_event("expand:mod:0")
    p.dispatch_event("state:purple")
    st = payload(p)
    assert st["state"] == "offline" and st["selected"]["expanded"] == ["mod:0"]
    assert p.preview_alert() == 3 and len(p._undo) == n


def test_preview_is_none_and_dt_is_the_players_when_closed(env):
    p, *_ = env
    assert p.preview_alert() is None
    assert p.preview_dt(0.02, 0.016) == 0.02


def test_open_starts_on_the_bridge_state(tmp_path, monkeypatch):
    monkeypatch.setattr(ld.paths, "game_asset_dirs", lambda rel: [tmp_path / "stock" / rel])
    monkeypatch.setattr(ld.paths, "project_asset_root", lambda: tmp_path)
    p = bep.BridgeEmittersPanel(pose_provider=lambda: POSE, instance_provider=lambda: "iid",
                                in_bridge_provider=lambda: True, io=FakeIO(),
                                alert_provider=lambda: 3)
    p.open()
    assert p.preview_alert() == 3


def test_deselect_and_clicking_empty_space_clear_the_selection(env_rt):
    p, h, rt = _sel(env_rt)
    p.dispatch_event("deselect")
    assert payload(p)["selected"] is None


def test_shift_flies_and_scroll_sets_the_speed(env):
    p, io, h, t, _ = env
    p.open()
    p.handle_input(h)                                   # attach + camera
    before = p._camera.speed
    h.held.add(FakeKeys.KEY_LEFT_SHIFT)
    h.scroll = 2.0
    t[0] += 0.05
    p.handle_input(h)
    assert p._camera.speed == pytest.approx(before * 1.25 ** 2)
    assert h.locked[-1] is True
    h.held.discard(FakeKeys.KEY_LEFT_SHIFT)
    p.handle_input(h)
    assert h.locked[-1] is False


def test_clicks_on_the_hint_and_status_lines_under_the_bar_do_not_pick(env):
    # Review M1: .be-top holds the bar + hint + hover/status rows (~90 CSS px).
    p, io, h, *_ = env
    p.open()
    click(p, h, (100.0, 200.0))                       # dsf 2 -> 100 CSS px down
    assert payload(p)["selected"] is None


def test_the_library_lists_only_this_textures_materials(env_rt):
    """A material belongs to one texture (Mark 2026-10-11): the library
    offers the selected object's texture's materials, nothing else."""
    p, h, rt = _sel(env_rt)
    p._doc["materials"]["Map 20"] = {"texture": "map 20.tga"}
    p._doc["materials"]["loose"] = {}                         # upgraded: no texture yet
    p.dispatch_event("material-new")
    names = [m["name"] for m in payload(p)["selected"]["library"]]
    assert names == ["loose", "redalertpanel 2"]


def test_linking_another_textures_material_is_refused(env_rt):
    p, h, rt = _sel(env_rt)
    p._doc["materials"]["Map 20"] = {"texture": "map 20.tga"}
    p.dispatch_event("material-link:Map 20")
    assert "7:redalertpanel" not in p._doc["objects"]
    assert "Map 20" in payload(p)["status"]
