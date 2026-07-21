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
    """Retained only to satisfy the handler's constructor signature; the
    handler no longer submits through it."""
    def submit(self, ch, clips, priority):
        raise AssertionError("handler must not call controller.submit anymore")


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
    CAT_NON_INTERRUPTABLE = 2

    def __init__(self):
        self._render_instance = 3
        self._animations = [("DBGuestReactRight",
                             "Bridge.Characters.CommonAnimations.ReactRight")]
        self._going_to_animate = 0
        self.cleared = 0
        self.enqueued = []

    def IsHidden(self): return 0

    def ClearExtraAnimations(self):
        self.cleared += 1

    def IsGoingToAnimate(self):
        return self._going_to_animate

    def SetCurrentAnimation(self, play, category, flags=0, name=None, **kw):
        self.enqueued.append((play, category))


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
    assert ch.cleared == 1                          # ClearExtraAnimations ran first
    assert len(ch.enqueued) == 1
    play, category = ch.enqueued[0]
    assert category == 2                            # CAT_NON_INTERRUPTABLE
    assert play == [("react.nif", 0.4)]


def test_handler_ignores_non_player_hits():
    ctrl = _Controller()
    ship, other = _Ship(), _Ship()
    ch = _Char()
    handler = HitReactionHandler(ctrl, get_player=lambda: ship,
                                 get_characters=lambda: [ch], anim_mgr=None)
    handler.on_weapon_hit(_Event(other, 99.0, _Vec(1, 0, 0)))
    assert ch.enqueued == []
    assert ch.cleared == 0


class _CharBlast:
    """Officer whose Blast reaction is registered with a *Fly* key (as in the SDK)."""
    CAT_NON_INTERRUPTABLE = 2

    def __init__(self):
        self._render_instance = 7
        self._animations = [
            ("EBG2MFly", "Bridge.Characters.CommonAnimations.Blast"),
        ]
        self._going_to_animate = 0
        self.cleared = 0
        self.enqueued = []

    def IsHidden(self): return 0

    def ClearExtraAnimations(self):
        self.cleared += 1

    def IsGoingToAnimate(self):
        return self._going_to_animate

    def SetCurrentAnimation(self, play, category, flags=0, name=None, **kw):
        self.enqueued.append((play, category))


def test_blast_resolves_via_fly_keyed_registration(monkeypatch):
    """Blast reaction must resolve even though the SDK key ends in 'Fly', not 'Blast'.

    Under the old endswith(reaction) logic this test fails because
    'EBG2MFly'.endswith('Blast') is False.  The fix matches on the module-path
    function name (entry[1].rsplit('.',1)[-1] == reaction) which is unambiguous.
    """
    import engine.bridge_hit_reactions as mod
    monkeypatch.setattr(mod, "build_sequence_clips",
                        lambda module_path, ch, anim_mgr: [("blast.nif", 1.2)])
    ctrl = _Controller()
    ship = _Ship()
    ch = _CharBlast()
    handler = HitReactionHandler(ctrl, get_player=lambda: ship,
                                 get_characters=lambda: [ch], anim_mgr=None)
    # damage >= 120 -> Blast severity
    handler.on_weapon_hit(_Event(ship, 150.0, _Vec(5.0, 0.0, 0.0)))
    assert ch.cleared == 1
    assert len(ch.enqueued) == 1, (
        "Blast reaction never resolved — _resolve_key still using key suffix?"
    )
    play, category = ch.enqueued[0]
    assert category == 2   # CAT_NON_INTERRUPTABLE
    assert play == [("blast.nif", 1.2)]


def test_handler_skips_reaction_when_already_going_to_animate(monkeypatch):
    """RE gate: ClearExtraAnimations() runs unconditionally, but the reaction
    is only enqueued if the officer is not already committed to a queued
    animation (a cat2/3/4 record already sitting in the queue)."""
    import engine.bridge_hit_reactions as mod
    monkeypatch.setattr(mod, "build_sequence_clips",
                        lambda module_path, ch, anim_mgr: [("react.nif", 0.4)])
    ctrl = _Controller()
    ship = _Ship()
    ch = _Char()
    ch._going_to_animate = 1
    handler = HitReactionHandler(ctrl, get_player=lambda: ship,
                                 get_characters=lambda: [ch], anim_mgr=None)
    handler.on_weapon_hit(_Event(ship, 5.0, _Vec(10.0, 0.0, 0.0)))
    assert ch.cleared == 1          # ClearExtraAnimations still ran
    assert ch.enqueued == []        # but the reaction was not enqueued
