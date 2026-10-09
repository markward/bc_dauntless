"""Bridge Emitters dev panel (spec 2026-10-08-bridge-emitters §4, §7, §8)."""
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
         "textures": ["redalertpanel.tga"], "material": 1},
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
    h.buttons.add(FakeKeys.MOUSE_BUTTON_RIGHT)
    h.held.add(FakeKeys.KEY_W)
    p.handle_input(h)                      # RMB edge: lock
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
    # dsf 2: the dock covers the right DOCK_CSS_PX*2 = 720 framebuffer pixels
    # (x >= 880). x=1000 is inside that *scaled* dock but OUTSIDE the
    # unscaled DOCK_CSS_PX=360 band (which would start at x >= 1240) -- this
    # pins the `* self._dsf(h, fb)` factor: a regression dropping it would
    # treat x=1000 as outside the dock and let the click through to a pick.
    click(p, h, (1000.0, 300.0))
    assert payload(p)["selected"] is None

    # Same x, but dsf 1 (window_size == framebuffer_size): the dock is now
    # only 360 px wide, so x=1000 is OUTSIDE it and the click DOES reach the
    # 3D view and select.
    h1 = FakeHDsf1()
    click(p, h1, (1000.0, 300.0))
    assert payload(p)["selected"]["key"] == "7:redalertpanel"


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
    p.dispatch_event("material:metalness:0.75")
    p.dispatch_event("save")
    saved = json.loads((tmp / "bridge_lighting" / f"{HASH}.json").read_text())
    assert saved["shapes"]["11:"] == {"block": 11, "name": "",
                                      "material": {"metalness": 0.75}}
    p.dispatch_event("material:metalness:0.1")
    p.dispatch_event("revert")
    st = payload(p)
    assert st["status"] == ""                 # loaded cleanly, matched, no warning
    assert st["selected"]["material"]["metalness"] == {"value": 0.75, "source": "override"}
    p.close()                                 # a fresh session reads it back too
    p.open()
    click(p, h, (400.0, 300.0))
    assert payload(p)["selected"]["material"]["metalness"]["value"] == 0.75


def test_material_override_edit_and_sources(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    st = payload(p)["selected"]["material"]
    assert st == {"roughness": {"value": 1.0, "source": "default"},
                  "metalness": {"value": 0.0, "source": "default"}}
    assert p.dispatch_event("material:roughness:0.35")
    st = payload(p)
    assert st["selected"]["material"]["roughness"] == {"value": 0.35, "source": "override"}
    assert st["dirty"] is True
    assert p.dispatch_event("material-clear:roughness")
    assert payload(p)["selected"]["material"]["roughness"]["source"] == "default"


def test_material_value_is_clamped_and_garbage_ignored(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material:metalness:7")
    assert payload(p)["selected"]["material"]["metalness"]["value"] == 1.0
    assert p.dispatch_event("material:metalness:abc") is True    # handled, no change
    assert payload(p)["selected"]["material"]["metalness"]["value"] == 1.0
    assert p.dispatch_event("material:shine:0.5") is True
    assert "shine" not in payload(p)["selected"]["material"]


def test_undo_restores_the_previous_document(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material:roughness:0.2")
    p.dispatch_event("material:roughness:0.4")
    p.dispatch_event("undo")
    assert payload(p)["selected"]["material"]["roughness"]["value"] == 0.2
    p.dispatch_event("undo")
    assert payload(p)["selected"]["material"]["roughness"]["source"] == "default"


def test_save_writes_the_project_file_and_revert_reloads(env):
    p, io, h, t, tmp = env
    p.open()
    click(p, h, (400.0, 300.0))
    p.dispatch_event("material:roughness:0.25")
    p.dispatch_event("save")
    path = tmp / "bridge_lighting" / f"{HASH}.json"
    saved = json.loads(path.read_text())
    assert saved["shapes"]["7:redalertpanel"]["material"] == {"roughness": 0.25}
    assert payload(p)["dirty"] is False
    p.dispatch_event("material:roughness:0.9")
    p.dispatch_event("revert")
    assert payload(p)["selected"]["material"]["roughness"]["value"] == 0.25


def test_save_is_refused_when_the_file_failed_to_load(env):
    p, io, h, t, tmp = env
    (tmp / "bridge_lighting").mkdir()
    bad = tmp / "bridge_lighting" / f"{HASH}.json"
    bad.write_text("{broken")
    p.open()
    click(p, h, (400.0, 300.0))
    st = payload(p)
    assert st["can_save"] is False
    assert st["status"]
    p.dispatch_event("material:roughness:0.5")
    p.dispatch_event("save")
    assert bad.read_text() == "{broken"


def test_close_while_flying_unlocks_cursor_and_clears_highlight(env):
    p, io, h, *_ = env
    p.open()
    click(p, h, (400.0, 300.0))
    h.buttons.add(FakeKeys.MOUSE_BUTTON_RIGHT)
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
    h.buttons.add(FakeKeys.MOUSE_BUTTON_RIGHT)
    p.handle_input(h)                      # RMB edge: lock
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
    h.buttons.add(FakeKeys.MOUSE_BUTTON_RIGHT)
    p.handle_input(h)                      # RMB edge: lock
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
