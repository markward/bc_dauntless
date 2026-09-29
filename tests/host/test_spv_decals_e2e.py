"""End to end: SPV decal authoring through the REAL host.

Drives the exact pipeline task 7's brief asks for: load the Ambassador with
its committed decal ("top"), drive the Ship Property Viewer's Decals pane
(spec docs/superpowers/specs/2026-09-28-spv-decal-editing-design.md) headless
to add a "bottom" placement via a synthetic hull hit, save into a TEMP
replacements root (the committed `native/assets/replacements/.../Masks/
decals.json` must never be written), then re-resolve through
`hull_decals.decals_for` and confirm `load_model` accepts the result.

"Synthetic hit" mirrors tests/ui/test_spv_decals_pane.py's `_arm_hit`: only
`host_io.ray_trace_mesh` is faked (a hull click's geometric trace), because
the fixed-camera hit-test math is exercised elsewhere. Every other step --
`host_io.world_to_body`'s inversion, `host_io.set_instance_decals`,
`host_io.instance_model` + `renderer.model_aabb` for sizing, the Save routing
and `hull_decals.decals_for` + `load_model` -- runs through the real
`_dauntless_host` binding, per this file's own fixture pattern (mirrors
tests/host/test_hull_decals_e2e.py).
"""
import json
import math
import os
import shutil
import subprocess

import pytest

from tests.helpers import bc_assets
from engine import host_io, mods, paths
from engine.appc import hull_decals
from engine.appc.math import TGMatrix3, TGPoint3
from engine.host_loop import BC_MODEL_SCALE, _world_matrix_from
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel

GAME_DATA = bc_assets.GAME_ROOT / "data"
AMB_DIR = "data/Models/Ships/Ambassador"
AMB_MODEL = f"{AMB_DIR}/Ambassador.nif"
AMBASSADOR_NIF = GAME_DATA / "Models" / "Ships" / "Ambassador" / "Ambassador.nif"
AMBASSADOR_TEX = GAME_DATA / "Models" / "Ships" / "Ambassador" / "High"

COMMITTED_MASKS = (paths.PROJECT_ROOT / "native" / "assets" / "replacements"
                   / AMB_DIR / "Masks")
COMMITTED_DECALS_JSON = COMMITTED_MASKS / "decals.json"

# The committed decals.json git-relative path -- for `git show HEAD:...`.
# The WORKING TREE copy of this one file (unlike the registry PNGs beside
# it) holds Mark's uncommitted live saves (`bottom`, `pylon` on top of
# `top`), so a test that assumes exactly one declared placement must read
# the committed blob, never COMMITTED_DECALS_JSON directly.
_COMMITTED_DECALS_JSON_GIT_REL = (
    "native/assets/replacements/" + AMB_DIR + "/Masks/decals.json")


def _head_decals_json_bytes() -> bytes:
    return subprocess.run(
        ["git", "show", f"HEAD:{_COMMITTED_DECALS_JSON_GIT_REL}"],
        cwd=paths.PROJECT_ROOT, check=True, capture_output=True).stdout

# Body-frame (NIF units) synthetic hit for "bottom": same x/y footprint as
# the committed "top" (origin ~(58, 146, 51)), opposite face -- the saucer
# underside rather than its dorsal surface.
BOTTOM_BODY_POINT = (58.0, 140.0, -40.0)
BOTTOM_BODY_NORMAL = (0.0, 0.0, -1.0)


def _skip_unless_assets_available():
    if not AMBASSADOR_NIF.is_file():
        pytest.skip(f"BC asset not available at {AMBASSADOR_NIF}")
    if not AMBASSADOR_TEX.is_dir():
        pytest.skip(f"BC texture dir not available at {AMBASSADOR_TEX}")


def _init_host(label):
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    try:
        _dauntless_host.init(640, 480, label)
    except RuntimeError as e:
        pytest.skip(f"no GL context available: {e}")
    return _dauntless_host


class _FakeShip:
    """Identity transform at the origin: the real host instance is set to
    match exactly (`set_world_transform`), so `host_io.world_to_body`'s
    real inversion round-trips a synthetic body-frame hit."""

    def GetWorldLocation(self):
        return TGPoint3(0.0, 0.0, 0.0)

    def GetWorldRotation(self):
        return TGMatrix3()

    def GetScale(self):
        return 1.0

    def GetRadius(self):
        return 10.0


