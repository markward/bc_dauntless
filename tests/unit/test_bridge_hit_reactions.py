from engine.bridge_hit_reactions import select_reaction, HitReactionHandler

# Severity thresholds (verify against combat damage magnitudes in tuning):
#   damage < 15  -> light lean (ReactLeft/ReactRight by bearing)
#   15..50       -> HitStanding
#   >= 50        -> HitHardStanding ; >= 120 -> Blast


def test_select_reaction_by_severity_and_direction():
    assert select_reaction(bearing_dot=+1.0, damage=5.0) == "ReactRight"
    assert select_reaction(bearing_dot=-1.0, damage=5.0) == "ReactLeft"
    assert select_reaction(bearing_dot=0.2, damage=30.0) == "HitStanding"
    assert select_reaction(bearing_dot=0.2, damage=80.0) == "HitHardStanding"
    assert select_reaction(bearing_dot=0.2, damage=200.0) == "Blast"


class _Controller:
    def __init__(self):
        self.submitted = []
    def submit(self, ch, clips, priority):
        self.submitted.append((ch, clips, priority))


class _Vec:
    def __init__(self, x, y, z): self.x, self.y, self.z = x, y, z
    def GetX(self): return self.x
    def GetY(self): return self.y
    def GetZ(self): return self.z


class _Col:
    def __init__(self, v): self._v = v
    def GetCol(self, i): return self._v        # always return the right axis


class _Ship:
    def __init__(self): pass
    def GetWorldLocation(self): return _Vec(0.0, 0.0, 0.0)
    def GetWorldRotation(self): return _Col(_Vec(1.0, 0.0, 0.0))   # right = +X


class _Char:
    def __init__(self):
        self._render_instance = 3
        self._animations = [("DBGuestReactRight",
                             "Bridge.Characters.CommonAnimations.ReactRight")]
    def IsHidden(self): return 0


class _Event:
    def __init__(self, target, damage, hit):
        self._t, self._d, self._h = target, damage, hit
    def GetTarget(self): return self._t
    def GetDamage(self): return self._d
    def GetHitPoint(self): return self._h


def test_handler_submits_directional_reaction(monkeypatch):
    import engine.bridge_hit_reactions as mod
    monkeypatch.setattr(mod, "build_sequence_clips",
                        lambda module_path, ch, anim_mgr: [("react.nif", 0.4)])
    ctrl = _Controller()
    ship = _Ship()
    ch = _Char()
    handler = HitReactionHandler(ctrl, get_player=lambda: ship,
                                 get_characters=lambda: [ch], anim_mgr=None)
    # Hit to starboard (+X): bearing_dot > 0 -> ReactRight, key DBGuestReactRight.
    handler.on_weapon_hit(_Event(ship, 5.0, _Vec(10.0, 0.0, 0.0)))
    assert len(ctrl.submitted) == 1
    assert ctrl.submitted[0][2] == 1               # reaction priority


def test_handler_ignores_non_player_hits():
    ctrl = _Controller()
    ship, other = _Ship(), _Ship()
    handler = HitReactionHandler(ctrl, get_player=lambda: ship,
                                 get_characters=lambda: [_Char()], anim_mgr=None)
    handler.on_weapon_hit(_Event(other, 99.0, _Vec(1, 0, 0)))
    assert ctrl.submitted == []
