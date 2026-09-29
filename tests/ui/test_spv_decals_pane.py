"""SPV Decals pane (spec docs/superpowers/specs/2026-09-28-spv-decal-editing-
design.md S3): the panel logic against a fake host_io that records every
set_instance_decals / ray_trace_mesh call.

The fake ship is ROTATED and SCALED on purpose, and its world is built from
the REAL instance composition -- `host_loop._world_matrix_from(loc, rot,
BC_MODEL_SCALE * GetScale())`, what the renderer draws and what the shader's
`p_body = inverse(inst.world) * pos` inverts. The decal maths is in that body
frame (NIF units: the committed Ambassador `top` is ~120 wide), so a fake that
re-derived its own composition would only check the code against itself
(fix round 1, C1: exactly that hid a 100x unit error). The fake
`host_io.world_to_body` inverts the fake world's LINEAR part generically, the
way the native binding inverts `inst->world_linear`.
"""
import json
import math
import struct
import zlib
from pathlib import Path

import pytest

from engine import host_io, mods, paths
from engine.appc import decals_writer, hull_decals
from engine.appc.math import TGMatrix3, TGPoint3
from engine.host_loop import BC_MODEL_SCALE, _world_matrix_from
from engine.ui import decal_editor
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel

AMB_DIR = "data/Models/Ships/Ambassador"
AMB_MODEL = f"{AMB_DIR}/Ambassador.nif"
BOP_DIR = "data/Models/Ships/BirdOfPrey"
BOP_MODEL = f"{BOP_DIR}/BirdOfPrey.nif"
IID = 7
SCALE = 2.0               # GetScale(); the instance scale is BC_MODEL_SCALE * this
RADIUS_GU = 10.0          # GetRadius(): UNSCALED GU => 1000 NIF units
AMB_COMMITTED = (Path(__file__).resolve().parents[2] / "native" / "assets"
                 / "replacements" / AMB_DIR / "Masks" / "decals.json")


def _png(width, height):
    """A real (decodable) RGBA PNG of the given size, all transparent."""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + b"\x00" * (4 * width) for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


class _FakeShip:
    """Rotated 90 deg about Z (body +Y -> world -X) and scaled x2."""

    def __init__(self):
        self._loc = TGPoint3(100.0, -50.0, 20.0)
        self._rot = TGMatrix3().MakeZRotation(math.pi / 2.0)

    def GetWorldLocation(self):
        return TGPoint3(self._loc.x, self._loc.y, self._loc.z)

    def GetWorldRotation(self):
        return self._rot

    def GetScale(self):
        return SCALE

    def GetRadius(self):
        return RADIUS_GU


def _instance_world(ship):
    """The render instance's world matrix (row-major 4x4, flat)."""
    return _world_matrix_from(ship.GetWorldLocation(), ship.GetWorldRotation(),
                              BC_MODEL_SCALE * ship.GetScale())


def _world_from_body(ship, p):
    m = _instance_world(ship)
    return tuple(m[4 * r] * p[0] + m[4 * r + 1] * p[1] + m[4 * r + 2] * p[2]
                 + m[4 * r + 3] for r in range(3))


def _world_dir_from_body(ship, n):
    v = TGPoint3(*n)
    v.MultMatrixLeft(ship.GetWorldRotation())
    return (v.x, v.y, v.z)


def _inverse3(a):
    """Inverse of a 3x3 (list of rows) by cofactors -- no numpy."""
    (a0, a1, a2), (b0, b1, b2), (c0, c1, c2) = a
    det = (a0 * (b1 * c2 - b2 * c1) - a1 * (b0 * c2 - b2 * c0)
           + a2 * (b0 * c1 - b1 * c0))
    return [[(b1 * c2 - b2 * c1) / det, (a2 * c1 - a1 * c2) / det, (a1 * b2 - a2 * b1) / det],
            [(b2 * c0 - b0 * c2) / det, (a0 * c2 - a2 * c0) / det, (a2 * b0 - a0 * b2) / det],
            [(b0 * c1 - b1 * c0) / det, (a1 * c0 - a0 * c1) / det, (a0 * b1 - a1 * b0) / det]]


def _fake_world_to_body(ship):
    """host_io.world_to_body's contract (world point + world normal -> body
    point + unit body normal), inverting the instance matrix generically."""
    def _w2b(iid, point, normal):
        m = _instance_world(ship)
        lin = [[m[4 * r + c] for c in range(3)] for r in range(3)]
        inv = _inverse3(lin)
        d = tuple(point[r] - m[4 * r + 3] for r in range(3))
        pb = tuple(sum(inv[r][c] * d[c] for c in range(3)) for r in range(3))
        nb = tuple(sum(inv[r][c] * normal[c] for c in range(3)) for r in range(3))
        k = math.sqrt(sum(v * v for v in nb))
        return pb, tuple(v / k for v in nb)
    return _w2b


