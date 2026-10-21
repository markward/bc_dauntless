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
    assert evs[0]["node"] == -1, "a body tear's rim is in the body frame"
    assert evs[0]["center_rest"] == pytest.approx(evs[0]["center"], abs=1e-6)
    _h.hull_damage_add_body(iid, (1.0, 2.0, 3.0), (0.0, 0.0, 1.0), 0.3, 1.0, 1)
    assert len(_breach(iid)) == 1, "already past breach: no second event"


def test_breach_burst_rim_is_in_the_body_frame(iid):
    """A sub-floor severed component's burst: node -1, so the molten rim's
    centre is the body-frame point itself."""
    _h.breach_burst(iid, (0.01, 0.02, 0.03), 0.1)
    (ev,) = _breach(iid)
    assert ev["node"] == -1
    assert ev["center"] == pytest.approx((1.0, 2.0, 3.0), abs=1e-4)
    assert ev["center_rest"] == pytest.approx(ev["center"], abs=1e-6)


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


def test_instance_severed_parts_is_zero_for_an_intact_or_stale_hull(iid):
    """Lights and emitters on a lost structure part read this mask every
    frame: an intact hull and a stale id both answer 0, never raise."""
    assert _h.instance_severed_parts(iid) == 0
    stale = _h.create_instance(0)
    _h.destroy_instance(stale)
    assert _h.instance_severed_parts(stale) == 0


def test_instance_severed_parts_is_a_required_binding():
    from engine import host_io
    assert "instance_severed_parts" in host_io._REQUIRED_BINDINGS


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


def _wing_frames(iid):
    """(rest, posed, posed->rest) for the wing, row-major 4x4."""
    rest = _mat(_h.instance_node_world(iid, _WING, False))
    posed = _mat(_h.instance_node_world(iid, _WING, True))
    assert rest != posed, "the wing is not posed"
    return rest, posed, _mul(rest, _inverse_rigid(posed))


def _posed_wing_hit(iid, posed):
    """A point on the POSED wing's surface: trace in from far outboard (-x)
    along the line through the posed wing node's origin."""
    o = (posed[0][3] - 2000.0, posed[1][3], posed[2][3])
    hit = _h.ray_trace_mesh(iid, o, (1.0, 0.0, 0.0), 4000.0)
    assert hit is not None, "no posed wing surface on the probe line"
    return hit[0], hit[1]


def test_wear_hit_on_a_posed_part_records_its_node(posed_bop):
    """No part is named: the binding attributes the posed hit by GEOMETRY and
    stores it on the wing's node, in the wing's REST frame."""
    iid = posed_bop
    _rest, posed, to_rest = _wing_frames(iid)
    q_posed, n_posed = _posed_wing_hit(iid, posed)
    q_rest = _apply(to_rest, q_posed)
    n_rest = _apply(to_rest, n_posed, 0.0)
    assert max(abs(a - b) for a, b in zip(q_posed, q_rest)) > 5.0, \
        "the pose barely moves the point: the test could not tell the frames apart"

    _h.hull_damage_add(iid, q_posed, n_posed, 0.3, 1.0, 1)
    (rec,) = _records(iid)
    assert rec["node"] >= 0, "the posed wing hit was not attributed to its node"
    assert rec["centre"] == pytest.approx(q_rest, abs=1e-2), \
        "the record must be stored in the wing's REST frame"
    assert rec["normal"] == pytest.approx(n_rest, abs=1e-3)

    # The body-frame binding attributes the same posed point the same way.
    _h.hull_damage_add_body(iid, q_posed, n_posed, 0.3, 1.0, 1)
    (rec2,) = _records(iid)
    assert rec2["wear"] == pytest.approx(2.0), "same node, same spot: merged"
    assert rec2["centre"] == pytest.approx(q_rest, abs=1e-2)


def _rest_wing_hit(iid, rest):
    """A point on the wing's REST surface: the same outboard probe as
    `_posed_wing_hit`, traced against the rest pose (rest_pose=True)."""
    o = (rest[0][3] - 2000.0, rest[1][3], rest[2][3])
    hit = _h.ray_trace_mesh(iid, o, (1.0, 0.0, 0.0), 4000.0, rest_pose=True)
    assert hit is not None, "no rest wing surface on the probe line"
    return hit[0], hit[1]


