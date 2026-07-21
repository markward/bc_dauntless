from engine import bridge_character_anim
from engine.appc import bridge_placement
from engine.appc.characters import CharacterClass


def _character_with(key, module_path, location="DBTactical"):
    ch = CharacterClass("body.nif", "head.nif")
    ch.SetLocation(location)
    ch.AddAnimation(key, module_path)
    return ch


def test_registered_module_path_uses_the_literal_key():
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    # literal — NOT prefixed with the location
    assert bridge_placement.registered_module_path(ch, "PushingButtons") == \
        "Some.Module.DBTConsoleInteraction"
    assert bridge_placement.registered_module_path(ch, "DBTacticalPushingButtons") is None


def test_push_buttons_misspelling_is_aliased():
    # BC ships a bug: MissionLib.PushButtons and 40 other sites ask for
    # "PushButtons", but all 14 character registrations spell it "PushingButtons", so those
    # calls are silent no-ops in the original. We deliberately FIX the typo.
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    assert bridge_placement.registered_module_path(ch, "PushButtons") == \
        "Some.Module.DBTConsoleInteraction"


def test_unregistered_key_resolves_to_none():
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    assert bridge_placement.registered_module_path(ch, "Nonexistent") is None
    assert bridge_placement.resolve_builder(ch, "Nonexistent") is None


def test_scripted_priority_outranks_idle_and_reactions():
    assert bridge_character_anim._SCRIPTED > bridge_character_anim._REACTION
    assert bridge_character_anim._SCRIPTED > bridge_character_anim._IDLE


def test_request_default_clears_the_active_action():
    ctrl = bridge_character_anim.BridgeCharacterAnimController()
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    # submit() keys off the render-instance id and refuses a hidden character
    # (bridge_character_anim.py:70-73), so a bare CharacterClass would be dropped.
    ch._render_instance = 7
    ch.SetHidden(0)
    assert ctrl.submit(ch, [("some/clip.nif", 1.0)],
                       priority=bridge_character_anim._SCRIPTED) is True
    assert ctrl.is_busy(ch) is True
    ctrl.request_default(ch)
    assert ctrl.is_busy(ch) is False


from engine.appc.ai import CharacterAction


def test_character_action_cast_is_the_missionlib_test_and_cast():
    # MissionLib.GetVoiceLinesFromSequence walks sequences with
    # App.CharacterAction_Cast(pAction) — the RTTI test-and-cast (stbc.exe
    # 0x0066f890). Returns the action itself for a CharacterAction, None for
    # anything else. Must be the real function on the App shim, not a
    # _NamedStub (a stub's truthy return would silently corrupt the walk).
    import App
    act = App.CharacterAction_Create(
        None, CharacterAction.AT_SAY_LINE, "E1M1_HELM_1", None, 1)
    assert App.CharacterAction_Cast(act) is act
    assert App.CharacterAction_Cast(App.TGAction_CreateNull()) is None
    assert App.CharacterAction_Cast(None) is None


class _FakeController:
    def __init__(self, accept=True):
        self.accept = accept
        self.submitted = []

    def is_busy(self, character):
        return False

    def submit(self, character, clips, priority, hold=False, on_complete=None):
        self.submitted.append((character, list(clips), priority, on_complete))
        return self.accept

    def request_default(self, character):
        self.submitted.append((character, "DEFAULT", None, None))


class _RecordingController:
    """The NEW seam (play_record/is_active/stop) that CharacterClass's AnimRec
    queue drives on drain — see docs/superpowers/plans/2026-07-21-
    characterclass-sp2-animation-queue.md. Mirrors the gesture/breathe branch
    of the real BridgeCharacterAnimController.play_record: records the
    submitted clips/priority/on_complete rather than touching a renderer."""
    def __init__(self):
        self.submitted = []
        self._playing = False

    def play_record(self, character, rec):
        clips = list(rec.play) if rec.play else []
        self.submitted.append(
            (character, clips, bridge_character_anim._SCRIPTED, rec.on_complete))
        self._playing = True

    def is_active(self, character):
        return self._playing

    def stop(self, character):
        self._playing = False


