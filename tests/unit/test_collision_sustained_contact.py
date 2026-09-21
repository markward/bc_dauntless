"""Sustained and rotation-driven contact must damage the hull.

WHY THIS FILE EXISTS. Live report 2026-09-09: "I literally ground my ship into
another one using angular acceleration and nothing happened." Measured, two
mechanisms produced exactly that, and together they made grinding inert
regardless of force or duration:

1. ``_resolve_body`` built each body's velocity from ``GetVelocity()`` --
   linear centre-of-mass only. ``_current_angular_velocity`` was never read, so
   a ship spinning at 2 rad/s in contact reported body velocity (0, 0, 0) and
   ``_respond_pair`` returned None. The rigid-body contact velocity is
   ``v_cm + omega x r``; only the first term existed.
2. ``if v_rel >= 0.0: return None`` -- the "receding / resting" debounce --
   discarded a resting contact outright. Probed: 120 frames of pressing in at
   0.4 GU/s registered ONE hit, because the first frame's impulse flips the
   relative velocity to receding and every later frame bails.

The fix keeps the debounce governing IMPULSE and de-penetration -- it is doing
real work there, and an impulse that cannot change angular velocity would
re-fire every frame against a spinning ship and fling the pair apart -- and
adds a separate, dt-scaled GRIND channel driven by tangential slip at the
contact point, which is what abrasion physically is. A contact with no relative
motion still does nothing.
"""
import pytest

from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass

GALAXY_MASS = 120.0
FRAME = 1.0 / 60.0


class _Hull:
    def IsDestroyed(self):
        return 0


def _ship(x, mass=GALAXY_MASS, vx=0.0, radius=1.0):
    s = ShipClass()
    s.SetTranslateXYZ(x, 0.0, 0.0)
    s.SetRadius(radius)
    s.SetMass(mass)
    s.SetVelocity(TGPoint3(vx, 0.0, 0.0))
    s.GetHull = lambda: _Hull()
    s.DamageSystem = lambda sub, dmg, src=None: None
    return s


@pytest.fixture
def damage_calls(monkeypatch):
    """Capture combat.apply_hit -- the collision module's own output boundary.
    The chain onward to host_io.hull_carve_add is pinned by
    test_collision_hull_carve.py; this file is about what collisions DECIDE."""
    import engine.appc.combat as combat
    calls = []
    monkeypatch.setattr(combat, "apply_hit",
                        lambda ship, dmg, *a, **k: calls.append((ship, dmg)))
    return calls


def _grind(a, b, frames, dt=FRAME):
    """Run `frames` frames of contact resolution, as tick_collisions does."""
    from engine.appc.collisions import _resolve_body, _respond_pair
    for _ in range(frames):
        _respond_pair(_resolve_body(a), _resolve_body(b), None, dt)


def test_a_spinning_ship_in_contact_damages_the_hull(damage_calls):
    """Rotation-driven contact must register. With omega absent from the
    contact velocity this produced zero damage no matter how long it ran."""
    a = _ship(0.0)
    b = _ship(1.5)
    # Body-frame yaw; _current_angular_velocity is body frame (ship_motion
    # post-multiplies the delta), so the implementation must rotate it into
    # world space before crossing it with the contact arm.
    a._current_angular_velocity = TGPoint3(0.0, 0.0, 2.0)

    _grind(a, b, frames=60)   # one second of grinding

    total = sum(d for _s, d in damage_calls)
    assert total > 0.0, (
        "a ship spinning against another hull took zero damage over a full "
        "second of contact")


def test_sustained_contact_keeps_accruing_damage(damage_calls):
    """Pressing into a hull must keep damaging while there is relative motion.

    Before the grind channel this registered exactly ONE hit in 120 frames --
    the impulse flipped the pair to receding and the debounce swallowed the
    rest.
    """
    a = _ship(0.0)
    b = _ship(1.5)
    a._current_angular_velocity = TGPoint3(0.0, 0.0, 1.0)

    _grind(a, b, frames=10)
    after_10 = sum(d for _s, d in damage_calls)
    damage_calls.clear()

    a2 = _ship(0.0)
    b2 = _ship(1.5)
    a2._current_angular_velocity = TGPoint3(0.0, 0.0, 1.0)
    _grind(a2, b2, frames=60)
    after_60 = sum(d for _s, d in damage_calls)

    assert after_60 > after_10 * 3.0, (
        f"damage did not keep accruing: 10 frames -> {after_10}, "
        f"60 frames -> {after_60}")


