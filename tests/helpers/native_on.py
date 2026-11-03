"""A fixture turning native combat on for a test (fire control native only,
Task 3: a tractor's decisions and its force are native only, M4).

    from tests.helpers.native_on import native_combat_on  # noqa: F401
    pytestmark = pytest.mark.usefixtures("native_combat_on")

Skips without the bindings. Objects made before the fixture runs (module
level) are pushed by configure()'s resync.
"""
import pytest

from engine.appc import native_combat as nc

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}


@pytest.fixture
def native_combat_on():
    if not nc.available():
        pytest.skip("native combat bindings not built")
    nc.reset()
    nc.configure(ON)
    assert nc.enabled()
    yield
    nc.reset()
