import pytest

from engine.core import stub_telemetry
from engine.core.ids import _Stub


@pytest.fixture(autouse=True)
def _clean_telemetry():
    prev = stub_telemetry.ENABLED
    stub_telemetry.reset()
    yield
    stub_telemetry.set_enabled(prev)
    stub_telemetry.reset()


def test_bool_still_true_and_unrecorded_when_disabled():
    stub_telemetry.set_enabled(False)
    s = _Stub("GetShields", "ShipClass")
    assert bool(s) is True
    if s:  # truth-test site, but disabled
        pass
    assert stub_telemetry.snapshot()["bool_sites"] == {}


def test_bool_records_caller_site_when_enabled_and_stays_true():
    stub_telemetry.set_enabled(True)
    s = _Stub("GetShields", "ShipClass")
    result = bool(s)  # <-- this line should be the recorded site
    assert result is True
    sites = stub_telemetry.snapshot()["bool_sites"]
    assert sum(sites.values()) == 1
    assert any("test_stub_telemetry_bool.py" in key for key in sites)
