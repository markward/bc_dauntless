import pytest
from engine import dev_light_preview, dev_mode
from engine.appc import subsystem_glow


@pytest.fixture(autouse=True)
def _dev_on(monkeypatch):
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    dev_light_preview.reset()
    yield
    dev_light_preview.reset()


def test_damaged_and_disabled_are_mutually_exclusive():
    dev_light_preview.set_systems_damaged(True)
    assert dev_light_preview.forced_glow_state() == subsystem_glow.DISABLED
    assert dev_light_preview.systems_damaged_active()
    assert not dev_light_preview.systems_disabled_active()
    # turning on 'disabled' clears 'damaged'
    dev_light_preview.set_systems_disabled(True)
    assert dev_light_preview.forced_glow_state() == subsystem_glow.DESTROYED
    assert dev_light_preview.systems_disabled_active()
    assert not dev_light_preview.systems_damaged_active()
    # turning it off returns to no forced state
    dev_light_preview.set_systems_disabled(False)
    assert dev_light_preview.forced_glow_state() is None


def test_forced_state_gated_off_when_dev_disabled(monkeypatch):
    dev_light_preview.set_systems_damaged(True)
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    assert dev_light_preview.forced_glow_state() is None
    assert not dev_light_preview.systems_damaged_active()


def test_glow_state_returns_forced_for_any_sub():
    class _Sub:
        def IsDestroyed(self): return False
        def IsDisabled(self): return False
    dev_light_preview.set_systems_damaged(True)
    assert subsystem_glow.glow_state(_Sub()) == subsystem_glow.DISABLED
    assert subsystem_glow.glow_state(None) == subsystem_glow.DISABLED
    dev_light_preview.set_systems_disabled(True)
    assert subsystem_glow.glow_state(_Sub()) == subsystem_glow.DESTROYED


def test_glow_state_real_classification_when_not_forced():
    class _Healthy:
        def IsDestroyed(self): return False
        def IsDisabled(self): return False
    class _Dis:
        def IsDestroyed(self): return False
        def IsDisabled(self): return True
    # no forced state -> real classification (byte-identical to today)
    assert subsystem_glow.glow_state(_Healthy()) == subsystem_glow.HEALTHY
    assert subsystem_glow.glow_state(_Dis()) == subsystem_glow.DISABLED
