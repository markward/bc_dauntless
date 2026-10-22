"""Collisions must reach the hull's plating wear.

WHY THIS FILE EXISTS. Live report 2026-09-09: ramming a ship left no visible
damage, and nothing in the suite covered the collision -> hull-damage path at
all: ``test_collisions.py::test_respond_pair_invokes_apply_hit_for_both_ships``
MONKEYPATCHES ``combat.apply_hit``, so coverage stopped exactly at the
boundary in question. This pins the whole chain -- collisions ->
combat.apply_hit -> hit_feedback.dispatch -> hull_wear -> host_io -- end to
end, now that the hull's damage is layered plating wear (an HullDamageStore
record per hit) rather than the old voxel carve.

The wear THRESHOLD a collision must clear (hull_wear.COLLISION_MIN_HULL_DAMAGE,
an impact, never a scrape) is pinned by tests/unit/test_hull_wear.py.
"""
import pytest

from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass

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
def wear_boundary(monkeypatch):
    """Capture host_io.hull_damage_add and neutralise the sibling native
    touches dispatch makes on the way there (they reject the int instance ids
    a unit test uses)."""
    from engine import host_io
    from engine.appc import damage_decals as dd, hull_breakup, hull_wear

    calls = []
    monkeypatch.setattr(host_io, "hull_damage_add",
                        lambda *a, **k: calls.append(a))
    monkeypatch.setattr(host_io, "world_to_body",
                        lambda iid, p, n: ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
    monkeypatch.setattr(host_io, "damage_decal_add", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "shield_hit", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "ray_trace_mesh",
                        lambda iid, o, d, m: ((1.0, 0.0, 0.0),
                                              (0.0, 0.0, 1.0), 0.5))
    monkeypatch.setattr(hull_breakup, "after_wear", lambda *a, **k: [])
    monkeypatch.setattr(dd, "current_game_time", lambda: 100.0)
    hull_wear.reset()
    yield calls
    hull_wear.reset()


def test_a_hard_collision_wears_both_hulls(wear_boundary):
    """Both ships in a kinetic impact get a plating-wear record.

    This is the assertion that was missing. It fails if anything in
    collisions -> combat.apply_hit -> hit_feedback.dispatch -> hull_wear ->
    host_io stops forwarding: a swallowed exception in dispatch,
    absorbed_hull never being set, or allow_structural_wear going False.
    """
    from engine.appc import hit_feedback, damage_eligibility as de
    from engine.appc.collisions import _resolve_body, _respond_pair

    hit_feedback._last_decal_emit.clear()
    de.reset()

    # Closing speed 20 GU/s -- far above any wear threshold, so this test
    # measures REACHABILITY, not tuning.
    a = _ship(0.0, GALAXY_MASS, +10.0)
    b = _ship(1.5, GALAXY_MASS, -10.0)
    de.update([a, b])

    _respond_pair(_resolve_body(a), _resolve_body(b),
                  ship_instances={a: 11, b: 22})

    # positional signature: (instance_id, point, normal, radius, wear, kind)
    worn = {c[0]: c[4] for c in wear_boundary}
    assert set(worn) == {11, 22}, (
        f"a collision must wear BOTH hulls; got {wear_boundary}")
    for iid, wear in worn.items():
        assert wear > 0.0, f"instance {iid} got a zero-wear record"
