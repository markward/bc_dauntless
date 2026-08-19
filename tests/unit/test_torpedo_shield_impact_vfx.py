"""A torpedo absorbed by shields must produce a shield-impact flash.

Entered at the host poller (_advance_combat), not at apply_hit, so the whole
chain is exercised: projectiles.update_all resolves the hit and the bubble
entry, host_loop routes it, apply_hit runs the cascade, hit_feedback classifies
and pushes the flash.

A photon torpedo is 500 damage (Tactical/Projectiles/PhotonTorpedo.GetDamage)
against a Galaxy facing of 4000-8000 (ships/Hardpoints/galaxy.py:738-743), so a
full facing absorbs it outright and the impact must classify SHIELD.
"""
import math

import pytest

from engine.appc import combat, hit_feedback, projectiles
from engine.appc.math import TGPoint3
from engine.appc.projectiles import Torpedo, register
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem

# Galaxy AABB half-extents x BC_MODEL_SCALE, as _cache_shield_hull_box leaves
# them. Values from native model_aabb (see combat._shield_face_from_hit_point).
from engine.host_loop import BC_MODEL_SCALE

GALAXY_HALF = tuple(v * BC_MODEL_SCALE for v in (232.064, 322.166, 70.4982))
SQRT3 = math.sqrt(3.0)


@pytest.fixture(autouse=True)
def _clear_registry():
    projectiles._active.clear()
    yield
    projectiles._active.clear()


def _target():
    s = ShipClass_Create("Target")
    s._hull = HullSubsystem("Hull")
    s._hull.SetMaxCondition(20000.0)
    ss = ShieldSubsystem("Shield Generator")
    ss.SetMaxShields(ShieldSubsystem.FRONT_SHIELDS, 8000.0)
    for f in (1, 2, 3, 4, 5):
        ss.SetMaxShields(f, 4000.0)
    s.SetShieldSubsystem(ss)
    s.SetTranslateXYZ(0.0, 0.0, 0.0)
    s._shield_hull_box = ((0.0, 0.0, 0.0), GALAXY_HALF)
    s._radius = math.sqrt(sum(v * v for v in GALAXY_HALF))   # bounding sphere
    return s


def _shooter():
    s = ShipClass_Create("Shooter")
    s.SetTranslateXYZ(0.0, 5000.0, 0.0)
    return s


def _place_one_step_outside_the_bubble(t, dt):
    """Put the torpedo half a tick short of the bow bubble surface, so this
    tick's segment crosses it. Placing it at the BOUNDING SPHERE instead — as
    these tests used to — is unreachable in flight now that the bubble stops
    the shot 1.55 GU earlier; the torpedo would already be inside, which is the
    fall-through-to-hull case, not the shield case."""
    step = abs(t._velocity.y) * dt
    t._position = TGPoint3(0.0, GALAXY_HALF[1] * SQRT3 + 0.5 * step, 0.0)


def _torpedo_inbound(src, speed_gu_s=55.0):
    """A photon torpedo closing on the bow along -Y."""
    t = Torpedo()
    t._damage = 500.0
    t._damage_radius_factor = 0.13
    t._source_ship = src
    t._velocity = TGPoint3(0.0, -speed_gu_s, 0.0)
    register(t)
    return t


def _run_tick(ships, dt, ship_instances, monkeypatch):
    """Drive _advance_combat, capturing host_io.shield_hit calls."""
    from engine import host_loop
    calls = []
    monkeypatch.setattr(hit_feedback.host_io, "shield_hit",
                        lambda iid, point, rgba, intensity, radius=0.0:
                            calls.append(point))
    # Everything else the frame pushes to the renderer is irrelevant here.
    for name in ("set_torpedoes", "set_dynamic_lights", "set_shockwaves",
                 "set_hit_vfx", "set_particle_emitters", "set_phaser_beams",
                 "set_tractor_beams"):
        monkeypatch.setattr(host_loop.host_io, name, lambda *a, **k: None)
    host_loop._advance_combat(ships, dt, ship_instances=ship_instances)
    return calls


def test_torpedo_absorbed_by_shields_fires_a_shield_flash(monkeypatch):
    src, tgt = _shooter(), _target()
    t = _torpedo_inbound(src)
    dt = 1.0 / 60.0
    _place_one_step_outside_the_bubble(t, dt)

    calls = _run_tick([src, tgt], dt, {tgt: 1}, monkeypatch)

    assert tgt.GetHull().GetCondition() == 20000.0, "shields should have absorbed it"
    assert len(calls) == 1, "a fully-absorbed torpedo must flash the shields"


def test_torpedo_shield_flash_is_anchored_on_the_bubble(monkeypatch):
    src, tgt = _shooter(), _target()
    t = _torpedo_inbound(src)
    dt = 1.0 / 60.0
    _place_one_step_outside_the_bubble(t, dt)

    calls = _run_tick([src, tgt], dt, {tgt: 1}, monkeypatch)

    assert len(calls) == 1
    # The bow bubble surface, not the hull nose and not where the torpedo
    # happened to stop.
    assert calls[0][1] == pytest.approx(GALAXY_HALF[1] * SQRT3, abs=1.0)


