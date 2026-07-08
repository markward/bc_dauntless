# engine/bridge_character_walk.py
"""BridgeCharacterWalkController — the CharacterAction AT_MOVE walk lifecycle.

A walk-on (E1M1 Picard/Saffi entering from the turbolift) is a hidden bridge
character being realized, revealed, and moved to a station via a root-motion
clip. This controller owns that one-shot lifecycle; it is kept separate from the
transient gesture/turn runner (bridge_character_anim) because its completion
signalling and root-motion playback differ.

Seam (mirrors bridge_character_anim / bridge_cutscene): CharacterAction.Play
QUEUES a request headlessly; update() — which has the renderer — drains it.
Completion is DEFERRED: on_complete (the action's Completed()) fires when the
walk clip settles, so the mission TGSequence advances exactly when the walk ends.
"""

from engine.appc.bridge_placement import capture_breathing

# Floor duration for a walk clip whose length the renderer can't report (headless
# FakeRenderer without load_animation_clips): completes on the next update.
_MIN_WALK_S = 0.0


class _Move:
    __slots__ = ("character", "clip_nif", "iid", "clip_index", "end_location",
                 "on_complete", "elapsed", "duration")

    def __init__(self, character, clip_nif, end_location, on_complete):
        self.character = character
        self.clip_nif = clip_nif
        self.end_location = end_location
        self.on_complete = on_complete
        self.iid = None
        self.clip_index = -1
        self.elapsed = 0.0
        self.duration = 0.0


class BridgeCharacterWalkController:
    def __init__(self, realize_fn=None, asset_resolver=None):
        self._pending = []          # [_Move] not yet started
        self._active = {}           # iid -> _Move
        self._realize = realize_fn or (lambda character: None)
        self._resolve = asset_resolver or (lambda p: p)

    def is_moving(self, character) -> bool:
        iid = getattr(character, "_render_instance", None)
        return iid is not None and iid in self._active

    def request_move(self, character, clip_nif, end_location, on_complete) -> None:
        self._pending.append(
            _Move(character, clip_nif, end_location, on_complete))

    def reset(self) -> None:
        self._pending = []
        self._active = {}

    def update(self, dt, *, renderer) -> None:
        if self._pending:
            pending, self._pending = self._pending, []
            for mv in pending:
                self._start(renderer, mv)
        if not self._active:
            return
        done = []
        for iid, mv in self._active.items():
            mv.elapsed += dt
            if mv.elapsed >= mv.duration:
                self._settle(renderer, mv)
                done.append(iid)
        for iid in done:
            self._active.pop(iid, None)

    def _complete(self, mv) -> None:
        cb = mv.on_complete
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def _start(self, renderer, mv) -> None:
        character = mv.character
        iid = getattr(character, "_render_instance", None)
        if iid is None:
            iid = self._realize(character)      # lazy build for hidden walk target
        if iid is None:
            self._complete(mv)                  # can't render -> don't stall sequence
            return
        try:
            character.SetHidden(0)              # reveal
            path = self._resolve(mv.clip_nif)
            clip_index = renderer.load_instance_clip(iid, path)
            if clip_index is None or clip_index < 0:
                self._complete(mv)
                return
            renderer.play_instance_walk(iid, clip_index)
        except Exception:
            self._complete(mv)
            return
        mv.iid = iid
        mv.clip_index = clip_index
        mv.elapsed = 0.0
        mv.duration = self._real_duration(renderer, path)
        self._active[iid] = mv

    def _settle(self, renderer, mv) -> None:
        """Walk finished: re-station the character (rest pose = walk's last frame),
        set its end location, resume breathing, and fire completion."""
        character = mv.character
        iid = mv.iid
        try:
            if mv.end_location:
                character.SetLocation(mv.end_location)
            # Freeze the rest pose at the walk clip's LAST frame -- the character is
            # now standing/seated at the destination -- so breathing layers over it.
            renderer.set_instance_rest_pose(iid, mv.clip_index, False)
            breathing = capture_breathing(character)
            if breathing:
                bidx = renderer.load_instance_clip(
                    iid, self._resolve(breathing["clip_nif"]))
                if bidx is not None and bidx >= 0:
                    renderer.play_instance_idle(iid, bidx)
                    from engine.bridge_character_anim import get_controller
                    ca = get_controller()
                    if ca is not None:
                        ca.set_idle(iid, bidx)
        except Exception:
            pass
        self._complete(mv)

    def _real_duration(self, renderer, path) -> float:
        fn = getattr(renderer, "load_animation_clips", None)
        if fn is None:
            return _MIN_WALK_S
        try:
            clips = fn(path)
            if clips:
                return float(clips[0].get("duration", 0.0) or 0.0)
        except Exception:
            pass
        return _MIN_WALK_S


_controller = None


def get_controller():
    return _controller


def set_controller(ctrl) -> None:
    global _controller
    _controller = ctrl


def clear_controller() -> None:
    global _controller
    _controller = None