def test_play_animation_submits_the_registered_gesture(monkeypatch):
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ch.SetActive(1)
    ctrl = _RecordingController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    monkeypatch.setattr("engine.bridge_idle_gestures.build_sequence_clips",
                        lambda path, character, anim_mgr: [("clip.nif", 1.0)])

    action = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION, "PushingButtons")
    action.Play()
    assert action.IsPlaying() is True                       # deferred
    # flag defaults to 0 => BC's non-interruptable mode => the SDK gate closes.
    # Nothing has retired yet -- this reads the PENDING record.
    assert ch.IsAnimatingNonInterruptable() == 1

    ch.UpdateAnimationQueue()                # drains -> play_record -> submit
    assert len(ctrl.submitted) == 1
    _c, clips, priority, on_complete = ctrl.submitted[0]
    assert clips == [("clip.nif", 1.0)]
    assert priority == bridge_character_anim._SCRIPTED
    assert on_complete == action.Completed

    on_complete()                             # controller settles
    assert action.IsPlaying() == 0            # completion guarantee


def test_play_animation_flag_1_is_interruptable(monkeypatch):
    # MissionLib.py:3543 passes flag=1 explicitly.
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ch.SetActive(1)
    ctrl = _RecordingController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    monkeypatch.setattr("engine.bridge_idle_gestures.build_sequence_clips",
                        lambda path, character, anim_mgr: [("clip.nif", 1.0)])

    action = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION,
                             "PushingButtons", None, 1)
    action.Play()
    assert ch.IsAnimatingInterruptable() == 1       # off the pending record
    assert ch.IsAnimatingNonInterruptable() == 0


def test_play_animation_unregistered_key_completes_immediately(monkeypatch):
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ch.SetActive(1)
    ctrl = _RecordingController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    # Prove the unregistered-key branch itself is what runs: if it were
    # skipped and build_sequence_clips were reached instead, this would blow
    # up (or, if silently swallowed, would still leave a trace we can check
    # for below). registered_module_path is the ONLY thing this branch may
    # call before bailing out.
    called = {"build_sequence_clips": False}
    def _boom(*a, **k):
        called["build_sequence_clips"] = True
        raise AssertionError("build_sequence_clips must not run for an "
                             "unregistered key")
    monkeypatch.setattr("engine.bridge_idle_gestures.build_sequence_clips", _boom)

    action = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION, "Nonexistent")
    action.Play()

    assert called["build_sequence_clips"] is False
    assert ctrl.submitted == []          # nothing submitted
    assert action.IsPlaying() == 0       # completed inline — never stalls a sequence
    assert ch.IsAnimating() == 0         # and left no state behind
    assert ch.GetCurrentAnimation() == ""      # animation state never touched
    assert ch.IsAnimatingNonInterruptable() == 0


def test_play_animation_file_resolves_registered_clip_name(monkeypatch):
    # FINDING 1: AT_PLAY_ANIMATION_FILE passes a bare CLIP NAME (e.g.
    # "db_P_Point_C_P", MaelstromE1M1.py:2025), registered earlier via
    # g_kAnimationManager.LoadAnimation(path, name) — NOT a resolvable path
    # itself. It must be resolved via App.g_kAnimationManager.path_for().
    import App
    App.g_kAnimationManager.LoadAnimation(
        "data/animations/db_P_Point_C_P.nif", "db_P_Point_C_P__t6")
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ch.SetActive(1)
    ctrl = _RecordingController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)

    action = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION_FILE,
                             "db_P_Point_C_P__t6")
    action.Play()
    assert ch.IsAnimatingNonInterruptable() == 1    # off the pending record

    ch.UpdateAnimationQueue()                # drains -> play_record -> submit
    assert len(ctrl.submitted) == 1
    _c, clips, priority, _cb = ctrl.submitted[0]
    assert clips == [("data/animations/db_P_Point_C_P.nif", 0.0)]
    assert priority == bridge_character_anim._SCRIPTED


def test_play_animation_file_unregistered_name_completes_immediately(monkeypatch):
    # FINDING 1: a clip name that was never LoadAnimation()-registered must
    # never reach the renderer and must never stall the sequence.
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ch.SetActive(1)
    ctrl = _RecordingController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)

    action = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION_FILE,
                             "totally_unregistered_clip_name__t6")
    action.Play()

    assert ctrl.submitted == []
    assert action.IsPlaying() == 0
    assert ch.IsAnimating() == 0
    assert ch.IsAnimatingNonInterruptable() == 0


