"""Regression: _place_one_character must use set_instance_rest_pose (static
pose, no play-through) and must NOT call set_instance_animation."""
from engine import host_loop


class _FakeRenderer:
    def __init__(self):
        self.rest_calls = []
        self.anim_calls = []

    def assemble_officer(self, *a):
        return 1                      # ModelHandle
    def create_bridge_instance(self, model):
        return 42                     # InstanceId
    def set_world_transform(self, iid, mat):
        pass
    def set_instance_rest_pose(self, iid, clip_index, at_start=False):
        self.rest_calls.append((iid, clip_index, at_start))
    def set_instance_animation(self, iid, clip_index, loop=False, sample_at_start=False):
        self.anim_calls.append((iid, clip_index, loop, sample_at_start))


class _FakeCharacter:
    def __init__(self):
        self._render_instance = None
    def appearance(self):
        return {"body_nif": "b.nif", "head_nif": "h.nif",
                "body_tex": None, "head_tex": None}
    def GetCharacterName(self):
        return "Helm"


def test_placement_uses_rest_pose_not_playthrough(monkeypatch):
    monkeypatch.setattr(
        "engine.appc.bridge_placement.capture_placement",
        lambda c: {"clip_nif": "data/animations/db_stand_h_m.nif",
                   "hidden": False, "sample_at_start": False},
    )
    r = _FakeRenderer()
    controller = host_loop.HostController.__new__(host_loop.HostController)
    controller.officer_instances = []
    host_loop._place_one_character(controller, r, _FakeCharacter(),
                                   "bridge", is_bridge=True)

    assert r.rest_calls == [(42, 0, False)]      # static, last-frame
    assert r.anim_calls == []                    # never plays the clip through
