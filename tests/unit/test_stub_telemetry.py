import pytest

from engine.core import stub_telemetry


@pytest.fixture(autouse=True)
def _clean_telemetry():
    prev = stub_telemetry.ENABLED
    stub_telemetry.reset()
    yield
    stub_telemetry.set_enabled(prev)
    stub_telemetry.reset()


def test_disabled_by_default_records_nothing():
    stub_telemetry.set_enabled(False)
    stub_telemetry.record_attr("ShipClass", "GetWarpCore")
    stub_telemetry.record_bool("ShipClass")
    stub_telemetry.record_coercion("int")
    snap = stub_telemetry.snapshot()
    assert snap["attr_hits"] == {}
    assert snap["bool_sites"] == {}
    assert snap["coercion_sites"] == {}


def test_enabled_records_attr_hits_with_counts():
    stub_telemetry.set_enabled(True)
    stub_telemetry.record_attr("ShipClass", "GetWarpCore")
    stub_telemetry.record_attr("ShipClass", "GetWarpCore")
    stub_telemetry.record_attr("Mission", "GetFriendlyGroup")
    snap = stub_telemetry.snapshot()
    assert snap["attr_hits"][("ShipClass", "GetWarpCore")] == 2
    assert snap["attr_hits"][("Mission", "GetFriendlyGroup")] == 1


def test_enabled_records_bool_site():
    stub_telemetry.set_enabled(True)
    stub_telemetry.record_bool("ShipClass")
    sites = stub_telemetry.snapshot()["bool_sites"]
    # Exactly one site recorded, keyed by a non-empty "file:line" string.
    # NOTE: this calls record_bool() directly, so the captured frame is not
    # this test line (the caller-depth is calibrated for the production path
    # _Stub.__bool__ -> record_bool). Asserting the *identity* of the site is
    # done in Task 3's test, which goes through __bool__. Here we only assert a
    # site was captured.
    assert sum(sites.values()) == 1
    assert all(isinstance(key, str) and key for key in sites)


def test_enabled_records_coercion_site():
    stub_telemetry.set_enabled(True)
    stub_telemetry.record_coercion("int")
    sites = stub_telemetry.snapshot()["coercion_sites"]
    # Exactly one site recorded, keyed by a (kind, "file:line") pair.
    # NOTE: this calls record_coercion() directly, so the captured frame is
    # not this test line — see test_stub_telemetry_appmodule.py for the
    # depth-calibrated assertion that goes through the real __int__ dunder.
    assert sum(sites.values()) == 1
    assert all(isinstance(k, tuple) and len(k) == 2 for k in sites)
    ((kind, site),) = list(sites.keys())
    assert kind == "int"
    assert isinstance(site, str) and site


def test_record_never_raises_even_on_bad_input():
    stub_telemetry.set_enabled(True)
    # None args must not blow up the game
    stub_telemetry.record_attr(None, None)
    stub_telemetry.record_bool(None)
    stub_telemetry.record_coercion(None)


def test_dump_report_is_string_and_ranks_by_frequency():
    stub_telemetry.set_enabled(True)
    stub_telemetry.record_attr("A", "rare")
    for _ in range(5):
        stub_telemetry.record_attr("B", "common")
    report = stub_telemetry.dump_report()
    assert isinstance(report, str)
    assert report.index("common") < report.index("rare")


def test_dump_report_includes_coercion_section():
    stub_telemetry.set_enabled(True)
    stub_telemetry.record_coercion("int")
    report = stub_telemetry.dump_report()
    assert "numeric-coercion call sites" in report


def test_env_truthy_parsing():
    # Falsy cases: empty string, "0", "false", "False"
    assert stub_telemetry._env_truthy("") is False
    assert stub_telemetry._env_truthy("0") is False
    assert stub_telemetry._env_truthy("false") is False
    assert stub_telemetry._env_truthy("False") is False
    # Truthy cases: "1", "true", "yes", and anything else
    assert stub_telemetry._env_truthy("1") is True
    assert stub_telemetry._env_truthy("true") is True
    assert stub_telemetry._env_truthy("yes") is True
    assert stub_telemetry._env_truthy("anything-else") is True