def test_queue_play_animation_completes_inline_when_character_cast_is_none(
        monkeypatch):
    # Mirrors test_at_turn_completes_inline_when_character_cast_is_none /
    # test_at_glance_away_completes_inline_when_character_cast_is_none: no
    # CharacterClass to enqueue against -> complete inline, never enqueue.
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda obj: None)
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    action = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION, "PushingButtons")
    action.Play()
    assert action.IsPlaying() == 0
    assert ch._anim_pending == []


def test_queue_play_animation_exception_is_best_effort(monkeypatch):
    # Mirrors test_queue_turn_exception_is_best_effort /
    # test_queue_glance_exception_is_best_effort: if CharacterClass_Cast (or
    # PlayAnimation) blows up, Play() must not propagate and the action must
    # complete inline so the mission TGSequence advances.
    def boom(obj):
        raise RuntimeError("cast blew up")
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast", boom)

    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    action = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION, "PushingButtons")
    action.Play()                                        # must not raise
    assert action.IsPlaying() == 0                       # completed inline


def test_queue_play_animation_detail_none_completes_inline():
    # BC no-ops an unresolved gesture; the sequence must still advance
    # instead of stalling on a None detail.
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    action = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION)
    action.Play()
    assert action.IsPlaying() == 0
    assert ch._anim_pending == []


def test_second_scripted_gesture_on_busy_officer_does_not_corrupt_first_action(
        monkeypatch):
    # The model changed here (SP2 P3): the OLD controller-level priority guard
    # (submit() rejecting an equal-or-lower-priority action on a busy officer)
    # is gone from this path -- PlayAnimation now enqueues via
    # SetCurrentAnimation, and the referee (character_anim_queue.classify)
    # says NON_INTERRUPTABLE-vs-NON_INTERRUPTABLE is COEXIST, not
    # reject-or-stop. So gesture B is no longer rejected: it is QUEUED behind
    # still-current gesture A, faithfully serializing the two scripted beats
    # instead of losing B. This is the SAME invariant the test used to check
    # (A survives B's arrival uncorrupted) expressed the new way.
    ch = _character_with("GestureA", "Mod.A")
    ch.AddAnimation("GestureB", "Mod.B")
    ch.SetActive(1)
    ctrl = _RecordingController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)

    def _clips(module_path, character, anim_mgr):
        return [("clipA.nif", 5.0)] if module_path == "Mod.A" else [("clipB.nif", 5.0)]
    monkeypatch.setattr("engine.bridge_idle_gestures.build_sequence_clips", _clips)

    action_a = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION, "GestureA")
    action_a.Play()
    ch.UpdateAnimationQueue()             # drains A -> _anim_current, submitted
    assert action_a.IsPlaying() == 1
    assert ch.IsAnimatingNonInterruptable() == 1
    assert len(ctrl.submitted) == 1

    action_b = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION, "GestureB")
    action_b.Play()

    # B is QUEUED, not lost or overwriting A. A's state is untouched.
    assert action_b.IsPlaying() == 1
    assert len(ch._anim_pending) == 1
    assert ch._anim_pending[0].category == ch.CAT_NON_INTERRUPTABLE
    assert len(ctrl.submitted) == 1        # B has not been submitted (still pending)
    assert action_a.IsPlaying() == 1        # A is still genuinely playing, uncorrupted


def test_request_default_fires_pending_on_complete(monkeypatch):
    # FINDING 3 (RED first): request_default drops an in-flight _Action; if
    # it carries an on_complete, that callback MUST fire (best-effort) so the
    # owning CharacterAction / TGSequence doesn't stall forever.
    ctrl = bridge_character_anim.BridgeCharacterAnimController()
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ch._render_instance = 7
    ch.SetHidden(0)
    fired = []
    assert ctrl.submit(ch, [("some/clip.nif", 1.0)],
                       priority=bridge_character_anim._SCRIPTED,
                       on_complete=lambda: fired.append(True)) is True
    assert ctrl.is_busy(ch) is True

    ctrl.request_default(ch)

    assert fired == [True]
    assert ctrl.is_busy(ch) is False


