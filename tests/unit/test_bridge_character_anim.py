from engine.bridge_character_anim import BridgeCharacterAnimController


class _FakeRenderer:
    def __init__(self):
        self.loaded = {}        # (iid, path) -> clip_index
        self.played = []        # (iid, clip_index)
        self.restored = []      # iid
        self.idled = []         # (iid, clip_index)
        self._next = 1
    def load_instance_clip(self, iid, path):
        key = (iid, path)
        if key not in self.loaded:
            self._next += 1
            self.loaded[key] = self._next
        return self.loaded[key]
    def play_instance_gesture(self, iid, clip_index):
        self.played.append((iid, clip_index))
    def restore_rest_pose(self, iid):
        self.restored.append(iid)
    def play_instance_idle(self, iid, clip_index):
        self.idled.append((iid, clip_index))


class _Char:
    def __init__(self, iid):
        self._render_instance = iid
    def IsHidden(self):
        return 0


def test_plays_clips_in_order_then_restores_rest():
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(42)
    ctrl.submit(ch, [("a.nif", 1.0), ("b.nif", 0.5)], priority=0)

    ctrl.update(0.0, renderer=r, anim_mgr=None)     # start clip a
    assert r.played == [(42, r.loaded[(42, "a.nif")])]

    ctrl.update(1.0, renderer=r, anim_mgr=None)     # a done -> start b
    assert r.played[-1] == (42, r.loaded[(42, "b.nif")])

    ctrl.update(0.5, renderer=r, anim_mgr=None)     # b done -> AT_DEFAULT
    assert r.restored == [42]


def test_reaction_preempts_idle():
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(7)
    ctrl.submit(ch, [("idle.nif", 5.0)], priority=0)
    ctrl.update(0.0, renderer=r, anim_mgr=None)     # idle playing
    ctrl.submit(ch, [("hit.nif", 0.4)], priority=1) # reaction preempts
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    assert r.played[-1] == (7, r.loaded[(7, "hit.nif")])

    # Lower-priority idle submitted during a reaction is dropped.
    ctrl.submit(ch, [("idle2.nif", 5.0)], priority=0)
    ctrl.update(0.1, renderer=r, anim_mgr=None)
    assert (7, r.loaded.get((7, "idle2.nif"))) not in r.played


def test_busy_returns_true_while_acting():
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(9)
    assert ctrl.is_busy(ch) is False
    ctrl.submit(ch, [("g.nif", 2.0)], priority=0)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    assert ctrl.is_busy(ch) is True


class _FakeRendererWithDurations(_FakeRenderer):
    """Adds load_animation_clips so the controller can resolve a clip's real
    length when the submitted (SDK) duration is 0."""
    def __init__(self, durations):
        super().__init__()
        self._durations = durations          # path -> seconds
    def load_animation_clips(self, path):
        return [{"duration": self._durations.get(path, 0.0)}]


def test_zero_sdk_duration_holds_for_real_clip_length():
    # sdk_dur == 0 -> the controller holds for the clip's natural length
    # (resolved via load_animation_clips), not a fixed fallback.
    ctrl = BridgeCharacterAnimController()
    r = _FakeRendererWithDurations({"g.nif": 2.0})
    ch = _Char(5)
    ctrl.submit(ch, [("g.nif", 0.0)], priority=0)
    ctrl.update(0.0, renderer=r, anim_mgr=None)       # start
    ctrl.update(1.0, renderer=r, anim_mgr=None)       # 1.0 < 2.0 -> still holding
    assert ctrl.is_busy(ch)
    assert r.restored == []
    ctrl.update(1.1, renderer=r, anim_mgr=None)       # 2.1 >= 2.0 -> restore
    assert r.restored == [5]


def test_start_clip_resolves_submitted_paths_via_asset_resolver():
    # The dbridge idle-gesture bug: idle/hit/scripted submissions carry raw
    # game-relative paths ("data/animations/..."). _start_clip must route them
    # through the controller's asset_resolver before load_instance_clip, or
    # the native loader misses (cwd != game/) and the gesture is a silent
    # no-op — the action "plays" invisibly for its duration. Turn/glance
    # already resolve at submit time; the resolver must be idempotent there.
    ctrl = BridgeCharacterAnimController(asset_resolver=lambda p: "/abs/" + p)
    r = _FakeRenderer()
    ch = _Char(3)
    ctrl.submit(ch, [("data/animations/g.nif", 1.0)], priority=0)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    assert (3, "/abs/data/animations/g.nif") in r.loaded
    assert (3, "data/animations/g.nif") not in r.loaded


