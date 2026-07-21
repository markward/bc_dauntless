"""AT_MOVE plays the SDK's builder TGSequence instead of mining a clip from it.

MoveFromL1ToP1 (PicardAnimations.py:86) returns a TGSequence that walks the
character, fires LiftDoorAction on "doorl1" 0.125s after the eyes-open action, sets
the end location, and fires CS_STANDING on completion. Extracting only the walk clip
(the old capture_move path) dropped the door, the sound and the events on the floor.

Only the WALK action routes to the walk controller. EyesOpenMouthClosed is also a
character-node TGAnimAction (a 0.1s facial clip) -- and it is the dependency the door
is scheduled off. Routing it to root-motion playback would drive the officer's whole
skeleton from an eyes-and-mouth clip.

The door step carries a 0.125s delay (AddAction(pDoorAction, pOpenEyes, 0.125)), so
it is scheduled on g_kTimerManager: these tests pump game time to fire it, exactly
as the host loop / mission harness do.
"""
import pytest

import App
from engine.appc.ai import CharacterAction
from engine.appc.bridge_set import BridgeObjectClass


@pytest.fixture(autouse=True)
def _bridge_set():
    """MoveFromL1ToP1 reaches for g_kSetManager.GetSet("bridge").GetObject("bridge")
    to hang the LiftDoorAction off the bridge model's anim node -- the set the real
    LoadBridge.Load builds. Without it the builder raises and the move degrades to
    an inline completion (which is exactly the bug this task fixes)."""
    s = App.BridgeSet_Create()
    s.AddObjectToSet(BridgeObjectClass("data/Models/Bridges/Galaxy/GalaxyBridge.nif"),
                     "bridge")
    App.g_kSetManager.AddSet(s, "bridge")
    yield s
    App.g_kSetManager.DeleteSet("bridge")


def _tick(seconds=0.25):
    """Advance game time in 60 Hz ticks so a sequence's delayed steps fire."""
    step = 1.0 / 60.0
    for _ in range(int(seconds / step) + 1):
        App.g_kTimerManager.tick(step)


def _picard_at_the_lift():
    """A character standing at the turbolift with Picard's real move registered
    (mirrors Picard.py:143). Same idiom as tests/unit/test_bridge_registered_clip.py."""
    c = App.CharacterClass_Create(
        "data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.nif",
        "data/Models/Characters/Heads/HeadFelix/felix_head.nif",
    )
    c.SetCharacterName("Picard")
    c.SetLocation("DBL1M")
    c.AddAnimation("DBL1MToP1", "Bridge.Characters.PicardAnimations.MoveFromL1ToP1")
    return c


class _FakeWalkController:
    def __init__(self):
        self.moves = []                 # (character, clip_nif)
        self._on_complete = None

    def request_move(self, character, clip_nif, on_complete):
        self.moves.append((character, clip_nif))
        self._on_complete = on_complete

    def finish(self):
        self._on_complete()


class _RecordingCutscene:
    """Stands in for BridgeCutsceneController: records the door clip NAMES that the
    builder's LiftDoorAction plays on the bridge (object) anim node."""
    def __init__(self):
        self.doors = []                 # clip names

    def request_object_anim(self, action, anim_node, clip_name):
        self.doors.append(str(clip_name))
        action.Completed()              # fire-and-forget, as the real door does

    def request_camera_path(self, action, anim_node, clip_name):
        action.Completed()


def test_at_move_plays_the_builder_sequence_so_the_door_fires(monkeypatch):
    """The builder's LiftDoorAction must actually be played, not dropped."""
    walk, cutscene = _FakeWalkController(), _RecordingCutscene()
    monkeypatch.setattr("engine.bridge_character_walk.get_controller", lambda: walk)
    monkeypatch.setattr("engine.bridge_cutscene.get_controller", lambda: cutscene)

    ch = _picard_at_the_lift()
    act = App.CharacterAction_Create(ch, CharacterAction.AT_MOVE, "P1")
    act.Play()
    ch.UpdateAnimationQueue()           # drain the queue -> play_record -> seq.Play()
    _tick()                             # the door is scheduled 0.125s in

    assert walk.moves, "the walk action must reach the walk controller"
    assert "doorl1" in cutscene.doors, \
        "the builder's LiftDoorAction must be played, not dropped"


def test_only_the_walk_action_routes_to_the_walk_controller(monkeypatch):
    """EyesOpenMouthClosed is ALSO a character-node TGAnimAction (a 0.1s facial clip).
    It must NOT be driven as a root-motion body clip."""
    walk, cutscene = _FakeWalkController(), _RecordingCutscene()
    monkeypatch.setattr("engine.bridge_character_walk.get_controller", lambda: walk)
    monkeypatch.setattr("engine.bridge_cutscene.get_controller", lambda: cutscene)

    ch = _picard_at_the_lift()
    act = App.CharacterAction_Create(ch, CharacterAction.AT_MOVE, "P1")
    act.Play()
    ch.UpdateAnimationQueue()
    _tick()

    assert len(walk.moves) == 1, "exactly one action is the walk: the marked one"
    clip_nif = walk.moves[0][1]
    assert "db_L1toP_P" in clip_nif                     # the walk clip
    assert "eyes_open_mouth_close" not in clip_nif      # not the facial clip