def test_request_default_swallows_a_raising_on_complete(monkeypatch):
    # FINDING 3: a raising callback must not break the controller.
    ctrl = bridge_character_anim.BridgeCharacterAnimController()
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ch._render_instance = 8
    ch.SetHidden(0)
    def _boom():
        raise RuntimeError("boom")
    assert ctrl.submit(ch, [("some/clip.nif", 1.0)],
                       priority=bridge_character_anim._SCRIPTED,
                       on_complete=_boom) is True

    ctrl.request_default(ch)             # must not raise

    assert ctrl.is_busy(ch) is False


import pytest


@pytest.mark.parametrize("verb", [
    CharacterAction.AT_DEFAULT,
    CharacterAction.AT_BREATHE,
    CharacterAction.AT_FORCE_BREATHE,
])
def test_default_and_breathe_restore_the_rest_pose(monkeypatch, verb):
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ch.set_current_animation("PushingButtons", CharacterClass.CAT_NON_INTERRUPTABLE)
    ctrl = _FakeController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)

    action = CharacterAction(ch, verb)
    action.Play()

    assert ctrl.submitted == [(ch, "DEFAULT", None, None)]
    assert action.IsPlaying() == 0          # completes inline
    assert ch.IsAnimating() == 0            # gate reopens


def test_queue_default_survives_reentrant_gesture_submitted_by_dropped_on_complete(
        monkeypatch):
    # Regression for the ordering requirement documented on _queue_default:
    # it must call cc.clear_current_animation() BEFORE ctrl.request_default(cc),
    # never after. request_default() fires the DROPPED transient action's
    # on_complete SYNCHRONOUSLY (BridgeCharacterAnimController.request_default),
    # and our event dispatch is synchronous, so that callback can re-enter:
    # a cancelled gesture's _done() runs Completed(), which can advance the
    # owning TGSequence and submit a BRAND-NEW gesture on the SAME officer —
    # including a fresh set_current_animation() call — before request_default()
    # returns. If _queue_default cleared AFTER request_default, that trailing
    # clear would wipe the state belonging to the newly-started gesture instead
    # of the cancelled one's, leaving the officer visibly gesturing while
    # IsAnimating()/IsAnimatingNonInterruptable() report idle.
    #
    # This drives the REAL BridgeCharacterAnimController (not _FakeController,
    # whose request_default is a stub that never fires on_complete and so can
    # never exercise re-entrancy). Gesture A's on_complete is a callback that
    # performs exactly what a real _done() -> Completed() -> TGSequence-advance
    # chain would do to submit gesture B: ctrl.submit(...) + set_current_animation
    # (see CharacterAction._queue_play_animation's _done(), which does the same
    # two calls). We inline that pair directly rather than building a full
    # TGSequence/CharacterAction B, because the two calls ARE the entirety of
    # what the real chain contributes at this boundary — building the sequence
    # machinery around them would not change what request_default() observes.
    from engine import bridge_character_anim as bca

    ch = _character_with("GestureA", "Mod.A")
    ch.AddAnimation("GestureB", "Mod.B")
    ch._render_instance = 123
    ch.SetHidden(0)
    ctrl = bca.BridgeCharacterAnimController()

    def _a_on_complete():
        # Simulates the re-entrant chain: a dropped gesture's completion
        # submits and marks a NEW gesture (B) on the SAME officer, all from
        # inside request_default()'s synchronous callback.
        assert ctrl.submit(ch, [("clipB.nif", 5.0)],
                           priority=bca._SCRIPTED) is True
        ch.set_current_animation("GestureB", CharacterClass.CAT_NON_INTERRUPTABLE)

    assert ctrl.submit(ch, [("clipA.nif", 5.0)], priority=bca._SCRIPTED,
                       on_complete=_a_on_complete) is True
    ch.set_current_animation("GestureA", CharacterClass.CAT_NON_INTERRUPTABLE)
    assert ctrl.is_busy(ch) is True

    monkeypatch.setattr(bca, "get_controller", lambda: ctrl)
    action = CharacterAction(ch, CharacterAction.AT_DEFAULT)
    action.Play()

    # B is the gesture ACTUALLY playing on the controller — it must survive
    # _queue_default's clear/request_default sequence intact, not read back
    # as idle.
    assert ch.GetCurrentAnimation() == "GestureB"
    assert ch.IsAnimatingNonInterruptable() == 1
    assert ctrl.is_busy(ch) is True


