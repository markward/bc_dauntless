"""Lift doors play the NAMED door clip, not the bridge's all-doors clip.

BC registers each door as its own external keyframe NIF (GalaxyBridge:
kAM.LoadAnimation("data/animations/db_door_l1.nif", "doorl1")) and each clip
drives exactly ONE door pair, opening and closing itself over 1s.

The bridge model's own embedded clip animates EVERY door (and, on EBridge, both
commander chairs), so playing it for a single lift cue is wrong.
"""
from engine.bridge_cutscene import BridgeCutsceneController


class _FakeAnimMgr:
    def __init__(self, paths):
        self._paths = paths

    def path_for(self, name):
        return self._paths.get(str(name))


class _RecordingRenderer:
    def __init__(self):
        self.node_clips = []      # (iid, path, loop, reverse)
        self.node_anims = []      # (iid, clip_index) — the WRONG path

    def play_instance_node_clip(self, iid, path, loop, reverse):
        self.node_clips.append((iid, path, loop, reverse))

    def play_instance_node_anim(self, iid, clip_index, loop=False, reverse=False):
        self.node_anims.append((iid, clip_index))


class _FakeAction:
    def __init__(self):
        self.completed = 0

    def Completed(self):
        self.completed += 1


class _FakeNode:
    def __init__(self, owner):
        self.owner = owner
        self.kind = "object"


class _FakeBridge:
    render_instance = 42


def _ctrl():
    return BridgeCutsceneController(asset_resolver=lambda rel: "/game/" + rel)


def test_named_door_clip_is_played_and_the_all_doors_clip_is_not():
    ctrl, r = _ctrl(), _RecordingRenderer()
    anim = _FakeAnimMgr({"doorl1": "data/animations/db_door_l1.nif"})
    act = _FakeAction()
    ctrl.request_object_anim(act, _FakeNode(_FakeBridge()), "doorl1")

    ctrl._update_doors(r, anim)

    assert r.node_clips == [(42, "/game/data/animations/db_door_l1.nif", False, False)]
    assert r.node_anims == [], "the bridge's embedded all-doors clip must never be played"
    assert act.completed == 1, "LiftDoorAction is fire-and-forget: complete exactly once"


def test_the_door_name_selects_the_clip():
    """L2 must open L2's door, not L1's."""
    ctrl, r = _ctrl(), _RecordingRenderer()
    anim = _FakeAnimMgr({"doorl1": "data/animations/db_door_l1.nif",
                         "EB_Door_L2": "data/animations/EB_door_L2.nif"})
    ctrl.request_object_anim(_FakeAction(), _FakeNode(_FakeBridge()), "EB_Door_L2")
    ctrl._update_doors(r, anim)
    assert r.node_clips[0][1] == "/game/data/animations/EB_door_L2.nif"


def test_unresolvable_door_name_completes_and_plays_nothing():
    """Never stall a mission TGSequence on a door we cannot resolve."""
    ctrl, r = _ctrl(), _RecordingRenderer()
    act = _FakeAction()
    ctrl.request_object_anim(act, _FakeNode(_FakeBridge()), "NoSuchDoor")
    ctrl._update_doors(r, _FakeAnimMgr({}))
    assert r.node_clips == [] and r.node_anims == []
    assert act.completed == 1


def test_door_waits_for_the_bridge_instance_to_be_realized():
    """No render instance yet -> stay pending, do not complete, do not play."""
    class _Unrealized:
        render_instance = None

    ctrl, r = _ctrl(), _RecordingRenderer()
    anim = _FakeAnimMgr({"doorl1": "data/animations/db_door_l1.nif"})
    act = _FakeAction()
    ctrl.request_object_anim(act, _FakeNode(_Unrealized()), "doorl1")
    ctrl._update_doors(r, anim)
    assert r.node_clips == [] and act.completed == 0
