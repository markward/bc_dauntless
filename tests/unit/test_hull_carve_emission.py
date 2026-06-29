"""dispatch deposits hull-carve *strength* whenever: the hit absorbs hull,
a mesh normal is present, the renderer is present, the hit is committed (not god
mode), AND the target ship is carve-eligible. There is NO per-hit magnitude gate
anymore — the C++ field accumulates strength and decides visibility — so even a
light hit deposits. Throttled per-ship. Mirrors test_decal_emission."""
import pytest

from engine.appc import hit_feedback
from engine.appc import damage_decals as dd
from engine.appc import hull_carve as hc
from engine.appc import damage_eligibility as de


class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _FakeHost:
    def __init__(self):
        self.carve_calls = []

    # Match the host_bindings.cc py::arg names (floor_radius defaults to 0).
    def hull_carve_add(self, instance_id, world_point, world_normal,
                       influ_radius, strength, time, floor_radius=0.0):
        self.carve_calls.append(dict(
            instance_id=instance_id, world_point=world_point,
            world_normal=world_normal, influ_radius=influ_radius,
            strength=strength, time=time, floor_radius=floor_radius))


class _Hull:
    def IsDestroyed(self):
        return 0


class _Ship:
    def GetHull(self):
        return _Hull()


@pytest.fixture
def patched(monkeypatch):
    # Deterministic clock; clear per-ship throttle and eligibility between tests.
    monkeypatch.setattr(dd, "current_game_time", lambda: 100.0)
    hit_feedback._last_carve_time.clear()
    de.reset()
    yield monkeypatch
    hit_feedback._last_carve_time.clear()
    de.reset()


def _dispatch(host, ship, *, absorbed_hull, normal=_Pt(0, 0, 1),
              persist_decal=True, source=None, radius=0.2):
    hit_feedback.dispatch(
        ship=ship, source=source, point=_Pt(1, 2, 3), normal=normal,
        damage=10.0, subsystem=None,
        absorbed_shields=0.0, absorbed_subsystem=0.0,
        absorbed_hull=absorbed_hull, sub_transition=None,
        host=host, ship_instances={ship: "IID"},
        weapon_type="torpedo", radius=radius, persist_decal=persist_decal,
    )


def test_deposit_on_eligible_hull_hit(patched):
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, absorbed_hull=100.0)
    assert len(host.carve_calls) == 1
    call = host.carve_calls[0]
    assert call["instance_id"] == "IID"
    assert call["world_point"] == (1, 2, 3)
    assert call["world_normal"] == (0, 0, 1)
    assert call["influ_radius"] == pytest.approx(hc.carve_influ_gu(0.2))
    assert call["strength"] == pytest.approx(hc.carve_strength(100.0))
    assert call["time"] == 100.0


def test_light_hit_still_deposits(patched):
    # No per-hit threshold: a light hit deposits (smaller) strength; the C++
    # field decides whether the accumulated total is visible yet.
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, absorbed_hull=1.0)
    assert len(host.carve_calls) == 1
    assert host.carve_calls[0]["strength"] == pytest.approx(hc.carve_strength(1.0))


def test_no_deposit_without_hull_damage(patched):
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, absorbed_hull=0.0)
    assert host.carve_calls == []


def test_no_deposit_when_not_eligible(patched):
    host = _FakeHost()
    ship = _Ship()
    # eligibility not set → ship not in current set
    _dispatch(host, ship, absorbed_hull=100.0)
    assert host.carve_calls == []


def test_no_deposit_without_normal(patched):
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, absorbed_hull=100.0, normal=None)
    assert host.carve_calls == []


def test_no_deposit_under_god_mode(patched):
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, absorbed_hull=100.0, persist_decal=False)
    assert host.carve_calls == []


def test_deposit_throttled_per_ship(patched):
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, absorbed_hull=100.0)
    _dispatch(host, ship, absorbed_hull=100.0)
    assert len(host.carve_calls) == 1


def test_headless_host_none_is_safe(patched):
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(None, ship, absorbed_hull=100.0)


def test_reset_carve_throttle_clears_state(patched):
    # After a mission swap, a fresh ship reusing a previous id() must not be
    # throttled on its first deposit.
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, absorbed_hull=100.0)
    assert len(host.carve_calls) == 1
    hit_feedback._last_carve_time.clear()
    _dispatch(host, ship, absorbed_hull=100.0)
    assert len(host.carve_calls) == 2  # throttle was cleared
