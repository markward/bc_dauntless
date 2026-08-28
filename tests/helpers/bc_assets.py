"""Guards for tests that need a retail Bridge Commander install.

game/ is developer-supplied and gitignored, so a clean checkout has no
textures, models or Maelstrom TGLs. The suite's convention is that
asset-dependent tests SKIP rather than fail in that situation (see
tools/check_test_baseline.py, which relies on it to stay runnable anywhere).
These helpers make that check one call instead of an open-coded path probe.
"""
from pathlib import Path, PurePosixPath
from typing import Optional

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GAME_ROOT = PROJECT_ROOT / "game"


def resolve_game_path(relpath: str) -> Optional[Path]:
    """The real path of <game>/<relpath>, or None if nothing there matches.

    Case-insensitively, because that is what the engine does: BC ships
    "Bridge Crew General.TGL" while the SDK scripts spell it ".tgl", and
    native/src/assets/src/path_resolver.cc bridges the two through a
    lower-cased map of directory entries. Comparing with a plain is_file()
    instead only agrees with the engine on a case-insensitive filesystem --
    it matches on macOS and Windows and silently stops matching on Linux,
    where a full retail install would start reporting itself as absent.

    Returns the path AS SPELLED ON DISK, so callers open the file the engine
    would open rather than a spelling that only resolves on some hosts. The
    walk runs even when the requested spelling would open directly: on a
    case-insensitive filesystem it opens whatever the case, and taking that
    shortcut would hand back the requested spelling on macOS and the real one
    on Linux -- the platform split this function exists to remove.
    """
    current = GAME_ROOT
    for part in PurePosixPath(relpath).parts:
        if not current.is_dir():
            return None
        wanted = part.lower()
        match = next((entry for entry in sorted(current.iterdir(), key=lambda e: e.name)
                      if entry.name.lower() == wanted), None)
        if match is None:
            return None
        current = match
    return current


def require_game_asset(relpath: str) -> Path:
    """Skip the calling test unless <game>/<relpath> is a file. Returns it.

    relpath is written as the SDK writes it (forward slashes, the SDK's
    casing); resolution matches the engine's, so a difference in case between
    the SDK's spelling and the disc's does not read as a missing asset. See
    resolve_game_path.
    """
    path = resolve_game_path(relpath)
    if path is None or not path.is_file():
        pytest.skip(f"BC assets not available: {relpath}")
    return path


def require_game_dir(relpath: str) -> Path:
    """Skip the calling test unless <game>/<relpath> is a directory.

    For dependencies satisfied by a tree rather than one file -- ship models,
    icon sets -- where naming the single file a test happens to reach would
    be both brittle and misleading about what is actually required.
    """
    path = resolve_game_path(relpath)
    if path is None or not path.is_dir():
        pytest.skip(f"BC assets not available: {relpath}/")
    return path