class _OffsetShip:
    """A ship in a set that is NOT the viewed one (the in-system-warp case):
    its world location is in its OWN set coordinates, and the renderer holds
    its instance at that point plus the set's view offset."""

    LOC = (1234.5, -2345.25, 345.75)

    def __init__(self, containing_set):
        self._set = containing_set

    def GetContainingSet(self):
        return self._set

    def GetWorldLocation(self):
        return TGPoint3(*self.LOC)

    def GetWorldRotation(self):
        return TGMatrix3()

    def GetScale(self):
        return 1.0

    def GetRadius(self):
        return 10.0


# A large offset on every axis, so an unshifted (set-coordinate) trace
# misses the hull outright rather than grazing it.
VIEW_OFFSET = (40000.0, -25000.0, 9000.0)


@pytest.fixture(autouse=True)
def _clean():
    hull_decals.reset()
    mods.invalidate_replacements()
    yield
    hull_decals.reset()
    mods.invalidate_replacements()


def test_spv_decal_authoring_end_to_end(tmp_path, monkeypatch):
    _skip_unless_assets_available()
    assert COMMITTED_DECALS_JSON.is_file()
    committed_before = COMMITTED_DECALS_JSON.read_bytes()

    # ── copy the committed Masks/ tree (registry PNGs, templates -- none of
    # those are ever hand-edited live) into a tmp replacements root, but
    # swap in the COMMITTED HEAD decals.json rather than the working-tree
    # one: the working copy holds Mark's uncommitted live saves (`bottom`,
    # `pylon` on top of `top`), and this test needs the known, single-
    # placement ("top") fixture to add "bottom" without a name collision
    # and assert an exact two-placement result. The real committed file
    # itself is never touched either way.
    tmp_masks = (tmp_path / "assets" / "replacements" / AMB_DIR / "Masks")
    shutil.copytree(COMMITTED_MASKS, tmp_masks)
    (tmp_masks / "decals.json").write_bytes(_head_decals_json_bytes())

    # ── Point asset resolution at the tmp replacements root from the start
    # (not just for the later Save step), so every read in this test --
    # including the very first decals_for() below -- sees the known fixture,
    # never the live/dirty real file.
    monkeypatch.setattr(paths, "project_asset_root",
                        lambda: tmp_path / "assets")
    mods.invalidate_replacements()

    # ── 1. Load the Ambassador with its committed decals ("top").
    committed_decals = hull_decals.decals_for(AMB_DIR, "Zhukov")
    assert [d[0] for d in committed_decals] == ["amb saucer:0"]

    host = _init_host("spv-decal-e2e")
    try:
        model = host.load_model(str(AMBASSADOR_NIF), str(AMBASSADOR_TEX),
                                 None, committed_decals)
        iid = host.create_instance(model)
        ship = _FakeShip()
        mat = _world_matrix_from(ship.GetWorldLocation(), ship.GetWorldRotation(),
                                  BC_MODEL_SCALE * ship.GetScale())
        host.set_world_transform(iid, mat)

        # ── 2. Drive the SPV panel headless: add "bottom" via a synthetic hit.
        import engine.ui.ship_property_viewer_panel as spv_mod
        monkeypatch.setattr(spv_mod, "build_descriptors", lambda s: [])
        model_rel = {"rel": AMB_MODEL}
        p = ShipPropertyViewerPanel(ship_getter=lambda: ship,
                                    iid_getter=lambda: iid,
                                    model_rel_getter=lambda s: model_rel["rel"])
        p.open()
        p.dispatch_event("decal-pane")
        assert [pl.name for pl in p._decal_working] == ["top"]
        p.dispatch_event("decal-registry:Zhukov")

        hit_world = tuple(
            mat[4 * r] * BOTTOM_BODY_POINT[0] + mat[4 * r + 1] * BOTTOM_BODY_POINT[1]
            + mat[4 * r + 2] * BOTTOM_BODY_POINT[2] + mat[4 * r + 3]
            for r in range(3))
        hit_normal = tuple(
            mat[4 * r] * BOTTOM_BODY_NORMAL[0] + mat[4 * r + 1] * BOTTOM_BODY_NORMAL[1]
            + mat[4 * r + 2] * BOTTOM_BODY_NORMAL[2]
            for r in range(3))
        monkeypatch.setattr(
            host_io, "ray_trace_mesh",
            lambda iid_, origin, direction, max_dist: (hit_world, hit_normal, 5.0))

        assert p.dispatch_event("decal-add:bottom")
        p.decal_click(320.0, 240.0, (640, 480))

        names = [pl.name for pl in p._decal_working]
        assert names == ["top", "bottom"], p._decal_error
        bottom = p._decal_working[1]
        from engine.ui import decal_editor
        centre = decal_editor.centre(bottom)
        for got, want in zip(centre, BOTTOM_BODY_POINT):
            assert got == pytest.approx(want, abs=1e-2)
        for got, want in zip(bottom.normal, BOTTOM_BODY_NORMAL):
            assert got == pytest.approx(want, abs=1e-3)
        assert decal_editor.chirality_ok(bottom)
        assert host.instance_decal_override_size(iid) == 2

        # ── 3. Save to the temp replacements root -- never the committed
        # file (paths.project_asset_root is already redirected there).
        target = mods.replacements_root() / AMB_DIR / "Masks" / "decals.json"
        assert target == tmp_masks / "decals.json"
        p.dispatch_event("save")
        assert "Saved" in (p._current_toast() or ""), p._decal_error

        assert COMMITTED_DECALS_JSON.read_bytes() == committed_before, (
            "the committed Ambassador decals.json must never be written")
        saved = json.loads(target.read_text())
        assert sorted(saved["decals"].keys()) == ["bottom", "top"]

        # ── 4. Re-resolve with decals_for: two placements, load_model accepts.
        hull_decals.reset()
        resolved = hull_decals.decals_for(AMB_DIR, "Zhukov")
        assert len(resolved) == 2

        handle2 = host.load_model(str(AMBASSADOR_NIF), str(AMBASSADOR_TEX),
                                  None, resolved)
        assert handle2 is not None
    finally:
        host.shutdown()


