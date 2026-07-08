from engine.appc.ai import CharacterAction
import engine.bridge_camera_watch as bcw


class _Char:
    def GetCharacterName(self):
        return "Picard"


class _RecordingWatch:
    def __init__(self):
        self.watched = []
        self.cleared = 0
    def watch(self, character, snap=False):
        self.watched.append((character, snap))
    def clear(self):
        self.cleared += 1


def _patch(monkeypatch, ctrl):
    monkeypatch.setattr(bcw, "get_controller", lambda: ctrl)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)


def test_watch_me_sets_target_and_completes(monkeypatch):
    ch = _Char()
    ctrl = _RecordingWatch()
    _patch(monkeypatch, ctrl)
    act = CharacterAction(ch, CharacterAction.AT_WATCH_ME)
    act.Play()
    assert ctrl.watched == [(ch, False)]
    assert act.IsPlaying() is False                     # inline


def test_look_at_me_now_snaps(monkeypatch):
    ch = _Char()
    ctrl = _RecordingWatch()
    _patch(monkeypatch, ctrl)
    CharacterAction(ch, CharacterAction.AT_LOOK_AT_ME_NOW).Play()
    assert ctrl.watched == [(ch, True)]


def test_look_at_me_eases(monkeypatch):
    ch = _Char()
    ctrl = _RecordingWatch()
    _patch(monkeypatch, ctrl)
    CharacterAction(ch, CharacterAction.AT_LOOK_AT_ME).Play()
    assert ctrl.watched == [(ch, False)]


def test_stop_watching_clears(monkeypatch):
    ch = _Char()
    ctrl = _RecordingWatch()
    _patch(monkeypatch, ctrl)
    act = CharacterAction(ch, CharacterAction.AT_STOP_WATCHING_ME)
    act.Play()
    assert ctrl.cleared == 1
    assert act.IsPlaying() is False


def test_watch_inline_when_no_controller(monkeypatch):
    ch = _Char()
    monkeypatch.setattr(bcw, "get_controller", lambda: None)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)
    act = CharacterAction(ch, CharacterAction.AT_WATCH_ME)
    act.Play()
    assert act.IsPlaying() is False                     # never stalls
