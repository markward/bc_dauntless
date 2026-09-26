"""Appendage severance: attribution, accumulation, threshold.

The behaviour these pin is the one that could not be achieved at all under
voxel connectivity — see part_severance's module docstring for the measurement.
"""
import types

import pytest

from engine.appc import articulation, part_pose, part_severance as ps


LEAF = "birdofprey"


class _Hull:
    def __init__(self, maxc=4000.0):
        self._max = maxc
        self.condition = maxc

    def GetMaxCondition(self):
        return self._max


class _Pos:
    def __init__(self, x, y, z): self._v = (x, y, z)
    def GetX(self): return self._v[0]
    def GetY(self): return self._v[1]
    def GetZ(self): return self._v[2]


class _Sub:
    def __init__(self, name, pos):
        self.name = name
        self._pos = _Pos(*pos)
        self.condition = 100.0

    def GetPosition(self): return self._pos
    def SetCondition(self, v): self.condition = float(v)


class _Ship:
    """Stands in for a ShipClass. Mirrors only the surface severance touches."""

    def __init__(self, hull=4000.0, subs=()):
        self._hull = _Hull(hull)
        self._subs = list(subs)
        self._articulation_leaf = LEAF      # pre-cached: no SDK import in tests
        self._articulation_poses = {}

    def GetHull(self): return self._hull
    def _iter_subsystems(self): return list(self._subs)


def _pose(ship, deflection):
    """Set `ship`'s per-part poses `deflection` of the way (0..1) along each
    part's swing from the NIF pose to its authored "cruise" pose -- the
    fully-deflected (up/cold) pose at 1.0 -- what `pose_for_part` reads."""
    ship._articulation_poses = {
        p.GetName(): part_pose.interpolate(
            part_pose.IDENTITY, p.pose_for("cruise"), p.anchor, deflection)
        for p in articulation.rig_for(LEAF)
    }


# ── Attribution ──────────────────────────────────────────────────────────────

def test_a_point_out_on_the_wing_resolves_to_that_wing():
    """Outboard of the body's |x| 0.31, only the wing box contains the point."""
    assert ps.part_for_point(LEAF, (0.8, 0.0, -0.4)) == "left wing01"
    assert ps.part_for_point(LEAF, (-0.8, 0.0, -0.4)) == "left wing"


def test_the_wing_root_is_ambiguous_and_falls_back_to_the_body():
    """The roots are EMBEDDED in the hull — the wing boxes overlap the body box
    from |x| 0.1236 to 0.31. A hit there is inside two boxes, and the safe
    answer is None (unattributed, i.e. behaves as it always did) rather than
    silently crediting a wing for damage done to the hull."""
    assert ps.part_for_point(LEAF, (0.20, -0.5, -0.03)) is None


def test_a_point_on_the_nose_resolves_to_the_head():
    assert ps.part_for_point(LEAF, (0.0, 0.85, 0.0)) == "head"


def test_a_ship_with_no_authored_boxes_attributes_nothing():
    """"galaxy" is deliberately NOT used here any more: boxes are now DERIVED
    (Task 5) from a realized instance's own geometry, so a leaf real enough
    to be realized elsewhere in the suite can legitimately pick up cached
    boxes from that -- an ACTUAL Galaxy has real named nodes, unlike the old
    hand-authored PART_BOXES, which never had a "galaxy" entry by
    construction. A leaf that can never resolve to a real hull is what this
    test actually needs to pin."""
    assert ps.part_for_point("no_such_ship", (0.8, 0.0, -0.4)) is None


# ── Accumulation and threshold ───────────────────────────────────────────────

# A point on the starboard wing, as `host_io.world_to_body` actually delivers
# it: body frame, MODEL units. In SHIP units this is (0.8, 0.0, -0.4).
WING_HIT_MODEL = (80.0, 0.0, -40.0)


def _wing_hit(ship, amount):
    # iid None = headless: the sim-side detach still runs, visuals are skipped.
    return ps.record_hit(ship, None, WING_HIT_MODEL, amount)


def test_damage_accumulates_on_the_part_it_landed_on():
    ship = _Ship()
    _wing_hit(ship, 100.0)
    _wing_hit(ship, 150.0)
    assert ps.damage_on(ship, "left wing01") == pytest.approx(250.0)
    assert ps.damage_on(ship, "left wing") == 0.0


