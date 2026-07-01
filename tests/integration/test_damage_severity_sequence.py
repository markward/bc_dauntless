"""Integration test for the full damage pipeline:
shields → hull bleed → subsystem flip → severity stream
SHIELD → HULL → CRITICAL → HULL.

Mocks the renderer and audio; asserts mutual-exclusivity (no tick has
both a shield_hit call and a hit_vfx descriptor pushed for the same
impact) and asserts the severity sequence.
"""
import pytest

from engine import host_io
from engine.appc import combat, hit_feedback, hit_vfx, camera_shake
from engine.appc.hit_feedback import Severity
from engine.appc.math import TGPoint3


# ── fixtures ───────────────────────────────────────────────────────────────


class _HullMarker:
    def GetCondition(self): return 1000.0


class _Shield:
    """6-face shield with FRONT (index 0) charged to `front_charge`.
    ApplyDamage on FRONT subtracts up to front_charge, returns overflow."""
    def __init__(self, front_charge):
        self._charges = [0.0] * 6
        self._charges[0] = float(front_charge)
    def ApplyDamage(self, face, dmg):
        absorb = min(self._charges[face], dmg)
        self._charges[face] -= absorb
        return dmg - absorb


class _Sensors:
    """Subsystem with MaxCondition=100, DisabledPercentage=0.5.

    IsDamaged flips True on the first tick condition drops below max
    (realistic SDK semantics). IsDisabled flips True once condition
    drops to 50% of max. IsDestroyed flips True once condition reaches
    zero. The narrowed CRITICAL rule excludes IsDamaged transitions,
    so this stub now matches what a real ShipSubsystem would look like.
    """
    def __init__(self):
        self.condition = 100.0
        self._max = 100.0
    def GetCondition(self): return self.condition
    def GetMaxCondition(self): return self._max
    def IsDamaged(self): return self.condition < self._max
    def IsDisabled(self): return self.condition <= 0.5 * self._max
    def IsDestroyed(self): return self.condition <= 0.0
    def GetPosition(self):
        return TGPoint3(0.0, 0.0, 0.0)
    def GetRadius(self):
        return 1000.0


class _Ship:
    def __init__(self, hull, shields, sensors):
        self._hull = hull
        self._shields = shields
        self._sensors = sensors
        self._loc = TGPoint3(0.0, 0.0, 0.0)
    def GetHull(self): return self._hull
    def GetShields(self): return self._shields
    def GetWorldLocation(self): return self._loc
    def GetSubsystems(self):
        return [self._sensors]
    def DamageSystem(self, sub, amount, source=None):
        if isinstance(sub, _Sensors):
            sub.condition = max(0.0, sub.condition - float(amount))
        # Hull DamageSystem is a no-op for this test (we only care about
        # the routing, not the hull condition).


class _ShieldHitSpy:
    """Captures only what mutual-exclusivity needs (instance_id + point).
    Positional-arg signature matching host_io.shield_hit; rgba/intensity are
    accepted but not stored — this test doesn't assert against them."""
    def __init__(self):
        self.shield_hit_calls = []
    def __call__(self, instance_id, point, rgba=(0.0, 0.0, 0.0, 0.0),
                 intensity=1.0):
        self.shield_hit_calls.append({"point": point, "instance_id": instance_id})


@pytest.fixture
def setup(monkeypatch):
    """Build ship + host_io shield-hit spy + camera-shake calls."""
    hit_vfx._active.clear()
    camera_shake.reset()

    hull = _HullMarker()
    shields = _Shield(front_charge=100.0)
    sensors = _Sensors()
    ship = _Ship(hull, shields, sensors)
    # Route the shield flash through the host_io spy; neutralize the sibling
    # wrappers so the decal / carve / spark paths never hit the real native.
    host = _ShieldHitSpy()
    monkeypatch.setattr(host_io, "shield_hit", host)
    monkeypatch.setattr(host_io, "world_to_body", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "damage_decal_add", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "hull_carve_add", lambda *a, **k: None)
    ship_instances = {ship: 42}

    class _StubSnd:
        def Play(self, position=None):
            return None
    class _StubMgr:
        def GetSound(self, _name):
            return _StubSnd()
    import App
    monkeypatch.setattr(App, "g_kSoundManager", _StubMgr(), raising=False)

    # Player gate: ship IS the player.
    class _Game:
        def GetPlayer(self): return ship
    monkeypatch.setattr(App, "Game_GetCurrentGame", lambda: _Game(), raising=False)

    import LoadTacticalSounds, LoadDamageHitSounds
    monkeypatch.setattr(LoadTacticalSounds, "GetRandomSound",
                          lambda pool: pool[0])
    monkeypatch.setattr(LoadDamageHitSounds, "GetRandomSound",
                          lambda pool: pool[0])

    return {"ship": ship, "host": host, "ship_instances": ship_instances,
            "sensors": sensors, "shields": shields}