def test_real_duration_lookup_uses_the_resolved_path():
    # Same choke point for the natural-length probe: sdk_dur == 0 must consult
    # load_animation_clips with the RESOLVED path.
    ctrl = BridgeCharacterAnimController(asset_resolver=lambda p: "/abs/" + p)
    r = _FakeRendererWithDurations({"/abs/g.nif": 2.0})
    ch = _Char(4)
    ctrl.submit(ch, [("g.nif", 0.0)], priority=0)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    ctrl.update(1.0, renderer=r, anim_mgr=None)       # 1.0 < 2.0 -> still holding
    assert ctrl.is_busy(ch)
    ctrl.update(1.1, renderer=r, anim_mgr=None)       # 2.1 >= 2.0 -> restore
    assert r.restored == [4]


def test_explicit_sdk_duration_is_honored_verbatim():
    # sdk_dur > 0 wins even when shorter than any floor, and real length is
    # NOT consulted.
    ctrl = BridgeCharacterAnimController()
    r = _FakeRendererWithDurations({"g.nif": 99.0})   # real length ignored
    ch = _Char(6)
    ctrl.submit(ch, [("g.nif", 0.3)], priority=0)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    ctrl.update(0.31, renderer=r, anim_mgr=None)      # 0.31 >= 0.3 -> restore
    assert r.restored == [6]


def test_zero_duration_unresolvable_uses_floor():
    # sdk_dur == 0 and no resolvable real length -> the controller holds for the
    # floor, not the very next tick.
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer()                               # no load_animation_clips
    ch = _Char(7)
    ctrl.submit(ch, [("g.nif", 0.0)], priority=0)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    ctrl.update(0.2, renderer=r, anim_mgr=None)       # 0.2 < 0.4 floor -> holding
    assert r.restored == []
    ctrl.update(0.3, renderer=r, anim_mgr=None)       # 0.5 >= 0.4 -> restore
    assert r.restored == [7]


def test_completion_resumes_breathing_when_idle_registered():
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(8)
    ctrl.set_idle(8, 99)                       # breathe clip index for iid 8
    ctrl.submit(ch, [("g.nif", 0.5)], priority=0)
    ctrl.update(0.0, renderer=r, anim_mgr=None)    # start gesture
    ctrl.update(0.5, renderer=r, anim_mgr=None)    # complete -> resume breathing
    assert r.idled == [(8, 99)]                # play_instance_idle called
    assert r.restored == []                    # NOT restore_rest_pose


def test_completion_falls_back_to_restore_when_no_idle():
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(9)                              # no set_idle for 9
    ctrl.submit(ch, [("g.nif", 0.5)], priority=0)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    ctrl.update(0.5, renderer=r, anim_mgr=None)
    assert r.idled == []
    assert r.restored == [9]                   # static fallback


def test_reset_clears_idle_registry():
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(10)
    ctrl.set_idle(10, 42)
    ctrl.reset()
    ctrl.submit(ch, [("g.nif", 0.5)], priority=0)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    ctrl.update(0.5, renderer=r, anim_mgr=None)
    assert r.idled == []                       # registry cleared -> fallback
    assert r.restored == [10]


def test_request_turn_holds_facing_captain(monkeypatch):
    import engine.bridge_character_anim as mod
    monkeypatch.setattr(mod, "capture_registered_clip",
                        lambda ch, suffix: {"clip_nif": f"{suffix}.nif"})
    ctrl = mod.BridgeCharacterAnimController()      # identity asset_resolver
    r = _FakeRenderer()
    ch = _Char(11)
    ctrl.request_turn(ch)
    ctrl.update(0.0, renderer=r, anim_mgr=None)        # start TurnCaptain
    gc_idx = r.loaded[(11, "TurnCaptain.nif")]
    assert r.played[-1] == (11, gc_idx)
    # No BreatheTurned swap; we hold the turn.
    assert 11 not in ctrl._idle_clips
    assert (11, "BreatheTurned.nif") not in r.loaded
    # On completion the glance HOLDS at the captain: no return-to-default.
    ctrl.update(0.5, renderer=r, anim_mgr=None)        # 0.5 >= 0.4 floor -> done
    assert r.restored == []
    assert r.idled == []
    assert ctrl.is_busy(ch) is False                   # action completed, popped


