import pytest

from engine.core import stub_telemetry
from engine.core.ids import TGObject
from engine import dev_mode


@pytest.fixture(autouse=True)
def _clean_telemetry():
    prev = stub_telemetry.ENABLED
    stub_telemetry.reset()
    yield
    stub_telemetry.set_enabled(prev)
    stub_telemetry.reset()


def test_end_to_end_report_names_hot_unimplemented_methods():
    stub_telemetry.set_enabled(True)
    ship = TGObject()
    for _ in range(3):
        ship.GetCloakingSubsystem   # simulate repeated hot access
    ship.NumProbes
    report = stub_telemetry.dump_report()
    assert "GetCloakingSubsystem" in report
    assert "NumProbes" in report
    # hotter method ranks above the colder one
    assert report.index("GetCloakingSubsystem") < report.index("NumProbes")


def test_dev_mode_enable_is_noop_without_developer(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    stub_telemetry.set_enabled(False)
    dev_mode.enable_stub_telemetry()
    assert stub_telemetry.ENABLED is False


def test_dev_mode_enable_turns_telemetry_on_in_developer(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    stub_telemetry.set_enabled(False)
    dev_mode.enable_stub_telemetry()
    assert stub_telemetry.ENABLED is True
