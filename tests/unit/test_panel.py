"""Unit tests for the abstract panel base."""
import pytest


def test_panel_subclass_must_implement_render_payload():
    from engine.ui.panel import Panel

    class Bad(Panel):
        @property
        def name(self):
            return "bad"

    with pytest.raises(TypeError):
        Bad()  # render_payload + dispatch_event still abstract


def test_panel_subclass_minimal_implementation():
    from engine.ui.panel import Panel

    class Minimal(Panel):
        @property
        def name(self):
            return "minimal"
        def render_payload(self):
            return None
        def dispatch_event(self, action):
            return False

    p = Minimal()
    assert p.name == "minimal"
    assert p.visible is True
    p.visible = False
    assert p.visible is False
    assert p.render_payload() is None
    assert p.dispatch_event("foo") is False


def test_panel_invalidate_is_a_noop_by_default():
    """Base implementation lets subclasses opt in to invalidation
    without forcing every Panel to override the hook."""
    from engine.ui.panel import Panel

    class Minimal(Panel):
        @property
        def name(self):
            return "minimal"
        def render_payload(self):
            return None
        def dispatch_event(self, action):
            return False

    p = Minimal()
    p.invalidate()  # must not raise
