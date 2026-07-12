"""Regression coverage for the App-module stub path reaching stub_telemetry.

Closes the blind spot described in
docs/superpowers/plans (see fix-stub-telemetry-blindspot report): App's
module-level ``__getattr__`` and its ``_Stub``/``_NamedStub`` fallback record
NOTHING today, so an undefined constant (App.<CLASS>.<CONST>) is invisible to
the heatmap and the truthy/int()==0 collapse traps go unrecorded.

``ThisSymbolIsGenuinelyUndefinedInTheShim`` is not defined anywhere in App.py
or the SDK shims (grep-verified) and does not start with WC_/KY_, so it always
falls through the module __getattr__ to a fresh _NamedStub — unlike
`TGUIObject`, which App.py now binds to real ALIGN_* constants and so no
longer collapses to a stub.
"""

import pytest

import App
from engine.core import stub_telemetry

UNDEFINED_NAME = "ThisSymbolIsGenuinelyUndefinedInTheShim"


@pytest.fixture(autouse=True)
def _clean_telemetry():
    prev = stub_telemetry.ENABLED
    stub_telemetry.reset()
    yield
    stub_telemetry.set_enabled(prev)
    stub_telemetry.reset()


def test_undefined_app_attr_records_owner_app_when_enabled():
    stub_telemetry.set_enabled(True)
    getattr(App, UNDEFINED_NAME)
    hits = stub_telemetry.snapshot()["attr_hits"]
    assert hits.get(("App", UNDEFINED_NAME)) == 1


def test_chained_named_stub_access_splits_owner_and_attr():
    stub_telemetry.set_enabled(True)
    stub = getattr(App, UNDEFINED_NAME)
    stub.ALIGN_BL  # chained attribute access on the returned _NamedStub
    hits = stub_telemetry.snapshot()["attr_hits"]
    # split at the FIRST dot: owner = the undefined class name, attr = ALIGN_BL
    assert hits.get((UNDEFINED_NAME, "ALIGN_BL")) == 1


def test_bool_of_named_stub_records_truthiness_trap():
    stub_telemetry.set_enabled(True)
    stub = getattr(App, UNDEFINED_NAME)
    result = bool(stub)  # <-- this line should be the recorded bool site
    assert result is True  # behaviour unchanged: still truthy
    sites = stub_telemetry.snapshot()["bool_sites"]
    assert any("test_stub_telemetry_appmodule.py" in site for site in sites)


def test_int_of_named_stub_records_coercion_site():
    stub_telemetry.set_enabled(True)
    stub = getattr(App, UNDEFINED_NAME)
    result = int(stub)  # <-- this line should be the recorded coercion site
    assert result == 0  # behaviour unchanged: still collapses to 0
    sites = stub_telemetry.snapshot()["coercion_sites"]
    assert any(kind == "int" and "test_stub_telemetry_appmodule.py" in site
               for (kind, site) in sites)


def test_float_and_index_of_named_stub_record_coercion_sites():
    stub_telemetry.set_enabled(True)
    stub = getattr(App, UNDEFINED_NAME)
    assert float(stub) == 0.0
    assert stub.__index__() == 0
    kinds = {kind for (kind, _site) in stub_telemetry.snapshot()["coercion_sites"]}
    assert kinds == {"float", "index"}


def test_disabled_records_nothing_for_app_module_stub_path():
    stub_telemetry.set_enabled(False)
    stub = getattr(App, UNDEFINED_NAME)
    stub.ALIGN_BL
    bool(stub)
    int(stub)
    float(stub)
    stub.__index__()
    snap = stub_telemetry.snapshot()
    assert snap["attr_hits"] == {}
    assert snap["bool_sites"] == {}
    assert snap["coercion_sites"] == {}
