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
                 "cur_duration", "hold")

    def __init__(self, iid, clips, priority, hold=False):
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


class BridgeCharacterAnimController:
    def __init__(self, asset_resolver=None):
        self._active = {}           # iid -> _Action
        self._dur_cache = {}        # nif_path -> real clip duration (s)
        self._body_turns = {}       # nif_path -> bool (clip rotates the body)
        self._idle_clips = {}       # iid -> looping breathe clip index
        self._pending_turns = []    # [(character, turn_bool), ...]
        self._resolve = asset_resolver or (lambda p: p)
        self._node_ctrl = None      # BridgeNodeAnimController (optional)

    def set_node_controller(self, ctrl) -> None:
        """Attach a BridgeNodeAnimController that handles the chair half of
        TurnCaptain / BackCaptain. Call once from the host after construction."""
        self._node_ctrl = ctrl

    def is_busy(self, character) -> bool:
        iid = getattr(character, "_render_instance", None)
        return iid in self._active

    def submit(self, character, clips, priority, hold=False) -> None:
        iid = getattr(character, "_render_instance", None)
        if iid is None or not clips:
            return
        if character.IsHidden():
            return
        cur = self._active.get(iid)
        if cur is not None and priority <= cur.priority:
            return                  # don't preempt equal/higher priority
        self._active[iid] = _Action(iid, list(clips), priority, hold)

    def set_idle(self, iid, clip_index) -> None:
        """Register the officer's looping breathe clip — what the controller
        returns to when its transient queue empties (AT_DEFAULT)."""
        self._idle_clips[iid] = clip_index

    def request_turn(self, character) -> None:
        """Queue a turn-to-captain (drained on the next update, which has the
        renderer). Called from CharacterClass.MenuUp via the registry."""
        self._pending_turns.append((character, True))

    def request_turn_back(self, character) -> None:
        """Queue a turn-back-to-normal (CharacterClass.MenuDown)."""
        self._pending_turns.append((character, False))

    def reset(self) -> None:
        self._active = {}
        self._idle_clips = {}
        self._pending_turns = []

    def update(self, dt, *, renderer, anim_mgr=None) -> None:
        if self._pending_turns:
            pending, self._pending_turns = self._pending_turns, []
            for character, turn in pending:
                self._process_turn(renderer, character, turn)
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

    def _process_turn(self, renderer, character, turn) -> None:
        """On menu open the officer turns to face the captain and HOLDS it; on
        close they turn back and resume normal breathing.

        Uses the SDK's TurnCaptain / BackCaptain. For seated officers the SDK
        builder is a multi-action sequence — the officer's BODY turn clip
        (e.g. db_face_capt_h) plus the CHAIR clip on the bridge-set node;
        capture_registered_clip picks the body clip (the chair-on-bridge-node
        is a separate set animation we don't drive). Best-effort: a missing clip
        skips that half.
        """
        iid = getattr(character, "_render_instance", None)
        if iid is None:
            return
        # A menu open/close is a deliberate user action and must always take
        # effect: evict any in-flight transient for this officer so the new
        # turn/back is never dropped by submit's equal-priority guard. Without
        # this, a fast open+close would drop the reverse turn while the forward
        # turn (same priority) is still playing, leaving the officer stuck
        # facing the captain until the next interaction.
        self._active.pop(iid, None)
        # Decide (from the FORWARD body clip) whether this officer turns via its
        # own BODY clip or is CHAIR-DRIVEN. BC encodes this asymmetry per station:
        # Helm/standing crew have a real db_face_capt_* clip that rotates Bip01
        # ~72deg (body-driven); Tactical's db_face_capt_t is EMPTY (chair-driven),
        # so the rotating chair must carry the officer. Driving BOTH double-turns
        # the officer. Compute once and use it consistently for turn AND unturn.
        chair_driven = not self._body_turns_officer(
            renderer, capture_registered_clip(character, "TurnCaptain"))
        if turn:
            if not chair_driven:
                # Body-driven (Helm): turn toward the captain and HOLD it while
                # the menu is open. No BreatheTurned swap — that clip over the
                # forward placement does not preserve the body's turn, so we hold
                # the turn clip's last frame instead.
                move = capture_registered_clip(character, "TurnCaptain")
                if move:
                    self.submit(character, [(self._resolve(move["clip_nif"]), 0.0)],
                                priority=_TURN, hold=True)
            else:
                # Chair-driven (Tactical): the body turn clip is EMPTY, so the
                # chair carries the body (below) and the head/upper-body look at
                # the captain comes from the BreatheTurned idle (breathing.NIF),
                # layered over the chair-rotated body. Fall back to plain Breathe
                # if this officer has no BreatheTurned registration.
                if not self._switch_idle(renderer, iid, character, "BreatheTurned"):
                    self._switch_idle(renderer, iid, character, "Breathe")
        else:
            if not chair_driven:
                # Body-driven: restore normal breathing as the default, then play
                # the reverse turn, which returns to that idle on completion.
                idle = capture_registered_clip(character, "Breathe")
                if idle and hasattr(renderer, "load_instance_clip"):
                    idx = renderer.load_instance_clip(
                        iid, self._resolve(idle["clip_nif"]))
                    if idx is not None and idx >= 0:
                        self.set_idle(iid, idx)
                move = capture_registered_clip(character, "BackCaptain")
                if move:
                    self.submit(character, [(self._resolve(move["clip_nif"]), 0.0)],
                                priority=_TURN, hold=False)
            else:
                # Chair-driven: the chair reverse carries the body back (below);
                # swap the idle back to plain forward Breathe and play it now.
                self._switch_idle(renderer, iid, character, "Breathe")
        # Chair half: rotate the seat (always) + couple the officer only when
        # chair-driven (delegated to the bridge-node controller). Standing
        # officers have no chair action (capture_chair_clip -> None) -> no-op.
        node_ctrl = getattr(self, "_node_ctrl", None)
        if node_ctrl is not None:
            chair = capture_chair_clip(character, "TurnCaptain" if turn
                                       else "BackCaptain")
            if turn:
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

    def _return_to_default(self, renderer, iid) -> None:
        """Resume the looping breathe idle if one is registered; otherwise snap
        to the static rest pose (officer with no breathe registration)."""
        idle = self._idle_clips.get(iid)
        if idle is not None and hasattr(renderer, "play_instance_idle"):
            renderer.play_instance_idle(iid, idle)
        elif hasattr(renderer, "restore_rest_pose"):
            renderer.restore_rest_pose(iid)

    def _switch_idle(self, renderer, iid, character, suffix) -> bool:
        """Capture the SDK breathe idle `<location>+suffix`, register it as the
        default, and play it now (looping, layered). Used for chair-driven
        officers, whose head/upper-body articulation lives in the BreatheTurned
        idle (their body turn clip is empty). Returns True if it played."""
        idle = capture_registered_clip(character, suffix)
        if not idle or not hasattr(renderer, "load_instance_clip"):
            return False
        idx = renderer.load_instance_clip(iid, self._resolve(idle["clip_nif"]))
        if idx is None or idx < 0:
            return False
        self.set_idle(iid, idx)
        self._return_to_default(renderer, iid)
        return True

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
