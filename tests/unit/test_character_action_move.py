import App
from engine.appc.ai import CharacterAction
from engine.appc import bridge_placement
from engine.appc.anim_node import TGAnimNode
from engine.appc.characters import CharacterClass
from engine import bridge_character_anim
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


def _move_char(name="Picard", location="DBL1M"):
    """A REAL CharacterClass — AT_MOVE now routes through CharacterClass.MoveTo
    (the queue/referee/SetFlags/SetCurrentAnimation door), so these tests need
    the genuine receiver, not the lightweight `_Char` double the other verbs
    still use."""
    ch = CharacterClass()
    ch.SetCharacterName(name)
    ch.SetLocation(location)
    return ch


class _RecordingWalkController:
    def __init__(self):
        self.requests = []
    def request_move(self, character, clip_nif, on_complete):
        self.requests.append((character, clip_nif, on_complete))


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
    """AT_MOVE -> CharacterClass.MoveTo enqueues a CAT_NON_INTERRUPTABLE
    record; the walk controller is NOT touched until the queue drains."""
    ch = _move_char()
    ctrl = _RecordingWalkController()
    monkeypatch.setattr(bcw, "get_controller", lambda: ctrl)
    built = {}
    def _resolve(c, suffix):
        if suffix != "ToP1":
            return None
        built["seq"] = _builder_seq(c, "db_L1toP_P", "DBGuest1")
        return built["seq"]
    monkeypatch.setattr(bridge_placement, "_resolve_builder_sequence", _resolve)
    monkeypatch.setattr(bridge_placement, "_nif_path_for_clip",
                        lambda name: "db_L1toP_P.nif")
    anim_ctrl = bridge_character_anim.BridgeCharacterAnimController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: anim_ctrl)

    act = CharacterAction(ch, CharacterAction.AT_MOVE, "P1")
    act.Play()

    assert act.IsPlaying() is True                    # deferred: not yet complete
    assert len(ch._anim_pending) == 1                 # enqueued, not yet played
    rec = ch._anim_pending[0]
    assert rec.category == CharacterClass.CAT_NON_INTERRUPTABLE
    assert rec.play is built["seq"]
    assert ctrl.requests == []                        # the queue hasn't drained yet

    ch.UpdateAnimationQueue()                         # drain -> play_record -> seq.Play()
    assert len(ctrl.requests) == 1
    character, clip_nif, on_complete = ctrl.requests[0]
    # request_move carries no end-location: the builder's own trailing
    # AT_SET_LOCATION_NAME action re-stations the officer (the SDK's mechanism).
    assert clip_nif == "db_L1toP_P.nif"
    assert ch.GetLocation() == "DBL1M"                # not yet re-stationed

    on_complete()                                     # controller signals settle
    assert act.IsPlaying() is False                   # now complete
    assert ch.GetLocation() == "DBGuest1"             # the builder set the station


def test_at_move_completes_inline_when_unresolvable(monkeypatch):
    ch = _move_char()
    ctrl = _RecordingWalkController()
    monkeypatch.setattr(bcw, "get_controller", lambda: ctrl)
    monkeypatch.setattr(bridge_placement, "_resolve_builder_sequence",
                        lambda c, suffix: None)          # no builder

    act = CharacterAction(ch, CharacterAction.AT_MOVE, "P1")
    act.Play()
    assert ctrl.requests == []
    assert act.IsPlaying() is False                   # never stalls the sequence


