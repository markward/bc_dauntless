"""engine.renderer MSAA wrappers forward to the host module, and the
max-samples query is safe to call before a GL context exists."""
from unittest.mock import MagicMock

import pytest

import engine.renderer as renderer


def test_set_msaa_samples_forwards(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_msaa_samples(4)
    fake.msaa_set_samples.assert_called_once_with(4)


def test_set_msaa_samples_coerces_to_int(monkeypatch):
    # The settings table indexes AA_MODE_SAMPLES, which is a tuple of ints, but
    # a JSON round-trip can hand back a float. pybind11 rejects a float for an
    # int arg, so the coercion is load-bearing rather than decorative.
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_msaa_samples(8.0)
    fake.msaa_set_samples.assert_called_once_with(8)


def test_max_msaa_samples_forwards(monkeypatch):
    fake = MagicMock()
    fake.msaa_max_samples.return_value = 8
    monkeypatch.setattr(renderer, "_h", fake)
    assert renderer.max_msaa_samples() == 8


def test_max_msaa_samples_does_not_crash_without_a_gl_context():
    """REGRESSION: this used to SEGFAULT the interpreter.

    msaa_max_samples calls query_gl_caps -> glGetIntegerv. With no context
    glad's function pointer is null, so the call took down the whole process
    rather than raising — which in a pytest run means every remaining test is
    lost, with a bare exit 139 and no failure report.

    The binding now guards on g_window and answers 0. Do not "simplify" that
    guard away.
    """
    host = pytest.importorskip("_dauntless_host")
    assert host.msaa_max_samples() == 0


def test_msaa_set_samples_accepts_a_request_without_a_gl_context():
    """The setter only stores an int; clamping and allocation happen in the
    frame, under a context. Settings are applied at boot before the first
    frame, so this ordering is the normal path, not an edge case."""
    host = pytest.importorskip("_dauntless_host")
    host.msaa_set_samples(4)
    host.msaa_set_samples(0)   # leave the global off for other tests
