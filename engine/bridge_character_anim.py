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


class _Action:
    __slots__ = ("iid", "clips", "priority", "index", "elapsed", "started")

    def __init__(self, iid, clips, priority):
        self.iid = iid
        self.clips = clips          # [(nif_path, duration), ...]
        self.priority = priority
        self.index = -1             # current clip; -1 = not yet started
        self.elapsed = 0.0
        self.started = False


class BridgeCharacterAnimController:
    def __init__(self):
        self._active = {}           # iid -> _Action

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
            _, dur = act.clips[act.index]
            if act.elapsed < dur:
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

    @staticmethod
    def _start_clip(renderer, act, index) -> None:
        path, _dur = act.clips[index]
        act.index = index
        act.elapsed = 0.0
        act.started = True
        if not hasattr(renderer, "load_instance_clip"):
            return
        clip_index = renderer.load_instance_clip(act.iid, path)
        if clip_index is not None and clip_index >= 0:
            renderer.set_instance_animation(act.iid, clip_index, False)


_controller = None


def get_controller():
    return _controller


def set_controller(ctrl) -> None:
    global _controller
    _controller = ctrl


def clear_controller() -> None:
    global _controller
    _controller = None
