# engine/bridge_character_anim.py
"""BridgeCharacterAnimController — per-character transient animation runner.

The officer's placement is a STATIC rest pose (set_instance_rest_pose). Idle
gestures and hit reactions are transient SDK TGSequences played over it: each
is a list of (nif_path, duration) clips played in order; when the last clip
ends the controller issues restore_rest_pose (the SDK's AT_DEFAULT). Reactions
(priority 1) preempt idle (priority 0); a lower-or-equal priority submission for
a busy character is dropped. Mirrors engine/bridge_cutscene.py.
"""

from engine.appc.bridge_placement import capture_registered_clip, capture_chair_clip

_IDLE = 0
_REACTION = 1
_TURN = 1       # turn-to-captain preempts idle (0); same band as reactions

# Floor for a clip with no SDK duration AND no resolvable natural length (e.g.
# a single-frame pose clip whose duration parses as 0). Keeps it on screen
# briefly instead of restoring the rest pose on the very next tick.
_MIN_GESTURE_HOLD_S = 0.4


class _Action:
    __slots__ = ("iid", "clips", "priority", "index", "elapsed", "started",
                 "cur_duration", "hold", "on_complete")

    def __init__(self, iid, clips, priority, hold=False, on_complete=None):
        self.iid = iid
        self.clips = clips          # [(nif_path, sdk_duration), ...]
        self.priority = priority
        self.index = -1             # current clip; -1 = not yet started
        self.elapsed = 0.0
        self.started = False
        self.cur_duration = 0.0     # effective hold for the current clip
        # hold=True: on completion HOLD the last frame instead of returning to
        # the default idle (turn-to-captain stays facing the captain while the
        # menu is open). The reverse turn (hold=False) returns to normal breathe.
        self.hold = hold
        self.on_complete = on_complete   # fired once when the last clip ends