def _close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# The COMMITTED Ambassador placement (NIF units), not a hand-sized stand-in.
_TOP = json.loads(AMB_COMMITTED.read_text())["decals"]["top"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors", lambda ship: [])
    repl = tmp_path / "replacements"
    monkeypatch.setattr(mods, "replacements_root", lambda: repl)
    monkeypatch.setattr(mods, "current", lambda: mods.ModIndex(files={}, mods=[]))
    monkeypatch.setattr(paths, "game_root", lambda: tmp_path / "stock")
    masks = repl / AMB_DIR / "Masks"
    (masks / "Zhukov").mkdir(parents=True)
    (masks / "Excalibur").mkdir(parents=True)
    (masks / "decals.json").write_text(json.dumps(
        {"format": 1, "default_registry": "Zhukov", "decals": {"top": _TOP}}))
    (masks / "Zhukov" / "top.png").write_bytes(_png(8, 2))
    (masks / "Zhukov" / "bottom.png").write_bytes(_png(200, 50))
    mods.invalidate_replacements()
    hull_decals.reset()

    calls = []
    monkeypatch.setattr(host_io, "set_instance_decals",
                        lambda iid, decals: calls.append((iid, decals)))
    traces = []
    hit = {"value": None}

    def _trace(iid, origin, direction, max_dist):
        traces.append((iid, origin, direction, max_dist))
        return hit["value"]
    monkeypatch.setattr(host_io, "ray_trace_mesh", _trace)
    ship = _FakeShip()
    monkeypatch.setattr(host_io, "world_to_body", _fake_world_to_body(ship))
    # No model handle headless: the radius falls back to GetRadius().
    monkeypatch.setattr(host_io, "instance_model", lambda iid: None)

    model = {"rel": AMB_MODEL}
    p = ShipPropertyViewerPanel(ship_getter=lambda: ship,
                                iid_getter=lambda: IID,
                                model_rel_getter=lambda s: model["rel"])
    p.open()
    yield {"p": p, "calls": calls, "hit": hit, "traces": traces, "ship": ship,
           "masks": masks, "repl": repl, "tmp": tmp_path, "model": model}
    mods.invalidate_replacements()
    hull_decals.reset()


def _payload(p):
    p.invalidate()
    js = p.render_payload()
    return json.loads(js[js.index("(") + 1: js.rindex(")")])


def _masks_of(decals):
    return [d[6] for d in decals]


def _placeholder():
    return str(paths.project_asset_root() / "textures" / "decal_placeholder.png")


# ── entering / leaving the pane ────────────────────────────────────────────

def test_entering_the_pane_forces_textured_mode_and_pushes_the_override(env):
    p, calls = env["p"], env["calls"]
    assert p.show_hull_texture is False
    p.dispatch_event("decal-pane")
    assert p.show_hull_texture is True
    iid, decals = calls[-1]
    assert iid == IID
    assert len(decals) == 1
    shape, origin, u, v, n, depth, mask = decals[0]
    assert shape == "amb saucer:0"
    assert _close(origin, _TOP["origin"]) and _close(n, _TOP["normal"])
    assert depth == pytest.approx(_TOP["depth"])
    assert mask == str(env["masks"] / "Zhukov" / "top.png")


def test_leaving_the_pane_restores_the_mode_and_clears_the_override(env):
    p, calls = env["p"], env["calls"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-pane")
    assert p.show_hull_texture is False
    assert calls[-1] == (IID, None)


def test_leaving_restores_a_textured_mode_that_was_already_on(env):
    p = env["p"]
    p.dispatch_event("toggle_hull_texture")
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-pane")
    assert p.show_hull_texture is True


def test_the_payload_carries_the_decals_pane(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    d = _payload(p)["decals"]
    assert d["registries"] == ["Excalibur", "Zhukov"]
    assert d["registry"] == "Zhukov"
    assert d["default_registry"] == "Zhukov"
    assert d["placements"] == [{"name": "top", "has_mask": True, "mask": "top"}]
    assert d["selected"] is None and d["adding"] is False and d["error"] is None


# ── Add ────────────────────────────────────────────────────────────────────

def _arm_hit(env, body_point, body_normal):
    ship = env["ship"]
    env["hit"]["value"] = (_world_from_body(ship, body_point),
                           _world_dir_from_body(ship, body_normal), 5.0)


def test_add_then_a_hull_click_places_a_chirality_ok_decal(env):
    p, calls = env["p"], env["calls"]
    p.dispatch_event("decal-pane")
    assert p.dispatch_event("decal-add:bottom")
    assert _payload(p)["decals"]["adding"] is True
    _arm_hit(env, (50.0, -100.0, -20.0), (0.0, 0.0, -1.0))

    p.decal_click(640.0, 360.0, (1280, 720))

    names = [pl.name for pl in p._decal_working]
    assert names == ["top", "bottom"]
    bottom = p._decal_working[1]
    assert decal_editor.chirality_ok(bottom)
    assert _close(decal_editor.centre(bottom), (50.0, -100.0, -20.0), 1e-6)
    assert _close(bottom.normal, (0.0, 0.0, -1.0))
    # Width is 25% of the NIF-unit radius: GetRadius() is UNSCALED GU, so
    # 10 GU / BC_MODEL_SCALE = 1000 units, whatever GetScale() says.
    assert decal_editor.width(bottom) == pytest.approx(250.0)
    # Zhukov/bottom.png is 200x50: height = width / 4.
    assert math.sqrt(sum(c * c for c in bottom.v_axis)) == pytest.approx(250.0 / 4)
    assert _payload(p)["decals"]["adding"] is False
    assert _payload(p)["decals"]["selected"] == "bottom"
    iid, decals = calls[-1]
    assert _masks_of(decals) == [str(env["masks"] / "Zhukov" / "top.png"),
                                 str(env["masks"] / "Zhukov" / "bottom.png")]
    # The trace went at the SPV instance.
    assert env["traces"][-1][0] == IID


def test_a_missed_click_sets_the_hint_and_places_nothing(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-add:bottom")
    env["hit"]["value"] = None
    p.decal_click(10.0, 10.0, (1280, 720))
    assert [pl.name for pl in p._decal_working] == ["top"]
    d = _payload(p)["decals"]
    assert d["error"] and "hull" in d["error"].lower()
    assert d["adding"] is True, "still armed so the next click can retry"


@pytest.mark.parametrize("name", ["", "../x", "a b", "top.png"])
def test_invalid_mask_names_are_refused_inline(env, name):
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-add:" + name)
    d = _payload(p)["decals"]
    assert d["adding"] is False
    assert d["error"]


def test_a_fifth_distinct_mask_is_refused_but_a_used_mask_is_not(env):
    """S2.4a: 4 distinct masks per model. b/c/d have no PNG: each missing
    stem still takes a slot (the placeholder stands in for a mask that WILL
    take one once authored)."""
    p = env["p"]
    p.dispatch_event("decal-pane")
    for i, name in enumerate(("b", "c", "d")):
        p.dispatch_event("decal-add:" + name)
        _arm_hit(env, (10.0 * i, 0.0, 60.0), (0.0, 0.0, 1.0))
        p.decal_click(1.0, 1.0, (1280, 720))
    assert len(p._decal_working) == 4
    p.dispatch_event("decal-add:e")
    d = _payload(p)["decals"]
    assert d["adding"] is False and "4" in d["error"] and "mask" in d["error"]
    # An already-used mask needs no new slot: allowed, auto-named.
    p.dispatch_event("decal-add:b")
    d = _payload(p)["decals"]
    assert d["adding"] is True and d["adding_name"] == "b_2" and d["error"] is None


def test_a_placement_without_a_mask_uses_the_placeholder(env):
    p, calls = env["p"], env["calls"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-add:port")
    _arm_hit(env, (150.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    p.decal_click(1.0, 1.0, (1280, 720))
    assert _masks_of(calls[-1][1])[1] == _placeholder()
    port = p._decal_working[1]
    # No PNG -> the 2:1 default aspect.
    assert decal_editor.width(port) == pytest.approx(
        2.0 * math.sqrt(sum(c * c for c in port.v_axis)))
    assert ({"name": "port", "has_mask": False, "mask": "port"}
            in _payload(p)["decals"]["placements"])


def test_the_placeholder_is_a_committed_64x32_png():
    path = Path(_placeholder())
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (64, 32)


# ── registry preview ───────────────────────────────────────────────────────

def test_a_registry_switch_changes_the_mask_paths(env):
    p, calls = env["p"], env["calls"]
    p.dispatch_event("decal-pane")
    (env["masks"] / "Excalibur" / "top.png").write_bytes(_png(8, 2))
    p.dispatch_event("decal-registry:Excalibur")
    assert _masks_of(calls[-1][1]) == [str(env["masks"] / "Excalibur" / "top.png")]
    assert _payload(p)["decals"]["registry"] == "Excalibur"


def test_a_registry_without_the_mask_previews_the_placeholder(env):
    p, calls = env["p"], env["calls"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-registry:Excalibur")
    assert _masks_of(calls[-1][1]) == [_placeholder()]


def test_an_unknown_registry_is_refused(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    assert not p.dispatch_event("decal-registry:Nope")
    assert _payload(p)["decals"]["registry"] == "Zhukov"


# ── select / delete / undo ─────────────────────────────────────────────────

def test_delete_removes_a_placement(env):
    p, calls = env["p"], env["calls"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-select:top")
    p.dispatch_event("decal-delete:top")
    assert p._decal_working == []
    assert calls[-1] == (IID, [])
    assert _payload(p)["decals"]["selected"] is None


def test_undo_restores_a_deleted_placement(env):
    p, calls = env["p"], env["calls"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-delete:top")
    p.dispatch_event("undo")
    assert [pl.name for pl in p._decal_working] == ["top"]
    assert len(calls[-1][1]) == 1


def test_undo_restores_a_placement_moved_by_the_gizmo(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-select:top")
    p.dispatch_event("set_tool:transform")
    before = p._decal_working[0]
    p._begin_axis_drag(0, 0.0)
    p._apply_axis_drag(1.0)
    p._end_axis_drag()
    assert p._decal_working[0] != before
    p.dispatch_event("undo")
    assert p._decal_working[0] == before


# ── gizmos (body frame; instance scale = BC_MODEL_SCALE * GetScale()) ────

def _u_hat(pl):
    return tuple(c / decal_editor.width(pl) for c in pl.u_axis)


def test_the_move_gizmo_drives_move_uv_in_model_units(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-select:top")
    p.dispatch_event("set_tool:transform")
    top = p._decal_working[0]
    g = p._active_gizmo()
    assert g is not None and g["handle_kind"] == 0
    # The gizmo sits ON the rendered hull at the decal centre, and its first
    # axis is the decal's u direction, in WORLD space.
    assert _close(g["origin"], _world_from_body(env["ship"], decal_editor.centre(top)),
                  1e-6)
    assert _close(g["axes"][0], _world_dir_from_body(env["ship"], _u_hat(top)), 1e-9)
    c0 = decal_editor.centre(top)
    p._begin_axis_drag(0, 0.0)
    p._apply_axis_drag(1.0)                 # 1 GU along world u
    c1 = decal_editor.centre(p._decal_working[0])
    # 1 GU = 1 / (BC_MODEL_SCALE * GetScale()) = 50 NIF units.
    step = 1.0 / (BC_MODEL_SCALE * SCALE)
    expect = tuple(c0[k] + step * _u_hat(top)[k] for k in range(3))
    assert _close(c1, expect, 1e-6)


def test_the_rotate_gizmo_rolls_about_the_normal(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-select:top")
    p.dispatch_event("set_tool:rotate")
    top = p._decal_working[0]
    g = p._active_gizmo()
    assert g is not None and g["handle_kind"] == 2
    n_hat = tuple(c / math.sqrt(sum(v * v for v in top.normal)) for c in top.normal)
    assert _close(g["axes"][2], _world_dir_from_body(env["ship"], n_hat), 1e-9)
    p._begin_ring_drag(2, 0.0)
    p._apply_ring_drag_angle(math.pi / 2.0)
    pl = p._decal_working[0]
    assert pl == decal_editor.roll(top, math.pi / 2.0)
    assert _close(decal_editor.centre(pl), decal_editor.centre(top), 1e-6)
    assert decal_editor.chirality_ok(pl)
    assert abs(sum(a * b for a, b in zip(_u_hat(pl), _u_hat(top)))) < 1e-9


def test_the_scale_gizmo_scales_uniformly(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-select:top")
    p.dispatch_event("set_tool:scale")
    assert p._active_gizmo()["handle_kind"] == 1
    from engine.ui.ship_property_viewer import gizmo_length
    w0 = decal_editor.width(p._decal_working[0])
    L = gizmo_length(p.camera)
    p._begin_scale_drag(0, L)
    p._apply_scale_drag(2.0 * L)
    pl = p._decal_working[0]
    assert decal_editor.width(pl) == pytest.approx(2.0 * w0)
    assert pl.depth == pytest.approx(2.0 * _TOP["depth"])


def test_the_scale_gizmo_locks_the_aspect_to_the_mask(env):
    """Spec S3: Scale is uniform "with the aspect locked to the mask". A 2:1
    placement whose mask (Zhukov/top.png, 8x2) is 4:1 snaps to 4:1 even at a
    1.0x scale; the width is old width x factor."""
    p = env["p"]
    p.dispatch_event("decal-pane")
    two_to_one = decal_editor.Placement(
        name="top", origin=(-50.0, 25.0, 60.0), u_axis=(100.0, 0.0, 0.0),
        v_axis=(0.0, -50.0, 0.0), normal=(0.0, 0.0, 1.0), depth=3.0)
    p._decal_working[0] = two_to_one
    p.dispatch_event("decal-select:top")
    p.dispatch_event("set_tool:scale")
    from engine.ui.ship_property_viewer import gizmo_length
    L = gizmo_length(p.camera)
    p._begin_scale_drag(0, L)
    p._apply_scale_drag(L)                  # factor 1.0
    pl = p._decal_working[0]
    h = math.sqrt(sum(c * c for c in pl.v_axis))
    assert decal_editor.width(pl) == pytest.approx(100.0)
    assert decal_editor.width(pl) / h == pytest.approx(4.0)
    assert _close(decal_editor.centre(pl), decal_editor.centre(two_to_one), 1e-9)
    assert pl.depth == pytest.approx(3.0)


def test_the_scale_gizmo_uses_the_default_aspect_without_a_mask(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-registry:Excalibur")      # no top.png there
    square = decal_editor.Placement(
        name="top", origin=(-50.0, 50.0, 60.0), u_axis=(100.0, 0.0, 0.0),
        v_axis=(0.0, -100.0, 0.0), normal=(0.0, 0.0, 1.0), depth=3.0)
    p._decal_working[0] = square
    p.dispatch_event("decal-select:top")
    p.dispatch_event("set_tool:scale")
    from engine.ui.ship_property_viewer import gizmo_length
    L = gizmo_length(p.camera)
    p._begin_scale_drag(0, L)
    p._apply_scale_drag(1.5 * L)
    pl = p._decal_working[0]
    h = math.sqrt(sum(c * c for c in pl.v_axis))
    assert decal_editor.width(pl) == pytest.approx(150.0)
    assert decal_editor.width(pl) / h == pytest.approx(2.0)
    assert pl.depth == pytest.approx(4.5)


def _wrap(deg):
    return (deg + 180.0) % 360.0 - 180.0


# ── the top-right tool panels (Transform / Rotate / Scale) ───────────────

def _select_top(p, tool):
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-select:top")
    p.dispatch_event("set_tool:" + tool)


def _roll_deg(pl):
    return math.degrees(decal_editor.roll_angle(
        pl, (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))


def test_the_sidebar_no_longer_carries_a_numbers_block(env):
    p = env["p"]
    _select_top(p, "transform")
    assert "numbers" not in _payload(p)["decals"]


def test_the_transform_panel_shows_the_decal_centre_in_body_units(env):
    p = env["p"]
    _select_top(p, "transform")
    c = _payload(p)["transform_coords"]
    assert _close((c["x"], c["y"], c["z"]),
                  decal_editor.centre(p._decal_working[0]), 1e-9)
    # A decal has no Copy/Paste/Mirror: the panel hides them.
    assert c["decal"] is True and c["can_paste"] is False
    # Steppers step in GU, like a hardpoint's; the numbers are NIF units.
    assert c["step_scale"] == pytest.approx(1.0 / BC_MODEL_SCALE)


def test_a_coord_nudge_recentres_the_decal_with_one_undo(env):
    p, calls = env["p"], env["calls"]
    _select_top(p, "transform")
    before = p._decal_working[0]
    n_undo = len(p._undo_stack)
    assert p.dispatch_event('coord_nudge:{"axis":2,"delta":5}')
    after = p._decal_working[0]
    c0, c1 = decal_editor.centre(before), decal_editor.centre(after)
    assert _close(c1, (c0[0], c0[1], c0[2] + 5.0), 1e-9)
    assert (after.u_axis, after.v_axis, after.normal) == (
        before.u_axis, before.v_axis, before.normal)
    assert len(p._undo_stack) == n_undo + 1
    assert _close(calls[-1][1][0][1], after.origin, 1e-9), "override re-pushed"
    p.dispatch_event("undo")
    assert p._decal_working[0] == before


def test_copy_paste_mirror_never_touch_a_decal(env):
    p = env["p"]
    _select_top(p, "transform")
    before = p._decal_working[0]
    for a in ("coord_copy", "coord_paste", "coord_mirror", "mirror_element"):
        p.dispatch_event(a)
    assert p._decal_working[0] == before
    assert p._coord_clipboard is None


def test_the_rotate_panel_shows_and_edits_the_roll(env):
    p = env["p"]
    _select_top(p, "rotate")
    r = _payload(p)["rotate_values"]
    assert r["decal"] is True and r["can_paste"] is False
    [f] = r["fields"]
    assert f["label"] == "Roll"
    before = p._decal_working[0]
    assert f["value"] == pytest.approx(_roll_deg(before))
    n_undo = len(p._undo_stack)
    assert p.dispatch_event('rotate_nudge:{"axis":0,"delta":10}')
    after = p._decal_working[0]
    assert after == decal_editor.roll(before, math.radians(10.0))
    assert _wrap(_payload(p)["rotate_values"]["fields"][0]["value"]
                 - f["value"]) == pytest.approx(10.0)
    assert len(p._undo_stack) == n_undo + 1
    # Only the one Roll row exists.
    assert not p.dispatch_event('rotate_nudge:{"axis":1,"delta":10}')
    assert p._decal_working[0] == after


def test_the_scale_panel_shows_width_and_depth(env):
    p = env["p"]
    _select_top(p, "scale")
    s = _payload(p)["scale_values"]
    assert s["decal"] is True and s["can_paste"] is False
    assert [f["label"] for f in s["fields"]] == ["Width", "Depth"]
    assert s["fields"][0]["value"] == pytest.approx(119.566, abs=1e-2)
    assert s["fields"][1]["value"] == pytest.approx(2.0)
    assert all(f["step_scale"] > 1.0 for f in s["fields"])


def test_a_width_nudge_is_aspect_locked_to_the_mask(env):
    """Zhukov/top.png is 8x2: the height snaps to width / 4."""
    p = env["p"]
    _select_top(p, "scale")
    c0 = decal_editor.centre(p._decal_working[0])
    w0 = decal_editor.width(p._decal_working[0])
    n_undo = len(p._undo_stack)
    assert p.dispatch_event('scale_nudge:{"index":0,"delta":10}')
    pl = p._decal_working[0]
    assert decal_editor.width(pl) == pytest.approx(w0 + 10.0)
    h = math.sqrt(sum(c * c for c in pl.v_axis))
    assert decal_editor.width(pl) / h == pytest.approx(4.0)
    assert _close(decal_editor.centre(pl), c0, 1e-9)
    assert len(p._undo_stack) == n_undo + 1


def test_a_depth_nudge_edits_depth_and_stays_positive(env):
    p = env["p"]
    _select_top(p, "scale")
    p.dispatch_event('scale_nudge:{"index":1,"delta":0.5}')
    assert p._decal_working[0].depth == pytest.approx(2.5)
    p.dispatch_event('scale_nudge:{"index":1,"delta":-100}')
    assert p._decal_working[0].depth > 0.0
    p.dispatch_event('scale_nudge:{"index":0,"delta":-1000}')
    assert decal_editor.width(p._decal_working[0]) > 0.0


def test_scale_copy_paste_uniform_never_touch_a_decal(env):
    p = env["p"]
    _select_top(p, "scale")
    before = p._decal_working[0]
    for a in ("scale_copy", "scale_paste", "scale_uniform",
              "rotate_copy", "rotate_paste", "rotate_mirror"):
        p.dispatch_event(a)
    assert p._decal_working[0] == before


def test_no_decal_panel_without_the_matching_tool_or_selection(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("set_tool:transform")
    assert _payload(p)["transform_coords"] is None      # nothing selected
    p.dispatch_event("decal-select:top")
    d = _payload(p)
    assert d["scale_values"] is None and d["rotate_values"] is None
    p.dispatch_event("decal-pane")                     # pane closed
    assert _payload(p)["transform_coords"] is None


def test_selecting_a_part_node_takes_the_panel_off_the_decal(env):
    p = env["p"]
    _select_top(p, "transform")
    p._model_part_nodes = [{"name": "wing", "bounds_min": [0, 0, 0],
                            "bounds_max": [1, 1, 1]}]
    p._select_part_node("wing", "breakage")
    assert p._decal_selected is None
    assert _payload(p)["transform_coords"] is None


def test_reposition_reseats_the_selection_at_the_next_click(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-select:top")
    p.dispatch_event("decal-reposition")
    assert _payload(p)["decals"]["reposition"] is True
    _arm_hit(env, (200.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    p.decal_click(1.0, 1.0, (1280, 720))
    pl = p._decal_working[0]
    assert _close(decal_editor.centre(pl), (200.0, 0.0, 0.0), 1e-6)
    assert _close(pl.normal, (1.0, 0.0, 0.0))
    assert decal_editor.chirality_ok(pl)
    assert _payload(p)["decals"]["reposition"] is False


# ── frame conversion: the committed Ambassador `top` round-trips ──────────

def test_a_click_on_the_ambassador_top_centre_round_trips_in_nif_units(env):
    """C1: the committed `top` centre is ~(-2, 176, 50) NIF units. A world
    click there, through the real instance composition, must come back to
    that body point -- not to a point 100x closer to the origin."""
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-select:top")
    top = p._decal_working[0]
    c = decal_editor.centre(top)
    assert math.sqrt(sum(v * v for v in c)) > 100.0, "NIF units, not GU"
    p.dispatch_event("set_tool:transform")
    world_c = _world_from_body(env["ship"], c)
    assert _close(p._active_gizmo()["origin"], world_c, 1e-6)
    p.dispatch_event("set_tool:transform")
    p.dispatch_event("decal-reposition")
    env["hit"]["value"] = (world_c, _world_dir_from_body(env["ship"], top.normal), 5.0)
    p.decal_click(640.0, 360.0, (1280, 720))
    pl = p._decal_working[0]
    assert _close(decal_editor.centre(pl), c, 1e-6)
    assert decal_editor.width(pl) == pytest.approx(decal_editor.width(top))


def test_the_radius_comes_from_the_model_bounds_when_there_is_a_handle(
        env, monkeypatch):
    from engine import renderer
    monkeypatch.setattr(host_io, "instance_model", lambda iid: 5)
    monkeypatch.setattr(renderer, "model_aabb",
                        lambda h: ((0.0, 0.0, 0.0), (300.0, 400.0, 0.0)))
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-add:port")
    _arm_hit(env, (150.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    p.decal_click(1.0, 1.0, (1280, 720))
    # |centre| + |half extents| = 500 NIF units -> width 125.
    assert decal_editor.width(p._decal_working[1]) == pytest.approx(125.0)


# ── fix round 1: undo past the load, default registry, iid change ─────────

def test_undo_past_the_pane_load_keeps_the_pane_alive(env):
    """I1: a hardpoint edit staged BEFORE the pane loaded leaves a snapshot
    whose decal list is None; undoing it must not blank the loaded pane."""
    p, calls = env["p"], env["calls"]
    p._descriptors = [{"name": "Hull", "properties": {"radius": 1.0},
                       "world_pos": (0.0, 0.0, 0.0), "parent_index": None}]
    p.dispatch_event('set_radius:{"i":0,"value":3.0}')
    p.dispatch_event("decal-pane")
    p.dispatch_event("undo")                 # undoes the radius edit
    assert 0 not in p._pending_radius
    assert p._decal_working is not None
    assert [pl.name for pl in p._decal_working] == ["top"]
    assert p.dispatch_event("decal-select:top")
    assert len(calls[-1][1]) == 1


def test_default_registry_must_be_an_existing_folder_and_may_have_spaces(env):
    p = env["p"]
    (env["masks"] / "USS Excalibur.v2").mkdir()
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-default:Nope")
    d = _payload(p)["decals"]
    assert d["default_registry"] == "Zhukov" and d["error"]
    p.dispatch_event("decal-default:USS Excalibur.v2")
    d = _payload(p)["decals"]
    assert d["default_registry"] == "USS Excalibur.v2" and d["error"] is None


def test_an_iid_change_clears_the_old_instance_before_pushing(env):
    p, calls = env["p"], env["calls"]
    iid = {"v": IID}
    p._iid_getter = lambda: iid["v"]
    p.dispatch_event("decal-pane")
    iid["v"] = 9
    p.dispatch_event("decal-delete:top")
    assert calls[-2:] == [(IID, None), (9, [])]


# ── save ───────────────────────────────────────────────────────────────────

def _record_writes(monkeypatch):
    writes = []
    monkeypatch.setattr(decals_writer, "write_decals",
                        lambda path, pls, reg, passthrough=None:
                        writes.append((path, pls, reg)))
    return writes


def test_save_writes_the_stock_class_decals_json(env, monkeypatch):
    p = env["p"]
    writes = _record_writes(monkeypatch)
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-delete:top")
    assert _payload(p)["pending_count"] == 1
    p.dispatch_event("save")
    path, pls, reg = writes[-1]
    assert path == env["masks"] / "decals.json"
    assert pls == [] and reg == "Zhukov"
    assert _payload(p)["pending_count"] == 0
    assert not p._undo_stack
    assert "Saved" in (p._current_toast() or "")


def test_save_writes_into_the_mod_that_supplies_the_model(env, monkeypatch):
    p = env["p"]
    writes = _record_writes(monkeypatch)
    nif = env["tmp"] / "NifMod" / "Data" / "Models" / "Ships" / "BirdOfPrey" \
        / "BirdOfPrey.nif"
    index = mods.ModIndex(files={mods.fold(BOP_MODEL): mods.ModFile(
        abs_path=nif, mod_name="NifMod", target="game",
        rel=mods.fold(BOP_MODEL), raw_rel=BOP_MODEL)}, mods=[])
    monkeypatch.setattr(mods, "current", lambda: index)
    # The mod ships a registry folder (with a space in its name) but no
    # decals.json yet: the first save for the class.
    tail_rel = f"{BOP_DIR}/Masks/IKS Rotarran/tail.png"
    tail = nif.parent / "Masks" / "IKS Rotarran" / "tail.png"
    tail.parent.mkdir(parents=True)
    tail.write_bytes(_png(40, 10))
    index.files[mods.fold(tail_rel)] = mods.ModFile(
        abs_path=tail, mod_name="NifMod", target="game",
        rel=mods.fold(tail_rel), raw_rel=tail_rel)
    env["model"]["rel"] = BOP_MODEL
    p.dispatch_event("decal-pane")
    assert p._decal_working == []
    assert _payload(p)["decals"]["registries"] == ["IKS Rotarran"]
    p.dispatch_event("decal-add:tail")
    _arm_hit(env, (0.0, -300.0, 50.0), (0.0, 0.0, 1.0))
    p.decal_click(1.0, 1.0, (1280, 720))
    p.dispatch_event("decal-default:IKS Rotarran")
    p.dispatch_event("save")
    path, pls, reg = writes[-1]
    assert path == nif.parent / "Masks" / "decals.json"
    assert [pl.name for pl in pls] == ["tail"] and reg == "IKS Rotarran"


def test_a_failed_save_keeps_the_staged_edits(env, monkeypatch):
    p = env["p"]

    def _boom(path, pls, reg, passthrough=None):
        raise ValueError("corrupt decals.json")
    monkeypatch.setattr(decals_writer, "write_decals", _boom)
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-delete:top")
    p.dispatch_event("save")
    assert p._decal_working == []
    assert _payload(p)["pending_count"] == 1
    assert "corrupt" in (p._current_toast() or "")


def test_edits_survive_leaving_the_pane_until_saved(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-delete:top")
    p.dispatch_event("decal-pane")
    assert _payload(p)["pending_count"] == 1
    p.dispatch_event("decal-pane")
    assert p._decal_working == []


# ── lifecycle ──────────────────────────────────────────────────────────────

def test_closing_the_spv_clears_the_override(env):
    p, calls = env["p"], env["calls"]
    p.dispatch_event("decal-pane")
    p.close()
    assert calls[-1] == (IID, None)
    assert p.show_hull_texture is False


def test_a_mission_swap_clears_the_override(env):
    p, calls = env["p"], env["calls"]
    p.dispatch_event("decal-pane")
    p.on_mission_swap()
    assert calls[-1] == (IID, None)


def test_nothing_is_pushed_when_the_pane_was_never_entered(env):
    p, calls = env["p"], env["calls"]
    p.close()
    p.on_mission_swap()
    assert calls == []


# ── final review: malformed placements are never dropped (fix 2) ─────────

# A 2-vector origin with a non-numeric depth, and one missing its normal:
# neither can become an editable Placement, and neither may vanish on Save.
_BROKEN = {"shape": "amb saucer:0", "origin": [1, 2], "u_axis": [1, 0, 0],
           "v_axis": [0, 1, 0], "normal": [0, 0, 1], "depth": "deep",
           "note": {"keep": [1, None]}}
_NO_NORMAL = {"origin": [0, 0, 0], "u_axis": [1, 0, 0], "v_axis": [0, 1, 0],
              "depth": 1}


def _write_with_broken(env, **extra):
    (env["masks"] / "decals.json").write_text(json.dumps(
        {"format": 1, "default_registry": "Zhukov",
         "decals": {"broken": _BROKEN, "top": _TOP, "nonormal": _NO_NORMAL,
                    **extra}}))
    mods.invalidate_replacements()


def test_a_malformed_placement_is_listed_as_unreadable(env):
    p = env["p"]
    _write_with_broken(env)
    p.dispatch_event("decal-pane")
    assert [pl.name for pl in p._decal_working] == ["top"]
    d = _payload(p)["decals"]
    assert {"name": "top", "has_mask": True, "mask": "top"} in d["placements"]
    unreadable = [x for x in d["placements"] if x.get("unreadable")]
    assert [x["name"] for x in unreadable] == ["broken", "nonormal"]
    # Not selectable, not editable.
    assert not p.dispatch_event("decal-select:broken")
    assert _payload(p)["decals"]["selected"] is None
    # Its name is taken: a new placement using mask `broken` cannot shadow
    # it, and is auto-named past it instead.
    p.dispatch_event("decal-add:broken")
    assert _payload(p)["decals"]["adding_name"] == "broken_2"


def test_a_malformed_placement_survives_a_save_unchanged(env):
    p = env["p"]
    _write_with_broken(env)
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-select:top")
    p.dispatch_event("set_tool:scale")
    p.dispatch_event('scale_nudge:{"index":1,"delta":0.5}')
    p.dispatch_event("save")
    assert "Saved" in (p._current_toast() or "")
    doc = json.loads((env["masks"] / "decals.json").read_text())
    assert json.dumps(doc["decals"]["broken"]) == json.dumps(_BROKEN)
    assert json.dumps(doc["decals"]["nonormal"]) == json.dumps(_NO_NORMAL)
    assert doc["decals"]["top"]["depth"] == pytest.approx(_TOP["depth"] + 0.5)


def test_an_unreadable_placement_can_be_deleted_and_undone(env):
    p = env["p"]
    _write_with_broken(env)
    p.dispatch_event("decal-pane")
    assert p.dispatch_event("decal-delete:broken")
    d = _payload(p)["decals"]
    assert "broken" not in [x["name"] for x in d["placements"]]
    assert d["dirty"] is True
    p.dispatch_event("undo")
    assert "broken" in [x["name"] for x in _payload(p)["decals"]["placements"]]
    assert _payload(p)["decals"]["dirty"] is False
    p.dispatch_event("decal-delete:broken")
    p.dispatch_event("save")
    doc = json.loads((env["masks"] / "decals.json").read_text())
    assert list(doc["decals"]) == ["top", "nonormal"]


def test_unreadable_placements_count_toward_the_cap(env):
    p = env["p"]
    extra = {"extra%d" % i: _NO_NORMAL for i in range(13)}
    _write_with_broken(env, **extra)
    p.dispatch_event("decal-pane")
    d = _payload(p)["decals"]
    assert len(d["placements"]) == 16 and d["can_add"] is False
    p.dispatch_event("decal-add:bottom")
    d = _payload(p)["decals"]
    assert d["adding"] is False and "16" in d["error"]


def test_unreadable_placements_do_not_take_a_mask_slot(env):
    """Their mask is unknown, and the game skips an unreadable entry before
    it reaches the mask cap (hull_decals.decals_for): so they take no slot."""
    p = env["p"]
    _write_with_broken(env)                       # top + 2 unreadable
    p.dispatch_event("decal-pane")
    for i, name in enumerate(("b", "c", "d")):
        p.dispatch_event("decal-add:" + name)
        assert _payload(p)["decals"]["adding"] is True, name
        _arm_hit(env, (10.0 * i, 0.0, 60.0), (0.0, 0.0, 1.0))
        p.decal_click(1.0, 1.0, (1280, 720))
    assert [pl.name for pl in p._decal_working] == ["top", "b", "c", "d"]


# ── final review: a preview the game won't show is flagged (fix 4) ──────

NOT_SHOWN = ("Not shown in game — no registry for this ship. "
             "Use 'Make X the class default'.")


def _no_default(env):
    (env["masks"] / "decals.json").write_text(json.dumps(
        {"format": 1, "decals": {"top": _TOP}}))
    mods.invalidate_replacements()


def test_a_fallback_preview_carries_a_persistent_not_in_game_hint(env):
    p = env["p"]
    _no_default(env)
    p.dispatch_event("decal-pane")
    d = _payload(p)["decals"]
    assert d["registry"] == "Excalibur"        # the first folder, previewed
    assert d["hint"] == NOT_SHOWN
    p.dispatch_event("decal-select:top")        # clears errors, not the hint
    assert _payload(p)["decals"]["hint"] == NOT_SHOWN
    p.dispatch_event("decal-default:Excalibur")
    assert _payload(p)["decals"]["hint"] is None


def test_no_hint_when_the_class_has_a_default(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    assert _payload(p)["decals"]["hint"] is None


def test_no_hint_when_the_ship_swaps_its_id_texture(env, monkeypatch):
    from engine.appc import registry_texture
    _no_default(env)
    monkeypatch.setattr(registry_texture, "replacements_for",
                        lambda ship: [("ID", "/x/Zhukov.tga")])
    p = env["p"]
    p.dispatch_event("decal-pane")
    d = _payload(p)["decals"]
    assert d["registry"] == "Zhukov" and d["hint"] is None


def test_clearing_the_class_default_brings_the_hint_back_and_saves(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    assert p.dispatch_event("decal-default:")
    d = _payload(p)["decals"]
    assert d["default_registry"] is None and d["hint"] == NOT_SHOWN
    assert d["dirty"] is True
    p.dispatch_event("save")
    doc = json.loads((env["masks"] / "decals.json").read_text())
    assert "default_registry" not in doc


# ── reusable masks (spec S2.4a): Add offers every mask, auto-names ───────

def _add(env, mask, at=(0.0, 0.0, 60.0), normal=(0.0, 0.0, 1.0)):
    p = env["p"]
    p.dispatch_event("decal-add:" + mask)
    _arm_hit(env, at, normal)
    p.decal_click(1.0, 1.0, (1280, 720))


def test_the_add_picker_offers_every_mask_even_when_placed(env):
    """Zhukov holds bottom.png and top.png; `top` is placed. Both PNG stems
    are still offered, then the default names (case-folded dedupe)."""
    p = env["p"]
    p.dispatch_event("decal-pane")
    assert _payload(p)["decals"]["suggested_names"] == [
        "bottom", "top", "port", "starboard", "bow", "stern"]


def test_picking_a_mask_twice_auto_names_the_second(env):
    p, calls = env["p"], env["calls"]
    (env["masks"] / "Zhukov" / "pylon.png").write_bytes(_png(300, 100))
    p.dispatch_event("decal-pane")
    _add(env, "pylon", at=(80.0, 0.0, 0.0), normal=(1.0, 0.0, 0.0))
    _add(env, "pylon", at=(-80.0, 0.0, 0.0), normal=(-1.0, 0.0, 0.0))
    names = [pl.name for pl in p._decal_working]
    assert names == ["top", "pylon", "pylon_2"]
    first, second = p._decal_working[1], p._decal_working[2]
    assert first.mask == "" and second.mask == "pylon"
    assert _payload(p)["decals"]["selected"] == "pylon_2"
    pylon_png = str(env["masks"] / "Zhukov" / "pylon.png")
    assert _masks_of(calls[-1][1])[1:] == [pylon_png, pylon_png]
    # Both sized from pylon.png's 3:1 aspect.
    for pl in (first, second):
        h = math.sqrt(sum(c * c for c in pl.v_axis))
        assert decal_editor.width(pl) / h == pytest.approx(3.0)
    placements = _payload(p)["decals"]["placements"]
    assert {"name": "pylon_2", "has_mask": True, "mask": "pylon"} in placements
    assert {"name": "pylon", "has_mask": True, "mask": "pylon"} in placements


def test_a_third_pick_and_a_taken_unreadable_name_skip_to_the_next_free(env):
    p = env["p"]
    (env["masks"] / "decals.json").write_text(json.dumps(
        {"format": 1, "default_registry": "Zhukov",
         "decals": {"top": _TOP, "pylon": _NO_NORMAL}}))
    mods.invalidate_replacements()
    p.dispatch_event("decal-pane")
    _add(env, "pylon")
    _add(env, "pylon")
    _add(env, "top")
    assert [(pl.name, decal_editor.mask_of(pl)) for pl in p._decal_working] == [
        ("top", "top"), ("pylon_2", "pylon"), ("pylon_3", "pylon"),
        ("top_2", "top")]


def test_a_shared_missing_mask_previews_the_placeholder_for_both(env):
    p, calls = env["p"], env["calls"]
    p.dispatch_event("decal-pane")
    _add(env, "pylon")
    _add(env, "pylon")
    assert _masks_of(calls[-1][1])[1:] == [_placeholder(), _placeholder()]
    placements = _payload(p)["decals"]["placements"]
    assert {"name": "pylon_2", "has_mask": False, "mask": "pylon"} in placements
    # 2:1 default aspect for both.
    for pl in p._decal_working[1:]:
        h = math.sqrt(sum(c * c for c in pl.v_axis))
        assert decal_editor.width(pl) / h == pytest.approx(2.0)


def test_has_mask_and_the_override_follow_the_mask_not_the_name(env):
    """A loaded `neck` placement using mask `top` (no neck.png exists)."""
    p, calls = env["p"], env["calls"]
    (env["masks"] / "decals.json").write_text(json.dumps(
        {"format": 1, "default_registry": "Zhukov",
         "decals": {"top": _TOP, "neck": dict(_TOP, mask="top")}}))
    mods.invalidate_replacements()
    p.dispatch_event("decal-pane")
    top_png = str(env["masks"] / "Zhukov" / "top.png")
    assert _masks_of(calls[-1][1]) == [top_png, top_png]
    assert ({"name": "neck", "has_mask": True, "mask": "top"}
            in _payload(p)["decals"]["placements"])


def _load_neck_2_to_1(env):
    """`neck` (mask `top`, 8x2 -> 4:1), authored at 2:1."""
    (env["masks"] / "decals.json").write_text(json.dumps(
        {"format": 1, "default_registry": "Zhukov",
         "decals": {"top": _TOP,
                    "neck": {"origin": [-50.0, 25.0, 60.0],
                             "u_axis": [100.0, 0.0, 0.0],
                             "v_axis": [0.0, -50.0, 0.0],
                             "normal": [0.0, 0.0, 1.0], "depth": 3.0,
                             "mask": "top"}}}))
    mods.invalidate_replacements()


def test_a_width_nudge_locks_to_the_placements_mask_aspect(env):
    p = env["p"]
    _load_neck_2_to_1(env)
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-select:neck")
    p.dispatch_event("set_tool:scale")
    assert p.dispatch_event('scale_nudge:{"index":0,"delta":10}')
    pl = p._decal_working[1]
    h = math.sqrt(sum(c * c for c in pl.v_axis))
    assert decal_editor.width(pl) == pytest.approx(110.0)
    assert decal_editor.width(pl) / h == pytest.approx(4.0)
    assert pl.mask == "top"


def test_the_scale_gizmo_locks_to_the_placements_mask_aspect(env):
    p = env["p"]
    _load_neck_2_to_1(env)
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-select:neck")
    p.dispatch_event("set_tool:scale")
    from engine.ui.ship_property_viewer import gizmo_length
    L = gizmo_length(p.camera)
    p._begin_scale_drag(0, L)
    p._apply_scale_drag(L)
    p._end_axis_drag()
    pl = p._decal_working[1]
    h = math.sqrt(sum(c * c for c in pl.v_axis))
    assert decal_editor.width(pl) / h == pytest.approx(4.0)
    assert pl.mask == "top"


def test_a_seventeenth_placement_is_refused(env):
    p = env["p"]
    decals = {"top": _TOP}
    decals.update({"top_%d" % i: dict(_TOP, mask="top") for i in range(2, 17)})
    (env["masks"] / "decals.json").write_text(json.dumps(
        {"format": 1, "default_registry": "Zhukov", "decals": decals}))
    mods.invalidate_replacements()
    p.dispatch_event("decal-pane")
    d = _payload(p)["decals"]
    assert len(d["placements"]) == 16 and d["can_add"] is False
    p.dispatch_event("decal-add:top")
    d = _payload(p)["decals"]
    assert d["adding"] is False and "16" in d["error"]
    assert len(p._decal_working) == 16


def test_move_rotate_reposition_delete_and_undo_keep_the_mask(env):
    p = env["p"]
    _load_neck_2_to_1(env)
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-select:neck")
    p.dispatch_event("set_tool:transform")
    p._begin_axis_drag(0, 0.0)
    p._apply_axis_drag(1.0)
    p._end_axis_drag()
    assert p._decal_working[1].mask == "top"
    p.dispatch_event("set_tool:rotate")
    p._begin_ring_drag(2, 0.0)
    p._apply_ring_drag_angle(0.3)
    assert p._decal_working[1].mask == "top"
    p.dispatch_event('rotate_nudge:{"index":0,"delta":5}')
    p.dispatch_event("set_tool:transform")
    p.dispatch_event('coord_nudge:{"index":0,"delta":5}')
    assert p._decal_working[1].mask == "top"
    p.dispatch_event("decal-reposition")
    _arm_hit(env, (200.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    p.decal_click(1.0, 1.0, (1280, 720))
    assert p._decal_working[1].mask == "top"
    p.dispatch_event("decal-delete:neck")
    p.dispatch_event("undo")
    assert [(pl.name, pl.mask) for pl in p._decal_working] == [
        ("top", ""), ("neck", "top")]


def test_save_writes_the_mask_key_only_where_it_differs(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    _add(env, "pylon")
    _add(env, "pylon")
    p.dispatch_event("save")
    assert "Saved" in (p._current_toast() or "")
    doc = json.loads((env["masks"] / "decals.json").read_text())
    assert "mask" not in doc["decals"]["pylon"]
    assert doc["decals"]["pylon_2"]["mask"] == "pylon"
    assert "mask" not in doc["decals"]["top"]
