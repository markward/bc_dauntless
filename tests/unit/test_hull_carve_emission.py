"""dispatch deposits hull-carve *strength* whenever: the hit absorbs hull,
a mesh normal is present, a renderer instance is mapped, the hit is committed
(not god mode), AND the target ship is carve-eligible. There is NO per-hit
magnitude gate anymore — the C++ field accumulates strength and decides
visibility — so even a light hit deposits. Throttled per-ship. Mirrors
test_decal_emission.

Native carve routes through engine.host_io.hull_carve_add; these tests patch
that wrapper (host_io owns the single guard point) rather than injecting a raw
host= module (Task 4 of the host_io façade refactor)."""
import pytest

from engine import host_io
from engine.appc import hit_feedback
from engine.appc import damage_decals as dd
from engine.appc import hull_carve as hc
from engine.appc import damage_eligibility as de


class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _CarveCapture:
    """Positional-arg capture matching host_io.hull_carve_add's signature
    (instance_id, world_point, world_normal, influ_radius, strength, time,
    floor_radius=0.0, radius_modifier=1.0)."""

    def __init__(self):
        self.carve_calls = []

    def __call__(self, instance_id, world_point, world_normal,
                 influ_radius, strength, time, floor_radius=0.0,
                 radius_modifier=1.0):
        self.carve_calls.append(dict(
            instance_id=instance_id, world_point=world_point,
            world_normal=world_normal, influ_radius=influ_radius,
            strength=strength, time=time, floor_radius=floor_radius,
            radius_modifier=radius_modifier))


class _Hull:
    def IsDestroyed(self):
        return 0


class _Ship:
    def GetHull(self):
        return _Hull()

    def GetRadius(self):
        return 2.0


@pytest.fixture
def carve(monkeypatch):
    """Patch host_io.hull_carve_add with a call-capturing spy and return it."""
    spy = _CarveCapture()
    monkeypatch.setattr(host_io, "hull_carve_add", spy)
    return spy


@pytest.fixture(autouse=True)
def _isolate_host_io(monkeypatch):
    """Neutralize the sibling host_io hit/damage wrappers so dispatch's spark /
    flash / decal paths never reach the strict real native binding (which
    rejects the string 'IID' these unit tests use). world_to_body → None
    (flash only, no spark anchor); the rest → no-op."""
    monkeypatch.setattr(host_io, "world_to_body", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "shield_hit", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "damage_decal_add", lambda *a, **k: None)


@pytest.fixture
def patched(monkeypatch):
    # Deterministic clock; clear per-ship throttle and eligibility between tests.
    monkeypatch.setattr(dd, "current_game_time", lambda: 100.0)
    hit_feedback._last_carve_time.clear()
    hit_feedback._pending_carve_strength.clear()
    de.reset()
    yield monkeypatch
    hit_feedback._last_carve_time.clear()
    hit_feedback._pending_carve_strength.clear()
    de.reset()


def _dispatch(ship, *, absorbed_hull, normal=_Pt(0, 0, 1),
              persist_decal=True, source=None, radius=0.2):
    hit_feedback.dispatch(
        ship=ship, source=source, point=_Pt(1, 2, 3), normal=normal,
        damage=10.0, subsystem=None,
        absorbed_shields=0.0, absorbed_subsystem=0.0,
        absorbed_hull=absorbed_hull, sub_transition=None,
        ship_instances={ship: "IID"},
        weapon_type="torpedo", radius=radius, persist_decal=persist_decal,
    )


def test_deposit_on_eligible_hull_hit(patched, carve):
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(ship, absorbed_hull=100.0)
    assert len(carve.carve_calls) == 1
    call = carve.carve_calls[0]
    assert call["instance_id"] == "IID"
    assert call["world_point"] == (1, 2, 3)
    assert call["world_normal"] == (0, 0, 1)
    assert call["influ_radius"] == pytest.approx(hc.carve_influ_gu(0.2))
    assert call["strength"] == pytest.approx(hc.carve_strength(100.0))
    assert call["time"] == 100.0
    # Absolute carve size: the only per-ship scale is DamageRadMod (default 1.0).
    assert call["radius_modifier"] == pytest.approx(1.0)
    assert call["floor_radius"] == pytest.approx(0.0)  # combat carves strength-gated


