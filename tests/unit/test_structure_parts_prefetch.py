"""Structure parts (severance's regions) are detected from the moment a ship
is realised, not at its first damaged draw, and cached on disk
(layered damage phase 4 §2.2).

Both ship realize sites -- realize_set_objects and the controller's
_MissionLoader._realize_session -- queue the hull's fill-volume decode AND its
structure-part detection. The second site used to queue neither. A renderer
without the binding (a stale .so) never blocks spawn. The disk cache's root
is pushed from Python at boot, resolved at use through paths.
"""
import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import App
from engine import paths
import engine.renderer as renderer
from engine.appc.sets import SetClass_Create


class _FakeRenderer:
    """Just enough renderer for both realize sites, recording the prefetches."""

    def __init__(self):
        self._next = 1
        self.fill_prefetches = []
        self.structure_prefetches = []

    def load_model(self, path, search, texture_replacements=None, decals=None):
        return 100

    def model_aabb(self, h):
        return ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))

    def model_bounds(self, h):
        return [(0.0, 0.0, 0.0, 10.0)]

    def create_instance(self, h):
        iid = self._next
        self._next += 1
        return iid

    def destroy_instance(self, iid):
        pass

    def set_world_transform(self, iid, m):
        pass

    def set_rim_eligible(self, iid, b):
        pass

    def set_surface_rock(self, iid, rock):
        pass

    def set_rim_strength(self, iid, s):
        pass

    def prewarm_trace_accel(self, handle):
        pass

    def prefetch_hull_fill(self, handle):
        self.fill_prefetches.append(handle)

    def prefetch_structure_parts(self, handle):
        self.structure_prefetches.append(handle)


def _one_ship_set(name):
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, name)
    ship = App.ShipClass_Create()
    ship.SetName(name + " hull")
    s.AddObjectToSet(ship, name + " hull")
    return s, ship


def test_realize_set_objects_prefetches_the_structure_parts(monkeypatch):
    from engine import host_loop as hl
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")
    sess = hl.MissionSession(mission_name="t")
    s, ship = _one_ship_set("SP1")

    r = _FakeRenderer()
    hl.realize_set_objects(sess, s, r)

    assert ship in sess.ship_instances
    assert r.structure_prefetches == [100]
    assert r.fill_prefetches == [100]


def test_realize_session_prefetches_the_fill_and_the_structure_parts(monkeypatch):
    """Ledger carry-over: the controller's realize path queued neither."""
    from tools import mission_harness
    mission_harness.setup_sdk()
    from engine import host_loop as hl
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")

    controller = hl.HostController()
    r = _FakeRenderer()
    controller.renderer = r
    controller.loader = hl._MissionLoader(controller, verbose=False)
    session = controller.loader.load_quickbattle()

    from engine.core.game import Game_GetCurrentGame
    player = Game_GetCurrentGame().GetPlayer()
    assert player is not None and player in session.ship_instances
    assert 100 in r.structure_prefetches, \
        "the controller's realize path never started structure-part detection"
    assert 100 in r.fill_prefetches, \
        "the controller's realize path never queued the hull fill decode"


@pytest.mark.parametrize("missing", ["prefetch_structure_parts", "prefetch_hull_fill"])
def test_a_renderer_without_the_binding_never_blocks_spawn(monkeypatch, missing):
    from engine import host_loop as hl
    monkeypatch.setattr(hl, "_ship_nif_path", lambda ship, **k: "fake.nif")
    sess = hl.MissionSession(mission_name="t")
    s, ship = _one_ship_set("SP2" + missing)

    # A stale .so: the same renderer with that one method absent.
    stale = type("_Stale", (), {k: v for k, v in vars(_FakeRenderer).items()
                                if k != missing})
    r = stale()
    assert not hasattr(r, missing)
    hl.realize_set_objects(sess, s, r)

    assert ship in sess.ship_instances
    # The other prefetch still ran: one failing never skips its sibling.
    other = (r.fill_prefetches if missing == "prefetch_structure_parts"
             else r.structure_prefetches)
    assert other == [100]


def test_cache_root_is_structure_parts_under_the_cache_dir(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "data"))
    root = paths.structure_parts_cache_root()
    assert root == paths.cache_dir() / "structure_parts"
    assert root.is_relative_to(tmp_path / "data")
    assert not root.exists(), "resolving the root must not create it"


def test_facades_forward_to_the_bindings(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.prefetch_structure_parts(7)
    fake.prefetch_structure_parts.assert_called_once_with(7)
    renderer.structure_parts_set_cache_root(Path("/some/root"))
    fake.structure_parts_set_cache_root.assert_called_once_with("/some/root")
    assert "prefetch_structure_parts" in renderer._REQUIRED_BINDINGS
    assert "structure_parts_set_cache_root" in renderer._REQUIRED_BINDINGS


def test_host_loop_pushes_the_cache_root_at_boot():
    """Beside set_project_asset_root, resolved at the push, never captured."""
    src = Path(inspect.getsourcefile(__import__("engine.host_loop").host_loop)).read_text()
    push = "r.structure_parts_set_cache_root(str(_paths.structure_parts_cache_root()))"
    assert push in src
    assert src.index(push) > src.index(
        "r.set_project_asset_root(str(_paths.project_asset_root()))")
