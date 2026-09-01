"""Ship-only loops must not iterate every set object.

A SetClass holds waypoints, planets and light placements alongside ships.
`TGObject.__getattr__` hands back a truthy `_Stub` for any unknown engine
method, so a ship-only loop that walks a whole set silently "works" on those
objects — it just calls no-ops (and, worse, reads stub *values* into real
arithmetic). See docs/plans/2026-07-13-vacuous-hasattr-sweep.md.

Covered here:
  * collision_avoidance._world_velocity — a Planet has no GetVelocity, so the
    stub's components poisoned the relative-velocity solve.
  * warp._silence_ship_weapons — walks `_objects.values()` of the source set.
  * ship_motion's immobility gate — vacuously true on any non-ship.
  * DamageableObject.IsDying/IsDead — BC defines them there, we defined them
    on ShipClass only.
  * subsystems._get_xyz's accessor probe — the same trap in the shared
    position helper: it tried GetTranslate first behind a hasattr, so any
    TGObject without a real one read the stub's components as the ORIGIN.
"""
import App
import pytest

from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from engine.appc.planet import Planet
from engine.appc.placement import Waypoint
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import HullSubsystem
from engine.core import stub_telemetry


@pytest.fixture(autouse=True)
def _isolate():
    App.g_kSetManager._sets.clear()
    yield
    App.g_kSetManager._sets.clear()
    stub_telemetry.set_enabled(False)
    stub_telemetry.reset()


@pytest.fixture
def _watch_stubs():
    """Record every stub attribute access made inside the block."""
    stub_telemetry.reset()
    stub_telemetry.set_enabled(True)
    yield lambda: stub_telemetry.snapshot()["attr_hits"]
    stub_telemetry.set_enabled(False)


def _ship(name="Ship", loc=(0.0, 0.0, 0.0), radius=20.0):
    s = ShipClass_Create(name)
    h = HullSubsystem("Hull")
    h.SetMaxCondition(1e9)
    s._hull = h
    s.SetWorldLocation(TGPoint3(*loc))
    s.SetRadius(radius)
    return s


# ── collision avoidance ──────────────────────────────────────────────────────


def test_world_velocity_does_not_stub_probe_an_object_without_velocity(_watch_stubs):
    """A Planet is an ObjectClass — GetVelocity lives on PhysicsObjectClass, so
    it doesn't have one. _world_velocity called it anyway on every obstacle,
    every avoidance evaluation: 4,924 recorded stub hits (heatmap ranks 7-10).
    Ask whether the object implements the call instead."""
    from engine.appc.collision_avoidance import _world_velocity

    _world_velocity(Planet(200.0, "planet.nif"))

    assert _watch_stubs() == {}


def test_world_velocity_of_an_object_without_velocity_is_zero():
    """The value read out must stay the zero vector — which is what the stub
    already produced (TGPoint3.__init__ floats its args and _Stub.__float__ is
    0.0), and what collisions._resolve_body forces for planets. Pinned so the
    churn fix provably changes no behaviour."""
    from engine.appc.collision_avoidance import _world_velocity

    v = _world_velocity(Planet(200.0, "planet.nif"))

    assert (v.x, v.y, v.z) == (0.0, 0.0, 0.0)


def test_ai_ship_avoids_a_planet_dead_ahead():
    """Characterization: planet avoidance works today (the stub velocity
    already floats to zero) and must keep working after the fix."""
    from engine.appc import collision_avoidance
    collision_avoidance.reset_avoidance_state()

    pSet = App.SetClass_Create()
    pSet.SetName("S")
    App.g_kSetManager._sets["S"] = pSet

    ship = _ship("Ship", loc=(0.0, 0.0, 0.0), radius=20.0)
    ship.SetAI(object())
    ship.SetVelocity(TGPoint3(0.0, 30.0, 0.0))   # 30 GU/s straight at it
    pSet.AddObjectToSet(ship, "Ship")

    planet = Planet(150.0, "planet.nif")
    planet.SetWorldLocation(TGPoint3(0.0, 400.0, 0.0))
    pSet.AddObjectToSet(planet, "Planet")

    heading, speed = collision_avoidance._test_course_override(ship)

    assert heading is not None, "no evasion against a planet dead ahead"


# ── warp: silence weapons on the ships of a set, not every object ────────────


def test_silence_ship_weapons_ignores_non_ship_set_objects(_watch_stubs):
    """The warp depart/arrive actions walk `src._objects.values()` and call
    _silence_ship_weapons on each — waypoints and light placements included.
    Those have no weapon systems; the getters must not be probed on them."""
    from engine.appc.warp import _silence_ship_weapons

    _silence_ship_weapons(Waypoint())
    _silence_ship_weapons(Planet(200.0, "planet.nif"))

    assert _watch_stubs() == {}


# ── HUD reticle: the target can be a planet ──────────────────────────────────


def test_reticle_text_does_not_stub_probe_a_planet_target(_watch_stubs):
    """The reticle reads the TARGET's velocity, and a planet is targetable —
    the other source of the Planet.GetVelocity stub rows. A planet has no
    velocity; the readout must be 0 kph without touching a stub."""
    import math
    from engine.ui.reticle_text import build_reticle_text, _ReticleCam

    planet = Planet(150.0, "planet.nif")
    planet.SetWorldLocation(TGPoint3(0.0, 0.0, 0.0))
    planet.SetName("Haven")

    player = _ship("Player", loc=(0.0, -500.0, 0.0))
    player.SetTarget(planet)

    cam = _ReticleCam(eye=(0.0, -500.0, 0.0), target=(0.0, 0.0, 0.0),
                      up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(60.0),
                      near=1.0, far=50000.0)
    out = build_reticle_text(player, cam, (1280, 720))

    assert "0 kph" in out["line2"]
    hits = _watch_stubs()
    assert not any(attr.startswith("GetVelocity") for _owner, attr in hits)