def test_request_turn_back_restores_normal_breathe(monkeypatch):
    import engine.bridge_character_anim as mod
    monkeypatch.setattr(mod, "capture_registered_clip",
                        lambda ch, suffix: {"clip_nif": f"{suffix}.nif"})
    ctrl = mod.BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(12)
    ctrl.request_turn_back(ch)
    ctrl.update(0.0, renderer=r, anim_mgr=None)        # start BackCaptain
    breathe_idx = r.loaded[(12, "Breathe.nif")]
    away_idx = r.loaded[(12, "BackCaptain.nif")]
    assert ctrl._idle_clips[12] == breathe_idx
    assert r.played[-1] == (12, away_idx)
    # On completion the look-away returns to the normal breathe idle.
    ctrl.update(0.5, renderer=r, anim_mgr=None)        # complete
    assert r.idled[-1] == (12, breathe_idx)


def test_turn_back_evicts_in_flight_forward_turn(monkeypatch):
    # Fast open+close: the forward turn is still in _active when turn-back is
    # requested. The back must still play (not be dropped by submit's equal-
    # priority guard), so the officer never gets stuck facing the captain.
    import engine.bridge_character_anim as mod
    monkeypatch.setattr(mod, "capture_registered_clip",
                        lambda ch, suffix: {"clip_nif": f"{suffix}.nif"})
    ctrl = mod.BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(20)
    ctrl.request_turn(ch)                              # open
    ctrl.update(0.0, renderer=r, anim_mgr=None)        # forward TurnCaptain plays
    assert r.played[-1] == (20, r.loaded[(20, "TurnCaptain.nif")])
    ctrl.request_turn_back(ch)                         # close while forward in-flight
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    assert r.played[-1] == (20, r.loaded[(20, "BackCaptain.nif")])


def test_request_turn_missing_clips_is_graceful(monkeypatch):
    import engine.bridge_character_anim as mod
    monkeypatch.setattr(mod, "capture_registered_clip", lambda ch, suffix: None)
    ctrl = mod.BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(13)
    ctrl.request_turn(ch)
    ctrl.update(0.0, renderer=r, anim_mgr=None)     # no crash; nothing submitted
    assert 13 not in ctrl._idle_clips
    assert r.played == []


def test_asset_resolver_applied(monkeypatch):
    import engine.bridge_character_anim as mod
    monkeypatch.setattr(mod, "capture_registered_clip",
                        lambda ch, suffix: {"clip_nif": f"{suffix}.nif"})
    ctrl = mod.BridgeCharacterAnimController(asset_resolver=lambda p: "/abs/" + p)
    r = _FakeRenderer()
    ch = _Char(14)
    ctrl.request_turn(ch)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    assert (14, "/abs/TurnCaptain.nif") in r.loaded
    # Turn-to does not load BreatheTurned (it un-turns); it holds the turn.
    assert (14, "/abs/BreatheTurned.nif") not in r.loaded


def test_node_controller_turn_chair_called_on_request_turn(monkeypatch):
    """When a node controller is attached, turn_chair is called on request_turn
    and unturn_chair on request_turn_back. Standing officers (chair=None) still
    reach the node controller (it no-ops internally for None chair)."""
    import engine.bridge_character_anim as mod
    monkeypatch.setattr(mod, "capture_registered_clip",
                        lambda ch, suffix: {"clip_nif": f"{suffix}.nif"})
    # Monkeypatch capture_chair_clip: seated officer returns a dict, standing None.
    monkeypatch.setattr(mod, "capture_chair_clip",
                        lambda ch, suffix: {"clip_nif": f"chair_{suffix}.nif"})

    class _FakeNodeCtrl:
        def __init__(self):
            self.turned = []
            self.unturned = []
        def turn_chair(self, officer, chair, *, renderer, couple=True):
            self.turned.append((officer, chair, couple))
        def unturn_chair(self, officer, chair, *, renderer):
            self.unturned.append((officer, chair))

    node_ctrl = _FakeNodeCtrl()
    ctrl = mod.BridgeCharacterAnimController()
    ctrl.set_node_controller(node_ctrl)
    r = _FakeRenderer()
    ch = _Char(15)

    ctrl.request_turn(ch)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    assert len(node_ctrl.turned) == 1
    assert node_ctrl.turned[0][0] is ch
    assert node_ctrl.turned[0][1]["clip_nif"] == "chair_TurnCaptain.nif"

    ctrl.request_turn_back(ch)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    assert len(node_ctrl.unturned) == 1
    assert node_ctrl.unturned[0][0] is ch
    assert node_ctrl.unturned[0][1]["clip_nif"] == "chair_BackCaptain.nif"


