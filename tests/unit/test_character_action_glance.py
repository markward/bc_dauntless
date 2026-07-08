from engine.appc.ai import CharacterAction
from engine.appc import bridge_placement
import engine.bridge_character_anim as bca


class _Char:
    def __init__(self):
        self._render_instance = 55
    def GetCharacterName(self):
        return "Liu"
    def IsHidden(self):
        return 0


class _RecordingGlanceController:
    def __init__(self):
        self.calls = []
    def request_glance(self, character, detail, on_complete=None):
        self.calls.append((detail, on_complete))


def test_at_glance_at_queues(monkeypatch):
    ch = _Char()
    ctrl = _RecordingGlanceController()
    monkeypatch.setattr(bca, "get_controller", lambda: ctrl)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)
    act = CharacterAction(ch, CharacterAction.AT_GLANCE_AT, "Left")
    act.Play()
    assert ctrl.calls[0][0] == "Left"
    assert act.IsPlaying() is True
    ctrl.calls[0][1]()                                 # controller settles
    assert act.IsPlaying() is False


def test_at_glance_inline_when_no_controller(monkeypatch):
    ch = _Char()
    monkeypatch.setattr(bca, "get_controller", lambda: None)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)
    act = CharacterAction(ch, CharacterAction.AT_GLANCE_AWAY)
    act.Play()
    assert act.IsPlaying() is False


def test_request_glance_inline_when_unresolved(monkeypatch):
    import engine.bridge_character_anim as m
    monkeypatch.setattr(m, "capture_registered_clip", lambda ch, suffix: None)
    ctrl = bca.BridgeCharacterAnimController()

    class _R:  # renderer unused on the unresolved path
        pass
    ch = _Char()
    fired = []
    ctrl.request_glance(ch, "Left", on_complete=lambda: fired.append(True))
    ctrl.update(0.0, renderer=_R())
    assert fired == [True]