def test_the_wing_shears_at_twenty_percent_of_max_hull():
    """4000 hull x 0.20 = 800. Cumulative: eight 100-point hits, not one big
    one — the whole point of the rule is that chipping away works."""
    ship = _Ship(hull=4000.0)
    for _ in range(7):
        assert _wing_hit(ship, 100.0) is None      # 700: still attached
    assert _wing_hit(ship, 100.0) == "left wing01"  # 800: gone
    assert ps.is_detached(ship, "left wing01")


def test_the_other_wing_is_unaffected():
    ship = _Ship()
    _wing_hit(ship, 5000.0)
    assert ps.is_detached(ship, "left wing01")
    assert not ps.is_detached(ship, "left wing")


def test_a_part_never_severs_twice():
    """`sever` marks detached BEFORE destroying subsystems, so a re-entrant hit
    arriving from a subsystem-destruction event cannot shed the same wing
    again (which would spawn a second chunk)."""
    ship = _Ship()
    assert _wing_hit(ship, 5000.0) == "left wing01"
    assert _wing_hit(ship, 5000.0) is None
    assert ps.sever(ship, None, "left wing01") is None


def test_a_non_detachable_part_accumulates_nothing():
    """The head is a boxed part but has no `detach_fraction` authored on its
    template, so it can be hit forever and never come off. The body must
    never detach either."""
    ship = _Ship()
    for _ in range(50):
        assert ps.record_hit(ship, None, (0.0, 85.0, 0.0), 500.0) is None
    assert ps.damage_on(ship, "head") == 0.0
    assert not ps.is_detached(ship, "head")


def test_unattributed_damage_does_not_accumulate_anywhere():
    ship = _Ship()
    ps.record_hit(ship, None, (20.0, -50.0, -3.0), 5000.0)  # ambiguous wing root
    assert ps.damage_on(ship, "left wing01") == 0.0
    assert not ps.is_detached(ship, "left wing01")


def test_zero_and_negative_damage_are_ignored():
    ship = _Ship()
    assert _wing_hit(ship, 0.0) is None
    assert _wing_hit(ship, -10.0) is None
    assert ps.damage_on(ship, "left wing01") == 0.0


def test_a_ship_with_no_detachable_parts_is_untouched():
    """The overwhelmingly common case, and it must cost almost nothing: a hull
    with no authored parts returns before any geometry is considered."""
    ship = _Ship()
    ship._articulation_leaf = "galaxy"
    assert _wing_hit(ship, 100000.0) is None
    assert ps.damage_on(ship, "left wing01") == 0.0


def test_a_ship_without_a_hull_never_severs():
    """A hull-less object would give max_hull 0; a 0 limit must NOT read as
    'already exceeded', or every prop would shed parts on its first scratch."""
    ship = _Ship()
    ship._hull = None
    ship.GetHull = lambda: None
    assert _wing_hit(ship, 100000.0) is None


# ── Subsystems ───────────────────────────────────────────────────────────────

def test_a_severed_wing_destroys_the_cannon_mounted_on_it():
    """Star Cannon is authored at (1.008, 0.450, -0.670) — on the starboard
    wing. A gun that has left the ship cannot keep firing."""
    star = _Sub("Star Cannon", (1.008, 0.450, -0.670))
    port = _Sub("Port Cannon", (-1.009, 0.450, -0.670))
    body = _Sub("Warp Core", (0.0, -0.33, 0.0))
    ship = _Ship(subs=(star, port, body))

    _wing_hit(ship, 5000.0)

    assert star.condition == 0.0, "the cannon on the severed wing must die"
    assert port.condition == 100.0, "the other wing's cannon is untouched"
    assert body.condition == 100.0, "body subsystems are untouched"


