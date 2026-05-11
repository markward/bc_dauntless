"""Test fixtures for engine.ui — installs a FakeDom in place of the real
binding layer for all tests in this directory."""
import pytest

from engine.ui import bindings as bindings_module
from engine.ui._dom import FakeDom


@pytest.fixture
def fake_dom(monkeypatch) -> FakeDom:
    dom = FakeDom()
    monkeypatch.setattr(bindings_module, "_active_dom", dom)
    return dom