class _TurnRecordingController(_FakeController):
    def __init__(self):
        super().__init__()
        self.turns = []
        self.turn_calls = []      # (kind, detail, now) — full call shape
        self.pending = []         # on_completes we were handed but have not fired

    def request_turn_to(self, character, detail, *, back=False, now=False,
                        hold=True, on_complete=None):
        kind = "back" if back else "to"
        self.turns.append((kind, detail))
        self.turn_calls.append((kind, detail, bool(now)))
        if on_complete is not None:
            self.pending.append(on_complete)
            on_complete()          # settle immediately, so the test is synchronous


class _DeferringTurnController(_TurnRecordingController):
    """Like the real controller: an awaited turn's on_complete fires LATER
    (when the animation settles), not synchronously with the request."""

    def request_turn_to(self, character, detail, *, back=False, now=False,
                        hold=True, on_complete=None):
        kind = "back" if back else "to"
        self.turns.append((kind, detail))
        self.turn_calls.append((kind, detail, bool(now)))
        if on_complete is not None:
            self.pending.append(on_complete)


def _spy_speech(monkeypatch):
    spoken = []
    monkeypatch.setattr(CharacterAction, "_do_play",
                        lambda self: (spoken.append(self._detail), 1.5)[1])
    return spoken


def test_say_line_overlaps_the_turn_with_the_line(monkeypatch):
    # GROUND TRUTH (Ghidra, stbc.exe 1.1): AT_SAY_LINE's opening turn is an
    # AT_TURN_NOW sub-action — it starts the animated turn and self-completes
    # IMMEDIATELY, so the line begins while the officer is still visibly
    # turning. It is NOT awaited (that is AT_SAY_LINE_AFTER_TURN's job) and it
    # is NOT an orientation snap.
    ch = _character_with("IncomingMsg6", "Some.Module.Unused")
    ctrl = _DeferringTurnController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    spoken = _spy_speech(monkeypatch)

    action = CharacterAction(ch, CharacterAction.AT_SAY_LINE,
                             "IncomingMsg6", "Captain", 1)
    action.Play()

    assert ctrl.turn_calls == [("to", "Captain", True)]   # fire-and-forget turn
    assert ctrl.pending == []                             # nothing awaited
    assert spoken == ["IncomingMsg6"]                     # line already started
    assert action.IsPlaying() is True                     # ...and still blocks


def test_say_line_after_turn_waits_for_the_turn_to_settle(monkeypatch):
    # AT_SAY_LINE_AFTER_TURN differs from AT_SAY_LINE by ONE immediate: its
    # opening turn is AT_TURN (awaited), so the line does not start until the
    # turn animation settles.
    ch = _character_with("IncomingMsg6", "Some.Module.Unused")
    ctrl = _DeferringTurnController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    spoken = _spy_speech(monkeypatch)

    action = CharacterAction(ch, CharacterAction.AT_SAY_LINE_AFTER_TURN,
                             "IncomingMsg6", "Captain", 1)
    action.Play()

    assert ctrl.turn_calls == [("to", "Captain", False)]  # awaited turn
    assert spoken == []                                   # not yet — still turning
    assert len(ctrl.pending) == 1

    ctrl.pending.pop()()                                  # the turn settles

    assert spoken == ["IncomingMsg6"]


@pytest.mark.parametrize("verb", [
    CharacterAction.AT_SAY_LINE,
    CharacterAction.AT_SAY_LINE_AFTER_TURN,
])
def test_turn_back_is_fire_and_forget_and_the_action_completes_at_end_of_line(
        monkeypatch, verb):
    # The CharacterAction completes at END-OF-LINE, not after the turn-back:
    # BC's TurnBack sub-action self-completes as soon as it STARTS the swivel.
    # The next action in the outer TGSequence therefore begins the moment the
    # audio ends, with the turn-back playing out underneath it.
    ch = _character_with("IncomingMsg6", "Some.Module.Unused")
    ctrl = _DeferringTurnController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    spoken = _spy_speech(monkeypatch)

    action = CharacterAction(ch, verb, "IncomingMsg6", "Captain", 1)
    action.Play()
    if verb == CharacterAction.AT_SAY_LINE_AFTER_TURN:
        ctrl.pending.pop()()                  # the opening turn settles
    assert spoken == ["IncomingMsg6"]
    assert action.IsPlaying() is True         # the line still blocks the sequence

    import App
    App.g_kRealtimeTimerManager.tick(1.5)     # the line's real duration elapses

    assert ctrl.turn_calls[-1] == ("back", "Captain", True)   # started, not awaited
    assert ctrl.pending == []                 # nobody is waiting on the swivel
    assert action.IsPlaying() is False        # completed at end-of-line