class BridgeCharacterAnimController:
    def __init__(self, asset_resolver=None):
        self._active = {}           # iid -> _Action
        self._dur_cache = {}        # nif_path -> real clip duration (s)
        self._body_turns = {}       # nif_path -> bool (clip rotates the body)
        self._idle_clips = {}       # iid -> looping breathe clip index
        self._pending_turns = []    # [(character, detail, back, hold, now,
                                     #   on_complete), ...]
        self._resolve = asset_resolver or (lambda p: p)
        self._node_ctrl = None      # BridgeNodeAnimController (optional)

    def set_node_controller(self, ctrl) -> None:
        """Attach a BridgeNodeAnimController that handles the chair half of
        TurnCaptain / BackCaptain. Call once from the host after construction."""
        self._node_ctrl = ctrl

    def is_busy(self, character) -> bool:
        iid = getattr(character, "_render_instance", None)
        return iid in self._active

    def submit(self, character, clips, priority, hold=False,
               on_complete=None) -> bool:
        """Returns True iff an _Action was actually created and stored; False
        on every no-op path (no render instance, no clips, hidden character,
        or dropped by the equal/higher-priority guard). Callers that need to
        guarantee on_complete fires (e.g. _process_turn) must check this."""
        iid = getattr(character, "_render_instance", None)
        if iid is None or not clips:
            return False
        if character.IsHidden():
            return False
        cur = self._active.get(iid)
        if cur is not None and priority <= cur.priority:
            return False            # don't preempt equal/higher priority
        self._active[iid] = _Action(iid, list(clips), priority, hold, on_complete)
        return True

    def set_idle(self, iid, clip_index) -> None:
        """Register the officer's looping breathe clip — what the controller
        returns to when its transient queue empties (AT_DEFAULT)."""
        self._idle_clips[iid] = clip_index

    def request_turn(self, character) -> None:
        """Queue a turn-to-captain (drained on the next update, which has the
        renderer). Called from CharacterClass.MenuUp via the registry."""
        self.request_turn_to(character, "Captain", back=False, hold=True)

    def request_turn_back(self, character) -> None:
        """Queue a turn-back-to-normal (CharacterClass.MenuDown)."""
        self.request_turn_to(character, "Captain", back=True, hold=True)

    def request_turn_to(self, character, detail, *, back=False, hold=True,
                        now=False, on_complete=None) -> None:
        """Queue a body turn toward `detail` (SDK AT_TURN / AT_TURN_BACK). Suffix
        is "Turn"+detail (or "Back"+detail); reuses the menu turn's body+chair
        coupling. on_complete fires once when the turn settles/holds, or inline
        when chair-driven / now / unresolved."""
        self._pending_turns.append(
            (character, str(detail), bool(back), bool(hold), bool(now),
             on_complete))

    def reset(self) -> None:
        self._active = {}
        self._idle_clips = {}
        self._pending_turns = []

    def update(self, dt, *, renderer, anim_mgr=None) -> None:
        if self._pending_turns:
            pending, self._pending_turns = self._pending_turns, []
            for entry in pending:
                self._process_turn(renderer, *entry)
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
                if not act.hold:
                    self._return_to_default(renderer, iid)
                # hold=True leaves the native renderer holding the last frame
                # (the turned-to-captain pose) until the reverse turn replaces it.
                if act.on_complete is not None:
                    try:
                        act.on_complete()
                    except Exception:
                        pass
                done.append(iid)
        for iid in done:
            self._active.pop(iid, None)

    def _body_turns_officer(self, renderer, move) -> bool:
        """True if the captured body turn clip actually rotates the officer.
        Tactical's db_face_capt_t is EMPTY (0 keys, 0 duration) -> False, so the
        chair must carry it; Helm's db_face_capt_h rotates Bip01 ~72deg -> True.
        Cached per NIF path. Headless / unloadable -> True (body-driven default,
        the pre-chair behaviour, so nothing regresses without a renderer)."""
        if not move:
            return False
        path = self._resolve(move["clip_nif"])
        cached = self._body_turns.get(path)
        if cached is not None:
            return cached
        fn = getattr(renderer, "load_animation_clips", None)
        if fn is None:
            return True
        result = True
        try:
            clips = fn(path)
            if not clips:
                result = False
            else:
                c = clips[0]
                result = (float(c.get("duration", 0.0)) > 1e-4 and
                          any(tr.get("rotation") for tr in c.get("tracks", [])))
        except Exception:
            result = True
        self._body_turns[path] = result
        return result

    def _process_turn(self, renderer, character, detail, back, hold, now,
                      on_complete) -> None:
        """Turn `character` toward `detail` (body clip + chair). Suffix
        "Turn"+detail forward, "Back"+detail reverse. Fires on_complete exactly
        once — via the submitted body _Action for a body-driven, non-`now` turn,
        else inline (chair-driven / now / unresolved) so completion is
        guaranteed."""
        turn_suffix = "Turn" + detail
        back_suffix = "Back" + detail

        def _fire_inline():
            if on_complete is not None:
                try:
                    on_complete()
                except Exception:
                    pass

        iid = getattr(character, "_render_instance", None)
        if iid is None:
            _fire_inline()
            return
        # A turn must always take effect: evict any in-flight transient so the
        # new turn is never dropped by submit's equal-priority guard.
        self._active.pop(iid, None)
        # Body-driven vs chair-driven is decided from the FORWARD body clip
        # (BC's per-station asymmetry): Helm rotates Bip01 ~72deg (body-driven);
        # Tactical's clip is EMPTY (chair-driven). Compute once, use for both
        # directions.
        chair_driven = not self._body_turns_officer(
            renderer, capture_registered_clip(character, turn_suffix))
        # The body _Action carries on_complete only for a body-driven, non-`now`
        # turn; every other path fires inline below (avoids double-fire).
        action_cb = None if now else on_complete
        body_submitted = False
        if not back:
            move = capture_registered_clip(character, turn_suffix)
            if move and not chair_driven:
                body_submitted = self.submit(
                    character, [(self._resolve(move["clip_nif"]), 0.0)],
                    priority=_TURN, hold=hold, on_complete=action_cb)
        else:
            # Turn back: restore normal breathing as the default, then play the
            # reverse turn, which returns to that idle on completion.
            idle = capture_registered_clip(character, "Breathe")
            if idle:
                idx = renderer.load_instance_clip(
                    iid, self._resolve(idle["clip_nif"]))
                if idx is not None and idx >= 0:
                    self.set_idle(iid, idx)
            move = capture_registered_clip(character, back_suffix)
            if move and not chair_driven:
                body_submitted = self.submit(
                    character, [(self._resolve(move["clip_nif"]), 0.0)],
                    priority=_TURN, hold=False, on_complete=action_cb)
        # Chair half: rotate the seat (always) + couple the officer only when
        # chair-driven. Standing officers have no chair action -> no-op.
        node_ctrl = getattr(self, "_node_ctrl", None)
        if node_ctrl is not None:
            chair = capture_chair_clip(character, turn_suffix if not back
                                       else back_suffix)
            if not back:
                node_ctrl.turn_chair(character, chair, renderer=renderer,
                                     couple=chair_driven)
            else:
                node_ctrl.unturn_chair(character, chair, renderer=renderer)
                # Do NOT release coupling here: the officer must keep riding the
                # seat as the reverse clip plays back. The coupling self-heals to
                # identity when the chair settles at rest (R_delta -> I -> the
                # officer's placement) and stays there harmlessly. Coupling is
                # dropped only on reset() (mission swap) or when re-turned (the
                # _coupled dict entry is overwritten). Releasing now would freeze
                # the officer at the turned pose while the chair animates back.
        # Guarantee completion: body-driven non-`now` turns complete when the
        # _Action settles; everything else completes now.
        if now or not body_submitted:
            _fire_inline()

    def _return_to_default(self, renderer, iid) -> None:
        """Resume the looping breathe idle if one is registered; otherwise snap
        to the static rest pose (officer with no breathe registration)."""
        idle = self._idle_clips.get(iid)
        if idle is not None:
            renderer.play_instance_idle(iid, idle)
        else:
            renderer.restore_rest_pose(iid)

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
        clip_index = renderer.load_instance_clip(act.iid, path)
        if clip_index is not None and clip_index >= 0:
            renderer.play_instance_gesture(act.iid, clip_index)

    def _real_duration(self, renderer, path) -> float:
        """The clip's natural length (seconds), cached per path. 0.0 when the
        renderer can't report it (e.g. headless FakeRenderer)."""
        if path in self._dur_cache:
            return self._dur_cache[path]
        dur = 0.0
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
