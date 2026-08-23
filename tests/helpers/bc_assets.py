"""Guards for tests that need a retail Bridge Commander install.

game/ is developer-supplied and gitignored, so a clean checkout has no
textures, models or Maelstrom TGLs. The suite's convention is that
asset-dependent tests SKIP rather than fail in that situation (see
tools/check_test_baseline.py, which relies on it to stay runnable anywhere).
These helpers make that check one call instead of an open-coded path probe.
"""
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GAME_ROOT = PROJECT_ROOT / "game"


def require_game_asset(relpath: str) -> Path:
    """Skip the calling test unless <game>/<relpath> exists. Returns the path.

    relpath is written as the SDK writes it (forward slashes, BC's casing);
    Path handles the separator, and the lookup is as case-sensitive as the
    host filesystem -- the same resolution the engine itself gets.
    """
    path = GAME_ROOT / relpath
    if not path.is_file():
        pytest.skip(f"BC assets not available: {relpath}")
    return path
