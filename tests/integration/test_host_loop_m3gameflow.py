"""Renderer host-loop smoke for M3Gameflow.

Runs engine.host_loop.run() with OPEN_STBC_HOST_HEADLESS=1 and an
OPEN_STBC_HOST_MISSION pointing at M3Gameflow. Asserts the run
completes the configured tick budget without raising.

Two preconditions must hold:
  - The `_dauntless_host` native extension is built (importorskip).
  - The BC `game/` install is on disk (gitignored copyrighted assets).
    Probe via game/data/Bridge existence.

The test skips cleanly when either is missing — matches the pattern in
tests/integration/test_gameloop_harness.py and accommodates CI/dev
environments without the BC install."""
import os
from pathlib import Path
import pytest

pytest.importorskip("_dauntless_host")

# Probe the BC game install. The renderer's host_loop loads bridge NIFs
# from game/data/Bridge before any mission script runs, so a missing
# game dir would surface as a renderer-side RuntimeError. Skip rather
# than fail in environments where the BC assets aren't on disk.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_GAME_BRIDGE = _PROJECT_ROOT / "game" / "data" / "Bridge"
if not _GAME_BRIDGE.exists():
    pytest.skip(
        f"BC game install missing (no {_GAME_BRIDGE}); renderer "
        "verification requires the gitignored game/ directory.",
        allow_module_level=True,
    )


def test_host_loop_runs_m3gameflow_120_ticks(monkeypatch):
    """120 ticks ≈ 2 seconds at 60Hz. Smallest viable smoke for the
    renderer + M3Gameflow integration. Headless mode hides the window."""
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")
    monkeypatch.setenv(
        "OPEN_STBC_HOST_MISSION",
        "Custom.Tutorial.Episode.M3Gameflow.M3Gameflow",
    )
    from engine.host_loop import run
    rc = run(max_ticks=120)
    assert rc == 0
