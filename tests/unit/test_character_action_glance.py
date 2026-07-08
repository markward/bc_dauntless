from engine.appc.ai import CharacterAction
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


def test_request_glance_fires_on_complete_when_dropped_by_priority_guard(
        monkeypatch):
    """A glance (_REACTION priority) submitted while a same-priority _Action
    already occupies the character's iid is dropped by submit()'s
    equal-priority guard. on_complete must still fire inline, or a mission
    TGSequence waiting on IsPlaying() hangs forever (Finding 1)."""
    import engine.bridge_character_anim as m
    monkeypatch.setattr(
        m, "capture_registered_clip",
        lambda ch, suffix: {"clip_nif": "GlanceLeft.nif"})
    ctrl = bca.BridgeCharacterAnimController()

    class _R:  # renderer unused: submit() is dropped before it touches it
        pass

    ch = _Char()
    iid = ch._render_instance

    # Pre-occupy the iid with an already-started, long-running _Action at the
    # same priority band as the glance (_REACTION == _TURN == 1).
    blocker = bca._Action(iid, [("Blocker.nif", 0.0)], priority=bca._REACTION)
    blocker.started = True
    blocker.index = 0
    blocker.elapsed = 0.0
    blocker.cur_duration = 1000.0
    ctrl._active[iid] = blocker

    fired = []
    ctrl.request_glance(ch, "Left", on_complete=lambda: fired.append(True))
    ctrl.update(0.0, renderer=_R())

    assert fired == [True]
