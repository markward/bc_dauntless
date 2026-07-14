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


def test_play_animation_submits_the_registered_gesture(monkeypatch):
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ctrl = _FakeController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    monkeypatch.setattr("engine.bridge_idle_gestures.build_sequence_clips",
                        lambda path, character, anim_mgr: [("clip.nif", 1.0)])

    action = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION, "PushingButtons")
    action.Play()

    assert len(ctrl.submitted) == 1
    _c, clips, priority, _cb = ctrl.submitted[0]
    assert clips == [("clip.nif", 1.0)]
    assert priority == bridge_character_anim._SCRIPTED
    # flag defaults to 0 => BC's non-interruptable mode => the SDK gate closes
    assert ch.IsAnimatingNonInterruptable() == 1


def test_play_animation_flag_1_is_interruptable(monkeypatch):
    # MissionLib.py:3543 passes flag=1 explicitly.
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ctrl = _FakeController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)
    monkeypatch.setattr("engine.bridge_idle_gestures.build_sequence_clips",
                        lambda path, character, anim_mgr: [("clip.nif", 1.0)])

    action = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION,
                             "PushingButtons", None, 1)
    action.Play()
    assert ch.IsAnimatingInterruptable() == 1
    assert ch.IsAnimatingNonInterruptable() == 0


def test_play_animation_unregistered_key_completes_immediately(monkeypatch):
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ctrl = _FakeController()
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
    # FINDING 1 (RED first): AT_PLAY_ANIMATION_FILE passes a bare CLIP NAME
    # (e.g. "db_P_Point_C_P", MaelstromE1M1.py:2025), registered earlier via
    # g_kAnimationManager.LoadAnimation(path, name) — NOT a resolvable path
    # itself. It must be resolved via App.g_kAnimationManager.path_for().
    import App
    App.g_kAnimationManager.LoadAnimation(
        "data/animations/db_P_Point_C_P.nif", "db_P_Point_C_P__t6")
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ctrl = _FakeController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)

    action = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION_FILE,
                             "db_P_Point_C_P__t6")
    action.Play()

    assert len(ctrl.submitted) == 1
    _c, clips, priority, _cb = ctrl.submitted[0]
    assert clips == [("data/animations/db_P_Point_C_P.nif", 0.0)]
    assert priority == bridge_character_anim._SCRIPTED
    assert ch.IsAnimatingNonInterruptable() == 1


def test_play_animation_file_unregistered_name_completes_immediately(monkeypatch):
    # FINDING 1: a clip name that was never LoadAnimation()-registered must
    # never reach the renderer and must never stall the sequence.
    ch = _character_with("PushingButtons", "Some.Module.DBTConsoleInteraction")
    ctrl = _FakeController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: ctrl)

    action = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION_FILE,
                             "totally_unregistered_clip_name__t6")
    action.Play()

    assert ctrl.submitted == []
    assert action.IsPlaying() == 0
    assert ch.IsAnimating() == 0


def test_second_scripted_gesture_on_busy_officer_does_not_corrupt_first_action(
        monkeypatch):
    # FINDING 2 (RED first): using the REAL controller so the priority guard
    # genuinely fires. Officer is mid-gesture A (_SCRIPTED priority, still
    # playing); a second scripted gesture B on the SAME officer must be
    # rejected by submit()'s equal-priority guard WITHOUT corrupting A's
    # still-in-flight animation state.
    from engine import bridge_character_anim as bca
    from engine.bridge_idle_gestures import build_sequence_clips as _real
    ch = _character_with("GestureA", "Mod.A")
    ch.AddAnimation("GestureB", "Mod.B")
    ch._render_instance = 99
    ch.SetHidden(0)
    ctrl = bca.BridgeCharacterAnimController()
    monkeypatch.setattr(bca, "get_controller", lambda: ctrl)

    def _clips(module_path, character, anim_mgr):
        return [("clipA.nif", 5.0)] if module_path == "Mod.A" else [("clipB.nif", 5.0)]
    monkeypatch.setattr("engine.bridge_idle_gestures.build_sequence_clips", _clips)

    action_a = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION, "GestureA")
    action_a.Play()
    assert ctrl.is_busy(ch) is True
    assert action_a.IsPlaying() == 1
    assert ch.GetCurrentAnimation() == "GestureA"
    assert ch.IsAnimatingNonInterruptable() == 1

    action_b = CharacterAction(ch, CharacterAction.AT_PLAY_ANIMATION, "GestureB")
    action_b.Play()

    assert action_b.IsPlaying() == 0     # B rejected by the priority guard, completes
    # A's state must survive B's rejected submission untouched.
    assert ctrl.is_busy(ch) is True
    assert ch.GetCurrentAnimation() == "GestureA"
    assert ch.IsAnimatingNonInterruptable() == 1
    assert action_a.IsPlaying() == 1     # A is still genuinely playing


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