def test_at_move_completes_exactly_once_when_the_sequence_finishes(monkeypatch):
    walk, cutscene = _FakeWalkController(), _RecordingCutscene()
    monkeypatch.setattr("engine.bridge_character_walk.get_controller", lambda: walk)
    monkeypatch.setattr("engine.bridge_cutscene.get_controller", lambda: cutscene)

    ch = _picard_at_the_lift()
    act = App.CharacterAction_Create(ch, CharacterAction.AT_MOVE, "P1")
    completions = []
    real_completed = act.Completed

    def counting_completed():
        completions.append(1)
        real_completed()

    act.Completed = counting_completed
    act.Play()
    ch.UpdateAnimationQueue()           # drain the queue -> play_record -> seq.Play()
    _tick()                            # the door fires and completes
    assert not completions, "the move must not complete before the walk settles"
    walk.finish()                      # the walk clip settles -> sequence completes

    assert len(completions) == 1, "zero completions hangs the mission; two double-advance it"


def _picard_standing_at_guest1():
    """Picard's SIT-DOWN (MoveFromP1ToP, PicardAnimations.py:108): standing at the
    guest-1 mark, moving to the guest chair. Its AppendAction chains the trailing
    AT_SET_LOCATION_NAME onto the WALK action, not the door."""
    c = App.CharacterClass_Create(
        "data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.nif",
        "data/Models/Characters/Heads/HeadFelix/felix_head.nif",
    )
    c.SetCharacterName("Picard")
    c.SetLocation("DBGuest1")
    c.AddAnimation("DBGuest1ToP", "Bridge.Characters.PicardAnimations.MoveFromP1ToP")
    return c


def test_walk_completion_sets_the_location_synchronously(monkeypatch):
    """The load-bearing ordering guarantee behind BridgeCharacterWalkController._settle.

    _settle fires the walk action's Completed() and then resolves the officer's idle
    from GetLocation(). That is only correct if the builder's trailing
    AT_SET_LOCATION_NAME runs SYNCHRONOUSLY inside that Completed() -- i.e. the whole
    chain (Completed -> g_kEventManager.AddEvent -> TGSequence._on_dependency_complete
    -> _begin_step at delay 0 -> CharacterAction.Play -> SetLocation) is inline, with
    no deferred timer. Pinned here against the REAL SDK builder: if any link in that
    chain ever starts deferring, this test fails and _settle's ordering is unsound."""
    walk, cutscene = _FakeWalkController(), _RecordingCutscene()
    monkeypatch.setattr("engine.bridge_character_walk.get_controller", lambda: walk)
    monkeypatch.setattr("engine.bridge_cutscene.get_controller", lambda: cutscene)

    ch = _picard_standing_at_guest1()
    act = App.CharacterAction_Create(ch, CharacterAction.AT_MOVE, "P")
    act.Play()
    ch.UpdateAnimationQueue()                   # drain the queue -> play_record -> seq.Play()
    assert walk.moves, "the real builder's walk action must reach the walk controller"
    assert ch.GetLocation() == "DBGuest1"       # not re-stationed until the walk ends

    walk.finish()                               # exactly what _settle's _complete(mv) does
    # NO tick: the location must already be the destination the instant Completed returns.
    assert ch.GetLocation() == "DBGuest", \
        "the builder's AT_SET_LOCATION_NAME must run synchronously on walk completion"


def test_unresolvable_builder_completes_inline(monkeypatch):
    """No registered <location>To<detail> builder -> complete, never stall."""
    monkeypatch.setattr("engine.bridge_character_walk.get_controller",
                        lambda: _FakeWalkController())
    act = App.CharacterAction_Create(
        _picard_at_the_lift(), CharacterAction.AT_MOVE, "NoSuchMark")
    act.Play()
    assert act.IsPlaying() == 0


def test_headless_no_walk_controller_still_completes(monkeypatch):
    """No renderer/controller anywhere (the harness + most of the suite) --
    NOT bridge_character_walk/bridge_cutscene, and NOT bridge_character_anim
    either (mission_harness.py never wires it; only a live host_loop.run()
    does) -- must never stall. The queue's own no-controller fallback
    (CharacterClass._anim_play_now) plays a resolved builder TGSequence
    directly since it is self-contained (its own completed event, attached by
    MoveTo, is what fires our Completed() -- there is no on_complete on the
    record itself to rescue)."""
    monkeypatch.setattr("engine.bridge_character_walk.get_controller", lambda: None)
    monkeypatch.setattr("engine.bridge_cutscene.get_controller", lambda: None)
    ch = _picard_at_the_lift()
    act = App.CharacterAction_Create(ch, CharacterAction.AT_MOVE, "P1")
    act.Play()
    ch.UpdateAnimationQueue()           # drain the queue -> the fallback plays the seq directly
    _tick()                            # the door step's timer still has to fire
    assert act.IsPlaying() == 0
