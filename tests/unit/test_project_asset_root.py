"""The renderer's PROJECT asset root -- where project-authored (non-BC)
textures such as the collision-scuff normal map live: <PROJECT_ROOT>/native/
assets. The binary only knew BC's game root, so a project asset had no way
to resolve; this push mirrors hull_volume_set_cache_root (same boot site,
same no-guard contract).
"""
import ast
import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from engine import paths
import engine.renderer as renderer


def test_root_is_native_assets_under_the_project():
    root = paths.project_asset_root()
    assert root == paths.PROJECT_ROOT / "native" / "assets"
    assert "game" not in root.parts and "sdk" not in root.parts


def test_facade_pushes_the_root_as_str(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_project_asset_root(Path("/some/root"))
    fake.set_project_asset_root.assert_called_once_with("/some/root")


def test_a_renderer_failure_propagates(monkeypatch):
    fake = MagicMock()
    fake.set_project_asset_root.side_effect = RuntimeError("no renderer")
    monkeypatch.setattr(renderer, "_h", fake)
    with pytest.raises(RuntimeError):
        renderer.set_project_asset_root("/some/root")


def test_binding_is_required_and_unguarded():
    assert "set_project_asset_root" in renderer._REQUIRED_BINDINGS
    src = inspect.getsource(renderer.set_project_asset_root)
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("hasattr", "getattr"), src


def test_host_loop_pushes_it_beside_the_game_root():
    """Same boot site as set_game_root / hull_volume_set_cache_root, bare."""
    src = Path(inspect.getsourcefile(__import__("engine.host_loop").host_loop)).read_text()
    assert "r.set_project_asset_root(str(_paths.project_asset_root()))" in src