def test_rest_pose_trace_ignores_the_pose(posed_bop):
    iid = posed_bop
    rest, posed, _to_rest = _wing_frames(iid)
    o = (rest[0][3] - 2000.0, rest[1][3], rest[2][3])
    at_rest = _h.ray_trace_mesh(iid, o, (1.0, 0.0, 0.0), 4000.0, rest_pose=True)
    as_drawn = _h.ray_trace_mesh(iid, o, (1.0, 0.0, 0.0), 4000.0)
    assert at_rest is not None
    assert as_drawn is None or max(
        abs(a - b) for a, b in zip(at_rest[0], as_drawn[0])) > 1.0, \
        "the rest-pose trace hit the posed wing"


def test_rest_frame_writer_keeps_its_part_without_conversion(posed_bop):
    """Authored (DamageTool) volumes are already rest-frame: rest_frame=True
    attributes them in REST space -- the wing's own node -- and stores the
    point unconverted, so the damage shows on the wing whatever its pose."""
    iid = posed_bop
    rest, _posed, _to_rest = _wing_frames(iid)
    q_rest, n_rest = _rest_wing_hit(iid, rest)
    _h.hull_damage_add_body(iid, q_rest, n_rest, 0.3, 1.0, 3, rest_frame=True)
    (rec,) = _records(iid)
    assert rec["node"] >= 0, "the authored wing volume lost its part"
    assert rec["centre"] == pytest.approx(q_rest, abs=1e-4), "converted: it must not be"
    # The same rest point on an UNPOSED instance attributes the same way (as at
    # mission init, before any pose).
    assert _h.clear_instance_node_overrides(iid)
    _h.hull_damage_add(iid, q_rest, n_rest, 0.3, 1.0, 3, rest_frame=True)
    recs = _records(iid)
    assert len(recs) == 1 and recs[0]["wear"] == pytest.approx(2.0), \
        "same node, same spot: merged"


def test_posed_part_tear_vents_at_the_drawn_hit(posed_bop, breach_wear):
    """Venting is placed through the instance world (posed body frame), so a
    tear on a posed part vents where the part is DRAWN, not at its rest spot.
    The event also carries the record's node and rest centre, which the molten
    rim is drawn from (it glows on the part)."""
    iid = posed_bop
    _rest, posed, _to_rest = _wing_frames(iid)
    q_posed, n_posed = _posed_wing_hit(iid, posed)
    for _ in range(5):
        _h.hull_damage_add_body(iid, q_posed, n_posed, 0.3, 1.0, 1)
    (rec,) = _records(iid)
    assert rec["node"] >= 0
    (ev,) = _breach(iid)
    assert ev["center"] == pytest.approx(q_posed, abs=1e-2)
    # The molten rim is drawn on the part: the record's node and REST centre.
    assert ev["node"] == rec["node"]
    assert ev["center_rest"] == pytest.approx(rec["centre"], abs=1e-4)


# ── Fix round 3: a rigged ship at the identity pose ─────────────────────────
# The identity pose clears the override map (a BoP at red alert), so without
# a native `rigged` flag every hit there was filed on the body and left the
# wing when it swung. A rigged instance with no overrides attributes in REST
# space (posed == rest): the hit keeps the wing's own node.

@pytest.fixture
def bop_at_identity(posed_bop):
    iid = posed_bop
    rest, _posed, _to_rest = _wing_frames(iid)
    assert _h.clear_instance_node_overrides(iid)
    return iid, rest


def test_rigged_instance_at_identity_files_the_hit_on_its_part(bop_at_identity):
    iid, rest = bop_at_identity
    q, n = _rest_wing_hit(iid, rest)
    assert _h.set_instance_rigged(iid, True)
    _h.hull_damage_add(iid, q, n, 0.3, 1.0, 1)
    (rec,) = _records(iid)
    assert rec["node"] >= 0, "a rigged ship's identity-pose hit fell on the body"
    assert rec["centre"] == pytest.approx(q, abs=1e-4), "posed == rest: no conversion"


def test_unrigged_instance_at_identity_stays_on_the_free_body_path(bop_at_identity):
    iid, rest = bop_at_identity
    q, n = _rest_wing_hit(iid, rest)
    assert _h.set_instance_rigged(iid, False)
    _h.hull_damage_add(iid, q, n, 0.3, 1.0, 1)
    (rec,) = _records(iid)
    assert rec["node"] == -1


def test_set_instance_rigged_on_a_stale_id_is_false():
    stale = _h.create_instance(0)
    _h.destroy_instance(stale)
    assert _h.set_instance_rigged(stale, True) is False
