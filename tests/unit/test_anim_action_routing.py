# tests/unit/test_anim_action_routing.py
from engine.appc.actions import TGAnimAction_Create
from engine.appc.anim_node import TGAnimNode
import engine.bridge_cutscene as bc


class _RecordingController:
    def __init__(self):
        self.camera = []
        self.door = []

    def request_camera_path(self, action, node, clip):
        self.camera.append((action, node, clip))

    def request_object_anim(self, action, node, clip):
        self.door.append((action, node, clip))


def teardown_function(_):
    bc.clear_controller()


def test_camera_action_defers_to_controller():
    ctrl = _RecordingController()
    bc.set_controller(ctrl)
    node = TGAnimNode(kind="camera")
    action = TGAnimAction_Create(node, "WalkCameraToCaptD", 1, 0, 0, 0)
    action.Play()
    assert ctrl.camera == [(action, node, "WalkCameraToCaptD")]
    assert action.IsPlaying() is True            # deferred, not completed


def test_object_action_defers_to_controller():
    ctrl = _RecordingController()
    bc.set_controller(ctrl)
    node = TGAnimNode(kind="object")
    action = TGAnimAction_Create(node, "DB_Door_L1", 0, 0)
    action.Play()
    assert ctrl.door == [(action, node, "DB_Door_L1")]


def test_character_gesture_action_completes_instantly():
    # A _NodeStub (no .kind) or no controller -> instant complete, no defer.
    bc.clear_controller()
    node = TGAnimNode(kind="camera")
    action = TGAnimAction_Create(node, "twitch", 0, 0)
    action.Play()
    assert action.IsPlaying() is False           # completed (no controller)
