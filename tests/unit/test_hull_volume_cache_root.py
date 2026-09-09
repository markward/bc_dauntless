"""The hull-volume cache root -- plan §4 requires it resolve through
engine/paths.py at USE, never at import. Nothing in plan 1 exercised this
(nothing had ever constructed a HullVolumeCache), so it was untested surface
until this task.

Four things are asserted:
  1. the computed root ends in cache/hull_volumes (the weapon_icons.py
     cache/icons/... convention);
  2. it is computed fresh on every call, not captured once at import -- proven
     by monkeypatching the underlying project-root source and observing the
     SECOND call reflect the change, not just that two unpatched calls agree;
  3. neither "game" nor "sdk" appears as a path segment in it;
  4. a renderer failure from the façade wrapper propagates rather than being
     swallowed -- matching the push_resolution contract in
     engine/appc/hull_volume.py, where the caller's dev_mode.log_swallowed is
     the intended visibility mechanism.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from engine import paths
import engine.renderer as renderer


# ── 1. shape ─────────────────────────────────────────────────────────────

def test_root_ends_in_cache_hull_volumes():
    root = paths.hull_volume_cache_root()
    assert root.parts[-2:] == ("cache", "hull_volumes")


# ── 2. resolved at call time, not captured at import ────────────────────

def test_root_is_resolved_at_call_time_not_captured(monkeypatch, tmp_path):
    """Discriminator: if hull_volume_cache_root() (or anything it depends on)
    captured PROJECT_ROOT once at import -- the exact trap game_root() /
    sdk_root() / game_asset() exist to avoid -- patching the underlying
    source AFTER import and calling again would have no effect. Calling the
    function twice with nothing changed in between (the naive version of this
    test) would pass whether or not the value was memoized at import, because
    both calls would just return the same memoized constant -- so the
    discriminating step is patching PROJECT_ROOT and asserting the SECOND call
    reflects it.
    """
    first = paths.hull_volume_cache_root()

    fake_root = tmp_path / "a-different-checkout"
    monkeypatch.setattr(paths, "PROJECT_ROOT", fake_root)

    second = paths.hull_volume_cache_root()

    assert second == fake_root / "cache" / "hull_volumes"
    assert second != first


# ── 3. no "game"/"sdk" path segment ──────────────────────────────────────

def test_root_spells_neither_game_nor_sdk_as_a_segment():
    root = paths.hull_volume_cache_root()
    assert "game" not in root.parts
    assert "sdk" not in root.parts


# ── 4. renderer failures propagate, are not swallowed ────────────────────

def test_cache_root_push_forwards_to_the_binding(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.hull_volume_set_cache_root("/some/root")
    fake.hull_volume_set_cache_root.assert_called_once_with("/some/root")


def test_cache_root_push_coerces_a_path_object_to_str(monkeypatch):
    """host_loop passes paths.hull_volume_cache_root(), a Path, straight
    through -- the pybind signature is a plain str argument."""
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.hull_volume_set_cache_root(Path("/some/root"))
    fake.hull_volume_set_cache_root.assert_called_once_with("/some/root")


def test_a_renderer_failure_propagates(monkeypatch):
    """A broken binding (stale .so, a pybind arg-type regression) must NOT be
    swallowed inside the façade wrapper -- the boot call site in host_loop.py
    calls this bare (no try/except), exactly like set_game_root just above
    it, on the theory that a broken cache-root push should be as loud as a
    broken game-root push. Were this wrapper to swallow the exception, that
    boot-time visibility would be permanently disabled -- indistinguishable
    from "nothing went wrong"."""
    fake = MagicMock()
    fake.hull_volume_set_cache_root.side_effect = RuntimeError("no renderer")
    monkeypatch.setattr(renderer, "_h", fake)
    with pytest.raises(RuntimeError):
        renderer.hull_volume_set_cache_root("/some/root")


def test_no_hasattr_guard_around_the_wrapper_call():
    """Static check matching the brief's constraint #2: host_loop.py:4780
    documents a feature (hull bound spheres) that shipped completely inert
    because a hasattr guard on a REQUIRED binding turned a loud missing-
    binding AttributeError into a silent per-call skip. hull_volume_set_
    cache_root is REQUIRED (see _REQUIRED_BINDINGS), so its call site in
    engine/renderer.py must call _h.hull_volume_set_cache_root directly, with
    no hasattr/getattr guard wrapped around it."""
    import ast
    import inspect

    src = inspect.getsource(renderer.hull_volume_set_cache_root)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = (func.id if isinstance(func, ast.Name)
                    else func.attr if isinstance(func, ast.Attribute) else None)
            assert name not in ("hasattr", "getattr"), (
                "hull_volume_set_cache_root must call _h directly, no "
                "hasattr/getattr guard")


def test_binding_is_required_not_optional():
    """A binding degraded to _OPTIONAL_BINDINGS would make a stale/incomplete
    .so fail silently (warn-only, and only under --developer) instead of the
    loud validate_bindings() ERROR this feature needs."""
    assert "hull_volume_set_cache_root" in renderer._REQUIRED_BINDINGS
    assert "hull_volume_set_cache_root" not in renderer._OPTIONAL_BINDINGS
