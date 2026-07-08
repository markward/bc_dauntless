import engine.host_loop as HL


class _FakeR:
    def __init__(self):
        self.vis = {}
    def set_visible(self, iid, v):
        self.vis[iid] = v


class _Char:
    def __init__(self, iid, hidden):
        self._render_instance = iid
        self._hidden = hidden
    def IsHidden(self):
        return self._hidden


class _Controller:
    def __init__(self, chars):
        self._chars = chars


def test_bridge_visibility_sync_drives_set_visible(monkeypatch):
    revealed = _Char(11, 0)
    hidden = _Char(12, 1)
    unrealized = _Char(None, 0)
    monkeypatch.setattr(HL, "_bridge_characters_for_sync",
                        lambda controller: [revealed, hidden, unrealized])
    r = _FakeR()
    HL._sync_bridge_character_visibility(_Controller([]), r)
    assert r.vis == {11: True, 12: False}    # unrealized (iid None) skipped
