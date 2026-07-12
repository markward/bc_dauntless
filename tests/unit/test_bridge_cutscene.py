# tests/unit/test_bridge_cutscene.py
from engine.bridge_cutscene import (
    BridgeCutsceneController, get_controller, set_controller, clear_controller,
)


class _FakeAction:
    def __init__(self):
        self.completed = False

    def Completed(self):
        self.completed = True


class _FakeCamera:
    def __init__(self):
        self.pose = None
        self.cleared = False

    def set_anim_pose(self, eye, target, up):
        self.pose = (eye, target, up)

    def clear_anim_pose(self):
        self.cleared = True
        self.pose = None


class _FakeViewMode:
    def __init__(self):
        self.bridge = False

    def set_bridge(self):
        self.bridge = True


class _FakeRenderer:
    def __init__(self):
        self.anim_calls = []
        self.node_anim_calls = []
        self.node_clip_calls = []

    def load_animation_clips(self, path):
        # Two-key straight slide on +X over 1 second, identity rotation.
        return [{
            "name": "cam", "duration": 1.0,
            "tracks": [{
                "node": "cam",
                "translation": [(0.0, 0.0, 0.0, 0.0), (1.0, 10.0, 0.0, 0.0)],
                "rotation": [(0.0, 0.0, 0.0, 0.0, 1.0),
                             (1.0, 0.0, 0.0, 0.0, 1.0)],
            }],
        }]

    def set_instance_animation(self, iid, clip_index, loop=False):
        self.anim_calls.append((iid, clip_index, loop))

    def play_instance_node_anim(self, iid, clip_index, loop=False, reverse=False):
        self.node_anim_calls.append((iid, clip_index, loop, reverse))

    def play_instance_node_clip(self, iid, path, loop, reverse):
        self.node_clip_calls.append((iid, path, loop, reverse))


class _FakeAnimMgr:
    def __init__(self, paths=None):
        self._paths = paths or {
            "WalkCameraToCaptD": "data/animations/db_camera_walk_capt.nif",
            "DB_Door_L1": "data/animations/db_door_l1.nif",
        }

    def path_for(self, name):
        return self._paths.get(str(name), "data/animations/db_camera_walk_capt.nif")


class _Owner:
    def __init__(self):
        self.render_instance = 77


class _FakeNode:
    def __init__(self, kind, owner=None):
        self.kind = kind
        self.owner = owner


def _ctx(cam, vm, rend, mgr):
    return dict(bridge_camera=cam, view_mode=vm, renderer=rend, anim_mgr=mgr)


def test_camera_path_drives_pose_and_completes_at_duration():
    ctrl = BridgeCutsceneController()
    action = _FakeAction()
    ctrl.request_camera_path(action, _FakeNode("camera"), "WalkCameraToCaptD")

    cam, vm, rend, mgr = _FakeCamera(), _FakeViewMode(), _FakeRenderer(), _FakeAnimMgr()
    # First update loads the clip, flips to bridge, samples t=0.
    ctrl.update(0.0, **_ctx(cam, vm, rend, mgr))
    assert vm.bridge is True
    assert cam.pose is not None
    eye0 = cam.pose[0]
    assert eye0 == (0.0, 0.0, 0.0)

    # Halfway: eye should be at +5 on X.
    ctrl.update(0.5, **_ctx(cam, vm, rend, mgr))
    assert abs(cam.pose[0][0] - 5.0) < 1e-6
    assert action.completed is False

    # Reaching duration completes the action and clears the pose.
    ctrl.update(0.5, **_ctx(cam, vm, rend, mgr))
    assert action.completed is True
    assert cam.cleared is True


def test_object_anim_plays_the_named_door_clip():
    """Doors are drained by _update_doors directly -- the view-independent
    half of the pump (see host_loop._pump_bridge_doors) -- NOT by update()
    (the view-gated camera half)."""
    ctrl = BridgeCutsceneController()
    action = _FakeAction()
    node = _FakeNode("object", owner=_Owner())
    ctrl.request_object_anim(action, node, "DB_Door_L1")

    rend, mgr = _FakeRenderer(), _FakeAnimMgr()
    ctrl._update_doors(rend, mgr)
    # Plays ONLY the named door's own external keyframe NIF (resolved through
    # AnimationManager) on the owner's render instance -- never the bridge
    # model's embedded all-doors clip.
    assert rend.node_clip_calls == [
        (77, "data/animations/db_door_l1.nif", False, False)]
    assert rend.node_anim_calls == []
    assert action.completed is True       # door is fire-and-forget


def test_object_anim_waits_for_render_instance():
    ctrl = BridgeCutsceneController()
    action = _FakeAction()
    owner = _Owner()
    owner.render_instance = None          # not realized yet
    node = _FakeNode("object", owner=owner)
    ctrl.request_object_anim(action, node, "DB_Door_L1")

    rend, mgr = _FakeRenderer(), _FakeAnimMgr()
    ctrl._update_doors(rend, mgr)
    assert rend.node_clip_calls == []     # deferred
    owner.render_instance = 99
    ctrl._update_doors(rend, mgr)
    assert rend.node_clip_calls == [
        (99, "data/animations/db_door_l1.nif", False, False)]


def test_has_pending_camera_flag():
    ctrl = BridgeCutsceneController()
    assert ctrl.has_pending_camera() is False
    ctrl.request_camera_path(_FakeAction(), _FakeNode("camera"), "X")
    assert ctrl.has_pending_camera() is True        # pending branch
    ctrl._pending_camera = None
    ctrl._active_camera = object()                  # simulate in-flight playback
    assert ctrl.has_pending_camera() is True        # active branch
    ctrl._active_camera = None
    assert ctrl.has_pending_camera() is False


def test_module_level_registry():
    clear_controller()
    assert get_controller() is None
    ctrl = BridgeCutsceneController()
    set_controller(ctrl)
    assert get_controller() is ctrl
    clear_controller()
    assert get_controller() is None
