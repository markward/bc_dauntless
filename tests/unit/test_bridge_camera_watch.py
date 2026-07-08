from engine.bridge_camera_watch import BridgeCameraWatchController


class _R:
    def __init__(self, center=(1.0, 2.0, 3.0)):
        self._c = center
        self.asked = []
    def get_instance_head_center(self, iid):
        self.asked.append(iid)
        return self._c


class _Char:
    def __init__(self, iid=42):
        self._render_instance = iid


def test_watch_resolves_head_center():
    ctrl = BridgeCameraWatchController()
    r = _R((5.0, 6.0, 7.0))
    ch = _Char(iid=42)
    ctrl.watch(ch)
    assert ctrl.is_watching() is True
    assert ctrl.resolve_target_world(r) == (5.0, 6.0, 7.0)
    assert r.asked == [42]


def test_clear_stops_watching():
    ctrl = BridgeCameraWatchController()
    ctrl.watch(_Char())
    ctrl.clear()
    assert ctrl.is_watching() is False
    assert ctrl.resolve_target_world(_R()) is None


def test_unrealized_character_resolves_none():
    ctrl = BridgeCameraWatchController()
    ch = _Char(iid=None)
    ctrl.watch(ch)
    assert ctrl.resolve_target_world(_R()) is None      # no instance yet


def test_snap_consumed_once():
    ctrl = BridgeCameraWatchController()
    ctrl.watch(_Char(), snap=True)
    assert ctrl.consume_snap() is True
    assert ctrl.consume_snap() is False                 # one-shot


def test_watch_supersedes_target():
    ctrl = BridgeCameraWatchController()
    a, b = _Char(1), _Char(2)
    ctrl.watch(a)
    ctrl.watch(b)
    r = _R()
    ctrl.resolve_target_world(r)
    assert r.asked == [2]                               # latest wins


def test_reset_clears():
    ctrl = BridgeCameraWatchController()
    ctrl.watch(_Char(), snap=True)
    ctrl.reset()
    assert ctrl.is_watching() is False
    assert ctrl.consume_snap() is False
