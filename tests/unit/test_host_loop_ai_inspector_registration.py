"""W4.T2 — AI Inspector panel registration behind the developer flag.

The dev-panel registration in engine/host_loop.py is deeply inline in the main
loop. This task factors the AI inspector's registration into the small,
unit-testable seam ``_register_ai_inspector(registry)`` and verifies both
branches:

* dev mode ON  -> a panel named "ai-inspector" is registered AND a pause-menu
  entry labelled "AI Inspector..." exists whose handler opens that panel.
* dev mode OFF -> nothing is registered and no AI Inspector menu entry exists
  (production path byte-identical).
"""
import pytest

from engine.ui.panel_registry import PanelRegistry


@pytest.fixture
def dev_env():
    """Force/reset dev mode and the dev pause-menu registry around each test."""
    import _dauntless_host
    import engine.dev_mode as dev_mode

    original_dev = getattr(_dauntless_host, "developer_mode", False)
    original_entries = list(dev_mode._dev_pause_menu_entries)
    dev_mode._dev_pause_menu_entries.clear()
    try:
        yield _dauntless_host, dev_mode
    finally:
        dev_mode._dev_pause_menu_entries.clear()
        dev_mode._dev_pause_menu_entries.extend(original_entries)
        _dauntless_host.developer_mode = original_dev


def _menu_labels(dev_mode):
    return [label for label, _ in dev_mode.dev_pause_menu_entries()]


def test_registers_panel_and_menu_entry_when_dev_enabled(dev_env):
    _dauntless_host, dev_mode = dev_env
    _dauntless_host.developer_mode = True
    from engine.host_loop import _register_ai_inspector

    registry = PanelRegistry()
    panel = _register_ai_inspector(registry)

    # Panel is in the registry under its canonical name.
    names = [p.name for p in registry._panels]
    assert "ai-inspector" in names

    # A pause-menu entry exists for the inspector, and it opens the panel.
    ai_entries = [
        (label, handler)
        for label, handler in dev_mode.dev_pause_menu_entries()
        if "AI Inspector" in label
    ]
    assert len(ai_entries) == 1
    label, handler = ai_entries[0]
    assert label == "AI Inspector…"

    assert panel.is_open() is False
    handler()
    assert panel.is_open() is True


def test_no_registration_when_dev_disabled(dev_env):
    _dauntless_host, dev_mode = dev_env
    _dauntless_host.developer_mode = False
    from engine.host_loop import _register_ai_inspector

    registry = PanelRegistry()
    _register_ai_inspector(registry)

    names = [p.name for p in registry._panels]
    assert "ai-inspector" not in names
    assert not any("AI Inspector" in label for label in _menu_labels(dev_mode))
