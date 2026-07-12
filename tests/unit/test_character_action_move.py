import App
from engine.appc.ai import CharacterAction
from engine.appc import bridge_placement
from engine.appc.anim_node import TGAnimNode
import engine.bridge_character_walk as bcw


class _Char:
    def __init__(self, name="Picard"):
        self._character_name = name
        self._location = "DBL1M"
        self._node = TGAnimNode(owner=self, kind="character")
    def GetCharacterName(self):
        return self._character_name
    def GetAnimNode(self):
        return self._node
    def SetLocation(self, loc):
        self._location = loc
    def GetLocation(self):
        return self._location


class _RecordingWalkController:
    def __init__(self):
        self.requests = []
    def request_move(self, character, clip_nif, end_location, on_complete):
        self.requests.append((character, clip_nif, end_location, on_complete))


def _builder_seq(ch, clip, end_location):
    """A stand-in for an SDK move builder's TGSequence (PicardAnimations.
    MoveFromL1ToP1): the walk clip on the character's anim node, then the trailing
    AT_SET_LOCATION_NAME that re-stations the officer once the walk completes."""
    seq = App.TGSequence_Create()
    seq.AddAction(App.TGAnimAction_Create(ch.GetAnimNode(), clip))
    seq.AppendAction(App.CharacterAction_Create(
        ch, CharacterAction.AT_SET_LOCATION_NAME, end_location))
    return seq


def test_at_move_queues_walk_and_defers_completion(monkeypatch):
    ch = _Char()
    ctrl = _RecordingWalkController()
    monkeypatch.setattr(bcw, "get_controller", lambda: ctrl)
    monkeypatch.setattr(bridge_placement, "_resolve_builder_sequence",
                        lambda c, suffix: _builder_seq(c, "db_L1toP_P", "DBGuest1")
                        if suffix == "ToP1" else None)
    monkeypatch.setattr(bridge_placement, "_nif_path_for_clip",
                        lambda name: "db_L1toP_P.nif")
    # Cast is identity for our fake (it isn't a real CharacterClass).
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)

    act = CharacterAction(ch, CharacterAction.AT_MOVE, "P1")
    act.Play()

    assert act.IsPlaying() is True                    # deferred: not yet complete
    assert len(ctrl.requests) == 1
    character, clip_nif, end_location, on_complete = ctrl.requests[0]
    # end_location is None by design: the builder's own trailing
    # AT_SET_LOCATION_NAME action re-stations the officer (the SDK's mechanism).
    assert (clip_nif, end_location) == ("db_L1toP_P.nif", None)
    assert ch.GetLocation() == "DBL1M"                # not yet re-stationed

    on_complete()                                     # controller signals settle
    assert act.IsPlaying() is False                   # now complete
    assert ch.GetLocation() == "DBGuest1"             # the builder set the station


def test_at_move_completes_inline_when_unresolvable(monkeypatch):
    ch = _Char()
    ctrl = _RecordingWalkController()
    monkeypatch.setattr(bcw, "get_controller", lambda: ctrl)
    monkeypatch.setattr(bridge_placement, "_resolve_builder_sequence",
                        lambda c, suffix: None)          # no builder
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)

    act = CharacterAction(ch, CharacterAction.AT_MOVE, "P1")
    act.Play()
    assert ctrl.requests == []
    assert act.IsPlaying() is False                   # never stalls the sequence


def test_at_set_location_name_updates_location():
    ch = _Char()
    act = CharacterAction(ch, CharacterAction.AT_SET_LOCATION_NAME, "DBGuest1")
    act.Play()
    assert ch.GetLocation() == "DBGuest1"
    assert act.IsPlaying() is False


def test_at_watch_me_completes_inline():
    ch = _Char()
    act = CharacterAction(ch, CharacterAction.AT_WATCH_ME)
    act.Play()
    assert act.IsPlaying() is False                   # sequencing advances


class _RecordingCameraWatch:
    """Watch-controller double so these regressions can assert the real
    camera-framing target/clear calls, not just that the action completes.
    AT_WATCH_ME/AT_LOOK_AT_ME(_NOW) aim the bridge camera at the character —
    they do NOT toggle a CS_TURNED status flag (that was the placeholder
    this task replaces)."""
    def __init__(self):
        self.watched = []
        self.cleared = 0
    def watch(self, character, snap=False):
        self.watched.append((character, snap))
    def clear(self):
        self.cleared += 1


def test_at_watch_me_sets_camera_watch_target(monkeypatch):
    import engine.bridge_camera_watch as bridge_camera_watch
    ch = _Char()
    ctrl = _RecordingCameraWatch()
    monkeypatch.setattr(bridge_camera_watch, "get_controller", lambda: ctrl)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)
    act = CharacterAction(ch, CharacterAction.AT_WATCH_ME)
    act.Play()
    assert ctrl.watched == [(ch, False)]
    assert ctrl.cleared == 0
    assert act.IsPlaying() is False


def test_at_stop_watching_me_clears_camera_watch(monkeypatch):
    import engine.bridge_camera_watch as bridge_camera_watch
    ch = _Char()
    ctrl = _RecordingCameraWatch()
    monkeypatch.setattr(bridge_camera_watch, "get_controller", lambda: ctrl)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)
    act = CharacterAction(ch, CharacterAction.AT_STOP_WATCHING_ME)
    act.Play()
    assert ctrl.cleared == 1
    assert ctrl.watched == []
    assert act.IsPlaying() is False


def test_at_move_does_not_raise_when_the_builder_raises(monkeypatch):
    ch = _Char()
    ctrl = _RecordingWalkController()
    monkeypatch.setattr(bcw, "get_controller", lambda: ctrl)

    def _raise(character, suffix):
        raise RuntimeError("SDK builder blew up")

    monkeypatch.setattr(bridge_placement, "_resolve_builder_sequence", _raise)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)

    act = CharacterAction(ch, CharacterAction.AT_MOVE, "P1")
    act.Play()                                         # must not raise

    assert ctrl.requests == []
    assert act.IsPlaying() is False                    # completed inline
