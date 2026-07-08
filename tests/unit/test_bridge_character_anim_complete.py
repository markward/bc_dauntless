from engine.bridge_character_anim import BridgeCharacterAnimController


class _FakeRenderer:
    def __init__(self, clip_dur=1.0):
        self._next = 10
        self._dur = clip_dur
        self.gestures = []
        self.idled = []
        self.restored = []
    def load_instance_clip(self, iid, path):
        self._next += 1
        return self._next
    def play_instance_gesture(self, iid, ci):
        self.gestures.append((iid, ci))
    def play_instance_idle(self, iid, ci):
        self.idled.append((iid, ci))
    def restore_rest_pose(self, iid):
        self.restored.append(iid)
    def load_animation_clips(self, path):
        # Non-empty + a rotation track => _body_turns_officer -> body-driven.
        return [{"duration": self._dur,
                 "tracks": [{"rotation": [(0.0, (0, 0, 0, 1))]}]}]


class _EmptyBodyRenderer(_FakeRenderer):
    def load_animation_clips(self, path):
        return []                       # empty clip => chair-driven officer


class _Char:
    def __init__(self, iid=77, name="Picard", loc="DBGuest"):
        self._render_instance = iid
        self._name = name
        self._location = loc
    def GetCharacterName(self):
        return self._name
    def GetLocation(self):
        return self._location
    def IsHidden(self):
        return 0


class _HiddenChar(_Char):
    def IsHidden(self):
        return 1


def _patch_clips(monkeypatch, chair=None):
    import engine.bridge_character_anim as m
    monkeypatch.setattr(m, "capture_registered_clip",
                        lambda ch, suffix: {"clip_nif": suffix + ".nif"})
    monkeypatch.setattr(m, "capture_chair_clip", lambda ch, suffix: chair)


def test_submit_on_complete_fires_once_on_settle(monkeypatch):
    _patch_clips(monkeypatch)
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer(clip_dur=1.0)
    ch = _Char()
    fired = []
    ctrl.submit(ch, [("clip.nif", 0.0)], priority=1,
                on_complete=lambda: fired.append(True))
    ctrl.update(0.0, renderer=r)        # start clip 0
    ctrl.update(2.0, renderer=r)        # elapsed >= dur -> settle
    assert fired == [True]
    ctrl.update(0.1, renderer=r)        # no double-fire (action popped)
    assert fired == [True]


def test_submit_without_on_complete_is_unchanged(monkeypatch):
    _patch_clips(monkeypatch)
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer(clip_dur=1.0)
    ch = _Char()
    ctrl.submit(ch, [("clip.nif", 0.0)], priority=1)   # no on_complete
    ctrl.update(0.0, renderer=r)
    ctrl.update(2.0, renderer=r)                        # settles, returns to rest
    assert r.restored == [77]                           # menu-path behaviour intact


def test_request_turn_to_body_driven_defers_then_completes(monkeypatch):
    _patch_clips(monkeypatch)
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer(clip_dur=1.0)
    ch = _Char()
    fired = []
    ctrl.request_turn_to(ch, "Captain", on_complete=lambda: fired.append(True))
    ctrl.update(0.0, renderer=r)        # drain -> submit body clip (hold=True)
    assert fired == []                  # deferred
    ctrl.update(2.0, renderer=r)        # hold-point reached
    assert fired == [True]


def test_request_turn_to_chair_driven_completes_inline(monkeypatch):
    _patch_clips(monkeypatch)
    ctrl = BridgeCharacterAnimController()
    r = _EmptyBodyRenderer()            # empty body clip => chair-driven
    ch = _Char()
    fired = []
    ctrl.request_turn_to(ch, "Captain", on_complete=lambda: fired.append(True))
    ctrl.update(0.0, renderer=r)        # no body _Action -> inline completion
    assert fired == [True]


def test_request_turn_to_now_completes_inline(monkeypatch):
    _patch_clips(monkeypatch)
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer(clip_dur=1.0)
    ch = _Char()
    fired = []
    ctrl.request_turn_to(ch, "Captain", now=True,
                         on_complete=lambda: fired.append(True))
    ctrl.update(0.0, renderer=r)        # now -> inline, does not wait for settle
    assert fired == [True]


def test_request_turn_to_hidden_character_completes_inline(monkeypatch):
    # Regression: submit() no-ops (IsHidden) without creating an _Action, so
    # body_submitted must reflect that -> on_complete fires inline instead of
    # being silently dropped waiting on an _Action that never exists.
    _patch_clips(monkeypatch)
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer(clip_dur=1.0)     # body-driven clip (would defer if visible)
    ch = _HiddenChar()
    fired = []
    ctrl.request_turn_to(ch, "Captain", on_complete=lambda: fired.append(True))
    ctrl.update(0.0, renderer=r)        # hidden -> body clip never submitted
    assert fired == [True]


def test_request_turn_back_delegates(monkeypatch):
    _patch_clips(monkeypatch)
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer(clip_dur=1.0)
    ch = _Char()
    ctrl.request_turn_back(ch)          # menu path, no on_complete
    ctrl.update(0.0, renderer=r)        # must not raise; drains cleanly
    ctrl.update(2.0, renderer=r)
