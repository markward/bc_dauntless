"""End-to-end (headless): a turn dispatch flows through the real
BridgeCharacterAnimController to a deferred completion, and a watch dispatch
flows through the real BridgeCameraWatchController to a resolved camera target."""
from engine.appc.ai import CharacterAction
from engine.bridge_character_anim import BridgeCharacterAnimController
import engine.bridge_character_anim as bca
from engine.bridge_camera_watch import BridgeCameraWatchController
import engine.bridge_camera_watch as bcw


class _AnimRenderer:
    def __init__(self):
        self._n = 0
    def load_instance_clip(self, iid, path):
        self._n += 1
        return self._n
    def play_instance_gesture(self, iid, ci):
        pass
    def play_instance_idle(self, iid, ci):
        pass
    def restore_rest_pose(self, iid):
        pass
    def load_animation_clips(self, path):
        return [{"duration": 1.0,
                 "tracks": [{"rotation": [(0.0, (0, 0, 0, 1))]}]}]


class _Char:
    def __init__(self):
        self._render_instance = 88
    def GetCharacterName(self):
        return "Picard"
    def GetLocation(self):
        return "DBGuest"
    def IsHidden(self):
        return 0


def test_turn_dispatch_to_deferred_completion(monkeypatch):
    # SP2 T14b: AT_TURN now routes through the real CharacterClass door
    # (TurnTowards), so the character under test must be a real CharacterClass
    # -- its AnimRec queue has to be drained (UpdateAnimationQueue) before the
    # controller ever sees the turn request.
    from engine.appc.characters import CharacterClass_Create

    monkeypatch.setattr(bca, "capture_registered_clip",
                        lambda ch, suffix: {"clip_nif": suffix + ".nif"})
    monkeypatch.setattr(bca, "capture_chair_clip", lambda ch, suffix: None)
    ctrl = BridgeCharacterAnimController()
    monkeypatch.setattr(bca, "get_controller", lambda: ctrl)
    r = _AnimRenderer()
    ch = CharacterClass_Create()
    ch.SetCharacterName("Picard")
    ch.SetLocation("DBGuest")
    ch._render_instance = 88

    act = CharacterAction(ch, CharacterAction.AT_TURN, "Captain")
    act.Play()
    assert act.IsPlaying() is True                 # deferred to the queue
    ch.UpdateAnimationQueue()                       # drains the record -> play_record()
    assert act.IsPlaying() is True                 # deferred to the controller
    ctrl.update(0.0, renderer=r)                    # drain -> submit body clip
    assert act.IsPlaying() is True
    ctrl.update(2.0, renderer=r)                    # settle -> Completed()
    assert act.IsPlaying() is False


def test_watch_dispatch_to_camera_target(monkeypatch):
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)
    ctrl = BridgeCameraWatchController()
    monkeypatch.setattr(bcw, "get_controller", lambda: ctrl)
    ch = _Char()

    CharacterAction(ch, CharacterAction.AT_WATCH_ME).Play()

    class _R:
        def get_instance_head_center(self, iid):
            return (iid + 0.0, 0.0, 0.0)
    assert ctrl.resolve_target_world(_R()) == (88.0, 0.0, 0.0)

    CharacterAction(ch, CharacterAction.AT_STOP_WATCHING_ME).Play()
    assert ctrl.resolve_target_world(_R()) is None
