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


def test_request_turn_swaps_idle_and_submits_turn(monkeypatch):
    import engine.bridge_character_anim as mod
    monkeypatch.setattr(mod, "capture_registered_clip",
                        lambda ch, suffix: {"clip_nif": f"{suffix}.nif"})
    ctrl = mod.BridgeCharacterAnimController()      # identity asset_resolver
    r = _FakeRenderer()
    ch = _Char(11)
    ctrl.request_turn(ch)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    # BreatheTurned became the default idle; the TurnCaptain transient is playing.
    bt_idx = r.loaded[(11, "BreatheTurned.nif")]
    tc_idx = r.loaded[(11, "TurnCaptain.nif")]
    assert ctrl._idle_clips[11] == bt_idx
    assert r.played[-1] == (11, tc_idx)


def test_request_turn_back_restores_normal_breathe(monkeypatch):
    import engine.bridge_character_anim as mod
    monkeypatch.setattr(mod, "capture_registered_clip",
                        lambda ch, suffix: {"clip_nif": f"{suffix}.nif"})
    ctrl = mod.BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(12)
    ctrl.request_turn_back(ch)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    breathe_idx = r.loaded[(12, "Breathe.nif")]
    back_idx = r.loaded[(12, "BackCaptain.nif")]
    assert ctrl._idle_clips[12] == breathe_idx
    assert r.played[-1] == (12, back_idx)


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
    assert (14, "/abs/BreatheTurned.nif") in r.loaded
    assert (14, "/abs/TurnCaptain.nif") in r.loaded
