from engine.appc import bridge_placement as bp


class _AnimNode:
    def __init__(self, kind):
        self.kind = kind


class _Action:
    def __init__(self, kind, clip):
        self._anim_node = _AnimNode(kind)
        self._clip = clip


class _Seq:
    def __init__(self, actions):
        self._actions = actions
    def GetNumActions(self):
        return len(self._actions)
    def GetAction(self, i):
        return self._actions[i]


def test_capture_chair_clip_returns_object_action(monkeypatch):
    # Builder produces a body (character) clip AND a chair (object) clip.
    seq = _Seq([_Action("character", "db_face_capt_h"),
                _Action("object", "db_chair_H_face_capt")])
    monkeypatch.setattr(bp, "_resolve_builder_sequence",
                        lambda character, suffix: seq)
    monkeypatch.setattr(bp, "_nif_path_for_clip",
                        lambda name: f"data/animations/{name}.nif")
    out = bp.capture_chair_clip(object(), "TurnCaptain")
    assert out == {"clip_nif": "data/animations/db_chair_H_face_capt.nif"}


def test_capture_chair_clip_none_when_no_object_action(monkeypatch):
    seq = _Seq([_Action("character", "db_face_capt_h")])
    monkeypatch.setattr(bp, "_resolve_builder_sequence",
                        lambda character, suffix: seq)
    monkeypatch.setattr(bp, "_nif_path_for_clip",
                        lambda name: f"data/animations/{name}.nif")
    assert bp.capture_chair_clip(object(), "TurnCaptain") is None