# ── partial absorption must still flash the shields ────────────────────────
#
# BC's impact loop runs TWO passes (stbc_reference spec/ShieldFacingDamage.md
# §3.1): pass 1 hits the facing and fires a shield-hit event, then the residual
# is RE-DISPATCHED against the hull in pass 2. A shot that overdraws a weakened
# facing therefore produces BOTH a shield flash and a hull impact.
#
# We classified winner-take-all: any hull leak-through returned HULL, which took
# the hit_vfx branch and never called shield_hit. So once a facing was worn down
# — the normal state after any sustained exchange — torpedoes stopped flashing
# the shields entirely, which reads as "torpedoes don't hit shields".

def test_partial_absorption_fires_both_the_flash_and_the_hull_impact(monkeypatch):
    src, tgt = _shooter(), _target()
    # Facing worn down to less than the torpedo's 500: absorbs 200, leaks 300.
    tgt.GetShields().SetCurrentShields(ShieldSubsystem.FRONT_SHIELDS, 200.0)
    t = _torpedo_inbound(src)
    dt = 1.0 / 60.0
    _place_one_step_outside_the_bubble(t, dt)

    from engine.appc import hit_vfx
    spawned = []
    monkeypatch.setattr(hit_vfx, "spawn",
                        lambda *a, **k: spawned.append(k.get("severity")))

    calls = _run_tick([src, tgt], dt, {tgt: 1}, monkeypatch)

    assert tgt.GetShields().GetCurrentShields(ShieldSubsystem.FRONT_SHIELDS) == 0.0
    assert tgt.GetHull().GetCondition() == 20000.0 - 300.0
    assert len(calls) == 1, "the facing absorbed 200 — it must flash"
    assert len(spawned) == 1, "and the 300 that got through must show a hull impact"


def test_zero_absorption_does_not_flash(monkeypatch):
    """A facing that is fully down absorbs nothing, so there is nothing to
    flash — only the hull impact."""
    src, tgt = _shooter(), _target()
    tgt.GetShields().SetCurrentShields(ShieldSubsystem.FRONT_SHIELDS, 0.0)
    t = _torpedo_inbound(src)
    dt = 1.0 / 60.0
    _place_one_step_outside_the_bubble(t, dt)

    calls = _run_tick([src, tgt], dt, {tgt: 1}, monkeypatch)

    assert tgt.GetHull().GetCondition() < 20000.0
    assert calls == []


# ── the torpedo meets the bubble, not the bounding sphere ──────────────────
#
# Collision tested ship.GetRadius() -- an isotropic bounding sphere, 4.03 GU on
# a Galaxy -- against a bubble whose semi-axes are 4.02 / 5.58 / 1.22. It
# matched only on the flank, by coincidence:
#
#   bow/stern : detonated 1.55 GU INSIDE the bubble (1.7 ticks past crossing)
#   dorsal    : detonated 2.81 GU OUTSIDE, never reaching the shield at all
#
# BC's projectile loop calls TestHit, which intersects the shield ellipsoid
# FIRST and only falls to the hull when no live facing stops the shot
# (stbc_reference spec/ShieldFacingDamage.md §3.1, §2.3).

def test_torpedo_detonates_on_the_bubble_not_the_bounding_sphere():
    from engine.appc.projectiles import update_all
    src, tgt = _shooter(), _target()
    t = _torpedo_inbound(src)
    dt = 1.0 / 60.0
    step = abs(t._velocity.y) * dt
    bubble_y = GALAXY_HALF[1] * SQRT3
    # One step outside the bubble — and still well outside the bounding
    # sphere, so the OLD rule would not have registered a hit this tick at all.
    t._position = TGPoint3(0.0, bubble_y + 0.5 * step, 0.0)
    assert t._position.y > tgt._radius, "premise: outside the bounding sphere"

    hits = update_all(dt, [src, tgt])

    assert len(hits) == 1, "the segment crossed the bubble — that is the hit"
    assert t._position.y == pytest.approx(bubble_y, abs=1e-3), \
        "the torpedo stops ON the bubble"


def test_torpedo_with_shields_down_still_uses_the_hull_path():
    from engine.appc.projectiles import update_all
    src, tgt = _shooter(), _target()
    tgt.GetShields().TurnOff()
    t = _torpedo_inbound(src)
    dt = 1.0 / 60.0
    step = abs(t._velocity.y) * dt
    bubble_y = GALAXY_HALF[1] * SQRT3
    t._position = TGPoint3(0.0, bubble_y + 0.5 * step, 0.0)

    assert update_all(dt, [src, tgt]) == [], "no bubble to stop it out here"

    # It carries on and detonates at the bounding sphere, as before.
    t._position = TGPoint3(0.0, tgt._radius + 0.5 * step, 0.0)
    assert len(update_all(dt, [src, tgt])) == 1


def test_dorsal_torpedo_reaches_the_thin_axis_of_the_bubble():
    """The dorsal bubble semi-axis (1.22 GU) is far inside the bounding sphere
    (4.03), so the old rule detonated the torpedo 2.81 GU short of the shield."""
    from engine.appc.projectiles import update_all
    src, tgt = _shooter(), _target()
    t = _torpedo_inbound(src)
    dt = 1.0 / 60.0
    speed = abs(t._velocity.y)
    t._velocity = TGPoint3(0.0, 0.0, -speed)          # straight down onto the dorsal
    step = speed * dt
    bubble_z = GALAXY_HALF[2] * SQRT3
    t._position = TGPoint3(0.0, 0.0, bubble_z + 0.5 * step)

    hits = update_all(dt, [src, tgt])

    assert len(hits) == 1
    assert t._position.z == pytest.approx(bubble_z, abs=1e-3)
