from engine.bridge_character_anim import BridgeCharacterAnimController


class _FakeRenderer:
    def __init__(self):
        self.loaded = {}        # (iid, path) -> clip_index
        self.played = []        # (iid, clip_index)
        self.restored = []      # iid
        self._next = 1
    def load_instance_clip(self, iid, path):
        key = (iid, path)
        if key not in self.loaded:
            self._next += 1
            self.loaded[key] = self._next
        return self.loaded[key]
    def set_instance_animation(self, iid, clip_index, loop=False):
        self.played.append((iid, clip_index))
    def restore_rest_pose(self, iid):
        self.restored.append(iid)


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
