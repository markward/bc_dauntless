"""Collisions must reach the hull-carve boundary, and the tuning that decides
whether the result is visible.

WHY THIS FILE EXISTS. Live report 2026-09-09: ramming a ship leaves no visible
damage. Nothing in the suite covered the collision -> carve path at all:
``test_collisions.py::test_respond_pair_invokes_apply_hit_for_both_ships``
MONKEYPATCHES ``combat.apply_hit``, so coverage stopped exactly at the boundary
in question, and ``test_hull_carve_emission.py`` hands ``absorbed_hull`` to
``hit_feedback.dispatch`` directly, so it never exercises the computation of it
in ``combat.apply_hit``. Between the two, the whole chain was dark.

The chain is NOT broken -- a collision does reach ``host_io.hull_carve_add``,
which the first test pins. What makes a ram look like nothing happened is
arithmetic: ``scenegraph::kHullCarveStrengthIso`` is 150 absorbed-hull before
any hole appears, and ``_ke_damage`` is QUADRATIC in closing speed. For a
Galaxy-class pair that puts the threshold at exactly 1.0 GU/s of CLOSING speed
(630 km/h) -- and a chase, where both ships already match velocity, never gets
near it. An ordinary manoeuvring bump at 0.5 GU/s does 37.5 damage, a quarter
of what the smallest possible hole needs. The second test records that,
measured, so a future tuning change has to confront the numbers.
"""
import pytest

from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass

# scenegraph/hull_carve.h: strength below this carves NOTHING (radius 0.0).
# Duplicated here deliberately -- it is a C++ constant with no Python binding,
# and this file's whole point is to state the threshold ordinary collisions
# are measured against. If the C++ value changes, this number must too.
HULL_CARVE_STRENGTH_ISO = 150.0

# ships/Hardpoints/Galaxy.py: `Galaxy.SetMass(120.0)`. NOT in
# GlobalPropertyTemplates.py, which carries only 12 masses and no Galaxy.
GALAXY_MASS = 120.0


class _Hull:
    def IsDestroyed(self):
        return 0


def _ship(x, mass, vx, radius=1.0):
    s = ShipClass()
    s.SetTranslateXYZ(x, 0.0, 0.0)
    s.SetRadius(radius)
    s.SetMass(mass)
    s.SetVelocity(TGPoint3(vx, 0.0, 0.0))
    # combat.apply_hit only sets absorbed_hull when the ship has a hull AND a
    # DamageSystem; a bare ShipClass has neither, and a fixture without them
    # reports absorbed_hull 0.0 and silently proves nothing.
    s.GetHull = lambda: _Hull()
    s.DamageSystem = lambda sub, dmg, src=None: None
    return s


@pytest.fixture
def carve_boundary(monkeypatch):
    """Capture host_io.hull_carve_add and neutralise the sibling native
    touches dispatch makes on the way there (they reject the int instance ids
    a unit test uses)."""
    from engine import host_io
    from engine.appc import damage_decals as dd

    calls = []
    monkeypatch.setattr(host_io, "hull_carve_add",
                        lambda *a, **k: calls.append(a))
    monkeypatch.setattr(host_io, "world_to_body",
                        lambda iid, p, n: ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
    monkeypatch.setattr(host_io, "damage_decal_add", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "shield_hit", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "ray_trace_mesh",
                        lambda iid, o, d, m: ((1.0, 0.0, 0.0),
                                              (0.0, 0.0, 1.0), 0.5))
    monkeypatch.setattr(dd, "current_game_time", lambda: 100.0)
    return calls


def test_a_hard_collision_reaches_the_hull_carve_boundary(carve_boundary):
    """Both ships in a kinetic impact deposit a carve, with strength equal to
    the hull damage they absorbed.

    This is the assertion that was missing. It fails if anything in
    collisions -> combat.apply_hit -> hit_feedback.dispatch -> host_io stops
    forwarding: a swallowed exception in dispatch, absorbed_hull never being
    set, allow_hull_carve going False, or the eligibility set not covering the
    ships involved.
    """
    from engine.appc import hit_feedback, damage_eligibility as de
    from engine.appc.collisions import _resolve_body, _respond_pair

    hit_feedback._last_carve_time.clear()
    hit_feedback._pending_carve_strength.clear()
    de.reset()

    # Closing speed 20 GU/s -- deliberately far above the iso, so this test
    # measures REACHABILITY, not tuning. The tuning is the next test.
    a = _ship(0.0, GALAXY_MASS, +10.0)
    b = _ship(1.5, GALAXY_MASS, -10.0)
    de.update([a, b])

    _respond_pair(_resolve_body(a), _resolve_body(b),
                  ship_instances={a: 11, b: 22})

    assert len(carve_boundary) == 2, (
        "a collision must carve BOTH hulls; got "
        f"{len(carve_boundary)} carve deposit(s)")
    # positional signature: (instance_id, point, normal, influ, strength, ...)
    deposited = {c[0]: c[4] for c in carve_boundary}
    assert set(deposited) == {11, 22}
    for iid, strength in deposited.items():
        assert strength > HULL_CARVE_STRENGTH_ISO, (
            f"instance {iid} deposited {strength}, at or below the "
            f"{HULL_CARVE_STRENGTH_ISO} iso -- it would carve nothing")


@pytest.mark.parametrize("v_rel_gu_s, expect_visible", [
    (0.1, False),    # 63 km/h -- station-keeping nudge:        1.5 damage
    (0.5, False),    # 315 km/h -- ordinary manoeuvring contact: 37.5 damage
    (0.9, False),    # 567 km/h -- a brisk bump, STILL short:   121.5 damage
    (1.2, True),     # 756 km/h -- just past the threshold:     216.0 damage
    (2.0, True),     # 1260 km/h -- a deliberate ram:           600.0 damage
    (6.3, True),     # 3969 km/h -- Galaxy flank speed head-on: 5953.5 damage
])
def test_only_a_deliberate_ram_clears_the_carve_iso(v_rel_gu_s, expect_visible):
    """The measured reason a ram can look like nothing happened.

    `_ke_damage` is quadratic in closing speed, so between an ordinary bump
    and a deliberate ram the damage moves by four orders of magnitude. For a
    Galaxy-class pair (mass 120, reduced mass 60) damage is exactly
    150 * v_rel**2, so the iso is crossed at exactly 1.0 GU/s (630 km/h) of
    CLOSING speed -- and a chase, where both ships already match velocity,
    never gets near that.

    This is tuning, not a defect: the deliberate design (spec §7) is that a
    collision should DENT rather than carve, and the dent brush is not built.
    If that tuning changes, these expectations change with it -- which is the
    point of pinning them.
    """
    from engine.appc.collisions import _ke_damage

    inv_sum = 1.0 / GALAXY_MASS + 1.0 / GALAXY_MASS
    damage = _ke_damage(inv_sum, v_rel_gu_s)
    assert (damage >= HULL_CARVE_STRENGTH_ISO) is expect_visible, (
        f"closing {v_rel_gu_s} GU/s ({v_rel_gu_s * 630:.0f} km/h) does "
        f"{damage:.1f} hull damage against a {HULL_CARVE_STRENGTH_ISO} iso")
