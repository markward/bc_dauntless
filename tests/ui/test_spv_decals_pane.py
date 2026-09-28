"""SPV Decals pane (spec docs/superpowers/specs/2026-09-28-spv-decal-editing-
design.md S3): the panel logic against a fake host_io that records every
set_instance_decals / ray_trace_mesh call.

The fake ship is ROTATED and SCALED on purpose: the decal maths is in the
ship-BODY frame (unscaled model units), while ray_trace_mesh answers in world
coordinates -- a conversion that silently assumed identity/unit scale would
pass an axis-aligned fixture and misplace every decal on a real ship.
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
from engine.ui import decal_editor
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel

AMB_DIR = "data/Models/Ships/Ambassador"
AMB_MODEL = f"{AMB_DIR}/Ambassador.nif"
BOP_DIR = "data/Models/Ships/BirdOfPrey"
BOP_MODEL = f"{BOP_DIR}/BirdOfPrey.nif"
IID = 7
SCALE = 2.0
RADIUS_GU = 10.0          # => 5.0 model units at SCALE 2


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


def _world_from_body(ship, p, scale=SCALE):
    v = TGPoint3(p[0] * scale, p[1] * scale, p[2] * scale)
    v.MultMatrixLeft(ship.GetWorldRotation())
    loc = ship.GetWorldLocation()
    return (loc.x + v.x, loc.y + v.y, loc.z + v.z)


def _world_dir_from_body(ship, n):
    v = TGPoint3(*n)
    v.MultMatrixLeft(ship.GetWorldRotation())
    return (v.x, v.y, v.z)


def _close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


_TOP = {"shape": "amb saucer:0", "origin": [0.0, 1.0, 2.0],
        "u_axis": [1.0, 0.0, 0.0], "v_axis": [0.0, -0.5, 0.0],
        "normal": [0.0, 0.0, 1.0], "depth": 0.1}


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
    assert _close(origin, (0.0, 1.0, 2.0)) and _close(n, (0.0, 0.0, 1.0))
    assert depth == pytest.approx(0.1)
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
    assert d["placements"] == [{"name": "top", "has_mask": True}]
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
    _arm_hit(env, (0.5, -1.0, -2.0), (0.0, 0.0, -1.0))

    p.decal_click(640.0, 360.0, (1280, 720))

    names = [pl.name for pl in p._decal_working]
    assert names == ["top", "bottom"]
    bottom = p._decal_working[1]
    assert decal_editor.chirality_ok(bottom)
    assert _close(decal_editor.centre(bottom), (0.5, -1.0, -2.0))
    assert _close(bottom.normal, (0.0, 0.0, -1.0))
    # Width is 25% of the MODEL-unit radius (10 GU / scale 2 = 5).
    assert decal_editor.width(bottom) == pytest.approx(1.25)
    # Zhukov/bottom.png is 200x50: height = width / 4.
    assert math.sqrt(sum(c * c for c in bottom.v_axis)) == pytest.approx(1.25 / 4)
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


@pytest.mark.parametrize("name", ["top", "TOP", "", "../x", "a b"])
def test_duplicate_and_invalid_names_are_refused_inline(env, name):
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-add:" + name)
    d = _payload(p)["decals"]
    assert d["adding"] is False
    assert d["error"]


def test_a_fifth_placement_is_refused(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    for i, name in enumerate(("b", "c", "d")):
        p.dispatch_event("decal-add:" + name)
        _arm_hit(env, (0.1 * i, 0.0, 1.0), (0.0, 0.0, 1.0))
        p.decal_click(1.0, 1.0, (1280, 720))
    assert len(p._decal_working) == 4
    p.dispatch_event("decal-add:e")
    d = _payload(p)["decals"]
    assert d["adding"] is False and "4" in d["error"]


def test_a_placement_without_a_mask_uses_the_placeholder(env):
    p, calls = env["p"], env["calls"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-add:port")
    _arm_hit(env, (1.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    p.decal_click(1.0, 1.0, (1280, 720))
    assert _masks_of(calls[-1][1])[1] == _placeholder()
    port = p._decal_working[1]
    # No PNG -> the 2:1 default aspect.
    assert decal_editor.width(port) == pytest.approx(
        2.0 * math.sqrt(sum(c * c for c in port.v_axis)))
    assert {"name": "port", "has_mask": False} in _payload(p)["decals"]["placements"]


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


# ── gizmos (body frame, scale divided out) ─────────────────────────────────

def test_the_move_gizmo_drives_move_uv_in_model_units(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-select:top")
    p.dispatch_event("set_tool:transform")
    g = p._active_gizmo()
    assert g is not None and g["handle_kind"] == 0
    # The gizmo's first axis is the decal's u direction, in WORLD space.
    assert _close(g["axes"][0], _world_dir_from_body(env["ship"], (1.0, 0.0, 0.0)))
    assert _close(g["origin"], _world_from_body(
        env["ship"], decal_editor.centre(p._decal_working[0])))
    c0 = decal_editor.centre(p._decal_working[0])
    p._begin_axis_drag(0, 0.0)
    p._apply_axis_drag(1.0)                 # 1 GU along world u
    c1 = decal_editor.centre(p._decal_working[0])
    assert _close(c1, (c0[0] + 1.0 / SCALE, c0[1], c0[2]))


def test_the_rotate_gizmo_rolls_about_the_normal(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-select:top")
    p.dispatch_event("set_tool:rotate")
    g = p._active_gizmo()
    assert g is not None and g["handle_kind"] == 2
    assert _close(g["axes"][2], _world_dir_from_body(env["ship"], (0.0, 0.0, 1.0)))
    c0 = decal_editor.centre(p._decal_working[0])
    p._begin_ring_drag(2, 0.0)
    p._apply_ring_drag_angle(math.pi / 2.0)
    pl = p._decal_working[0]
    assert _close(decal_editor.centre(pl), c0)
    assert decal_editor.chirality_ok(pl)
    u_hat = tuple(c / decal_editor.width(pl) for c in pl.u_axis)
    assert _close(u_hat, (0.0, 1.0, 0.0), 1e-9)


def test_the_scale_gizmo_scales_uniformly(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-select:top")
    p.dispatch_event("set_tool:scale")
    assert p._active_gizmo()["handle_kind"] == 1
    from engine.ui.ship_property_viewer import gizmo_length
    L = gizmo_length(p.camera)
    p._begin_scale_drag(0, L)
    p._apply_scale_drag(2.0 * L)
    pl = p._decal_working[0]
    assert decal_editor.width(pl) == pytest.approx(2.0)
    assert pl.depth == pytest.approx(0.2)


def test_the_numbers_panel_nudges_width_roll_depth_and_centre(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-select:top")
    n = _payload(p)["decals"]["numbers"]
    assert n["width"] == pytest.approx(1.0)
    assert n["depth"] == pytest.approx(0.1)
    assert n["roll"] == pytest.approx(0.0, abs=1e-9)
    p.dispatch_event('decal-nudge:{"field":"depth","delta":0.05}')
    p.dispatch_event('decal-nudge:{"field":"roll","delta":10}')
    p.dispatch_event('decal-nudge:{"field":"z","delta":0.5}')
    n2 = _payload(p)["decals"]["numbers"]
    assert n2["depth"] == pytest.approx(0.15)
    assert n2["roll"] == pytest.approx(10.0)
    assert n2["centre"][2] == pytest.approx(n["centre"][2] + 0.5)


def test_reposition_reseats_the_selection_at_the_next_click(env):
    p = env["p"]
    p.dispatch_event("decal-pane")
    p.dispatch_event("decal-select:top")
    p.dispatch_event("decal-reposition")
    assert _payload(p)["decals"]["reposition"] is True
    _arm_hit(env, (2.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    p.decal_click(1.0, 1.0, (1280, 720))
    pl = p._decal_working[0]
    assert _close(decal_editor.centre(pl), (2.0, 0.0, 0.0))
    assert _close(pl.normal, (1.0, 0.0, 0.0))
    assert decal_editor.chirality_ok(pl)
    assert _payload(p)["decals"]["reposition"] is False


# ── frame conversion ───────────────────────────────────────────────────────

def test_world_hit_to_body_inverts_rotation_translation_and_scale(env):
    from engine.ui.ship_property_viewer_panel import world_hit_to_body
    ship = env["ship"]
    b = (0.3, -1.7, 2.2)
    nb = (0.0, 0.6, 0.8)
    pb, nb2 = world_hit_to_body(ship, _world_from_body(ship, b),
                                _world_dir_from_body(ship, nb))
    assert _close(pb, b) and _close(nb2, nb)


# ── save ───────────────────────────────────────────────────────────────────

def _record_writes(monkeypatch):
    writes = []
    monkeypatch.setattr(decals_writer, "write_decals",
                        lambda path, pls, reg: writes.append((path, pls, reg)))
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
    env["model"]["rel"] = BOP_MODEL
    p.dispatch_event("decal-pane")
    assert p._decal_working == []
    p.dispatch_event("decal-add:tail")
    _arm_hit(env, (0.0, -3.0, 0.5), (0.0, 0.0, 1.0))
    p.decal_click(1.0, 1.0, (1280, 720))
    p.dispatch_event("decal-default:IKS")
    p.dispatch_event("save")
    path, pls, reg = writes[-1]
    assert path == nif.parent / "Masks" / "decals.json"
    assert [pl.name for pl in pls] == ["tail"] and reg == "IKS"


def test_a_failed_save_keeps_the_staged_edits(env, monkeypatch):
    p = env["p"]

    def _boom(path, pls, reg):
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
