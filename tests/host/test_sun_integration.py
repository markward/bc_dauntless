"""Integration tests for sun rendering wiring in host_loop.run()."""
import os

import pytest

from tests.helpers import bc_assets

GALAXY_NIF = bc_assets.GAME_ROOT / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"


@pytest.fixture(autouse=True)
def _mods_scan_is_hermetic(monkeypatch, tmp_path):
    """Isolate the real mods.install() scan Task 10 wired into host_loop.run().

    Every test below calls the REAL host_loop.run(), which (since Task 10)
    calls mods.install() on the success path. Without this, that call
    resolves its mods root from real ambient argv/env exactly as boot does
    in production -- correct for boot, but it means these tests perform a
    LIVE scan of whatever sits in the developer's own mods/ directory (this
    worktree keeps a real reference mod there for manual verification),
    making their output and mods._INDEX's contents machine-dependent. See
    tests/host/test_host_loop_first_run.py's identical fixture for the full
    discovery story.
    """
    monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))


def test_run_M1Basic_with_sun_wiring_does_not_crash():
    """M1Basic/Biranu1 has Sun_Create with no texture; aggregator drops it
    with a warning. run() must still complete rc=0."""
    if not GALAXY_NIF.is_file():
        pytest.skip("BC assets not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    try:
        from engine import host_loop
        rc = host_loop.run("Custom.Tutorial.Episode.M1Basic.M1Basic", max_ticks=2)
        assert rc == 0
    finally:
        os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)


def test_run_M1Basic_verbose_logs_sun_count(capsys):
    """With verbose=1, tick-0 sun log line appears."""
    if not GALAXY_NIF.is_file():
        pytest.skip("BC assets not available")
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    os.environ["OPEN_STBC_HOST_VERBOSE"] = "1"
    try:
        from engine import host_loop
        host_loop.run("Custom.Tutorial.Episode.M1Basic.M1Basic", max_ticks=2)
    finally:
        os.environ.pop("OPEN_STBC_HOST_VERBOSE", None)
        os.environ.pop("OPEN_STBC_HOST_HEADLESS", None)
    out = capsys.readouterr().out
    assert "suns:" in out


def test_aggregate_suns_called_does_not_raise():
    """Calling _aggregate_suns() outside run() must not raise."""
    from engine import host_loop
    result = host_loop._aggregate_suns()
    assert isinstance(result, list)
