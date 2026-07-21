"""CharacterAction's AT_GLANCE_AT/AT_GLANCE_AWAY verbs, re-pointed (SP2 P2)
through the CharacterClass door (GlanceAt/GlanceAway) instead of calling the
glance controller directly. The CharacterClass AnimRec queue now owns the
actual controller call (via UpdateAnimationQueue -> play_record);
CharacterAction only enqueues and waits for its on_complete to fire.

Follows the same pattern as the already-migrated turn tests, see
test_character_action_turn.py.
"""
from engine.appc.ai import CharacterAction
from engine.appc.characters import CharacterClass_Create
import engine.bridge_character_anim as bca


class _Char:
    def __init__(self):
        self._render_instance = 55
    def GetCharacterName(self):
        return "Liu"
    def IsHidden(self):
        return 0


def _char(active=True):
    ch = CharacterClass_Create()
    if active:
        ch.SetActive(1)
    return ch


def _real_controller_recording_glances(monkeypatch):
    """A real BridgeCharacterAnimController with request_glance swapped for a
    recording fake -- so play_record/is_active/stop stay the genuine
    plumbing the CharacterClass queue calls, and only the glance call itself
    is observed."""
    ctrl = bca.BridgeCharacterAnimController()
    calls = []

    def _recording_request_glance(character, detail, on_complete=None):
        calls.append(dict(character=character, detail=detail,
                          on_complete=on_complete))

    monkeypatch.setattr(ctrl, "request_glance", _recording_request_glance)
    monkeypatch.setattr(bca, "get_controller", lambda: ctrl)
    return ctrl, calls


def test_at_glance_at_queues(monkeypatch):
    ch = _char()
    ctrl, calls = _real_controller_recording_glances(monkeypatch)
    act = CharacterAction(ch, CharacterAction.AT_GLANCE_AT, "Left")
    act.Play()
    assert act.IsPlaying() is True                     # deferred
    assert len(ch._anim_pending) == 1
    rec = ch._anim_pending[0]
    assert rec.category == ch.CAT_GLANCE
    assert rec.name == "Left"
    assert rec.on_complete == act.Completed

    ch.UpdateAnimationQueue()                          # drains the queue -> plays
    assert len(calls) == 1
    c = calls[0]
    assert c["detail"] == "Left"
    assert c["on_complete"] == act.Completed
    c["on_complete"]()                                 # controller settles
    assert act.IsPlaying() is False


def test_at_glance_away_completes_via_queue_drain(monkeypatch):
    ch = _char()
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)
    bca.clear_controller()
    act = CharacterAction(ch, CharacterAction.AT_GLANCE_AWAY)
    act.Play()
    assert act.IsPlaying() is True                     # deferred, no longer inline

    # GlanceAway is CAT_GLANCE_BACK, routed through Special6, which declines
    # with no glance-target -- the record is retired and its on_complete
    # fires via ReleaseCurrentAnimation on a later drain.
    for _ in range(3):
        if not act.IsPlaying():
            break
        ch.UpdateAnimationQueue()
    assert act.IsPlaying() is False


def test_at_glance_away_completes_inline_when_character_cast_is_none(
        monkeypatch):
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: None)
    act = CharacterAction(_char(), CharacterAction.AT_GLANCE_AWAY)
    act.Play()
    assert act.IsPlaying() is False


def test_queue_glance_exception_is_best_effort(monkeypatch):
    # If CharacterClass_Cast (or GlanceAt/GlanceAway) blows up, Play() must
    # not propagate and the action must complete inline so the mission
    # TGSequence advances.
    def boom(obj):
        raise RuntimeError("cast blew up")

    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast", boom)

    act = CharacterAction(_char(), CharacterAction.AT_GLANCE_AT, "Left")
    act.Play()                                          # must not raise
    assert act.IsPlaying() is False                     # completed inline


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