# ── the shared position helper ───────────────────────────────────────────────


def test_get_xyz_probes_the_accessor_with_implements_not_hasattr():
    """`_get_xyz` tries GetTranslate, GetWorldLocation, ... in order. hasattr
    is vacuously true for all of them on any TGObject, so the loop always
    "found" GetTranslate, called the `_Stub`, and read .x/.y/.z off it as 0.0 —
    the origin, for an object that has a perfectly good position.

    Every ObjectClass defines GetTranslate, which is why this never fired in
    production — but _get_xyz is the shared helper behind perception and
    can_detect, and a positionless read there is silent.

    ⚠️ This used the live `projectiles.Torpedo` until 2026-09-01, when
    Torpedo was promoted from TGObject to ObjectClass so it could become a
    real set member (emitter gaps #6/#7). It therefore has GetTranslate now,
    and the premise no longer holds for it. A sweep of every TGObject subclass
    in engine.appc found NO remaining production class with this shape, so the
    subject below is a purpose-built double — deliberately minimal, mirroring
    exactly the condition under test. If a real class ever regains this shape,
    prefer it: a live subject cannot drift away from production the way a
    double can."""
    from engine.appc.subsystems import _get_xyz
    from engine.core.ids import TGObject, implements

    class _PositionedNonObjectClass(TGObject):
        """A TGObject with a real GetWorldLocation and no real GetTranslate."""

        def __init__(self, point):
            super().__init__()
            self._point = point

        def GetWorldLocation(self):
            return self._point

    subject = _PositionedNonObjectClass(TGPoint3(0.0, 500.0, 0.0))

    # The premise: no real GetTranslate, but a real GetWorldLocation.
    assert not implements(subject, "GetTranslate")
    assert implements(subject, "GetWorldLocation")
    assert hasattr(subject, "GetTranslate")       # ...and hasattr says yes

    assert _get_xyz(subject) == (0.0, 500.0, 0.0)


def test_a_torpedo_still_reads_its_position_after_the_promotion():
    """The promotion above must not have moved a torpedo's position read.

    ObjectClass.GetTranslate and Torpedo's own GetWorldLocation both resolve
    `self._position`, so _get_xyz now takes the FIRST accessor instead of the
    second and must still land on the same coordinates. That equivalence is
    the whole reason the base-class change was safe; pin it."""
    from engine.appc.projectiles import Torpedo
    from engine.appc.subsystems import _get_xyz

    torp = Torpedo()
    torp._position = TGPoint3(0.0, 500.0, 0.0)

    assert _get_xyz(torp) == (0.0, 500.0, 0.0)


def test_get_xyz_is_unchanged_for_every_object_class():
    """The fix must not move any position that used to resolve. ObjectClass
    really defines GetTranslate, so ships, planets and bare objects keep
    taking the first accessor exactly as before."""
    from engine.appc.objects import ObjectClass
    from engine.appc.subsystems import _get_xyz

    ship = _ship("Galaxy", loc=(1.0, -2.0, 3.0))
    planet = Planet(150.0, "planet.nif")
    planet.SetWorldLocation(TGPoint3(4.0, 5.0, -6.0))
    bare = ObjectClass()
    bare.SetWorldLocation(TGPoint3(-7.0, 8.0, 9.0))

    assert _get_xyz(ship) == (1.0, -2.0, 3.0)
    assert _get_xyz(planet) == (4.0, 5.0, -6.0)
    assert _get_xyz(bare) == (-7.0, 8.0, 9.0)


# ── ship_motion: immobility gate ─────────────────────────────────────────────


def test_immobility_gate_does_not_stub_probe_a_non_ship(_watch_stubs):
    """`getattr(ship, "IsImmobile", None) is not None` is vacuously true on any
    TGObject. The gate must ask whether the class really implements it."""
    from engine.appc.ship_motion import _step_ship_motion

    _step_ship_motion(Waypoint(), 1.0 / 60.0)

    hits = _watch_stubs()
    assert not any(attr == "IsImmobile" for _owner, attr in hits)


# ── DamageableObject lifecycle flags ─────────────────────────────────────────


def test_damageable_object_has_the_lifecycle_flags():
    """BC declares IsDying/IsDead/SetDead on DamageableObject
    (sdk/Build/scripts/App.py:5363-5365), not on ShipClass. Our shim put them
    on ShipClass, so the `hasattr(self, "IsDying") and not self.IsDying()`
    death guards in objects.py read False on any other DamageableObject."""
    from engine.appc.objects import DamageableObject
    from engine.core.ids import implements

    obj = DamageableObject()

    assert implements(obj, "IsDying")
    assert implements(obj, "IsDead")
    assert obj.IsDying() == 0
    assert obj.IsDead() == 0
    obj.SetDying(1)
    assert obj.IsDying() == 1


def test_physics_object_is_not_damageable():
    """Guard the move: the flags belong on DamageableObject, no higher."""
    from engine.core.ids import implements

    assert not implements(PhysicsObjectClass(), "IsDying")