def test_chair_driven_only_when_body_clip_empty(monkeypatch):
    """The officer is coupled to the chair (couple=True) ONLY when its forward
    body turn clip is empty (Tactical). A body that rotates the officer (Helm)
    -> couple=False (seat mesh turns, officer turns via its own body clip), so
    the officer is not double-rotated. Also: an empty body clip must NOT be
    submitted to the body controller."""
    import engine.bridge_character_anim as mod
    monkeypatch.setattr(mod, "capture_registered_clip",
                        lambda ch, suffix: {"clip_nif": f"{suffix}.nif"})
    monkeypatch.setattr(mod, "capture_chair_clip",
                        lambda ch, suffix: {"clip_nif": f"chair_{suffix}.nif"})

    class _ClipRenderer(_FakeRenderer):
        def __init__(self, empty_body):
            super().__init__()
            self._empty = empty_body
        def load_animation_clips(self, path):
            if "TurnCaptain" in path and self._empty:
                return [{"duration": 0.0, "tracks": []}]          # empty body
            return [{"duration": 0.5,
                     "tracks": [{"node": "Bip01", "rotation": [(0, 0, 0, 0, 1)]}]}]

    class _FakeNodeCtrl:
        def __init__(self):
            self.turned = []
        def turn_chair(self, officer, chair, *, renderer, couple=True):
            self.turned.append(couple)
        def unturn_chair(self, officer, chair, *, renderer):
            pass

    # Empty body clip -> chair-driven (couple=True), body NOT submitted.
    nc = _FakeNodeCtrl()
    ctrl = mod.BridgeCharacterAnimController()
    ctrl.set_node_controller(nc)
    r = _ClipRenderer(empty_body=True)
    ch = _Char(20)
    ctrl.request_turn(ch)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    assert nc.turned == [True]               # coupled
    assert ctrl.is_busy(ch) is False         # empty body clip not submitted

    # Real body clip -> body-driven (couple=False), body IS submitted.
    nc2 = _FakeNodeCtrl()
    ctrl2 = mod.BridgeCharacterAnimController()
    ctrl2.set_node_controller(nc2)
    r2 = _ClipRenderer(empty_body=False)
    ch2 = _Char(21)
    ctrl2.request_turn(ch2)
    ctrl2.update(0.0, renderer=r2, anim_mgr=None)
    assert nc2.turned == [False]             # not coupled (body turns it)
    assert ctrl2.is_busy(ch2) is True        # body clip submitted + playing


def test_node_controller_not_called_when_absent(monkeypatch):
    """Without set_node_controller the body-clip logic is unchanged."""
    import engine.bridge_character_anim as mod
    monkeypatch.setattr(mod, "capture_registered_clip",
                        lambda ch, suffix: {"clip_nif": f"{suffix}.nif"})
    ctrl = mod.BridgeCharacterAnimController()
    # _node_ctrl defaults to None; no error on request_turn
    r = _FakeRenderer()
    ch = _Char(16)
    ctrl.request_turn(ch)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    assert r.played  # body clip still plays


# ── CharacterClass queue seam: is_active / stop / play_record ──────────────

from engine.appc.character_anim_queue import AnimRec


def test_play_record_turn_appends_pending_turn_with_callback():
    ctrl = BridgeCharacterAnimController()
    ch = _Char(30)
    calls = []
    rec = AnimRec(category=ctrl._CAT_TURN, name="Captain",
                  on_complete=lambda: calls.append("done"))
    ctrl.play_record(ch, rec)
    assert len(ctrl._pending_turns) == 1
    entry = ctrl._pending_turns[0]
    assert entry[0] is ch
    assert entry[1] == "Captain"
    assert entry[2] is False               # back=False
    assert entry[5] is rec.on_complete


def test_play_record_turn_back_appends_pending_turn_back_true():
    ctrl = BridgeCharacterAnimController()
    ch = _Char(31)
    rec = AnimRec(category=ctrl._CAT_TURN_BACK, name="Captain")
    ctrl.play_record(ch, rec)
    assert len(ctrl._pending_turns) == 1
    assert ctrl._pending_turns[0][2] is True    # back=True


def test_play_record_glance_appends_pending_glance_with_callback():
    ctrl = BridgeCharacterAnimController()
    ch = _Char(32)
    calls = []
    rec = AnimRec(category=ctrl._CAT_GLANCE, name="Helm",
                  on_complete=lambda: calls.append("done"))
    ctrl.play_record(ch, rec)
    assert len(ctrl._pending_glances) == 1
    entry = ctrl._pending_glances[0]
    assert entry[0] is ch
    assert entry[1] == "Helm"
    assert entry[2] is rec.on_complete