def test_subsystem_kill_uses_the_REST_mount_even_mid_travel():
    """Attribution here is a REST-pose question, and must stay one.

    the structures this compares against are never articulated: the derived
    per-part boxes are authored rest-pose, and the .dhv SDF stays baked from
    the NIF in rest pose. (The per-instance carve field is the exception, and
    needs no transform either: it is both deposited and SAMPLED in posed body
    space -- opaque.vert builds `v_position_ws` from the override-composed
    `world_per_node`. A `rest_from_posed_at` primitive was written for a
    pull-back that turned out not to be wanted, reverted, and has now been
    deleted.) Collision spheres DO articulate as of the part-aware
    sim-geometry plan, but nothing in this path reads them. See spec 4.3.1.
    So the authored mount is the right thing to test, at any deflection.

    This test exists because the implementation plan originally specified the
    opposite -- routing this through part_transform_point, so an ARTICULATED
    mount would be tested against REST boxes. That mismatches frames and
    misattributes. Caught in pre-flight; pinned here so it is not re-attempted.

    Contrast subsystem_world_position, which feeds what is DRAWN (beam
    origins, SPV pins) and therefore MUST articulate.
    """
    star = _Sub("Star Cannon", (1.008, 0.450, -0.670))
    body = _Sub("Warp Core", (0.0, -0.33, 0.0))
    ship = _Ship(subs=(star, body))
    _pose(ship, 0.5)                          # mid-travel: guards against a
                                              # fix that special-cases only
                                              # the endpoints

    ps.sever(ship, None, "left wing01")

    assert star.condition == 0.0, (
        "the cannon authored on the starboard wing must die with it, "
        "regardless of where the wing is currently drawn")
    assert body.condition == 100.0


def test_reset_clears_damage_and_detachments():
    ship = _Ship()
    _wing_hit(ship, 5000.0)
    ps.reset_ship(ship)
    assert ps.damage_on(ship, "left wing01") == 0.0
    assert not ps.is_detached(ship, "left wing01")


# ── Units ────────────────────────────────────────────────────────────────────

def test_record_hit_takes_MODEL_units_not_ship_units():
    """REGRESSION. This shipped broken and attribution never fired once.

    `part_for_point` works in SHIP units (what hardpoints author: a BoP wingtip
    is x = 1.008). But `host_io.world_to_body` returns the body frame in MODEL
    units -- it inverts the instance world matrix, which carries
    BC_MODEL_SCALE -- so the same wingtip arrives as x = 100.8, a hundred times
    larger. Tested against a ship-units box it lands nowhere and attributes to
    nothing, which looks exactly like the player missing.

    The original test suite did not catch it because it fed `record_hit`
    SHIP units directly, never exercising the conversion -- the test carried
    the same bug as the code. The subsystem half worked throughout, because
    `GetPosition()` really is in ship units, which made the suite look healthy.

    So this asserts the two frames explicitly rather than trusting one number.
    """
    ship = _Ship()
    ps.record_hit(ship, None, (80.0, 0.0, -40.0), 100.0)     # MODEL units
    assert ps.damage_on(ship, "left wing01") == pytest.approx(100.0)

    # The SAME numbers read as ship units, converted a second time by
    # MODEL_TO_SHIP, land deep inside the hull -- inside the BODY box only
    # (not ambiguous), whose template authors no detach_fraction, so they
    # must attribute to nothing.
    other = _Ship()
    ps.record_hit(other, None, (0.8, 0.0, -0.4), 100.0)
    assert ps.damage_on(other, "left wing01") == 0.0, (
        "a ship-units point must NOT be accepted as model units")


# ── The hit must be attributed in the pose the ship is IN ────────────────────
# `record_hit` used to test a POSED point (host_io.world_to_body inverts the
# instance world matrix, which carries no node override -- so a hit arrives
# where the wing is DRAWN) against the REST boxes. Survivable against the old
# hand-drawn boxes, which deliberately swallowed the body at the wing roots;
# not survivable against the derived ones, which are tighter. A Bird of Prey
# at cruise took sustained wing fire and shed nothing, while the same ship at
# red alert shed normally. `part_for_live_point` -- already the rule for
# emitter attribution -- moves the QUERY instead of the boxes.

# The starboard mirror of the measurement in `part_for_live_point`'s own
# docstring: a rest wingtip that is drawn a quarter of a hull away once the
# wings are up.
WINGTIP_REST = (1.0, 0.0, -0.7)


def _posed_wingtip(ship, part_name="left wing01"):
    """Where WINGTIP_REST is DRAWN in `ship`'s current pose, ship units."""
    part = next(p for p in articulation.rig_for(LEAF)
                if p.GetName() == part_name)
    return part_pose.apply(articulation.pose_for_part(ship, part),
                           WINGTIP_REST)


def test_a_hit_on_a_POSED_wingtip_still_attributes_to_that_wing():
    """THE POINT. The hit lands where the wing IS, not where its box was
    baked."""
    ship = _Ship()
    _pose(ship, 1.0)                                  # wings fully up
    posed = _posed_wingtip(ship)
    assert posed != WINGTIP_REST, "the fixture must actually move the point"
    assert ps.part_for_point(LEAF, posed) is None, (
        "guard: if the rest boxes still contained the posed point this test "
        "would pass without the fix")

    ps.record_hit(ship, None, tuple(c / ps.MODEL_TO_SHIP for c in posed), 100.0)
    assert ps.damage_on(ship, "left wing01") == pytest.approx(100.0)