# ── helpers ────────────────────────────────────────────────────────────────


def _severity_for_last_push(host_before_count, host, snapshot_before, snapshot_after):
    """Decide what severity this tick produced by looking at how the
    captured state changed."""
    new_shield_hit = len(host.shield_hit_calls) > host_before_count
    new_descriptor = len(snapshot_after) > len(snapshot_before)
    # Mutual exclusivity invariant — exactly one fires per impact.
    assert not (new_shield_hit and new_descriptor), \
        "shield_hit and hit_vfx fired together — mutual exclusivity broken"
    if new_shield_hit:
        return Severity.SHIELD
    if new_descriptor:
        return Severity(snapshot_after[-1]["severity"])
    raise AssertionError("neither shield_hit nor hit_vfx fired")


# ── tests ──────────────────────────────────────────────────────────────────


def test_severity_sequence_shield_then_hull_then_critical(setup):
    """10 ticks of 30 damage each, fire on FRONT face of a ship with:
    - FRONT shield charge 100
    - sensors MaxCondition 100, DisabledPercentage 0.5

    Expected stream (each tick = one apply_hit call):
       1: SHIELD  (shield 70 / sensors 100)
       2: SHIELD  (shield 40 / sensors 100)
       3: SHIELD  (shield 10 / sensors 100)
       4: HULL    (shield 0, sensors 80; no IsDisabled/IsDestroyed flip)
       5: CRITICAL (sensors 50, IsDisabled flips True)
       6: HULL    (sensors 20; IsDisabled already True, no new flip)
       7: CRITICAL (sensors 0, IsDestroyed flips True)
       8-10: HULL (sensors stays destroyed, no further transition)
    """
    ship = setup["ship"]
    host = setup["host"]
    ship_instances = setup["ship_instances"]

    expected = [
        Severity.SHIELD, Severity.SHIELD, Severity.SHIELD,
        Severity.HULL,
        Severity.CRITICAL,
        Severity.HULL,
        Severity.CRITICAL,
        Severity.HULL, Severity.HULL, Severity.HULL,
    ]
    actual = []

    point = TGPoint3(0.0, 1.0, 0.0)   # FRONT face — body +Y.
    for tick in range(10):
        host_before = len(host.shield_hit_calls)
        snap_before = hit_vfx.snapshot()
        combat.apply_hit(ship, damage=30.0, hit_point=point,
                          source=None,
                          normal=TGPoint3(0.0, 1.0, 0.0),
                          ship_instances=ship_instances)
        snap_after = hit_vfx.snapshot()
        actual.append(_severity_for_last_push(host_before, host,
                                                snap_before, snap_after))

    assert actual == expected, f"got {actual}, expected {expected}"


def test_camera_shake_fires_only_when_target_is_player(setup, monkeypatch):
    ship = setup["ship"]
    host = setup["host"]
    ship_instances = setup["ship_instances"]

    # Re-confirm ship IS player → energy should accumulate.
    camera_shake.reset()
    for _ in range(5):
        combat.apply_hit(ship, damage=30.0, hit_point=TGPoint3(0, 1, 0),
                          source=None,
                          normal=None,
                          ship_instances=ship_instances)
    energy_when_player = camera_shake.get_energy()
    assert energy_when_player > 0.0

    # Now point player to someone else.
    hull2 = _HullMarker()
    shields2 = _Shield(front_charge=0.0)
    sensors2 = _Sensors()
    other = _Ship(hull2, shields2, sensors2)
    import App
    class _Game2:
        def GetPlayer(self): return other
    monkeypatch.setattr(App, "Game_GetCurrentGame", lambda: _Game2(), raising=False)

    camera_shake.reset()
    for _ in range(5):
        combat.apply_hit(ship, damage=30.0, hit_point=TGPoint3(0, 1, 0),
                          source=None,
                          normal=None,
                          ship_instances=ship_instances)
    assert camera_shake.get_energy() == 0.0
