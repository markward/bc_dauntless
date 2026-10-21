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


@pytest.fixture
def breach_wear():
    """Pin params[16] (breach_wear) for the test, restored after, so the
    native value another test left behind can never move the crossing."""
    from engine.appc import plating_dials
    breach = 4.5
    params = list(plating_dials.params())
    params[plating_dials.DIAL_ORDER.index("breach_wear")] = breach
    _h.set_plating_params(params)
    yield breach
    _h.set_plating_params(list(plating_dials.params()))


def test_tear_vents_once_when_wear_first_crosses_breach(iid, breach_wear):
    breach = breach_wear
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


def test_hull_split_parts_returns_nothing_for_an_intact_ship(iid):
    assert _h.hull_split_parts(iid) == []
    _h.hull_damage_add_body(iid, (1.0, 2.0, 3.0), (0.0, 0.0, 1.0), 0.3, 1.0, 1)
    assert _h.hull_split_parts(iid) == [], "no model, no parts: nothing severs"
    stale = _h.create_instance(0)
    _h.destroy_instance(stale)
    assert _h.hull_split_parts(stale) == []


def test_hull_split_parts_is_a_required_binding():
    from engine import host_io
    assert "hull_split_parts" in host_io._REQUIRED_BINDINGS


def test_structure_part_at_is_minus_one_until_parts_are_known(iid):
    assert _h.structure_part_at(iid, (0.0, 0.0, 0.0)) == -1, "no model, no parts"
    stale = _h.create_instance(0)
    _h.destroy_instance(stale)
    assert _h.structure_part_at(stale, (0.0, 0.0, 0.0)) == -1


def test_structure_part_at_is_a_required_binding():
    from engine import host_io
    assert "structure_part_at" in host_io._REQUIRED_BINDINGS


# ── Damage moves with articulated parts (layered damage phase 4 §2.1) ────────
# A hit on a posed part is recorded on that part's NODE, in the node's REST
# frame, so the hole moves with the part. Needs a real model with a named,
# posable node: the stock Bird of Prey's "left wing", loaded under a headless
# GL context.

_WING = "left wing"


@pytest.fixture
def posed_bop(breach_wear, monkeypatch):
    from engine import paths
    from tests.helpers import bc_assets
    nif = bc_assets.require_game_asset("data/Models/Ships/BirdOfPrey/BirdOfPrey.nif")
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")
    try:
        _h.init(64, 64, "test_hull_damage_bindings_posed")
    except RuntimeError as e:
        pytest.skip(f"no GL context: {e}")
    try:
        search = [str(p) for p in paths.game_asset_dirs("data/Models/Ships/BirdOfPrey")]
        model = _h.load_model(str(nif), search)
        i = _h.create_instance(model)
        _h.set_world_transform(i, [1.0, 0.0, 0.0, 0.0,
                                   0.0, 1.0, 0.0, 0.0,
                                   0.0, 0.0, 1.0, 0.0,
                                   0.0, 0.0, 0.0, 1.0])
        # 40 degrees about the node's parent-space x axis, then a lift: a
        # pose with both rotation and translation.
        import math
        c, s = math.cos(math.radians(40.0)), math.sin(math.radians(40.0))
        pose_col_major = [1.0, 0.0, 0.0, 0.0,
                          0.0, c, s, 0.0,
                          0.0, -s, c, 0.0,
                          0.0, 0.0, 25.0, 1.0]
        assert _h.set_instance_node_transform(i, _WING, pose_col_major)
        yield i
        _h.destroy_instance(i)
    finally:
        _h.shutdown()


def _mat(rows16):
    return [rows16[r * 4:(r + 1) * 4] for r in range(4)]


def _mul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def _apply(m, p, w=1.0):
    v = (p[0], p[1], p[2], w)
    return tuple(sum(m[r][k] * v[k] for k in range(4)) for r in range(3))


def _inverse_rigid(m):
    """Inverse of a rotation + translation (row-major 4x4)."""
    rt = [[m[c][r] for c in range(3)] for r in range(3)]
    t = [m[r][3] for r in range(3)]
    ti = [-sum(rt[r][k] * t[k] for k in range(3)) for r in range(3)]
    return [rt[0] + [ti[0]], rt[1] + [ti[1]], rt[2] + [ti[2]], [0.0, 0.0, 0.0, 1.0]]


def test_wear_hit_on_a_posed_part_records_its_node(posed_bop):
    iid = posed_bop
    rest = _mat(_h.instance_node_world(iid, _WING, False))
    posed = _mat(_h.instance_node_world(iid, _WING, True))
    assert rest != posed, "the wing is not posed"
    # A point and normal fixed to the wing: given in REST body coordinates,
    # carried to where the posed wing draws them (P . R^-1).
    q_rest = _apply(rest, (10.0, -5.0, 3.0))
    n_rest = (0.0, 0.6, 0.8)
    to_posed = _mul(posed, _inverse_rigid(rest))
    q_posed = _apply(to_posed, q_rest)
    n_posed = _apply(to_posed, n_rest, 0.0)
    assert max(abs(a - b) for a, b in zip(q_posed, q_rest)) > 5.0, \
        "the pose barely moves the point: the test could not tell the frames apart"

    _h.hull_damage_add(iid, q_posed, n_posed, 0.3, 1.0, 1, _WING)
    (rec,) = _records(iid)
    assert rec["node"] >= 0, "the record lost its node"
    assert rec["centre"] == pytest.approx(q_rest, abs=1e-2), \
        "the record must be stored in the node's REST frame"
    assert rec["normal"] == pytest.approx(n_rest, abs=1e-4)

    # The body-frame binding takes the same posed point to the same record.
    _h.hull_damage_add_body(iid, q_posed, n_posed, 0.3, 1.0, 1, _WING)
    (rec2,) = _records(iid)
    assert rec2["wear"] == pytest.approx(2.0), "same node, same spot: merged"
    assert rec2["centre"] == pytest.approx(q_rest, abs=1e-2)

    # The same posed point on the hull BODY is a different record (-1).
    _h.hull_damage_add_body(iid, q_posed, n_posed, 0.3, 1.0, 1)
    nodes = sorted(r["node"] for r in _records(iid))
    assert nodes[0] == -1 and nodes[1] == rec["node"]


def test_posed_part_tear_vents_at_the_drawn_hit(posed_bop, breach_wear):
    """Venting is placed through the instance world (posed body frame), so a
    tear on a posed part vents where the part is DRAWN, not at its rest spot."""
    iid = posed_bop
    rest = _mat(_h.instance_node_world(iid, _WING, False))
    posed = _mat(_h.instance_node_world(iid, _WING, True))
    q_posed = _apply(_mul(posed, _inverse_rigid(rest)), _apply(rest, (10.0, -5.0, 3.0)))
    for _ in range(5):
        _h.hull_damage_add_body(iid, q_posed, (0.0, 0.0, 1.0), 0.3, 1.0, 1, _WING)
    (ev,) = _breach(iid)
    assert ev["center"] == pytest.approx(q_posed, abs=1e-2)


def test_unknown_node_name_records_on_the_body(iid):
    _h.hull_damage_add_body(iid, (1.0, 2.0, 3.0), (0.0, 0.0, 1.0), 0.3, 1.0, 1,
                            "no such node")
    (rec,) = _records(iid)
    assert rec["node"] == -1
    assert rec["centre"] == pytest.approx((1.0, 2.0, 3.0), abs=1e-6)
