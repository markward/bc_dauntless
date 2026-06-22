from engine.appc import warp_gates as wg


class _Sub:
    def __init__(self, disabled=False, on=True, power=1.0):
        self._d, self._on, self._p = disabled, on, power
    def IsDisabled(self): return 1 if self._d else 0
    def IsOn(self): return 1 if self._on else 0
    def GetPowerPercentageWanted(self): return self._p


class _Ship:
    def __init__(self, impulse=None, warp=None):
        self._imp, self._warp = impulse, warp
    def GetImpulseEngineSubsystem(self): return self._imp
    def GetWarpEngineSubsystem(self): return self._warp
    def GetContainingSet(self): return None


def test_all_clear_allows():
    r = wg.warp_gate(_Ship(_Sub(), _Sub()))
    assert r.allowed is True and r.deny_line is None


def test_impulse_off_deferred_allows_without_power_model():
    # Power-allocation gate is deferred (no Engines power category modeled yet),
    # so a power-wanted-0.0 ship is NOT blocked under normal play.
    r = wg.warp_gate(_Ship(_Sub(power=0.0), _Sub()))
    assert r.allowed is True


def test_impulse_off_blocks_when_power_modeled(monkeypatch):
    # The faithful logic is preserved: flip the flag and it blocks (XO line).
    monkeypatch.setattr(wg, "_POWER_MODEL_AVAILABLE", True)
    r = wg.warp_gate(_Ship(_Sub(power=0.0), _Sub()))
    assert (r.allowed, r.deny_line) == (False, "EngineeringNeedPowerToEngines")


def test_warp_disabled_blocks_cantwarp1():
    # The damage gate is always active (IsDisabled is real, modeled state).
    r = wg.warp_gate(_Ship(_Sub(), _Sub(disabled=True)))
    assert (r.allowed, r.deny_line) == (False, "CantWarp1")


def test_warp_off_deferred_allows_without_power_model():
    r = wg.warp_gate(_Ship(_Sub(), _Sub(on=False)))
    assert r.allowed is True


def test_warp_off_blocks_when_power_modeled(monkeypatch):
    monkeypatch.setattr(wg, "_POWER_MODEL_AVAILABLE", True)
    r = wg.warp_gate(_Ship(_Sub(), _Sub(on=False)))
    assert (r.allowed, r.deny_line) == (False, "CantWarp5")


def test_no_warp_subsystem_blocks_silently():
    r = wg.warp_gate(_Ship(_Sub(), None))
    assert r.allowed is False and r.deny_line is None and r.silent is True


def test_no_ship_blocks_silently():
    r = wg.warp_gate(None)
    assert r.allowed is False and r.silent is True


def test_order_impulse_before_warp_when_power_modeled(monkeypatch):
    # With the power model on, both impulse-off and warp-disabled hold ->
    # impulse (XO) line wins (WarpPressed order).
    monkeypatch.setattr(wg, "_POWER_MODEL_AVAILABLE", True)
    r = wg.warp_gate(_Ship(_Sub(power=0.0), _Sub(disabled=True)))
    assert r.deny_line == "EngineeringNeedPowerToEngines"


def test_power_deferred_impulse_off_falls_through_to_warp_damage():
    # Default (power deferred): impulse-off is skipped, so a damaged warp engine
    # is the deciding block.
    r = wg.warp_gate(_Ship(_Sub(power=0.0), _Sub(disabled=True)))
    assert (r.allowed, r.deny_line) == (False, "CantWarp1")


class _RaisingShip:
    """Ship whose subsystem accessors raise — must not propagate out of
    warp_gate (invariant: warp_gate never raises; internal error fails open)."""
    def __init__(self, raise_on_impulse=False, raise_on_warp=True):
        self._ri, self._rw = raise_on_impulse, raise_on_warp
    def GetImpulseEngineSubsystem(self):
        if self._ri:
            raise RuntimeError("malformed ship: impulse accessor")
        return _Sub()
    def GetWarpEngineSubsystem(self):
        if self._rw:
            raise RuntimeError("malformed ship: warp accessor")
        return _Sub()
    def GetContainingSet(self): return None