def test_a_hull_click_lands_on_the_hull_under_a_view_offset(monkeypatch):
    """The in-system-warp case: the SPV works in the ship's OWN set
    coordinates, but the renderer holds its instance in VIEW coordinates
    (set point + view offset). A real cursor ray (manual_aim.cursor_ray from
    the SPV camera, set coords) must be shifted into view coords before the
    REAL native ray_trace_mesh, and the hit handed to the REAL native
    world_to_body, so the placement lands on the hull point under the
    cursor. Nothing on that path is faked except the frames lookup that
    says which offset the ship's set has."""
    _skip_unless_assets_available()
    committed_decals = hull_decals.decals_for(AMB_DIR, "Zhukov")
    host = _init_host("spv-decal-e2e-offset")
    try:
        model = host.load_model(str(AMBASSADOR_NIF), str(AMBASSADOR_TEX),
                                None, committed_decals)
        iid = host.create_instance(model)
        ship_set = object()
        ship = _OffsetShip(ship_set)
        set_mat = _world_matrix_from(ship.GetWorldLocation(), ship.GetWorldRotation(),
                                     BC_MODEL_SCALE * ship.GetScale())
        view_mat = list(set_mat)
        for r in range(3):                       # what host_loop pushes
            view_mat[4 * r + 3] += VIEW_OFFSET[r]
        host.set_world_transform(iid, view_mat)

        from engine.systems import frames
        monkeypatch.setattr(
            frames, "view_offset",
            lambda s: VIEW_OFFSET if s is ship_set else None)

        import engine.ui.ship_property_viewer_panel as spv_mod
        from engine.ui import decal_editor
        from engine.ui.ship_property_viewer import OrbitCamera
        monkeypatch.setattr(spv_mod, "build_descriptors", lambda s: [])
        p = ShipPropertyViewerPanel(ship_getter=lambda: ship,
                                    iid_getter=lambda: iid,
                                    model_rel_getter=lambda s: AMB_MODEL)
        p.open()
        p.dispatch_event("decal-pane")
        top = p._decal_working[0]
        want = decal_editor.centre(top)          # on the saucer's dorsal face
        # Aim the SPV camera (SET coordinates) straight down at that point.
        target = tuple(set_mat[4 * r] * want[0] + set_mat[4 * r + 1] * want[1]
                       + set_mat[4 * r + 2] * want[2] + set_mat[4 * r + 3]
                       for r in range(3))
        p.camera = OrbitCamera(target=target, distance=4.0,
                               yaw=0.0, pitch=math.pi / 2.0 - 0.05)

        p.dispatch_event("decal-select:top")
        p.dispatch_event("decal-reposition")
        p.decal_click(320.0, 240.0, (640, 480))   # the viewport centre

        assert p._decal_error is None, p._decal_error
        pl = p._decal_working[0]
        got = decal_editor.centre(pl)
        # The ray is ~3 deg off vertical, so x/y land within a few units of
        # the aimed point wherever the surface sits in z, and the hit is on
        # the dorsal face (normal up). An unshifted trace misses outright
        # (MISS_HINT) -- verified by mutating the pane's frames.shifted.
        assert abs(got[0] - want[0]) < 5.0 and abs(got[1] - want[1]) < 5.0, got
        assert abs(got[2] - want[2]) < 20.0, got
        assert pl.normal[2] > 0.8, pl.normal
        assert decal_editor.chirality_ok(pl)
    finally:
        host.shutdown()
