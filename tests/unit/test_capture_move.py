from engine.appc import bridge_placement


class _AnimNode:
    def __init__(self, kind):
        self.kind = kind


class _AnimAction:
    """Stands in for a TGAnimAction: has an anim node + clip name."""
    def __init__(self, kind, clip):
        self._anim_node = _AnimNode(kind)
        self._clip = clip


class _CharAction:
    """Stands in for a CharacterAction inside the builder sequence."""
    def __init__(self, action_type, detail):
        self._action_type = action_type
        self._detail = detail


class _Seq:
    def __init__(self, actions):
        self._actions = actions
    def GetNumActions(self):
        return len(self._actions)
    def GetAction(self, i):
        return self._actions[i]


AT_SET_LOCATION_NAME = 1   # CharacterAction.AT_SET_LOCATION_NAME


def test_capture_move_extracts_walk_clip_and_end_location(monkeypatch):
    # Builder returns: [walk TGAnimAction on the character, trailing set-location].
    seq = _Seq([
        _AnimAction("character", "db_L1toP_P"),
        _CharAction(AT_SET_LOCATION_NAME, "DBGuest1"),
    ])
    monkeypatch.setattr(bridge_placement, "_resolve_builder_sequence",
                        lambda ch, suffix: seq if suffix == "ToP1" else None)
    monkeypatch.setattr(bridge_placement, "_nif_path_for_clip",
                        lambda name: "data/animations/db_L1toP_P.nif"
                        if name == "db_L1toP_P" else None)

    got = bridge_placement.capture_move(character=object(), detail="P1")
    assert got == {"clip_nif": "data/animations/db_L1toP_P.nif",
                   "end_location": "DBGuest1"}


def test_capture_move_none_when_no_builder(monkeypatch):
    monkeypatch.setattr(bridge_placement, "_resolve_builder_sequence",
                        lambda ch, suffix: None)
    assert bridge_placement.capture_move(character=object(), detail="P1") is None


def test_capture_move_none_when_clip_unresolvable(monkeypatch):
    seq = _Seq([_AnimAction("character", "missing_clip")])
    monkeypatch.setattr(bridge_placement, "_resolve_builder_sequence",
                        lambda ch, suffix: seq)
    monkeypatch.setattr(bridge_placement, "_nif_path_for_clip", lambda name: None)
    assert bridge_placement.capture_move(character=object(), detail="P1") is None