def test_warp_accessor_raising_fails_open():
    # GetWarpEngineSubsystem() raises -> warp_gate must not raise, fails open.
    r = wg.warp_gate(_RaisingShip(raise_on_warp=True))
    assert r.allowed is True


def test_impulse_accessor_raising_fails_open():
    # GetImpulseEngineSubsystem() raises -> warp_gate must not raise, fails open.
    r = wg.warp_gate(_RaisingShip(raise_on_impulse=True, raise_on_warp=False))
    assert r.allowed is True


def test_nebula_gate_blocks_cantwarp2(monkeypatch):
    from engine.appc import warp_gates as wg
    monkeypatch.setattr(wg, "_in_nebula", lambda s: True)
    r = wg.warp_gate(_Ship(_Sub(), _Sub()))
    assert (r.allowed, r.deny_line) == (False, "CantWarp2")


def test_asteroid_gate_blocks_cantwarp4(monkeypatch):
    from engine.appc import warp_gates as wg
    monkeypatch.setattr(wg, "_in_asteroid_field", lambda s: True)
    r = wg.warp_gate(_Ship(_Sub(), _Sub()))
    assert (r.allowed, r.deny_line) == (False, "CantWarp4")


def test_starbase_gate_inside_point_visibility(monkeypatch):
    import App
    from engine.appc import warp_gates as wg
    from engine.appc.sets import SetClass_Create

    App.g_kSetManager._sets.clear()
    sb_set = SetClass_Create()
    App.g_kSetManager.AddSet(sb_set, "Starbase12")

    starbase = App.ShipClass_Create()
    starbase.SetName("Starbase 12")
    starbase.SetTranslateXYZ(0.0, 0.0, 0.0)
    starbase.Update(0)
    sb_set.AddObjectToSet(starbase, "Starbase 12")

    # Give the starbase one "Inside Visibility 1" position-orientation property.
    pos = App.PositionOrientationProperty_Create("Inside Visibility 1")
    fwd = App.TGPoint3()
    fwd.SetXYZ(0.0, 1.0, 0.0)
    up = App.TGPoint3()
    up.SetXYZ(0.0, 0.0, 1.0)
    pos.SetOrientation(fwd, up, fwd)
    p = App.TGPoint3()
    p.SetXYZ(5.0, 0.0, 0.0)
    pos.SetPosition(p)
    # Real property-set add API: TGModelPropertySet.AddToSet(node_name, prop)
    # (engine/appc/properties.py); there is no AddProperty.
    starbase.GetPropertySet().AddToSet("Scene Root", pos)

    player = App.ShipClass_Create()
    player.SetName("player")
    player.SetTranslateXYZ(10.0, 0.0, 0.0)
    player.Update(0)
    sb_set.AddObjectToSet(player, "player")

    # Hook says the segment does NOT hit the starbase -> inside point is
    # visible -> in view -> blocked.
    wg.configure_gate_hooks(ray_collide=lambda sb, a, b: False)
    assert wg._near_starbase(player) is True

    # Now the segment DOES hit the starbase -> point occluded -> not in view.
    wg.configure_gate_hooks(ray_collide=lambda sb, a, b: True)
    assert wg._near_starbase(player) is False

    # No hook -> can't evaluate -> don't block.
    wg.configure_gate_hooks(ray_collide=None)
    assert wg._near_starbase(player) is False

    App.g_kSetManager._sets.clear()


def test_block_carries_human_reason():
    # dev-mode logging needs a human-readable reason on every block.
    r = wg.warp_gate(_Ship(_Sub(), _Sub(disabled=True)))
    assert r.allowed is False and r.reason and "warp engine disabled" in r.reason
    r2 = wg.warp_gate(_Ship(_Sub(), None))   # silent block still has a reason
    assert r2.allowed is False and r2.reason == "no warp engine subsystem"
    r3 = wg.warp_gate(None)
    assert r3.reason == "no player ship"
