# engine/bridge_cutscene.py
"""BridgeCutsceneController — the seam between the headless SDK action layer
and the host/renderer for bridge animation cutscenes.

A camera TGAnimAction queues a camera-path request here and defers its own
completion; each host tick update() loads the clip (native), samples it, and
drives _BridgeCamera, completing the action when the clip ends so the SDK
sequence proceeds (firing ET_CAMERA_ANIMATION_DONE). A door TGAnimAction
queues an object request naming its door clip (e.g. "doorl1"); each host
tick resolves that name through AnimationManager.path_for(...) and plays
ONLY that door's own external keyframe NIF via play_instance_node_clip
(fire-and-forget: LiftDoorAction returns 0, so the request completes the
instant the clip is queued).

See docs/superpowers/specs/2026-06-17-bridge-camera-walkon-cutscene-design.md.
"""
import logging

from engine.anim_sample import sample_translation, sample_rotation, quat_rotate

_logger = logging.getLogger(__name__)

# Camera node local basis the keyframe rotation orients. Derived from the
# db_camera_walk_capt.nif "Camera01" track: its rotation maps local +X to the
# view direction and local +Y to up. Verified against the path's final keyframe,
# which lands on the captain's-chair eye with forward = world -Y (into the
# bridge / toward the viewscreen) and up = world +Z — i.e. exactly the pose the
# normal _BridgeCamera holds after the cutscene, so the handoff is seamless.
LOCAL_FORWARD = (1.0, 0.0, 0.0)
LOCAL_UP = (0.0, 1.0, 0.0)


class BridgeCutsceneController:
    def __init__(self, asset_resolver=None):
        # Pending camera request: (action, clip_name) before the clip loads.
        self._pending_camera = None
        # Active camera playback: dict(action, track, duration, t).
        self._active_camera = None
        # Pending door requests: list of (action, owner, clip_name).
        self._pending_doors = []
        self._resolve = asset_resolver or (lambda p: p)

    # ── requests (called from TGAnimAction._do_play, headless) ───────────
    def request_camera_path(self, action, anim_node, clip_name):
        self._pending_camera = (action, str(clip_name))

    def request_object_anim(self, action, anim_node, clip_name):
        self._pending_doors.append(
            (action, getattr(anim_node, "owner", None), str(clip_name)))

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
        """The CAMERA half of the per-tick pump. View-gated in the host loop
        (it drives the bridge first-person camera, so it only makes sense
        while that view is showing). The DOOR half is drained separately and
        view-independently — see _update_doors and host_loop._pump_bridge_doors."""
        self._update_camera(dt, bridge_camera, view_mode, renderer, anim_mgr)

    def _update_doors(self, renderer, anim_mgr):
        still_pending = []
        for action, owner, clip_name in self._pending_doors:
            iid = getattr(owner, "render_instance", None)
            if iid is None:
                still_pending.append((action, owner, clip_name))   # wait for realize
                continue
            # BC's doors are NAMED external keyframe NIFs registered on the
            # AnimationManager (GalaxyBridge.PreloadAnimations: "doorl1" ->
            # db_door_l1.nif). Each clip drives exactly ONE door pair and opens
            # and closes itself over 1s -- which is why no LiftDoorAction call
            # site in the SDK ever passes the optional close clip.
            #
            # NOT the bridge model's embedded clip: that one animates all six
            # door pairs at once (and, on EBridge, both commander chairs).
            path = anim_mgr.path_for(clip_name) if anim_mgr is not None else None
            if path:
                try:
                    renderer.play_instance_node_clip(
                        iid, self._resolve(path), False, False)
                except Exception:
                    _logger.debug("door play failed: %r", clip_name, exc_info=True)
            else:
                _logger.warning("door clip %r not registered", clip_name)
            action.Completed()      # fire-and-forget: LiftDoorAction returns 0
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
