from engine.appc.ai import CharacterAction
import engine.bridge_character_anim as bca


class _Char:
    def __init__(self, name="Picard"):
        self._name = name
    def GetCharacterName(self):
        return self._name


class _RecordingTurnController:
    def __init__(self):
        self.calls = []
    def request_turn_to(self, character, detail, *, back=False, hold=True,
                        now=False, on_complete=None):
        self.calls.append(dict(character=character, detail=detail, back=back,
                               now=now, on_complete=on_complete))


def _patch(monkeypatch, ctrl):
    monkeypatch.setattr(bca, "get_controller", lambda: ctrl)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)


def test_at_turn_queues_and_defers(monkeypatch):
    ch = _Char()
    ctrl = _RecordingTurnController()
    _patch(monkeypatch, ctrl)
    act = CharacterAction(ch, CharacterAction.AT_TURN, "Captain")
    act.Play()
    assert act.IsPlaying() is True                     # deferred
    assert len(ctrl.calls) == 1
    c = ctrl.calls[0]
    assert (c["detail"], c["back"], c["now"]) == ("Captain", False, False)
    assert ch._last_turn_detail == "Captain"
    c["on_complete"]()                                 # controller settles
    assert act.IsPlaying() is False


def test_at_turn_now_completes_inline(monkeypatch):
    ch = _Char()
    ctrl = _RecordingTurnController()
    _patch(monkeypatch, ctrl)
    act = CharacterAction(ch, CharacterAction.AT_TURN_NOW, "C1")
    act.Play()
    assert act.IsPlaying() is False                    # _NOW: inline
    assert ctrl.calls[0]["now"] is True
    assert ctrl.calls[0]["on_complete"] is None        # completion not deferred


def test_at_turn_back_reverses_last_detail(monkeypatch):
    ch = _Char()
    ctrl = _RecordingTurnController()
    _patch(monkeypatch, ctrl)
    CharacterAction(ch, CharacterAction.AT_TURN, "Science").Play()
    back = CharacterAction(ch, CharacterAction.AT_TURN_BACK)  # bare
    back.Play()
    assert ctrl.calls[1]["detail"] == "Science"
    assert ctrl.calls[1]["back"] is True


def test_at_turn_back_defaults_to_captain(monkeypatch):
    ch = _Char()
    ctrl = _RecordingTurnController()
    _patch(monkeypatch, ctrl)
    CharacterAction(ch, CharacterAction.AT_TURN_BACK).Play()  # no prior turn
    assert ctrl.calls[0]["detail"] == "Captain"


def test_at_turn_back_clears_last_turn_detail(monkeypatch):
    ch = _Char()
    ctrl = _RecordingTurnController()
    _patch(monkeypatch, ctrl)
    CharacterAction(ch, CharacterAction.AT_TURN, "Science").Play()
    assert ch._last_turn_detail == "Science"
    CharacterAction(ch, CharacterAction.AT_TURN_BACK).Play()   # bare
    assert ctrl.calls[1]["detail"] == "Science"
    assert ch._last_turn_detail is None    # reset, not left stale for next back


def test_queue_turn_exception_is_best_effort(monkeypatch):
    # Mirrors _queue_move's exception-path test: if the turn controller (or
    # CharacterClass_Cast) blows up, Play() must not propagate and the
    # action must complete inline so the mission TGSequence advances.
    ch = _Char()

    class _RaisingTurnController:
        def request_turn_to(self, character, detail, *, back=False,
                            hold=True, now=False, on_complete=None):
            raise RuntimeError("turn controller blew up")

    monkeypatch.setattr(bca, "get_controller", lambda: _RaisingTurnController())
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)

    act = CharacterAction(ch, CharacterAction.AT_TURN, "Captain")
    act.Play()                                          # must not raise

    assert act.IsPlaying() is False                     # completed inline


def test_at_turn_completes_inline_when_no_controller(monkeypatch):
    ch = _Char()
    monkeypatch.setattr(bca, "get_controller", lambda: None)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)
    act = CharacterAction(ch, CharacterAction.AT_TURN, "Captain")
    act.Play()
    assert act.IsPlaying() is False                    # never stalls
