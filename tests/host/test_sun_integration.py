"""Integration tests for sun rendering wiring in host_loop.run()."""
import os

import pytest

from tests.helpers import bc_assets

GALAXY_NIF = bc_assets.GAME_ROOT / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif"


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
