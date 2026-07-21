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
_SCRIPTED = 2   # AT_PLAY_ANIMATION: a scripted mission beat outranks both —
                # submit() drops an equal-or-lower priority onto a busy officer,
                # and a scripted gesture must never lose to an idle fidget.

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
        self._pending_glances = []  # [(character, detail, on_complete), ...]
        self._pending_defaults = []  # [iid, ...]
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
        # Rescue the preempted action's on_complete (same guarantee _process_turn
        # and request_default give): a preempted _TURN can be carrying an
        # AT_SAY_LINE's speak-then-turn-back callback, and a mission TGSequence
        # is waiting on it — silently discarding it stalls that sequence forever.
        # Fire it only AFTER _active[iid] is replaced, so a re-entrant submit /
        # request_default from the callback sees the new state, never the stale
        # one. It cannot double-fire: `cur` is already out of _active.
        if cur is not None and cur.on_complete is not None:
            try:
                cur.on_complete()
            except Exception:
                pass
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

    def request_glance(self, character, detail, on_complete=None) -> None:
        """Queue a quick head/upper-body glance (SDK AT_GLANCE_AT/AWAY). Resolves
        "Glance"+detail; a graceful inline no-op if unregistered (niche action)."""
        self._pending_glances.append((character, str(detail), on_complete))

    def request_default(self, character) -> None:
        """AT_DEFAULT / AT_BREATHE: drop any transient clip and restore the
        officer's rest pose — which IS the breathe idle (capture_breathing
        feeds set_idle). The restore itself needs the renderer, so it is
        queued for the next update() tick, the same way turns and glances
        are. Never raises.

        If the dropped action carried an on_complete, fire it (best-effort):
        the owning CharacterAction / mission TGSequence is waiting on that
        callback, and silently dropping it would stall the sequence forever
        (same guarantee update() gives at a clip's natural end)."""
        iid = getattr(character, "_render_instance", None)
        if iid is None:
            return
        prev = self._active.pop(iid, None)   # cancel the transient clip
        self._pending_defaults.append(iid)   # restore the rest pose next tick
        if prev is not None and prev.on_complete is not None:
            try:
                prev.on_complete()
            except Exception:
                pass

    def _process_glance(self, renderer, character, detail, on_complete) -> None:
        """Play a quick glance. Fires on_complete exactly once — via the
        submitted _Action when submit() succeeds, else inline (unresolved clip
        / no render instance / dropped by submit's equal-priority guard) so
        completion is guaranteed and a waiting TGSequence never hangs."""
        clip = capture_registered_clip(character, "Glance" + detail)
        iid = getattr(character, "_render_instance", None)
        submitted = False
        if iid is not None and clip:
            submitted = self.submit(
                character, [(clip["clip_nif"], 0.0)],
                priority=_REACTION, on_complete=on_complete)
        if not submitted and on_complete is not None:
            try:
                on_complete()
            except Exception:
                pass

    def reset(self) -> None:
        self._active = {}
        self._idle_clips = {}
        self._pending_turns = []
        self._pending_glances = []
        self._pending_defaults = []

    def update(self, dt, *, renderer, anim_mgr=None) -> None:
        if self._pending_turns:
            pending, self._pending_turns = self._pending_turns, []
            for entry in pending:
                self._process_turn(renderer, *entry)
        if self._pending_glances:
            pending, self._pending_glances = self._pending_glances, []
            for character, detail, on_complete in pending:
                self._process_glance(renderer, character, detail, on_complete)
        if self._pending_defaults:
            pending, self._pending_defaults = self._pending_defaults, []
            for iid in pending:
                self._return_to_default(renderer, iid)
        # Iterate a SNAPSHOT: an on_complete below is a CharacterAction's
        # Completed(), event dispatch is synchronous, so it advances the owning
        # TGSequence and Play()s the next action — which can submit() /
        # request_default() on this or another officer, mutating _active from
        # inside this loop (RuntimeError: dictionary changed size during
        # iteration).
        for iid, act in list(self._active.items()):
            if self._active.get(iid) is not act:
                # Replaced (or cancelled) by a re-entrant call earlier in this
                # same drain/loop — the slot no longer belongs to `act`.
                continue
            if not act.started or act.index < 0:
                self._start_clip(renderer, act, 0)
                continue
            act.elapsed += dt
            if act.elapsed < act.cur_duration:
                continue
            nxt = act.index + 1
            if nxt < len(act.clips):
                self._start_clip(renderer, act, nxt)
                continue
            if not act.hold:
                self._return_to_default(renderer, iid)
            # hold=True leaves the native renderer holding the last frame
            # (the turned-to-captain pose) until the reverse turn replaces it.
            #
            # Remove the finished action BEFORE firing its on_complete: a
            # re-entrant submit() from the callback then lands in a CLEAN slot
            # and cannot be clobbered by a deferred pop afterwards (which used
            # to delete the brand-new action — its on_complete never fired, so
            # _current_anim leaked and the mission sequence froze). Only ever
            # remove `act` itself, never a replacement installed under the
            # same iid.
            if self._active.get(iid) is act:
                del self._active[iid]
            if act.on_complete is not None:
                try:
                    act.on_complete()
                except Exception:
                    pass

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
        # new turn is never dropped by submit's equal-priority guard. Rescue a
        # deferred on_complete off the evicted action first — a mission-driven
        # AT_TURN/AT_MOVE etc. mid-clip carries a callback that a waiting
        # TGSequence depends on; silently dropping it hangs that sequence
        # forever. Firing it here (one clip early) is a one-time, guaranteed
        # completion and cannot double-fire: the action is gone from _active,
        # so update() can never reach it again.
        prev = self._active.pop(iid, None)
        if prev is not None and prev.on_complete is not None:
            try:
                prev.on_complete()
            except Exception:
                pass
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
                    character, [(move["clip_nif"], 0.0)],
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
                    character, [(move["clip_nif"], 0.0)],
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
        # Resolve here, at the single choke point every submission funnels
        # through: idle gestures, hit reactions, scripted AT_PLAY_ANIMATION,
        # turns and glances all submit raw game-relative paths
        # ("data/animations/..."), which the native loader misses (cwd is not
        # game/) — load_instance_clip returns -1 and the gesture is a silent
        # no-op. This is the ONLY resolve site for submitted clips; direct
        # loads (_body_turns_officer, the breathe idle) resolve for themselves.
        path, sdk_dur = act.clips[index]
        path = self._resolve(path)
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

    # CAT_* mirror (avoid importing characters at module load — circular).
    # Matches engine.appc.characters.CharacterClass CAT_* exactly.
    _CAT_BREATHE, _CAT_INTERRUPTABLE, _CAT_NON_INTERRUPTABLE = 0, 1, 2
    _CAT_TURN, _CAT_TURN_BACK, _CAT_GLANCE, _CAT_GLANCE_BACK = 3, 4, 5, 6

    def is_active(self, character) -> bool:
        """Whether the character has a live transient clip (drives the queue's
        ReleaseCurrentAnimation). Same check as is_busy."""
        return self.is_busy(character)

    def stop(self, character) -> None:
        """Evict the character's live clip + any pending turn/glance/default for
        it. Rescue an evicted _Action's on_complete so a waiting mission
        TGSequence never hangs. A pending turn/glance (queued but not yet
        drained by update()) carries its own on_complete too — fire those as
        well, or the callback silently vanishes and the waiting TGSequence
        hangs (BUG 2). _pending_defaults entries are bare iids with no
        callback, so nothing to fire there. Never raises."""
        iid = getattr(character, "_render_instance", None)
        if iid is None:
            return
        prev = self._active.pop(iid, None)
        self._pending_defaults = [i for i in self._pending_defaults if i != iid]
        kept_turns = []
        removed_turns = []
        for e in self._pending_turns:
            if getattr(e[0], "_render_instance", None) == iid:
                removed_turns.append(e)
            else:
                kept_turns.append(e)
        self._pending_turns = kept_turns
        kept_glances = []
        removed_glances = []
        for e in self._pending_glances:
            if getattr(e[0], "_render_instance", None) == iid:
                removed_glances.append(e)
            else:
                kept_glances.append(e)
        self._pending_glances = kept_glances
        if prev is not None and prev.on_complete is not None:
            try:
                prev.on_complete()
            except Exception:
                pass
        for e in removed_turns:
            on_complete = e[5]
            if on_complete is not None:
                try:
                    on_complete()
                except Exception:
                    pass
        for e in removed_glances:
            on_complete = e[2]
            if on_complete is not None:
                try:
                    on_complete()
                except Exception:
                    pass

    def play_record(self, character, rec) -> None:
        """Play an animation record by mapping its CAT_ category to the existing
        deferred playback, threading the record's on_complete/hold/now. Turn and
        glance re-resolve the clip from character+name internally; gesture/move
        categories carry resolved clips on rec.play ([(nif, dur), ...])."""
        cat = rec.category
        if cat in (self._CAT_TURN, self._CAT_TURN_BACK):
            self.request_turn_to(character, rec.name or "Captain",
                                 back=(cat == self._CAT_TURN_BACK),
                                 hold=bool(rec.hold), now=bool(rec.now),
                                 on_complete=rec.on_complete)
        elif cat in (self._CAT_GLANCE, self._CAT_GLANCE_BACK):
            self.request_glance(character, rec.name or "", on_complete=rec.on_complete)
        else:
            # Gesture / breathe / move: rec.play carries resolved clips, OR (a
            # MoveTo record) a resolved SDK builder TGSequence.
            clips = rec.play if isinstance(rec.play, (list, tuple)) and rec.play else None
            if clips:
                self.submit(character, clips, priority=_SCRIPTED,
                            hold=bool(rec.hold), on_complete=rec.on_complete)
            elif rec.play is not None and hasattr(rec.play, "Play"):
                # A MoveTo's builder TGSequence (walk + door + AT_SET_LOCATION_
                # NAME): play it directly. The walk action inside defers to the
                # walk controller (actions.py TGAnimAction._do_play's
                # _walk_move path); the sequence's OWN completed event --
                # attached by CharacterClass.MoveTo -- fires the owning
                # CharacterAction's Completed() once the whole sequence
                # settles. Never fire rec.on_complete here: a MoveTo record's
                # on_complete is always None -- completion is the sequence's
                # event, not this record's. Never raise out of play_record.
                try:
                    rec.play.Play()
                except Exception:
                    pass
            elif rec.on_complete is not None:
                # Nothing to play — still fire completion so a sequence advances.
                try:
                    rec.on_complete()
                except Exception:
                    pass

    def _real_duration(self, renderer, path) -> float:
        """The clip's natural length (seconds), cached per path. 0.0 when the
        renderer can't report it (e.g. headless FakeRenderer). `path` arrives
        RESOLVED (_start_clip is the only caller) — do not resolve again."""
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
