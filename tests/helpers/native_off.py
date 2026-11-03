"""A fixture pinning DAUNTLESS_NATIVE_COMBAT=0 for a test (fire control
native only, ruling R1): the switch defaults on, so a test of the PYTHON arm
of a switch-governed piece -- K0, K2, K3, K4, native damage, or the
dispatched sensor queries (sensor_detection's `_py_*` rules) -- pins it off
itself. Fire control stays native (M9).

    from tests.helpers.native_off import native_switch_zero  # noqa: F401
    pytestmark = pytest.mark.usefixtures("native_switch_zero")

Typically a test whose doubles only the Python can see: a monkeypatched
module flag or dial dict entry (the native globals are pushed by the
setters, not read at use), a fake nebula or object the mirror has no row
for.
"""
import pytest

from engine.appc import native_combat as nc

ZERO = {"DAUNTLESS_NATIVE_COMBAT": "0"}


@pytest.fixture
def native_switch_zero():
    nc.configure(ZERO)
    assert not nc.enabled()
    yield