def test_say_line_turns_to_the_captain_and_back(monkeypatch):
    ch = _character_with("IncomingMsg6", "Some.Module.Unused")
    ctrl = _TurnRecordingController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    spoken = _spy_speech(monkeypatch)

    action = CharacterAction(ch, CharacterAction.AT_SAY_LINE,
                             "IncomingMsg6", "Captain", 1)
    action.Play()

    # The line genuinely BLOCKS the sequence for its real (mocked) 1.5s
    # duration -- _do_play's returned dur drives a real deferred timer via
    # _complete_after(dur, on_elapsed=...), exactly like every other speak
    # action (see test_actions.py's _advance_real_time-driven tests). The
    # turn-back only fires once that timer elapses, not synchronously with
    # Play().
    import App
    App.g_kRealtimeTimerManager.tick(1.5)

    assert ctrl.turns == [("to", "Captain"), ("back", "Captain")]
    assert spoken == ["IncomingMsg6"]


def test_say_line_without_a_turn_target_just_speaks(monkeypatch):
    # (None, 0) — speaks with no turn at all. The regression guard.
    ch = _character_with("IncomingMsg6", "Some.Module.Unused")
    ctrl = _TurnRecordingController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    spoken = []
    monkeypatch.setattr(CharacterAction, "_do_play",
                        lambda self: (spoken.append(self._detail), 1.5)[1])

    action = CharacterAction(ch, CharacterAction.AT_SAY_LINE,
                             "IncomingMsg6", None, 0)
    action.Play()

    assert ctrl.turns == []
    assert spoken == ["IncomingMsg6"]


def test_say_line_turns_to_but_does_not_turn_back(monkeypatch):
    ch = _character_with("IncomingMsg6", "Some.Module.Unused")
    ctrl = _TurnRecordingController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    monkeypatch.setattr(CharacterAction, "_do_play", lambda self: 1.5)

    action = CharacterAction(ch, CharacterAction.AT_SAY_LINE,
                             "IncomingMsg6", "Captain", 0)
    action.Play()

    assert ctrl.turns == [("to", "Captain")]
    assert ctrl.turn_calls == [("to", "Captain", True)]


def test_say_line_completes_even_when_complete_after_raises(monkeypatch):
    # Stall-hole regression: _speak() latches `spoke` BEFORE it calls
    # _complete_after(). If _complete_after then raises (e.g. the realtime
    # timer manager was torn down mid mission-swap), the old code relied on
    # the outer `except Exception: _speak()` in _queue_say_line to recover --
    # but the latch makes that second _speak() call a no-op, so the action
    # is left _playing with no timer scheduled and no Completed(). The
    # owning TGSequence then stalls forever. Play() must never do that.
    ch = _character_with("IncomingMsg6", "Some.Module.Unused")
    ctrl = _TurnRecordingController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    monkeypatch.setattr(CharacterAction, "_do_play", lambda self: 1.5)

    def _boom(self, duration_real_s, on_elapsed=None):
        raise RuntimeError("timer manager torn down")
    monkeypatch.setattr(CharacterAction, "_complete_after", _boom)

    action = CharacterAction(ch, CharacterAction.AT_SAY_LINE,
                             "IncomingMsg6", None, 0)
    action.Play()                                # must not raise

    assert action.IsPlaying() is False           # never left stuck _playing


def _count_completions(monkeypatch):
    """Count Completed() calls — a skipped action must complete exactly once."""
    calls = []
    orig = CharacterAction.Completed

    def _counted(self):
        calls.append(self)
        orig(self)
    monkeypatch.setattr(CharacterAction, "Completed", _counted)
    return calls