def test_a_resting_contact_with_no_relative_motion_does_nothing(damage_calls):
    """The guard against the opposite failure: two hulls overlapping but
    perfectly still must not grind themselves apart."""
    a = _ship(0.0)
    b = _ship(1.5)
    _grind(a, b, frames=120)
    assert damage_calls == [], (
        f"a motionless resting contact produced {len(damage_calls)} damage "
        "events")


def test_grind_damage_is_frame_rate_independent(damage_calls):
    """Damage must come out of dt, not out of frame count -- otherwise the
    same manoeuvre hurts more on a faster machine."""
    a = _ship(0.0)
    b = _ship(1.5)
    a._current_angular_velocity = TGPoint3(0.0, 0.0, 1.0)
    _grind(a, b, frames=120, dt=1.0 / 120.0)   # 1 s at 120 fps
    fast = sum(d for _s, d in damage_calls)
    damage_calls.clear()

    a2 = _ship(0.0)
    b2 = _ship(1.5)
    a2._current_angular_velocity = TGPoint3(0.0, 0.0, 1.0)
    _grind(a2, b2, frames=30, dt=1.0 / 30.0)   # 1 s at 30 fps
    slow = sum(d for _s, d in damage_calls)

    assert fast == pytest.approx(slow, rel=0.02), (
        f"1 s of the same grind gave {fast} at 120 fps but {slow} at 30 fps")


def test_dt_zero_is_the_pre_existing_behaviour(damage_calls):
    """Every existing caller and test passes no dt. With dt == 0 the grind
    channel must contribute nothing, so their behaviour is unchanged."""
    a = _ship(0.0)
    b = _ship(1.5)
    a._current_angular_velocity = TGPoint3(0.0, 0.0, 2.0)
    _grind(a, b, frames=60, dt=0.0)
    assert damage_calls == []


def test_grinding_never_posts_a_collision_event(monkeypatch, damage_calls):
    """Abrasion must stay silent on the SDK event channel.

    ET_OBJECT_COLLISION is not cosmetic: MissionLib.FriendlyFireCollisionHandler
    treats one as a GAME OVER, and E7M2 has its own ShipsCollided handler. A
    grind posting an event per frame would end a mission the instant you
    scraped a friendly. The impact path still emits exactly as before.
    """
    import engine.appc.collisions as collisions
    events = []
    monkeypatch.setattr(collisions, "_emit_object_collision",
                        lambda *a, **k: events.append(a))
    monkeypatch.setattr(collisions, "_emit_cloaked_collision",
                        lambda *a, **k: None)

    a = _ship(0.0)
    b = _ship(1.5)
    a._current_angular_velocity = TGPoint3(0.0, 0.0, 2.0)
    _grind(a, b, frames=120)

    assert sum(d for _s, d in damage_calls) > 0.0, "fixture did not grind"
    assert events == [], (
        f"grinding posted {len(events)} collision event(s); "
        "FriendlyFireCollisionHandler would end the mission")


