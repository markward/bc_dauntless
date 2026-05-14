"""WeaponSystem cursor-based firing: each StartFiring fires the next
eligible emitter in round-robin order.  StopFiring halts current firers.
No-eligible-emitter case is a silent no-op.

These tests use a minimal stub emitter so Task 3 lands without depending
on energy/torp Fire() semantics (Tasks 4/5).
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

    def StopFiring(self):
        self._firing = False
        self.stop_calls += 1


def _system_with(emitters):
    ws = WeaponSystem("Group")
    ws.TurnOn()
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
    ws.StartFiring(target=None, offset=None)
    # No emitters; must not raise, IsFiring stays 0.
    assert ws.IsFiring() == 0


def test_start_firing_picks_first_emitter():
    a = _StubEmitter("A")
    b = _StubEmitter("B")
    ws = _system_with([a, b])
    ws.StartFiring(target="T", offset="O")
    assert a.fire_calls == [("T", "O")]
    assert b.fire_calls == []
    assert ws.IsFiring() == 1


def test_cursor_advances_after_fire():
    a = _StubEmitter("A")
    b = _StubEmitter("B")
    c = _StubEmitter("C")
    ws = _system_with([a, b, c])
    ws.StartFiring(None, None)
    ws.StopFiring()
    ws.StartFiring(None, None)
    assert len(a.fire_calls) == 1
    assert len(b.fire_calls) == 1
    assert len(c.fire_calls) == 0


def test_cursor_wraps_around():
    a = _StubEmitter("A")
    b = _StubEmitter("B")
    ws = _system_with([a, b])
    for _ in range(3):
        ws.StartFiring(None, None)
        ws.StopFiring()
    # 3 clicks across 2 emitters → A,B,A
    assert len(a.fire_calls) == 2
    assert len(b.fire_calls) == 1


def test_cursor_skips_ineligible_emitters():
    a = _StubEmitter("A", can_fire=False)
    b = _StubEmitter("B", can_fire=True)
    ws = _system_with([a, b])
    ws.StartFiring(None, None)
    assert a.fire_calls == []
    assert b.fire_calls == [(None, None)]


def test_no_eligible_emitter_silent_no_op():
    a = _StubEmitter("A", can_fire=False)
    b = _StubEmitter("B", can_fire=False)
    ws = _system_with([a, b])
    ws.StartFiring(None, None)
    assert ws.IsFiring() == 0
    assert a.fire_calls == []
    assert b.fire_calls == []


def test_stop_firing_halts_active_emitters():
    a = _StubEmitter("A")
    ws = _system_with([a])
    ws.StartFiring(None, None)
    assert ws.IsFiring() == 1
    ws.StopFiring()
    assert ws.IsFiring() == 0
    assert a.stop_calls == 1


def test_is_firing_when_no_emitters():
    ws = WeaponSystem("Empty")
    assert ws.IsFiring() == 0
