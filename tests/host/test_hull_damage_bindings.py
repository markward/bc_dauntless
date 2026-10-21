"""The HullDamageStore bindings on a real (GL-free) render instance.

Wear and the scorch decal must agree on SIZE in the ship's body frame, and a
point handed over already in the body frame (pending phaser wear) must land
exactly there, radius still converted game units -> model units by the same
scale as the world-point path.
"""
import pytest

pytest.importorskip("_dauntless_host")

import _dauntless_host as _h  # noqa: E402

SCALE = 0.01   # game scale: 1 model unit = 0.01 GU


def _row_major_rot_z90(scale, tx, ty, tz):
    # Rotation +90 deg about Z times uniform scale: body X -> world Y.
    return [0.0, -scale, 0.0, tx,
            scale, 0.0, 0.0, ty,
            0.0, 0.0, scale, tz,
            0.0, 0.0, 0.0, 1.0]


@pytest.fixture
def iid():
    i = _h.create_instance(0)
    _h.set_world_transform(i, _row_major_rot_z90(SCALE, 100.0, 50.0, -7.0))
    yield i
    _h.destroy_instance(i)


def _records(iid):
    return _h._test_only_hull_damage_records(iid)


def test_scorch_radius_and_wear_reach_share_one_body_size_on_a_scaled_instance(iid):
    rel = (0.0, 0.2, 0.0)              # instance-relative world point
    n = (0.0, 1.0, 0.0)
    _h.damage_decal_add(iid, rel, n, 0.3, 1.0, 1, 0.0)
    _h.hull_damage_add(iid, rel, n, 0.3, 1.0, 1)
    (decal,) = _h._test_only_damage_decals(iid)
    (rec,) = _records(iid)
    assert rec["reach"] == pytest.approx(30.0, rel=1e-5)
    assert decal["radius"] == pytest.approx(rec["reach"], rel=1e-6)
    assert rec["centre"] == pytest.approx(decal["point"], abs=1e-4)
    assert rec["centre"] == pytest.approx((20.0, 0.0, 0.0), abs=1e-3)


def test_body_frame_add_lands_at_the_given_body_point(iid):
    _h.hull_damage_add_body(iid, (1.0, 2.0, 3.0), (0.0, 0.0, 1.0),
                            0.3, 0.75, 1)
    (rec,) = _records(iid)
    assert rec["centre"] == pytest.approx((1.0, 2.0, 3.0), abs=1e-6)
    assert rec["normal"] == pytest.approx((0.0, 0.0, 1.0), abs=1e-6)
    assert rec["reach"] == pytest.approx(30.0, rel=1e-5), \
        "radius GU -> model units by the same scale as the world-point path"
    assert rec["wear"] == pytest.approx(0.75)
    assert rec["kind"] == 1


def test_body_frame_add_ignores_unknown_kinds_and_stale_ids(iid):
    _h.hull_damage_add_body(iid, (1.0, 2.0, 3.0), (0.0, 0.0, 1.0),
                            0.3, 1.0, 2)
    assert _records(iid) == []
    stale = _h.create_instance(0)
    _h.destroy_instance(stale)
    _h.hull_damage_add_body(stale, (1.0, 2.0, 3.0), (0.0, 0.0, 1.0),
                            0.3, 1.0, 1)        # dropped, no raise


def test_python_merge_factor_matches_native():
    from engine.appc import hull_wear
    consts = _h._test_only_hull_damage_constants()
    assert hull_wear.MERGE_FACTOR == consts["merge_factor"]
    assert consts["capacity"] > 0


def _breach(iid):
    return _h._test_only_breach_events(iid)


def test_tear_vents_once_when_wear_first_crosses_breach(iid):
    breach = 4.5
    for i in range(5):
        assert _breach(iid) == [], f"no event before add {i}"
        _h.hull_damage_add_body(iid, (1.0, 2.0, 3.0), (0.0, 0.0, 1.0),
                                0.3, 1.0, 1)
        if i < 4:
            assert _breach(iid) == []
    evs = _breach(iid)
    assert len(evs) == 1
    assert evs[0]["center"] == pytest.approx((1.0, 2.0, 3.0), abs=1e-4)
    assert evs[0]["normal"] == pytest.approx((0.0, 0.0, 1.0), abs=1e-4)
    (rec,) = _records(iid)
    assert evs[0]["radius"] == pytest.approx(0.5 * rec["reach"], rel=1e-5)
    assert rec["wear"] > breach
    _h.hull_damage_add_body(iid, (1.0, 2.0, 3.0), (0.0, 0.0, 1.0), 0.3, 1.0, 1)
    assert len(_breach(iid)) == 1, "already past breach: no second event"


def test_internal_adds_never_vent(iid):
    for _ in range(8):
        _h.hull_damage_add_body(iid, (1.0, 2.0, 3.0), (0.0, 0.0, 0.0),
                                0.3, 1.0, 3)
    assert _breach(iid) == []
