"""End-to-end (headless): CharacterAction AT_MOVE -> walk controller -> settle,
for BOTH a standing walk-on (P1) and a seated sit-down (P), proving they are one
primitive differing only by clip + end-location."""
import App
from engine.appc.ai import CharacterAction
from engine.appc import bridge_placement
from engine.appc.anim_node import TGAnimNode
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


class _Char:
    def __init__(self):
        self._character_name = "Picard"
        self._render_instance = None
        self._location = "DBL1M"
        self._hidden = 1
        self._node = TGAnimNode(owner=self, kind="character")
    def GetCharacterName(self): return self._character_name
    def GetAnimNode(self): return self._node
    def SetHidden(self, h): self._hidden = 1 if h else 0
    def IsHidden(self): return self._hidden
    def SetLocation(self, loc): self._location = loc
    def GetLocation(self): return self._location


def _builder_seq(ch, clip, end_location):
    """Stands in for the SDK move builder (PicardAnimations.MoveFromL1ToP1 /
    MoveFromP1ToP): the walk clip on the character's anim node, then the trailing
    AT_SET_LOCATION_NAME that re-stations the officer once the walk settles."""
    seq = App.TGSequence_Create()
    seq.AddAction(App.TGAnimAction_Create(ch.GetAnimNode(), clip))
    seq.AppendAction(App.CharacterAction_Create(
        ch, CharacterAction.AT_SET_LOCATION_NAME, end_location))
    return seq


def _run_move(monkeypatch, detail, clip, end_location):
    ch = _Char()
    walk = BridgeCharacterWalkController(
        realize_fn=lambda c: setattr(c, "_render_instance", 777)
        or c._render_instance)
    monkeypatch.setattr(bcw, "get_controller", lambda: walk)
    monkeypatch.setattr(bcw, "capture_breathing", lambda c: None)
    monkeypatch.setattr(bridge_placement, "_resolve_builder_sequence",
                        lambda c, suffix: _builder_seq(c, clip, end_location)
                        if suffix == "To" + detail else None)
    monkeypatch.setattr(bridge_placement, "_nif_path_for_clip", lambda name: clip)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)
    r = _FakeRenderer()

    act = CharacterAction(ch, CharacterAction.AT_MOVE, detail)
    act.Play()
    assert act.IsPlaying() is True
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