def test_respects_sdk_damage_modifiers(patched, carve):
    # BC's per-ship DamageRadMod / DamageStrMod (set by loadspacehelper on big
    # structures) scale the carve radius and the deposited strength respectively.
    ship = _Ship()
    ship._vis_dmg_radius_mod = 8.0      # DamageRadMod (bigger holes)
    ship._vis_dmg_strength_mod = 0.125  # DamageStrMod (tankier: accumulates slower)
    de.set_current(frozenset({id(ship)}))
    _dispatch(ship, absorbed_hull=100.0)
    call = carve.carve_calls[0]
    assert call["radius_modifier"] == pytest.approx(8.0)
    assert call["strength"] == pytest.approx(hc.carve_strength(100.0) * 0.125)


def test_light_hit_still_deposits(patched, carve):
    # No per-hit threshold: a light hit deposits (smaller) strength; the C++
    # field decides whether the accumulated total is visible yet.
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(ship, absorbed_hull=1.0)
    assert len(carve.carve_calls) == 1
    assert carve.carve_calls[0]["strength"] == pytest.approx(hc.carve_strength(1.0))


def test_no_deposit_without_hull_damage(patched, carve):
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(ship, absorbed_hull=0.0)
    assert carve.carve_calls == []


def test_no_deposit_when_not_eligible(patched, carve):
    ship = _Ship()
    # eligibility not set → ship not in current set
    _dispatch(ship, absorbed_hull=100.0)
    assert carve.carve_calls == []


def test_no_deposit_without_normal(patched, carve):
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(ship, absorbed_hull=100.0, normal=None)
    assert carve.carve_calls == []


def test_no_deposit_under_god_mode(patched, carve):
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(ship, absorbed_hull=100.0, persist_decal=False)
    assert carve.carve_calls == []


def test_deposit_throttled_per_ship(patched, carve):
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(ship, absorbed_hull=100.0)
    _dispatch(ship, absorbed_hull=100.0)
    assert len(carve.carve_calls) == 1


def test_strength_accumulates_across_throttle_window(patched, carve):
    # The perf throttle must not discard damage: light hits within one window
    # accumulate, and the next emit after the window deposits the SUM. (Without
    # this, sustained phaser fire — a few hull/tick — never reaches the iso.)
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    clock = [100.0]
    patched.setattr(dd, "current_game_time", lambda: clock[0])
    _dispatch(ship, absorbed_hull=10.0)                 # first emit flushes
    assert len(carve.carve_calls) == 1
    for _ in range(4):                                  # same window: throttled
        _dispatch(ship, absorbed_hull=10.0)
    assert len(carve.carve_calls) == 1
    clock[0] += hc.CARVE_EMIT_INTERVAL + 0.01           # next window
    _dispatch(ship, absorbed_hull=10.0)
    assert len(carve.carve_calls) == 2
    # Deposit carries the 4 throttled hits + this one (the first was popped).
    assert carve.carve_calls[1]["strength"] == pytest.approx(hc.carve_strength(10.0) * 5)


def test_unmapped_ship_deposits_nothing(patched, carve):
    # No instance for the ship in ship_instances → the carve emit is skipped,
    # and dispatch must not raise. (The host_io.hull_carve_add wrapper itself
    # no-ops headless; here we assert the caller-side skip via an empty map.)
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    hit_feedback.dispatch(
        ship=ship, source=None, point=_Pt(1, 2, 3), normal=_Pt(0, 0, 1),
        damage=10.0, subsystem=None,
        absorbed_shields=0.0, absorbed_subsystem=0.0,
        absorbed_hull=100.0, sub_transition=None,
        ship_instances={},  # ship not mapped
        weapon_type="torpedo", radius=0.2, persist_decal=True,
    )
    assert carve.carve_calls == []


def test_reset_carve_throttle_clears_state(patched, carve):
    # After a mission swap, a fresh ship reusing a previous id() must not be
    # throttled on its first deposit.
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(ship, absorbed_hull=100.0)
    assert len(carve.carve_calls) == 1
    hit_feedback._last_carve_time.clear()
    _dispatch(ship, absorbed_hull=100.0)
    assert len(carve.carve_calls) == 2  # throttle was cleared
