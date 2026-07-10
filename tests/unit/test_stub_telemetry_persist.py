import json
import os

import pytest

from engine.core import stub_telemetry


@pytest.fixture(autouse=True)
def _clean_telemetry():
    prev = stub_telemetry.ENABLED
    stub_telemetry.reset()
    yield
    stub_telemetry.set_enabled(prev)
    stub_telemetry.reset()


def test_persist_run_writes_one_valid_json_line(tmp_path):
    stub_telemetry.set_enabled(True)
    stub_telemetry.record_attr("TorpedoTube", "GetMaxCharge")
    stub_telemetry.record_attr("TorpedoTube", "GetMaxCharge")
    stub_telemetry.record_attr("ShipClass", "GetWarpCore.GetMaxPower")  # dotted attr
    path = str(tmp_path / "hits.jsonl")

    stub_telemetry.persist_run(path)

    with open(path) as f:
        lines = f.read().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert isinstance(rec["t"], float)
    # pair key is tab-separated so a dotted attr is unambiguous
    assert rec["attr_hits"]["TorpedoTube\tGetMaxCharge"] == 2
    assert rec["attr_hits"]["ShipClass\tGetWarpCore.GetMaxPower"] == 1


def test_persist_run_appends_a_line_per_call(tmp_path):
    stub_telemetry.set_enabled(True)
    path = str(tmp_path / "hits.jsonl")
    stub_telemetry.record_attr("A", "x")
    stub_telemetry.persist_run(path)
    stub_telemetry.reset()
    stub_telemetry.record_attr("B", "y")
    stub_telemetry.persist_run(path)
    with open(path) as f:
        assert len(f.read().splitlines()) == 2


def test_persist_run_never_raises_on_bad_path():
    stub_telemetry.set_enabled(True)
    stub_telemetry.record_attr("A", "x")
    # a path whose parent directory does not exist must be swallowed
    stub_telemetry.persist_run("/no/such/dir/hits.jsonl")


def test_sidecar_path_is_absolute():
    assert os.path.isabs(stub_telemetry.SIDECAR_PATH)
