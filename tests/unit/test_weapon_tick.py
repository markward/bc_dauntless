from engine.appc.weapon_subsystems import WeaponSystem
from engine.appc.properties import WeaponSystemProperty


class FakeWeapon:
    def __init__(self, groups=(1,), can_fire=True, dumb=False):
        self._groups = set(groups); self._can = can_fire; self._dumb = dumb
        self._fire_timer = 0.0; self._firing = False
        self._target = None; self._target_offset = None
        self.fired = 0; self.dumb_fired = 0; self.stopped = 0
    def IsMemberOfGroup(self, g): return 1 if (g == 0 or g in self._groups) else 0
    def IsDumbFire(self): return 1 if self._dumb else 0
    def CanFire(self): return 1 if self._can else 0
    def IsFiring(self): return 1 if self._firing else 0
    def StopFiring(self): self.stopped += 1
    def Fire(self, target=None, offset=None):
        self.fired += 1; self._target = target; return None
    def FireDumb(self, iReserved=0, iForce=1): self.dumb_fired += 1


def _system(weapons, chains="", single_fire=False):
    sys_ = WeaponSystem("W")
    prop = WeaponSystemProperty("W")
    if chains:
        prop.SetFiringChainString(chains)
    sys_.SetProperty(prop)
    sys_._single_fire = single_fire
    for w in weapons:
        sys_._test_weapons = getattr(sys_, "_test_weapons", [])
        sys_._test_weapons.append(w)
    sys_.GetNumWeapons = lambda: len(weapons)
    sys_.GetWeapon = lambda i: weapons[i]
    sys_.GetParentShip = lambda: None
    return sys_


def test_timer_gates_below_033_and_force_update_bypasses():
    w = FakeWeapon()
    sys_ = _system([w])
    assert sys_.try_fire_weapon(w, 0.1, None, None) is False   # 0.1 < 0.33
    assert w.fired == 0
    sys_.SetForceUpdate(1)
    assert sys_.try_fire_weapon(w, 0.016, None, None) is True  # forced to 0.33
    assert w.fired == 1


def test_canfire_failure_calls_stopfiring():
    w = FakeWeapon(can_fire=False)
    sys_ = _system([w])
    sys_.SetForceUpdate(1)
    assert sys_.try_fire_weapon(w, 0.016, None, None) is False
    assert w.stopped == 1 and w.fired == 0


def test_update_weapons_round_robin_resumes_past_last_idx():
    a, b = FakeWeapon(), FakeWeapon()
    sys_ = _system([a, b], single_fire=True)
    sys_.SetForceUpdate(1); sys_._add_target(object())
    sys_.update_weapons(0.016)
    sys_.SetForceUpdate(1)
    sys_.update_weapons(0.016)
    assert a.fired == 1 and b.fired == 1     # alternated, not a-a


def test_single_fire_stops_after_first_success():
    a, b = FakeWeapon(), FakeWeapon()
    sys_ = _system([a, b], single_fire=True)
    sys_.SetForceUpdate(1); sys_._add_target(object())
    sys_.update_weapons(0.016)
    assert a.fired + b.fired == 1


def test_multi_fire_tries_every_group_member():
    a, b = FakeWeapon(), FakeWeapon()
    sys_ = _system([a, b], single_fire=False)
    sys_.SetForceUpdate(1); sys_._add_target(object())
    sys_.update_weapons(0.016)
    assert a.fired == 1 and b.fired == 1


def test_dumbfire_fallback_only_on_zero_targets_and_dumb_weapon():
    dumb = FakeWeapon(can_fire=False, dumb=True)
    guided = FakeWeapon(can_fire=False, dumb=False)
    sys_ = _system([dumb, guided])
    sys_.SetForceUpdate(1)
    sys_.update_weapons(0.016)               # zero targets
    assert dumb.dumb_fired == 1
    assert guided.dumb_fired == 0
    dumb.dumb_fired = 0
    sys_.SetForceUpdate(1); sys_._add_target(object())
    sys_.update_weapons(0.016)               # has a target -> no fallback
    assert dumb.dumb_fired == 0


def test_group_advance_on_dry_group():
    dry = FakeWeapon(groups=(1,), can_fire=False)
    wet = FakeWeapon(groups=(2,))
    sys_ = _system([dry, wet], chains="12;Chain")
    sys_.SetForceUpdate(1); sys_._add_target(object())
    assert sys_.update_weapons(0.016) is True
    assert wet.fired == 1
    assert sys_._last_group_fired == 2
