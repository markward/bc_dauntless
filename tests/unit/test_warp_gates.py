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


def test_impulse_off_blocks_with_xo_line():
    r = wg.warp_gate(_Ship(_Sub(power=0.0), _Sub()))
    assert r.allowed is False
    assert r.deny_line == "EngineeringNeedPowerToEngines"


def test_warp_disabled_blocks_cantwarp1():
    r = wg.warp_gate(_Ship(_Sub(), _Sub(disabled=True)))
    assert (r.allowed, r.deny_line) == (False, "CantWarp1")


def test_warp_off_blocks_cantwarp5():
    r = wg.warp_gate(_Ship(_Sub(), _Sub(on=False)))
    assert (r.allowed, r.deny_line) == (False, "CantWarp5")


def test_no_warp_subsystem_blocks_silently():
    r = wg.warp_gate(_Ship(_Sub(), None))
    assert r.allowed is False and r.deny_line is None and r.silent is True


def test_no_ship_blocks_silently():
    r = wg.warp_gate(None)
    assert r.allowed is False and r.silent is True


def test_order_impulse_before_warp():
    # both impulse-off and warp-disabled -> impulse (XO) line wins
    r = wg.warp_gate(_Ship(_Sub(power=0.0), _Sub(disabled=True)))
    assert r.deny_line == "EngineeringNeedPowerToEngines"


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
