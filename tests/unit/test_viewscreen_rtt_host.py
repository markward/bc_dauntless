"""Pure host-side helpers for the viewscreen RTT feed (step 5c). No renderer
or GL — they decide on/off and player-ship visibility from plain inputs."""
from engine.host_loop import _viewscreen_feed_on, _apply_bridge_player_visibility


class _FakeVS:
    def __init__(self, on):
        self._on = on
    def IsOn(self):
        return self._on


class _FakeRenderer:
    def __init__(self):
        self.visibility = []   # (iid, visible)
    def set_visible(self, iid, visible):
        self.visibility.append((iid, visible))


def test_feed_on_true_when_viewscreen_is_on():
    assert _viewscreen_feed_on(_FakeVS(1)) is True


def test_feed_off_when_viewscreen_off_or_missing():
    assert _viewscreen_feed_on(_FakeVS(0)) is False
    assert _viewscreen_feed_on(None) is False


def test_player_hidden_in_bridge_view():
    r = _FakeRenderer()
    _apply_bridge_player_visibility(r, 42, is_bridge=True, spv_open=False)
    assert r.visibility == [(42, False)]


def test_player_visible_in_exterior_view():
    r = _FakeRenderer()
    _apply_bridge_player_visibility(r, 42, is_bridge=False, spv_open=False)
    assert r.visibility == [(42, True)]


def test_no_visibility_change_while_spv_owns_frame():
    r = _FakeRenderer()
    _apply_bridge_player_visibility(r, 42, is_bridge=True, spv_open=True)
    assert r.visibility == []


def test_no_op_without_player_instance():
    r = _FakeRenderer()
    _apply_bridge_player_visibility(r, None, is_bridge=True, spv_open=False)
    assert r.visibility == []