def test_skipped_say_line_still_turns_the_officer_back(monkeypatch):
    # Backspace -> TGActionManager_SkipEvents -> TGAction.Skip ->
    # _cancel_deferred_timer(), which drops _deferred_on_elapsed — so the
    # _turn_back_now closure never ran. The forward turn used hold=True, so the
    # officer AND his chair held the turned-to-captain pose for the rest of the
    # scene. Skipping dialogue is routine in BC.
    ch = _character_with("IncomingMsg6", "Some.Module.Unused")
    ctrl = _TurnRecordingController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    monkeypatch.setattr(CharacterAction, "_do_play", lambda self: 1.5)
    completions = _count_completions(monkeypatch)

    action = CharacterAction(ch, CharacterAction.AT_SAY_LINE,
                             "IncomingMsg6", "Captain", 1)
    action.Play()
    assert ctrl.turns == [("to", "Captain")]     # turned, line playing
    assert completions == []

    action.Skip()                                # Backspace mid-line

    assert ctrl.turns == [("to", "Captain"), ("back", "Captain")]
    # fire-and-forget, like BC's TurnBack sub-action
    assert ctrl.turn_calls[-1] == ("back", "Captain", True)
    assert action.IsPlaying() is False           # skip completes immediately
    assert len(completions) == 1                 # exactly once

    import App
    App.g_kRealtimeTimerManager.tick(5.0)        # the cancelled timer is gone
    assert len(completions) == 1                 # still exactly once
    assert ctrl.turns == [("to", "Captain"), ("back", "Captain")]


def test_skipped_say_line_without_a_turn_is_unchanged(monkeypatch):
    # The Skip() contract for every other case is untouched: no turn owed, no
    # turn issued, still exactly one completion.
    ch = _character_with("IncomingMsg6", "Some.Module.Unused")
    ctrl = _TurnRecordingController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    monkeypatch.setattr(CharacterAction, "_do_play", lambda self: 1.5)
    completions = _count_completions(monkeypatch)

    action = CharacterAction(ch, CharacterAction.AT_SAY_LINE,
                             "IncomingMsg6", None, 0)
    action.Play()
    action.Skip()

    assert ctrl.turns == []
    assert len(completions) == 1


def test_skip_during_the_forward_turn_does_not_speak_afterwards(monkeypatch):
    # Skipped BEFORE the forward turn settles: the queued speak callback is
    # still live in the controller (and _process_turn rescues it when the
    # turn-back evicts the forward turn). It must NOT then speak the line the
    # player just skipped, and must not complete the action a second time.
    #
    # AT_SAY_LINE_AFTER_TURN is the verb whose speak is deferred behind the
    # opening turn's on_complete (AT_SAY_LINE overlaps the two by design and
    # has already spoken by the time Play() returns), so it is the one that can
    # be skipped mid-turn-before-line.
    ch = _character_with("IncomingMsg6", "Some.Module.Unused")

    ctrl = _DeferringTurnController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    spoken = _spy_speech(monkeypatch)
    completions = _count_completions(monkeypatch)

    action = CharacterAction(ch, CharacterAction.AT_SAY_LINE_AFTER_TURN,
                             "IncomingMsg6", "Captain", 1)
    action.Play()
    assert spoken == []                          # still turning
    action.Skip()                                # Backspace before the turn settles
    assert ("back", "Captain") in ctrl.turns
    assert len(completions) == 1

    for cb in list(ctrl.pending):                # the controller settles the turns
        cb()
    assert spoken == []                          # the skipped line never speaks
    assert len(completions) == 1                 # and never completes twice


