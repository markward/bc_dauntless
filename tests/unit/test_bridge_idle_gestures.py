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
