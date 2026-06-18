# engine/bridge_cutscene.py
"""BridgeCutsceneController — the seam between the headless SDK action layer
and the host/renderer for bridge animation cutscenes.

A camera TGAnimAction queues a camera-path request here and defers its own
completion; each host tick update() loads the clip (native), samples it, and
drives _BridgeCamera, completing the action when the clip ends so the SDK
sequence proceeds (firing ET_CAMERA_ANIMATION_DONE). A door TGAnimAction
queues an object request, which plays the bridge model's embedded clip 0
(the door keyframes baked into DBridge.nif) via set_instance_animation.

See docs/superpowers/specs/2026-06-17-bridge-camera-walkon-cutscene-design.md.
"""
from engine.anim_sample import sample_translation, sample_rotation, quat_rotate

# Camera node local basis the keyframe rotation orients. Derived from the
# db_camera_walk_capt.nif "Camera01" track: its rotation maps local +X to the
# view direction and local +Y to up. Verified against the path's final keyframe,
# which lands on the captain's-chair eye with forward = world -Y (into the
# bridge / toward the viewscreen) and up = world +Z — i.e. exactly the pose the
# normal _BridgeCamera holds after the cutscene, so the handoff is seamless.
LOCAL_FORWARD = (1.0, 0.0, 0.0)
LOCAL_UP = (0.0, 1.0, 0.0)


class BridgeCutsceneController:
    def __init__(self):
        # Pending camera request: (action, clip_name) before the clip loads.
        self._pending_camera = None
        # Active camera playback: dict(action, track, duration, t).
        self._active_camera = None
        # Pending door requests: list of (action, owner).
        self._pending_doors = []

    # ── requests (called from TGAnimAction._do_play, headless) ───────────
    def request_camera_path(self, action, anim_node, clip_name):
        self._pending_camera = (action, str(clip_name))

    def request_object_anim(self, action, anim_node, clip_name):
        self._pending_doors.append((action, getattr(anim_node, "owner", None)))

    def has_pending_camera(self):
        """True when a camera path is queued or actively playing."""
        return self._pending_camera is not None or self._active_camera is not None

    def reset(self):
        """Clear all pending/active state (called on mission swap so a stale
        cutscene from the prior mission cannot leak into the next)."""
        self._pending_camera = None
        self._active_camera = None
        self._pending_doors = []

    # ── per-tick host pump ───────────────────────────────────────────────
    def update(self, dt, *, bridge_camera, view_mode, renderer, anim_mgr):
        self._update_doors(renderer)
        self._update_camera(dt, bridge_camera, view_mode, renderer, anim_mgr)

    def _update_doors(self, renderer):
        still_pending = []
        for action, owner in self._pending_doors:
            iid = getattr(owner, "render_instance", None)
            if iid is None:
                still_pending.append((action, owner))   # wait for realize
                continue
            # The door keyframes are baked into the bridge model's clip 0.
            renderer.set_instance_animation(iid, 0, False)
            action.Completed()                            # fire-and-forget
        self._pending_doors = still_pending

    def _update_camera(self, dt, bridge_camera, view_mode, renderer, anim_mgr):
        if self._active_camera is None and self._pending_camera is not None:
            action, clip_name = self._pending_camera
            path = anim_mgr.path_for(clip_name)
            track = self._load_camera_track(renderer, path)
            if track is None:
                # Nothing to play (missing clip / no motion): complete now so
                # the SDK sequence is not stuck waiting on this action.
                self._pending_camera = None
                action.Completed()
                return
            self._pending_camera = None
            view_mode.set_bridge()
            duration = max(track["translation"][-1][0],
                           track["rotation"][-1][0] if track["rotation"] else 0.0)
            self._active_camera = dict(action=action, track=track,
                                       duration=duration, t=0.0)

        if self._active_camera is None:
            return

        ac = self._active_camera
        ac["t"] += dt
        t = min(ac["t"], ac["duration"])
        track = ac["track"]
        eye = sample_translation(track["translation"], t)
        q = sample_rotation(track["rotation"], t) if track["rotation"] else (0.0, 0.0, 0.0, 1.0)
        fwd = quat_rotate(q, LOCAL_FORWARD)
        up = quat_rotate(q, LOCAL_UP)
        target = (eye[0] + fwd[0], eye[1] + fwd[1], eye[2] + fwd[2])
        bridge_camera.set_anim_pose(eye, target, up)

        if ac["t"] >= ac["duration"]:
            bridge_camera.clear_anim_pose()
            ac["action"].Completed()
            self._active_camera = None

    @staticmethod
    def _load_camera_track(renderer, path):
        if not path:
            return None
        clips = renderer.load_animation_clips(path)
        if not clips:
            return None
        # The moving camera node: the track with translation keys (prefer the
        # one with the most, in case the NIF has multiple animated nodes).
        moving = [t for t in clips[0]["tracks"] if t["translation"]]
        if not moving:
            return None
        return max(moving, key=lambda t: len(t["translation"]))


# ── module-level registry (host sets one; actions look it up) ────────────
_controller = None


def get_controller():
    return _controller


def set_controller(ctrl):
    global _controller
    _controller = ctrl


def clear_controller():
    global _controller
    _controller = None