def test_gesture_landing_on_a_still_playing_turn_queues_behind_it_uncorrupted(
        monkeypatch):
    # SP2 P3 model change: this test USED TO reproduce a synchronous
    # re-entrant chain (gesture.Play() -> _queue_play_animation ->
    # ctrl.submit() preempting the in-flight turn action and rescuing its
    # on_complete SYNCHRONOUSLY, which could advance the owning TGSequence
    # into AT_DEFAULT on the same officer before submit() even returned, and
    # that AT_DEFAULT could pop the brand-new gesture and jam the officer's
    # animation state). That chain is now IMPOSSIBLE: _queue_play_animation no
    # longer calls the controller directly -- it calls
    # CharacterClass.PlayAnimation, which only enqueues via
    # SetCurrentAnimation. The referee (character_anim_queue.classify) says
    # the TURN row is COEXIST against every category, so a gesture landing on
    # a still-playing turn is QUEUED behind it, never preempting it
    # synchronously -- there is no controller call, no rescued on_complete,
    # no re-entrant TGSequence advance, and so no way to jam the officer via
    # this path. The invariant this test protects (the still-playing turn
    # survives a second scripted action landing on the same officer,
    # uncorrupted) now holds by construction; we still verify it explicitly.
    import App
    from engine import bridge_character_anim as bca
    from engine.appc.actions import TGSequence_Create

    ch = App.CharacterClass_Create(
        "data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.nif",
        "data/Models/Characters/Heads/HeadFelix/felix_head.nif",
    )
    ch.SetCharacterName("Test")
    ch.SetLocation("DBEngineer")
    # Real SDK-registered TurnCaptain builder, resolved the same way
    # capture_registered_clip does in production (test_bridge_registered_clip.py).
    ch.AddAnimation("DBEngineerTurnCaptain",
                    "Bridge.Characters.SmallAnimations.TurnAtETowardsCaptain")
    ch.AddAnimation("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ch._render_instance = 555
    ch.SetHidden(0)

    ctrl = bca.BridgeCharacterAnimController()
    monkeypatch.setattr(bca, "get_controller", lambda: ctrl)
    monkeypatch.setattr("engine.bridge_idle_gestures.build_sequence_clips",
                        lambda path, character, anim_mgr: [("gesture.nif", 5.0)])

    class _Renderer:
        def load_instance_clip(self, iid, path):
            return 1

        def play_instance_gesture(self, iid, ci):
            pass

        def play_instance_idle(self, iid, ci):
            pass

        def restore_rest_pose(self, iid):
            pass

        def load_animation_clips(self, path):
            # Nonzero duration + a rotation track -> body-driven turn, so
            # _process_turn genuinely submits a body _Action (not chair-only).
            return [{"duration": 5.0,
                     "tracks": [{"rotation": [(0.0, (0, 0, 0, 1))]}]}]

    r = _Renderer()

    turn_action = CharacterAction(ch, CharacterAction.AT_TURN, "Captain")
    default_action = CharacterAction(ch, CharacterAction.AT_DEFAULT)
    seq = TGSequence_Create()
    seq.AddAction(turn_action)
    seq.AppendAction(default_action)

    seq.Play()                        # turn_action.Play() -> CharacterClass.TurnTowards enqueues
    ch.UpdateAnimationQueue()         # CharacterClass queue drains the record -> play_record()
    ctrl.update(0.0, renderer=r)      # drains the pending turn -> installs the body _Action
    assert ctrl.is_busy(ch) is True
    assert turn_action.IsPlaying() is True   # genuinely mid-turn, not settled

    gesture = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION, "PushingButtons")
    gesture.Play()

    # QUEUED behind the turn, not preempting it -- the turn is untouched and
    # still genuinely playing; the gesture waits its turn.
    assert gesture.IsPlaying() == 1
    assert len(ch._anim_pending) == 1
    assert ch._anim_pending[0].category == ch.CAT_NON_INTERRUPTABLE
    assert turn_action.IsPlaying() is True    # NOT jammed / NOT corrupted
    assert ctrl.is_busy(ch) is True


def test_queue_turn_routes_through_turntowards_not_request_turn_to(monkeypatch):
    # SP2 T14b: the one door is CharacterClass.TurnTowards/TurnBack --
    # CharacterAction._queue_turn must not call the controller directly.
    from engine.appc.characters import CharacterClass_Create

    ch = CharacterClass_Create()
    ch.SetActive(1)

    calls = []
    monkeypatch.setattr(ch, "TurnTowards",
                        lambda name, now=False, on_complete=None:
                            (calls.append((name, now, on_complete)), 0)[1])

    def _boom(*a, **k):
        raise AssertionError("must not call the controller directly")

    class _NoDirectTurnController:
        request_turn_to = staticmethod(_boom)

    monkeypatch.setattr(bridge_character_anim, "get_controller",
                        lambda: _NoDirectTurnController())
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)

    act = CharacterAction(ch, CharacterAction.AT_TURN, "Captain")
    act.Play()

    assert len(calls) == 1
    name, now, on_complete = calls[0]
    assert name == "Captain"
    assert now is False
    assert on_complete == act.Completed
