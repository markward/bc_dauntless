"""The hull-volume cache root -- plan §4 requires it resolve through
engine/paths.py at USE, never at import. Nothing in plan 1 exercised this
(nothing had ever constructed a HullVolumeCache), so it was untested surface
until this task.

Three things are asserted:
  1. the computed root ends in cache/hull_volumes (the weapon_icons.py
     cache/icons/... convention);
  2. it is computed fresh on every call, not captured once at import -- proven
     by monkeypatching the underlying project-root source and observing the
     SECOND call reflect the change, not just that two unpatched calls agree;
  3. neither "game" nor "sdk" appears as a path segment in it.

The boot push of this root to the renderer went with the carve's per-instance
field pipeline (layered damage phase 4); the accessor stays until the native
.dhv pipeline's fate is settled.
"""
from engine import paths


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
    # The suite pins a temp data dir; this test is about the checkout layout.
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
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