def test_grind_contact_is_refined_to_the_mesh_like_an_impact(monkeypatch):
    """The grind must land on the HULL, not on the bounding sphere.

    The impact path traces from the other body's centre into this ship and
    carves at the mesh surface with the mesh normal. BC bounding spheres are
    5-22x too loose, so a carve deposited at the sphere contact point sits
    off the hull entirely, with a normal that is the centre-to-centre line
    rather than the local surface -- a scoop oriented and positioned wrong.
    Mirrors test_collisions.py::test_contact_point_refined_to_mesh_when_host_
    present for the grind channel.
    """
    from engine import host_io
    import engine.appc.combat as combat

    captured = []
    monkeypatch.setattr(
        combat, "apply_hit",
        lambda ship, dmg, hit_point, source=None, *, normal=None, **k:
            captured.append((ship, hit_point, normal)))

    def _fake_trace(iid, origin, direction, max_dist):
        # Encode which ship was traced in x (= iid); distinctive mesh normal.
        return ((float(iid), 7.0, 7.0), (0.0, 0.0, 1.0), 0.5)
    monkeypatch.setattr(host_io, "ray_trace_mesh", _fake_trace)

    a = _ship(0.0)
    b = _ship(1.5)
    a._current_angular_velocity = TGPoint3(0.0, 0.0, 2.0)
    insts = {a: 11, b: 22}
    from engine.appc.collisions import _resolve_body, _respond_pair
    _respond_pair(_resolve_body(a), _resolve_body(b), insts, FRAME)

    assert captured, "fixture did not grind"
    pts = {id(s): hp for s, hp, _n in captured}
    assert pts[id(a)].x == 11.0 and pts[id(a)].y == 7.0, (
        f"ship a's grind landed at {pts[id(a)]}, not on its mesh")
    assert pts[id(b)].x == 22.0 and pts[id(b)].y == 7.0, (
        f"ship b's grind landed at {pts[id(b)]}, not on its mesh")
    for _s, _hp, n in captured:
        assert (n.x, n.y, n.z) == (0.0, 0.0, 1.0), (
            f"grind used normal {n}, not the mesh surface normal")


# ── developer-mode collision log ─────────────────────────────────────────

def test_dev_log_names_both_parties_and_the_channel(monkeypatch, capsys, damage_calls):
    """A live "the ship collided with something" report had no trail at all:
    the impact channel posts an SDK event only some missions handle and the
    grind channel posts nothing. Under --developer both channels print who
    hit whom."""
    from engine import dev_mode
    import engine.appc.collisions as C
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    C._grind_log_last.clear()

    a = _ship(0.0, vx=1.0)
    b = _ship(1.5, vx=-1.0)
    a.SetName("Dauntless"); b.SetName("Devore")
    C.resolve_collisions([a, b], None, FRAME)          # approaching: impact
    # The impact de-penetrated the pair; put them back in contact, at rest,
    # and spin one so the grind channel is what fires.
    a.SetTranslateXYZ(0.0, 0.0, 0.0); b.SetTranslateXYZ(1.5, 0.0, 0.0)
    a.SetVelocity(TGPoint3(0.0, 0.0, 0.0)); b.SetVelocity(TGPoint3(0.0, 0.0, 0.0))
    a._current_angular_velocity = TGPoint3(0.0, 0.0, 2.0)
    _grind(a, b, frames=120)                           # resting + spin: grind
    err = capsys.readouterr().err
    impact = [l for l in err.splitlines() if "IMPACT" in l]
    grind = [l for l in err.splitlines() if "GRIND" in l]
    assert len(impact) == 1 and "'Dauntless'" in impact[0] and "'Devore'" in impact[0]
    assert len(grind) == 1, "grind is throttled to one line per pair per second"


def test_dev_log_is_silent_outside_developer_mode(monkeypatch, capsys, damage_calls):
    from engine import dev_mode
    import engine.appc.collisions as C
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    a = _ship(0.0, vx=1.0)
    b = _ship(1.5, vx=-1.0)
    C.resolve_collisions([a, b], None, FRAME)
    assert "[collision]" not in capsys.readouterr().err


def test_dev_log_reports_each_sides_hull_piece_count(monkeypatch, capsys, damage_calls):
    """Live 2026-09-21 (Collision Sim): every contact sat on the whole-body
    sphere for the whole session, so one side had no cached pieces — but the
    log could not say which. It now prints pieces=a:<n>/b:<n>."""
    from engine import dev_mode
    from engine.appc import hull_bounds
    import engine.appc.collisions as C
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    a = _ship(0.0, vx=1.0)
    b = _ship(1.5, vx=-1.0)
    hull_bounds.cache_hull_bound_spheres(a, [(0.0, 0.0, 0.0, 10.0), (5.0, 0.0, 0.0, 5.0)])
    C.resolve_collisions([a, b], None, FRAME)
    err = capsys.readouterr().err
    impact = [l for l in err.splitlines() if "IMPACT" in l]
    assert len(impact) == 1 and "pieces=a:2/b:0" in impact[0], impact