def test_a_posed_wing_still_SHEARS_at_its_threshold():
    """Attribution is only worth fixing if it reaches the detach. 4000 hull
    x 0.20 = 800."""
    ship = _Ship(hull=4000.0)
    _pose(ship, 1.0)
    model_pt = tuple(c / ps.MODEL_TO_SHIP for c in _posed_wingtip(ship))
    for _ in range(7):
        assert ps.record_hit(ship, None, model_pt, 100.0) is None
    assert ps.record_hit(ship, None, model_pt, 100.0) == "left wing01"
    assert ps.is_detached(ship, "left wing01")


def test_at_rest_attribution_is_UNCHANGED():
    """At the identity pose -- the pose the model ships in, and the one
    combat has run in until now -- every pullback is identity, so the live-pose query must
    give byte-identical answers to the rest-pose one."""
    ship = _Ship()
    _pose(ship, 0.0)
    assert _posed_wingtip(ship) == WINGTIP_REST
    ps.record_hit(ship, None,
                  tuple(c / ps.MODEL_TO_SHIP for c in WINGTIP_REST), 100.0)
    assert ps.damage_on(ship, "left wing01") == pytest.approx(100.0)

    # And a body hit stays unattributed at rest, exactly as before.
    body = _Ship()
    ps.record_hit(body, None, (0.0, -33.0, 0.0), 100.0)
    assert ps.damage_on(body, "left wing01") == 0.0
    assert ps.damage_on(body, "left wing") == 0.0


def test_the_conversion_constant_matches_BC_MODEL_SCALE():
    """MODEL_TO_SHIP is BC_MODEL_SCALE. If host_loop's value ever moves, this
    names the copy that has to move with it."""
    from engine import host_loop
    assert ps.MODEL_TO_SHIP == pytest.approx(host_loop.BC_MODEL_SCALE)


# ── Render sync: a severed part must not be re-posed (finding C1) ──────────────

def test_a_detached_part_is_not_repose_by_the_render_sync(monkeypatch):
    """REGRESSION. `_sync_ship_articulation` used to push a pose for EVERY
    rigged part whenever deflection changed, with no regard for severance.
    `set_instance_node_transform` and `set_instance_node_hidden` write into
    the SAME node_overrides slot, so re-posing a severed wing overwrote the
    zero matrix that was hiding it -- the wing snapped back onto the hull and
    animated with the good one, while its cannon stayed dead and its debris
    chunk flew off on its own. An identity push at the end of travel then
    ERASED the hide permanently.

    Fixed by skipping any part `part_severance.is_detached` reports as gone,
    mirroring the `part_transform_point` guard above."""
    from engine import host_loop

    calls = []
    monkeypatch.setattr(
        host_loop.host_io, "set_instance_node_transform",
        lambda iid, node, m16: calls.append((node, tuple(m16))) or True)

    ship = _Ship()
    _pose(ship, 0.5)  # a non-identity pose: the guard is live
    ps.detached_parts(ship).add("left wing01")
    session = types.SimpleNamespace(ship_articulation={})

    host_loop._sync_ship_articulation(session, ship, iid=1)

    port = next(p for p in articulation.rig_for(LEAF)
                if p.GetName() == "left wing")
    want = part_pose.matrix4_model(
        part_pose.interpolate(part_pose.IDENTITY, port.pose_for("cruise"),
                              port.anchor, 0.5),
        articulation.MODEL_TO_SHIP)
    assert [c[0] for c in calls] == ["left wing"], (
        "the severed wing must not receive a node-transform push")
    assert calls[0][1] == pytest.approx(want, abs=1e-12)


# ── The authored data ────────────────────────────────────────────────────────

def test_only_the_wings_are_detachable():
    d = articulation.detachable_for(LEAF)
    assert set(d) == {"left wing", "left wing01"}
    assert all(v == pytest.approx(0.20) for v in d.values())


def test_every_detachable_part_has_a_box():
    """A part that can shear but has no geometry would accumulate nothing and
    silently never detach."""
    parts = articulation.detachable_for(LEAF)
    boxes = articulation.part_boxes_for(LEAF)
    for name in parts:
        assert name in boxes, (LEAF, name)
