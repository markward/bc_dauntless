import engine.host_loop as HL


class _WatchCtrl:
    def __init__(self, target):
        self._t = target
    def resolve_target_world(self, r):
        return self._t


def test_watch_target_wins(monkeypatch):
    monkeypatch.setattr(HL, "_active_zoom_officer_world",
                        lambda panel, r: (9.0, 9.0, 9.0))
    got = HL._resolve_bridge_focus_world(_WatchCtrl((1.0, 2.0, 3.0)), None, None)
    assert got == (1.0, 2.0, 3.0)                       # watch over menu-zoom


def test_menu_zoom_when_no_watch(monkeypatch):
    monkeypatch.setattr(HL, "_active_zoom_officer_world",
                        lambda panel, r: (4.0, 5.0, 6.0))
    got = HL._resolve_bridge_focus_world(_WatchCtrl(None), None, None)
    assert got == (4.0, 5.0, 6.0)


def test_none_when_neither(monkeypatch):
    monkeypatch.setattr(HL, "_active_zoom_officer_world", lambda panel, r: None)
    assert HL._resolve_bridge_focus_world(_WatchCtrl(None), None, None) is None
    assert HL._resolve_bridge_focus_world(None, None, None) is None   # no ctrl


def test_set_zoom_target_snap_jumps_to_one():
    cam = HL._BridgeCamera()
    cam.set_zoom_target((1.0, 2.0, 3.0), 0.016, snap=True)
    assert cam._zoom_t == 1.0
    assert cam._zoom_active is True
    assert cam._zoom_target_world == (1.0, 2.0, 3.0)
