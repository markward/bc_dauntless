import random
from engine.bridge_idle_gestures import IdleGestureScheduler


class _Controller:
    def __init__(self):
        self.submitted = []
        self._busy = set()
    def is_busy(self, ch):
        return id(ch) in self._busy
    def submit(self, ch, clips, priority):
        self.submitted.append((ch, clips, priority))
        self._busy.add(id(ch))


class _Char:
    def __init__(self, registrations, standing=1):
        self._random_animations = registrations
        self._render_instance = 1
        self._standing = standing
    def IsStanding(self):
        return self._standing
    def IsHidden(self):
        return 0
    def IsMenuUp(self):
        return 1 if getattr(self, "_menu_up", False) else 0


def _builder_returns_one_clip(monkeypatch):
    # Stub the SDK builder resolution so no real SDK import is needed.
    import engine.bridge_idle_gestures as mod
    monkeypatch.setattr(
        mod, "build_sequence_clips",
        lambda module_path, ch, anim_mgr: [("clip.nif", 1.0)],
    )


def test_fires_after_interval_and_submits_idle(monkeypatch):
    _builder_returns_one_clip(monkeypatch)
    sched = IdleGestureScheduler(random.Random(0), interval=(5.0, 5.0))
    ctrl = _Controller()
    ch = _Char([("Bridge.Characters.CommonAnimations.LookAroundConsole",)])

    sched.update(4.0, [ch], renderer=None, anim_mgr=None, controller=ctrl)
    assert ctrl.submitted == []                    # not yet
    sched.update(2.0, [ch], renderer=None, anim_mgr=None, controller=ctrl)
    assert len(ctrl.submitted) == 1
    assert ctrl.submitted[0][2] == 0               # idle priority


def test_respects_sitting_only_mode(monkeypatch):
    _builder_returns_one_clip(monkeypatch)
    sched = IdleGestureScheduler(random.Random(0), interval=(0.0, 0.0))
    ctrl = _Controller()
    from engine.appc.characters import CharacterClass
    standing_char = _Char(
        [("Bridge.Characters.CommonAnimations.Foo", CharacterClass.SITTING_ONLY)],
        standing=1,
    )
    sched.update(0.0, [standing_char], renderer=None, anim_mgr=None, controller=ctrl)
    assert ctrl.submitted == []                    # sitting-only skipped while standing


def test_skips_busy_character(monkeypatch):
    _builder_returns_one_clip(monkeypatch)
    sched = IdleGestureScheduler(random.Random(0), interval=(0.0, 0.0))
    ctrl = _Controller()
    ch = _Char([("Bridge.Characters.CommonAnimations.Foo",)])
    ctrl._busy.add(id(ch))
    sched.update(1.0, [ch], renderer=None, anim_mgr=None, controller=ctrl)
    assert ctrl.submitted == []


def test_menu_up_officer_is_suppressed(monkeypatch):
    _builder_returns_one_clip(monkeypatch)
    sched = IdleGestureScheduler(random.Random(0), interval=(0.0, 0.0))
    ctrl = _Controller()
    ch = _Char([("Bridge.Characters.CommonAnimations.Foo",)])
    ch._menu_up = True                       # IsMenuUp() -> 1 (see _Char below)
    sched.update(1.0, [ch], renderer=None, anim_mgr=None, controller=ctrl)
    assert ctrl.submitted == []              # suppressed while menu is up


# ── build_sequence_clips: the canonical MissionLib-style sequence walk ───────
# Real App classes throughout — the walk's identity reads are cast-based
# (TGSequence_Cast / CharacterAction_Cast / TGAnimAction), so duck-typed fakes
# would not be recognised, exactly as in the native engine.

class _AnimMgr:
    def __init__(self, table):
        self._table = table
    def path_for(self, name):
        return self._table.get(name)


def _install_factory(monkeypatch, seq):
    import sys, types
    fake = types.ModuleType("fake_anim_mod")
    fake.Foo = staticmethod(lambda ch: seq)
    monkeypatch.setitem(sys.modules, "fake_anim_mod", fake)


def test_build_sequence_clips_reads_sdk_getduration(monkeypatch):
    # TGAnimAction extends TGTimedAction, whose SetDuration/GetDuration are
    # real SWIG surface (sdk App.py:2473-2474) — the SDK's explicit
    # per-gesture SetDuration (e.g. CommonAnimations.ShrugRight) must land in
    # the flattened clip list.
    import App
    from engine.bridge_idle_gestures import build_sequence_clips
    seq = App.TGSequence_Create()
    act = App.TGAnimAction_Create(None, "looking_left", 0, 0)
    act.SetDuration(2.5)
    seq.AppendAction(act)
    _install_factory(monkeypatch, seq)
    clips = build_sequence_clips(
        "fake_anim_mod.Foo", object(),
        _AnimMgr({"looking_left": "data/animations/looking_left.nif"}))
    assert clips == [("data/animations/looking_left.nif", 2.5)]


def test_build_sequence_clips_recurses_nested_sequences(monkeypatch):
    # MissionLib.GetVoiceLinesFromSequence idiom: an entry may itself be a
    # TGSequence (test with TGSequence_Cast, recurse, bound by GetNumActions).
    import App
    from engine.bridge_idle_gestures import build_sequence_clips
    inner = App.TGSequence_Create()
    inner.AppendAction(App.TGAnimAction_Create(None, "nod", 0, 0))
    outer = App.TGSequence_Create()
    outer.AppendAction(inner)
    _install_factory(monkeypatch, outer)
    clips = build_sequence_clips(
        "fake_anim_mod.Foo", object(),
        _AnimMgr({"nod": "data/animations/nod.nif"}))
    assert clips == [("data/animations/nod.nif", 0.0)]


def test_build_sequence_clips_flattens_play_animation_file(monkeypatch):
    # A CharacterAction in the walked sequence is read via the canonical
    # CharacterAction_Cast + GetActionType/GetDetail idiom. For
    # AT_PLAY_ANIMATION_FILE the detail is a bare registered clip name, so
    # path_for(detail) applies directly; there is no native duration (no such
    # getter on CharacterAction) — 0.0 lets the controller resolve the clip's
    # real length.
    import App
    from engine.bridge_idle_gestures import build_sequence_clips
    from engine.appc.ai import CharacterAction
    seq = App.TGSequence_Create()
    seq.AppendAction(App.CharacterAction_Create(
        None, CharacterAction.AT_PLAY_ANIMATION_FILE, "db_P_Point_C_P", None, 1))
    _install_factory(monkeypatch, seq)
    clips = build_sequence_clips(
        "fake_anim_mod.Foo", object(),
        _AnimMgr({"db_P_Point_C_P": "data/animations/point.nif"}))
    assert clips == [("data/animations/point.nif", 0.0)]


def test_build_sequence_clips_skips_non_animation_actions(monkeypatch):
    # Speak lines (and any other non-animation CharacterAction verb) must not
    # be flattened into the gesture clip list even when the anim manager could
    # resolve their detail string to a path — the walk filters on
    # GetActionType, it does not blindly path_for every detail.
    import App
    from engine.bridge_idle_gestures import build_sequence_clips
    from engine.appc.ai import CharacterAction
    seq = App.TGSequence_Create()
    seq.AppendAction(App.CharacterAction_Create(
        None, CharacterAction.AT_SAY_LINE, "E1M1_HELM_025", None, 1))
    _install_factory(monkeypatch, seq)
    clips = build_sequence_clips(
        "fake_anim_mod.Foo", object(),
        _AnimMgr({"E1M1_HELM_025": "data/animations/wrong.nif"}))
    assert clips == []
