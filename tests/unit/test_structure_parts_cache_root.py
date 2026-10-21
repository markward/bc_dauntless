"""The structure-parts cache root (.sps files, layered damage phase 4 §2.2)
must resolve through engine/paths.py at USE, never at import.

It replaces the carve's hull-volume cache root (.dhv), whose accessor went
with the carve's per-instance field pipeline; these are that root's guards,
carried over.

Three things are asserted:
  1. the computed root ends in cache/structure_parts;
  2. it is computed fresh on every call, not captured once at import -- proven
     by monkeypatching the underlying project-root source and observing the
     SECOND call reflect the change, not just that two unpatched calls agree;
  3. neither "game" nor "sdk" appears as a path segment in it.
"""
from engine import paths


# ── 1. shape ─────────────────────────────────────────────────────────────

def test_root_ends_in_cache_structure_parts():
    root = paths.structure_parts_cache_root()
    assert root.parts[-2:] == ("cache", "structure_parts")


# ── 2. resolved at call time, not captured at import ────────────────────

def test_root_is_resolved_at_call_time_not_captured(monkeypatch, tmp_path):
    """Discriminator: if structure_parts_cache_root() (or anything it depends
    on) captured PROJECT_ROOT once at import -- the exact trap game_root() /
    sdk_root() / game_asset() exist to avoid -- patching the underlying
    source AFTER import and calling again would have no effect. Two calls
    with nothing changed in between would agree whether or not the value was
    memoized, so the discriminating step is patching PROJECT_ROOT and
    asserting the SECOND call reflects it.
    """
    # The suite pins a temp data dir; this test is about the checkout layout.
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    first = paths.structure_parts_cache_root()

    fake_root = tmp_path / "a-different-checkout"
    monkeypatch.setattr(paths, "PROJECT_ROOT", fake_root)

    second = paths.structure_parts_cache_root()

    assert second == fake_root / "cache" / "structure_parts"
    assert second != first


# ── 3. no "game"/"sdk" path segment ──────────────────────────────────────

def test_root_spells_neither_game_nor_sdk_as_a_segment():
    root = paths.structure_parts_cache_root()
    assert "game" not in root.parts
    assert "sdk" not in root.parts


# ── the carve's root is gone ─────────────────────────────────────────────

def test_the_carve_hull_volume_root_is_gone():
    """Nothing reads or writes .dhv files any more (layered damage phase 4):
    its accessor must not linger as a second, dead cache root."""
    assert not hasattr(paths, "hull_volume_cache_root")
