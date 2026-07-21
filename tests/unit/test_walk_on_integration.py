"""End-to-end (headless): CharacterAction AT_MOVE -> walk controller -> settle,
for BOTH a standing walk-on (P1) and a seated sit-down (P), proving they are one
primitive differing only by clip + end-location."""
import App
from engine.appc.ai import CharacterAction
from engine.appc import bridge_placement
from engine.appc.anim_node import TGAnimNode
from engine.appc.characters import CharacterClass
from engine import bridge_character_anim
import engine.bridge_character_walk as bcw
from engine.bridge_character_walk import BridgeCharacterWalkController


class _FakeRenderer:
    def __init__(self):
        self._next = 100
        self.loaded = {}
        self.walked = []
        self.rest_poses = []
        self.idled = []
    def load_instance_clip(self, iid, path):
        self.loaded.setdefault((iid, path), len(self.loaded) + 200)
        return self.loaded[(iid, path)]
    def play_instance_walk(self, iid, ci):
        self.walked.append((iid, ci))
    def set_instance_rest_pose(self, iid, ci, at_start):
        self.rest_poses.append((iid, ci, at_start))
    def play_instance_idle(self, iid, ci):
        self.idled.append((iid, ci))
    def load_animation_clips(self, path):
        return [{"duration": 1.0}]
    def idle_clip_paths(self):
        rev = {idx: path for (_iid, path), idx in self.loaded.items()}
        return [rev.get(ci) for _iid, ci in self.idled]


def _Char(location="DBL1M"):
    """A REAL CharacterClass -- AT_MOVE now routes through CharacterClass.MoveTo
    (the queue/referee/SetFlags/SetCurrentAnimation door), so these tests need
    the genuine receiver, not a lightweight double."""
    ch = CharacterClass()
    ch.SetCharacterName("Picard")
    ch._render_instance = None
    ch.SetLocation(location)
    ch.SetHidden(1)
    return ch


def _builder_seq(ch, clip, end_location):
    """Stands in for the SDK move builder (PicardAnimations.MoveFromL1ToP1 /
    MoveFromP1ToP): the walk clip on the character's anim node, then the trailing
    AT_SET_LOCATION_NAME that re-stations the officer once the walk settles."""
    seq = App.TGSequence_Create()
    seq.AddAction(App.TGAnimAction_Create(ch.GetAnimNode(), clip))
    seq.AppendAction(App.CharacterAction_Create(
        ch, CharacterAction.AT_SET_LOCATION_NAME, end_location))
    return seq


def _run_move(monkeypatch, detail, clip, end_location, *,
              origin="DBL1M", breathing=lambda c: None):
    ch = _Char(location=origin)
    walk = BridgeCharacterWalkController(
        realize_fn=lambda c: setattr(c, "_render_instance", 777)
        or c._render_instance)
    monkeypatch.setattr(bcw, "get_controller", lambda: walk)
    monkeypatch.setattr(bcw, "capture_breathing", breathing)
    monkeypatch.setattr(bridge_placement, "_resolve_builder_sequence",
                        lambda c, suffix: _builder_seq(c, clip, end_location)
                        if suffix == "To" + detail else None)
    monkeypatch.setattr(bridge_placement, "_nif_path_for_clip", lambda name: clip)
    anim_ctrl = bridge_character_anim.BridgeCharacterAnimController()
    monkeypatch.setattr(bridge_character_anim, "get_controller", lambda: anim_ctrl)
    r = _FakeRenderer()

    act = CharacterAction(ch, CharacterAction.AT_MOVE, detail)
    act.Play()
    assert act.IsPlaying() is True
    ch.UpdateAnimationQueue()             # drain the queue -> play_record -> seq.Play()
    walk.update(0.0, renderer=r)          # realize + reveal + walk
    assert ch.IsHidden() == 0
    assert r.walked and r.walked[0][0] == 777
    walk.update(2.0, renderer=r)          # settle (dur 1.0)
    assert ch.GetLocation() == end_location
    assert act.IsPlaying() is False       # completion propagated to the action
    return r


def test_standing_walk_on(monkeypatch):
    r = _run_move(monkeypatch, "P1", "db_L1toP_P.nif", "DBGuest1")
    assert any(rp[2] is False for rp in r.rest_poses)   # frozen at last frame


def test_seated_sit_down(monkeypatch):
    # Same primitive: only clip + end-location differ (MoveFromP1ToP -> db_sit_P).
    r = _run_move(monkeypatch, "P", "db_sit_P.nif", "DBGuest")
    assert any(rp[2] is False for rp in r.rest_poses)


# ── the post-move idle must resolve against the DESTINATION location ──────────
#
# capture_breathing resolves the officer's looping idle from the SDK's registered
# "<GetLocation()>Breathe" builder. AT_MOVE no longer passes an engine-side
# end_location (the builder's own trailing AT_SET_LOCATION_NAME is the SDK's
# mechanism), and in the real builders that action chains onto the WALK step --
# so it only runs when the walk action Completes. If the walk controller resolves
# breathing BEFORE it fires that completion, it resolves against the ORIGIN.

_BREATHE_BY_LOCATION = {
    "DBGuest1": "db_breathe_standing_P.nif",   # standing at the guest-1 mark
    "DBGuest":  "db_breathe_seated_P.nif",     # seated in the guest chair
    "DBGuestT": "db_breathe_tactical_P.nif",
    # NB: no "DBGuestH" entry -- MoveFromHToT's ORIGIN has no registered
    # <origin>Breathe builder in the SDK either.
}


def _breathe_for_location(character):
    """The real capture_breathing shape: resolves against GetLocation() NOW."""
    nif = _BREATHE_BY_LOCATION.get(character.GetLocation())
    return {"clip_nif": nif} if nif else None


def test_seated_idle_resolves_against_the_destination_not_the_origin(monkeypatch):
    """MoveFromP1ToP: standing at DBGuest1 -> seated at DBGuest. The officer must
    get the SEATED breathe loop. Resolving against the stale origin gives a seated
    officer the STANDING idle."""
    r = _run_move(monkeypatch, "P", "db_sit_P.nif", "DBGuest",
                  origin="DBGuest1", breathing=_breathe_for_location)
    assert r.idle_clip_paths() == ["db_breathe_seated_P.nif"], \
        "the idle must be resolved against the destination location (DBGuest)"


def test_idle_still_applies_when_only_the_destination_has_a_breathe_clip(monkeypatch):
    """MoveFromHToT: the ORIGIN (DBGuestH) has no registered <origin>Breathe, the
    DESTINATION (DBGuestT) does. Resolving against the origin returns None and the
    officer ends up with NO idle at all."""
    r = _run_move(monkeypatch, "T", "DB_HtoT_P.nif", "DBGuestT",
                  origin="DBGuestH", breathing=_breathe_for_location)
    assert r.idle_clip_paths() == ["db_breathe_tactical_P.nif"], \
        "an officer whose origin has no Breathe entry must still get the destination idle"
