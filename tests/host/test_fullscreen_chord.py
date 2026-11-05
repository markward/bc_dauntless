"""Alt+Enter toggles full screen.

Not a BC binding: Enter has no WC_ALT_ENTER code (MODIFIER_CHORDS covers
ALT/CTRL/Shift x letters, digits and F-keys only), so the chord is ours to
spend. The poller's job is to route it through the Configuration panel's own
`toggle:fullscreen` branch, so the window, the row the player sees and the
persisted value can never disagree.

See engine/host_loop.py:_poll_fullscreen_chord and the Full Screen row in
docs/superpowers/specs -- the setting itself is tested in
tests/unit/test_configuration_panel.py.
"""
import pytest

from engine import host_io, host_loop
from engine.input_map import GLFW_KEYS
from engine.host_loop import _poll_fullscreen_chord


class _FakeKeys:
    """Deliberately WITHOUT a KEY_ENTER, because the real native keys
    submodule has none -- it exports 67 names and Enter is not one. Reading
    Enter's code from the host is therefore a guaranteed silent no-op, which
    is exactly how the first version of this hotkey shipped broken. The code
    comes from engine.input_map instead; ENTER below is that table's value."""

    KEY_LEFT_ALT = 342
    KEY_RIGHT_ALT = 346
    KEY_LEFT_CONTROL = 341
    KEY_RIGHT_CONTROL = 345
    KEY_LEFT_SHIFT = 340
    KEY_RIGHT_SHIFT = 344


class _FakeHost:
    keys = _FakeKeys()

    def __init__(self):
        self.held = set()

    def key_state(self, key):
        return key in self.held


class _FakePanel:
    """Just enough panel: the actions it was asked to dispatch, and the
    capturing_action the real one exposes while the Controls tab waits."""

    def __init__(self, capturing_action=None):
        self.actions = []
        self.capturing_action = capturing_action

    def dispatch_event(self, action):
        self.actions.append(action)
        return True


@pytest.fixture
def host(monkeypatch):
    """host_io.key_state reads the module-global native handle, not the
    `host` argument -- the argument only supplies the key-code table."""
    h = _FakeHost()
    monkeypatch.setattr(host_io, "_h", h)
    monkeypatch.setattr(host_loop, "_fullscreen_chord_prev", False)
    return h


ENTER = GLFW_KEYS["Enter"]


def _alt_enter(h):
    h.held = {_FakeKeys.KEY_LEFT_ALT, ENTER}


def test_alt_enter_dispatches_the_panel_toggle(host):
    panel = _FakePanel()
    _alt_enter(host)
    _poll_fullscreen_chord(host, panel)
    assert panel.actions == ["toggle:fullscreen"]


def test_holding_alt_enter_fires_once(host):
    """Rising edge only. A held chord that re-fired every frame would
    strobe the window at the frame rate."""
    panel = _FakePanel()
    _alt_enter(host)
    for _ in range(5):
        _poll_fullscreen_chord(host, panel)
    assert panel.actions == ["toggle:fullscreen"]


def test_releasing_and_pressing_again_fires_again(host):
    panel = _FakePanel()
    _alt_enter(host)
    _poll_fullscreen_chord(host, panel)
    host.held = set()
    _poll_fullscreen_chord(host, panel)
    _alt_enter(host)
    _poll_fullscreen_chord(host, panel)
    assert panel.actions == ["toggle:fullscreen"] * 2


def test_right_alt_works_too(host):
    panel = _FakePanel()
    host.held = {_FakeKeys.KEY_RIGHT_ALT, ENTER}
    _poll_fullscreen_chord(host, panel)
    assert panel.actions == ["toggle:fullscreen"]


def test_bare_enter_does_nothing(host):
    """Enter without Alt belongs to the SDK's raw key stream."""
    panel = _FakePanel()
    host.held = {ENTER}
    for _ in range(3):
        _poll_fullscreen_chord(host, panel)
    assert panel.actions == []


def test_bare_alt_does_nothing(host):
    panel = _FakePanel()
    host.held = {_FakeKeys.KEY_LEFT_ALT}
    _poll_fullscreen_chord(host, panel)
    assert panel.actions == []


def test_a_rebind_capture_owns_the_keystroke(host):
    """_handle_controls_capture is documented as the SOLE consumer of a
    press while the Controls tab awaits a key: binding Alt+Enter to an
    action must not also toggle the window."""
    panel = _FakePanel(capturing_action="fire_primary")
    _alt_enter(host)
    _poll_fullscreen_chord(host, panel)
    assert panel.actions == []


def test_a_chord_held_through_the_end_of_a_capture_does_not_fire(host):
    """The player released nothing, so there is no second press to honour:
    one keystroke must not both bind a key and toggle the window. This is
    why a suppressed frame still records the key LEVEL."""
    panel = _FakePanel(capturing_action="fire_primary")
    _alt_enter(host)
    _poll_fullscreen_chord(host, panel)
    panel.capturing_action = None
    _poll_fullscreen_chord(host, panel)
    assert panel.actions == []
    # Released and pressed afresh, it works again.
    host.held = set()
    _poll_fullscreen_chord(host, panel)
    _alt_enter(host)
    _poll_fullscreen_chord(host, panel)
    assert panel.actions == ["toggle:fullscreen"]


def test_no_panel_and_no_host_are_both_safe(host):
    _alt_enter(host)
    _poll_fullscreen_chord(host, None)       # pre-panel frame
    _poll_fullscreen_chord(None, _FakePanel())  # headless


def test_the_input_map_table_is_where_enters_code_comes_from():
    """The regression guard for the way this shipped broken: the poller must
    not depend on the host exposing Enter, because it does not. If this ever
    starts reading host.keys.KEY_ENTER, the hotkey silently stops working
    and nothing else fails."""
    assert GLFW_KEYS["Enter"] == 257
    import _dauntless_host
    assert not hasattr(_dauntless_host.keys, "KEY_ENTER"), (
        "the host now exports KEY_ENTER -- fine, but the poller still reads "
        "engine.input_map, so update the comment rather than the code")
