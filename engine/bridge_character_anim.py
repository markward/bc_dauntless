# engine/bridge_character_anim.py
"""BridgeCharacterAnimController — per-character transient animation runner.

The officer's placement is a STATIC rest pose (set_instance_rest_pose). Idle
gestures and hit reactions are transient SDK TGSequences played over it: each
is a list of (nif_path, duration) clips played in order; when the last clip
ends the controller issues restore_rest_pose (the SDK's AT_DEFAULT). Reactions
(priority 1) preempt idle (priority 0); a lower-or-equal priority submission for
a busy character is dropped. Mirrors engine/bridge_cutscene.py.
"""

_IDLE = 0
_REACTION = 1

# Floor for a clip with no SDK duration AND no resolvable natural length (e.g.
# a single-frame pose clip whose duration parses as 0). Keeps it on screen
# briefly instead of restoring the rest pose on the very next tick.
_MIN_GESTURE_HOLD_S = 0.4


class _Action:
    __slots__ = ("iid", "clips", "priority", "index", "elapsed", "started",
                 "cur_duration")

    def __init__(self, iid, clips, priority):
        self.iid = iid
        self.clips = clips          # [(nif_path, sdk_duration), ...]
        self.priority = priority
        self.index = -1             # current clip; -1 = not yet started
        self.elapsed = 0.0
        self.started = False
        self.cur_duration = 0.0     # effective hold for the current clip


class BridgeCharacterAnimController:
    def __init__(self):
        self._active = {}           # iid -> _Action
        self._dur_cache = {}        # nif_path -> real clip duration (s)

    def is_busy(self, character) -> bool:
        iid = getattr(character, "_render_instance", None)
        return iid in self._active

    def submit(self, character, clips, priority) -> None:
        iid = getattr(character, "_render_instance", None)
        if iid is None or not clips:
            return
        if character.IsHidden():
            return
        cur = self._active.get(iid)
        if cur is not None and priority <= cur.priority:
            return                  # don't preempt equal/higher priority
        self._active[iid] = _Action(iid, list(clips), priority)

    def reset(self) -> None:
        self._active = {}

    def update(self, dt, *, renderer, anim_mgr=None) -> None:
        done = []
        for iid, act in self._active.items():
            if not act.started or act.index < 0:
                self._start_clip(renderer, act, 0)
                continue
            act.elapsed += dt
            if act.elapsed < act.cur_duration:
                continue
            nxt = act.index + 1
            if nxt < len(act.clips):
                self._start_clip(renderer, act, nxt)
            else:
                if hasattr(renderer, "restore_rest_pose"):
                    renderer.restore_rest_pose(iid)
                done.append(iid)
        for iid in done:
            self._active.pop(iid, None)

    def _start_clip(self, renderer, act, index) -> None:
        path, sdk_dur = act.clips[index]
        act.index = index
        act.elapsed = 0.0
        act.started = True
        # Effective hold: the SDK's explicit SetDuration when it gave one (>0),
        # otherwise the clip's natural length so the gesture plays fully. Only
        # the no-SDK-duration path is floored, so explicit short SDK durations
        # are honored verbatim.
        if sdk_dur and sdk_dur > 0:
            act.cur_duration = sdk_dur
        else:
            real = self._real_duration(renderer, path)
            act.cur_duration = real if real > 0 else _MIN_GESTURE_HOLD_S
        if not hasattr(renderer, "play_instance_gesture"):
            return
        clip_index = renderer.load_instance_clip(act.iid, path)
        if clip_index is not None and clip_index >= 0:
            renderer.play_instance_gesture(act.iid, clip_index)

    def _real_duration(self, renderer, path) -> float:
        """The clip's natural length (seconds), cached per path. 0.0 when the
        renderer can't report it (e.g. headless FakeRenderer)."""
        if path in self._dur_cache:
            return self._dur_cache[path]
        dur = 0.0
        if hasattr(renderer, "load_animation_clips"):
            try:
                clips = renderer.load_animation_clips(path)
                if clips:
                    dur = float(clips[0].get("duration", 0.0) or 0.0)
            except Exception:
                dur = 0.0
        self._dur_cache[path] = dur
        return dur


_controller = None


def get_controller():
    return _controller


def set_controller(ctrl) -> None:
    global _controller
    _controller = ctrl


def clear_controller() -> None:
    global _controller
    _controller = None