def test_at_move_completion_guarantee_fires_exactly_once(monkeypatch):
    """The paramount invariant, proven end-to-end for both branches: Completed()
    fires EXACTLY once — via the queued-and-settled seq event when a builder
    resolves, and inline when it doesn't."""
    ctrl = _RecordingWalkController()
    monkeypatch.setattr(bcw, "get_controller", lambda: ctrl)
    anim_ctrl = bridge_character_anim.BridgeCharacterAnimController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: anim_ctrl)

    # ── resolvable builder: enqueue -> drain -> walk settles -> Completed() once
    ch = _move_char()
    monkeypatch.setattr(bridge_placement, "_resolve_builder_sequence",
                        lambda c, suffix: _builder_seq(c, "db_L1toP_P", "DBGuest1")
                        if suffix == "ToP1" else None)
    monkeypatch.setattr(bridge_placement, "_nif_path_for_clip",
                        lambda name: "db_L1toP_P.nif")

    act = CharacterAction(ch, CharacterAction.AT_MOVE, "P1")
    completions = []
    real_completed = act.Completed
    act.Completed = lambda: (completions.append(1), real_completed())

    act.Play()
    ch.UpdateAnimationQueue()
    assert len(ctrl.requests) == 1
    assert completions == []                          # not yet — the walk is mid-flight
    ctrl.requests[0][2]()                              # walk settles
    assert completions == [1], "zero completions hangs the sequence; two double-advance it"
    assert ch.GetLocation() == "DBGuest1"

    # ── no builder: completes inline, exactly once, no queue/walk involvement
    ch2 = _move_char()
    monkeypatch.setattr(bridge_placement, "_resolve_builder_sequence",
                        lambda c, suffix: None)
    act2 = CharacterAction(ch2, CharacterAction.AT_MOVE, "P1")
    completions2 = []
    real_completed2 = act2.Completed
    act2.Completed = lambda: (completions2.append(1), real_completed2())

    act2.Play()
    assert completions2 == [1]
    assert ctrl.requests == [ctrl.requests[0]]         # unchanged: no second walk request


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


# ── degrade paths (re-homed from the deleted tests/unit/test_capture_move.py) ──

def test_marked_walk_action_completes_inline_when_the_clip_is_unresolvable(monkeypatch):
    """TGAnimAction._do_play: a MARKED walk action whose clip resolves to no NIF
    must instant-complete -- never stall, never reach the walk controller."""
    ch = _Char()
    ctrl = _RecordingWalkController()
    monkeypatch.setattr(bcw, "get_controller", lambda: ctrl)
    monkeypatch.setattr(bridge_placement, "_nif_path_for_clip", lambda name: None)

    act = App.TGAnimAction_Create(ch.GetAnimNode(), "db_L1toP_P")
    act._walk_move = True                              # as AT_MOVE marks the walk
    act.Play()

    assert ctrl.requests == []                         # never reached the controller
    assert act.IsPlaying() is False                    # completed inline


def test_at_move_with_no_character_action_in_the_builder_completes_once(monkeypatch):
    """A builder sequence carrying NO character-node action (walk_action_of -> None)
    must still PLAY the sequence and complete exactly once."""
    ch = _move_char()
    ctrl = _RecordingWalkController()
    monkeypatch.setattr(bcw, "get_controller", lambda: ctrl)
    anim_ctrl = bridge_character_anim.BridgeCharacterAnimController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: anim_ctrl)

    def _no_character_seq(c, suffix):
        if suffix != "ToP1":
            return None
        seq = App.TGSequence_Create()
        # An object-node action only: no character clip anywhere in the builder.
        seq.AddAction(App.CharacterAction_Create(
            c, CharacterAction.AT_SET_LOCATION_NAME, "DBGuest1"))
        return seq

    monkeypatch.setattr(bridge_placement, "_resolve_builder_sequence", _no_character_seq)

    act = CharacterAction(ch, CharacterAction.AT_MOVE, "P1")
    completions = []
    real_completed = act.Completed
    act.Completed = lambda: (completions.append(1), real_completed())

    act.Play()
    assert completions == []                     # enqueued, not yet drained
    ch.UpdateAnimationQueue()                     # drain -> play_record -> seq.Play()

    assert ctrl.requests == []                    # nothing to walk
    assert ch.GetLocation() == "DBGuest1"         # the sequence still PLAYED
    assert len(completions) == 1, "zero completions hangs the sequence; two double-advance it"
    assert act.IsPlaying() is False


def test_at_move_does_not_raise_when_the_builder_raises(monkeypatch):
    ch = _move_char()
    ctrl = _RecordingWalkController()
    monkeypatch.setattr(bcw, "get_controller", lambda: ctrl)

    def _raise(character, suffix):
        raise RuntimeError("SDK builder blew up")

    monkeypatch.setattr(bridge_placement, "_resolve_builder_sequence", _raise)

    act = CharacterAction(ch, CharacterAction.AT_MOVE, "P1")
    act.Play()                                         # must not raise

    assert ctrl.requests == []
    assert act.IsPlaying() is False                    # completed inline
