"""dispatch must emit a hull-deform crater exactly when: hull damage clears
the deform threshold, a mesh normal is present, the renderer is present, the
hit is committed (not god mode), AND the target ship is deform-eligible.
Throttled per-ship. Mirrors test_decal_emission."""
import pytest

from engine.appc import hit_feedback
from engine.appc import damage_decals as dd
from engine.appc import hull_deformation as hd
from engine.appc import deform_eligibility as de


class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _FakeHost:
    def __init__(self):
        self.deform_calls = []

    # Match the host_bindings.cc py::arg names exactly.
    def hull_deform_add(self, *, instance_id, world_point, world_normal,
                        world_impact_dir, radius, depth):
        self.deform_calls.append(dict(
            instance_id=instance_id, world_point=world_point,
            world_normal=world_normal, world_impact_dir=world_impact_dir,
            radius=radius, depth=depth))


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
    hit_feedback._last_deform_emit.clear()
    de.reset()
    yield monkeypatch
    hit_feedback._last_deform_emit.clear()
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


def test_deform_emitted_on_strong_eligible_hit(patched):
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0)
    assert len(host.deform_calls) == 1
    call = host.deform_calls[0]
    assert call["instance_id"] == "IID"
    assert call["world_point"] == (1, 2, 3)
    assert call["world_normal"] == (0, 0, 1)
    assert call["world_impact_dir"] == pytest.approx((0.0, 0.0, -1.0))
    assert call["radius"] == pytest.approx(hd.crater_radius_gu(0.2))
    assert call["depth"] == pytest.approx(
        hd.crater_depth_gu(hd.MIN_DEFORM_HULL + 60.0))


def test_no_deform_below_threshold(patched):
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL - 1.0)
    assert host.deform_calls == []


def test_no_deform_when_not_eligible(patched):
    host = _FakeHost()
    ship = _Ship()
    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0)
    assert host.deform_calls == []


def test_no_deform_without_normal(patched):
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0, normal=None)
    assert host.deform_calls == []


def test_no_deform_under_god_mode(patched):
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0,
              persist_decal=False)
    assert host.deform_calls == []


def test_deform_throttled_per_ship(patched):
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0)
    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0)
    assert len(host.deform_calls) == 1


def test_headless_host_none_is_safe(patched):
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(None, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0)


def test_reset_deform_throttle_clears_state(patched):
    # After a mission swap, a fresh ship reusing a previous id() must not be
    # throttled on its first crater.
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))
    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0)
    assert len(host.deform_calls) == 1
    # Same frozen clock would normally throttle the second hit...
    hit_feedback.reset_deform_throttle()
    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0)
    assert len(host.deform_calls) == 2  # throttle was cleared


def test_impact_dir_uses_weapon_ray(patched):
    # Oblique source so the weapon ray is NOT collinear with -normal: this
    # proves dispatch actually threads source_pos through to impact_direction
    # rather than falling back to -normal. hit_point is (1,2,3), normal (0,0,1).
    host = _FakeHost()
    ship = _Ship()
    de.set_current(frozenset({id(ship)}))

    class _Src:
        def GetWorldLocation(self):
            # ray = hit - src = (1-11, 2-2, 3-13) = (-10, 0, -10) -> diagonal,
            # inward (dot -normal = 10 > 0), distinct from the (0,0,-1) fallback.
            return _Pt(11.0, 2.0, 13.0)

    _dispatch(host, ship, absorbed_hull=hd.MIN_DEFORM_HULL + 60.0, source=_Src())
    m = (10.0 ** 2 + 10.0 ** 2) ** 0.5
    got = host.deform_calls[0]["world_impact_dir"]
    assert got == pytest.approx((-10.0 / m, 0.0, -10.0 / m))
    assert got != pytest.approx((0.0, 0.0, -1.0))  # not the -normal fallback
