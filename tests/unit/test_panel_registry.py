from engine.ui.panel import Panel
from engine.ui.panel_registry import PanelRegistry


class _RecordingPanel(Panel):
    """Test fixture — records render and dispatch calls."""

    def __init__(self, name, payload="setX();"):
        super().__init__()
        self._name = name
        self._payload = payload
        self.dispatched = []
        self.render_calls = 0

    @property
    def name(self):
        return self._name

    def render_payload(self):
        self.render_calls += 1
        return self._payload

    def dispatch_event(self, action):
        self.dispatched.append(action)
        return True


def test_registry_collects_render_payloads_from_all_panels():
    a = _RecordingPanel("a", "setA();")
    b = _RecordingPanel("b", "setB();")
    reg = PanelRegistry()
    reg.register(a)
    reg.register(b)

    payloads = reg.render_all()

    assert "setA();" in payloads
    assert "setB();" in payloads


def test_registry_skips_panels_returning_none():
    a = _RecordingPanel("a", None)
    b = _RecordingPanel("b", "setB();")
    reg = PanelRegistry()
    reg.register(a); reg.register(b)
    payloads = reg.render_all()
    assert payloads == ["setB();"]


def test_registry_dispatch_routes_by_slash_prefix():
    a = _RecordingPanel("target")
    b = _RecordingPanel("other")
    reg = PanelRegistry()
    reg.register(a); reg.register(b)

    handled = reg.dispatch("target/USS Enterprise")

    assert handled is True
    assert a.dispatched == ["USS Enterprise"]
    assert b.dispatched == []


def test_registry_dispatch_falls_through_to_legacy_handler():
    """Unprefixed events route to the legacy handler (pause menu)."""
    a = _RecordingPanel("target")
    legacy_calls = []
    reg = PanelRegistry(legacy_handler=legacy_calls.append)
    reg.register(a)

    reg.dispatch("exit")

    assert a.dispatched == []
    assert legacy_calls == ["exit"]


def test_registry_dispatch_returns_false_when_unknown_and_no_legacy():
    reg = PanelRegistry()
    assert reg.dispatch("nobody/action") is False