def test_play_record_breathe_with_clips_creates_active_action():
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(33)
    calls = []
    rec = AnimRec(category=ctrl._CAT_BREATHE, play=[("clip.nif", 0.0)],
                  on_complete=lambda: calls.append("done"))
    ctrl.play_record(ch, rec)
    assert ctrl.is_active(ch) is True
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    assert (33, r.loaded[(33, "clip.nif")]) in r.played


def test_play_record_breathe_no_clips_fires_completion_inline():
    ctrl = BridgeCharacterAnimController()
    ch = _Char(34)
    calls = []
    rec = AnimRec(category=ctrl._CAT_BREATHE, play=None,
                  on_complete=lambda: calls.append("done"))
    ctrl.play_record(ch, rec)
    assert calls == ["done"]
    assert ctrl.is_active(ch) is False


def test_stop_evicts_active_action_and_rescues_on_complete_once():
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(35)
    calls = []
    ctrl.submit(ch, [("g.nif", 5.0)], priority=0,
               on_complete=lambda: calls.append("done"))
    ctrl.update(0.0, renderer=r, anim_mgr=None)      # start clip, becomes active
    assert ctrl.is_active(ch) is True
    ctrl.stop(ch)
    assert calls == ["done"]
    assert ctrl.is_active(ch) is False
    # A second stop() must not re-fire the callback.
    ctrl.stop(ch)
    assert calls == ["done"]


def test_is_active_reflects_active_dict():
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(36)
    assert ctrl.is_active(ch) is False
    ctrl.submit(ch, [("g.nif", 2.0)], priority=0)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    assert ctrl.is_active(ch) is True


# ── Task 14a (BUG 2): stop() must fire pending turn/glance on_complete ──────


def test_stop_fires_pending_turn_on_complete():
    # BUG 2: a turn request sits in _pending_turns (not yet drained by
    # update()) when stop() is called. stop() must fire its on_complete
    # instead of silently discarding the entry.
    ctrl = BridgeCharacterAnimController()
    ch = _Char(40)
    calls = []
    ctrl.request_turn_to(ch, "Captain", on_complete=lambda: calls.append("turn"))
    assert len(ctrl._pending_turns) == 1
    ctrl.stop(ch)
    assert calls == ["turn"]
    assert ctrl._pending_turns == []


def test_stop_fires_pending_glance_on_complete():
    # Symmetric case for a pending glance.
    ctrl = BridgeCharacterAnimController()
    ch = _Char(41)
    calls = []
    ctrl.request_glance(ch, "Helm", on_complete=lambda: calls.append("glance"))
    assert len(ctrl._pending_glances) == 1
    ctrl.stop(ch)
    assert calls == ["glance"]
    assert ctrl._pending_glances == []


def test_play_record_fires_on_complete_when_submit_drops_the_gesture():
    # Review fix #1: play_record's gesture/clip branch must fire rec.on_complete
    # inline when submit() DROPS the action (no render instance / hidden / a
    # same-priority incumbent), mirroring _process_turn/_process_glance. By the
    # time play_record runs, _anim_play_now has already marked rec.played, so the
    # queue's ReleaseCurrentAnimation rescue is disabled -- a dropped callback
    # here is lost and the owning mission TGSequence hangs forever.
    from engine.appc.character_anim_queue import AnimRec
    ctrl = BridgeCharacterAnimController()
    ch = _Char(None)                       # no render instance -> submit refuses
    fired = []
    rec = AnimRec(category=1, name=None, flags=0, play=[("g.nif", 1.0)],
                  on_complete=lambda: fired.append(1))
    ctrl.play_record(ch, rec)
    assert fired == [1]


def test_play_record_does_not_double_fire_when_submit_accepts():
    # The flip side: when submit() ACCEPTS, the controller owns firing
    # on_complete when the clip settles -- play_record must NOT also fire it.
    ctrl = BridgeCharacterAnimController()
    ch = _Char(77)
    fired = []
    from engine.appc.character_anim_queue import AnimRec
    rec = AnimRec(category=1, name=None, flags=0, play=[("g.nif", 1.0)],
                  on_complete=lambda: fired.append(1))
    ctrl.play_record(ch, rec)
    assert fired == []                     # not yet -- clip is in flight
    assert ctrl.is_active(ch) is True
