"""WeaponSystem dispatch through the BC tick (StartFiring arms, the
immediate forced update_weapons(0.0) dispatches this frame).

Multi-fire (default `_single_fire = False`): every eligible group member
fires in one tick.  Single-fire: one eligible emitter per tick, round-robin
via `_last_weapon_idx`.  StopFiring halts every child and disarms.
No-eligible-emitter case is a silent no-op (no Fire calls).
"""
from engine.appc.subsystems import WeaponSystem, ShipSubsystem


class _StubEmitter(ShipSubsystem):
    """Standalone child fitting the WeaponSystem firing contract."""
    def __init__(self, name, can_fire=True):
        super().__init__(name)
        self._can_fire = can_fire
        self.fire_calls = []
        self.stop_calls = 0
        self._firing = False

    def CanFire(self):
        return 1 if self._can_fire else 0

    def Fire(self, target, offset):
        self._firing = True
        self.fire_calls.append((target, offset))
        return True

    def IsFiring(self):
        return 1 if self._firing else 0

    def StopFiring(self):
        self._firing = False
        self.stop_calls += 1

    # Explicit (not the truthy TGObject _Stub): all in group 0, not dumbfire.
    def IsMemberOfGroup(self, g):
        return 1

    def IsDumbFire(self):
        return 0


def _system_with(emitters, single_fire=False):
    ws = WeaponSystem("Group")
    ws.TurnOn()
    ws._single_fire = single_fire
    for e in emitters:
        ws.AddChildSubsystem(e)
    return ws


def test_start_firing_no_ops_when_off():
    e = _StubEmitter("E0")
    ws = WeaponSystem("Off")
    ws.AddChildSubsystem(e)
    # Off by default; StartFiring should not call Fire.
    ws.StartFiring(target=None, offset=None)
    assert e.fire_calls == []


def test_start_firing_no_ops_when_no_emitters():
    ws = WeaponSystem("Empty")
    ws.TurnOn()
    ws.StartFiring(target=None, offset=None)   # must not raise
    ws.StopFiring()
    assert ws.IsFiring() == 0


def test_multi_fire_engages_all_eligible():
    """Default multi-fire: one trigger fires every eligible group member
    in the same tick (BC §3.2 walk — SetSingleFire(0) hardpoints)."""
    a = _StubEmitter("A")
    b = _StubEmitter("B")
    ws = _system_with([a, b])
    ws.StartFiring(target="T", offset="O")
    assert a.fire_calls == [("T", "O")]
    assert b.fire_calls == [("T", "O")]
    assert ws.IsFiring() == 1


def test_single_fire_picks_one_emitter():
    a = _StubEmitter("A")
    b = _StubEmitter("B")
    ws = _system_with([a, b], single_fire=True)
    ws.StartFiring(target="T", offset="O")
    assert a.fire_calls == [("T", "O")]
    assert b.fire_calls == []
    assert ws.IsFiring() == 1


def test_single_fire_cursor_advances_after_fire():
    a = _StubEmitter("A")
    b = _StubEmitter("B")
    c = _StubEmitter("C")
    ws = _system_with([a, b, c], single_fire=True)
    ws.StartFiring(None, None)
    ws.StopFiring()
    ws.StartFiring(None, None)
    assert len(a.fire_calls) == 1
    assert len(b.fire_calls) == 1
    assert len(c.fire_calls) == 0


def test_single_fire_cursor_wraps_around():
    a = _StubEmitter("A")
    b = _StubEmitter("B")
    ws = _system_with([a, b], single_fire=True)
    for _ in range(3):
        ws.StartFiring(None, None)
        ws.StopFiring()
    # 3 clicks across 2 emitters → A,B,A
    assert len(a.fire_calls) == 2
    assert len(b.fire_calls) == 1


def test_cursor_skips_ineligible_emitters():
    a = _StubEmitter("A", can_fire=False)
    b = _StubEmitter("B", can_fire=True)
    ws = _system_with([a, b], single_fire=True)
    ws.StartFiring(None, None)
    assert a.fire_calls == []
    assert b.fire_calls == [(None, None)]


def test_no_eligible_emitter_fires_nothing():
    a = _StubEmitter("A", can_fire=False)
    b = _StubEmitter("B", can_fire=False)
    ws = _system_with([a, b])
    ws.StartFiring(None, None)
    assert a.fire_calls == []
    assert b.fire_calls == []
    # The trigger stays armed (IsFiring reflects the held trigger); release
    # disarms.
    ws.StopFiring()
    assert ws.IsFiring() == 0


def test_stop_firing_halts_active_emitters():
    a = _StubEmitter("A")
    ws = _system_with([a])
    ws.StartFiring(None, None)
    assert ws.IsFiring() == 1
    ws.StopFiring()
    assert ws.IsFiring() == 0
    assert a.stop_calls >= 1


def test_is_firing_when_no_emitters():
    ws = WeaponSystem("Empty")
    assert ws.IsFiring() == 0
