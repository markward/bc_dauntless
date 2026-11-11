"""Shared fixtures for engine.missions tests."""
from pathlib import Path

import pytest

from engine import paths as _paths
from tools import dev_sdk  # reads SDK source as reference data (spec 2026-11-11 decision 5)

SDK_TGL_ROOT = dev_sdk.sdk_data() / "TGL"
GAME_TGL_ROOT = _paths.game_root() / "data" / "TGL"


@pytest.fixture
def tutorial_episode_tgl() -> Path:
    """One-entry sample shipped with the SDK."""
    return SDK_TGL_ROOT / "Tutorial" / "Episode" / "Episode.tgl"


@pytest.fixture
def maelstrom_tgl() -> Path:
    """Larger production sample with episode and mission keys."""
    return GAME_TGL_ROOT / "Maelstrom" / "Maelstrom.tgl"
