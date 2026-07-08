from engine.appc.ai import CharacterAction
from engine.appc import bridge_placement
import engine.bridge_character_walk as bcw


class _Char:
    def __init__(self, name="Picard"):
        self._character_name = name
        self._location = "DBL1M"
    def GetCharacterName(self):
        return self._character_name
    def SetLocation(self, loc):
        self._location = loc
    def GetLocation(self):
        return self._location


class _RecordingWalkController:
    def __init__(self):
        self.requests = []
    def request_move(self, character, clip_nif, end_location, on_complete):
        self.requests.append((character, clip_nif, end_location, on_complete))


def test_at_move_queues_walk_and_defers_completion(monkeypatch):
    ch = _Char()
    ctrl = _RecordingWalkController()
    monkeypatch.setattr(bcw, "get_controller", lambda: ctrl)
    monkeypatch.setattr(bridge_placement, "capture_move",
                        lambda character, detail: {
                            "clip_nif": "db_L1toP_P.nif",
                            "end_location": "DBGuest1"} if detail == "P1" else None)
    # Cast is identity for our fake (it isn't a real CharacterClass).
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)

    act = CharacterAction(ch, CharacterAction.AT_MOVE, "P1")
    act.Play()

    assert act.IsPlaying() is True                    # deferred: not yet complete
    assert len(ctrl.requests) == 1
    character, clip_nif, end_location, on_complete = ctrl.requests[0]
    assert (clip_nif, end_location) == ("db_L1toP_P.nif", "DBGuest1")

    on_complete()                                     # controller signals settle
    assert act.IsPlaying() is False                   # now complete


def test_at_move_completes_inline_when_unresolvable(monkeypatch):
    ch = _Char()
    ctrl = _RecordingWalkController()
    monkeypatch.setattr(bcw, "get_controller", lambda: ctrl)
    monkeypatch.setattr(bridge_placement, "capture_move",
                        lambda character, detail: None)   # no builder
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
