"""Shared torpedo-system test fixtures.

Extracted from tests/unit/test_torpedo_spread_volley.py when the Dual/Quad
spread fan was removed (Task 5 of the BC-faithful weapon dispatch branch —
the file's feature died with it, but Task 6/7's launch-fidelity tests reuse
exactly this ship+tube construction).

Task 7 adds the fire-gate helpers (``make_ship_with_two_tubes``,
``LiveTarget``-position helpers, and the game-clock drivers) used by
tests/unit/test_torpedo_fire_gates.py.
"""
import math as _math

from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc.properties import WeaponSystemProperty
from engine.appc.subsystems import TorpedoSystem, TorpedoTube


class LiveTarget:
    """A live (never-dead) target at a fixed world location."""
    def __init__(self, x, y, z):
        self._loc = TGPoint3(x, y, z)
    def GetWorldLocation(self): return self._loc
    def IsDead(self): return 0


def identity_rotation():
    R = TGMatrix3(); R.MakeIdentity()
    return R


def system_with_tubes(num_tubes, *, target=None, rot=None):
    """Build a TorpedoSystem with `num_tubes` ready PhotonTorpedo tubes on a
    ship at the origin with an (optional) axis-aligned rotation and target
    lock.  Returns (system, ship)."""
    from engine.appc.ships import ShipClass_Create
    ship = ShipClass_Create("Test")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    if rot is not None:
        ship.SetMatrixRotation(rot)
    ship._target = target
    ship._target_subsystem = None

    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    prop = WeaponSystemProperty("Torpedoes")
    prop.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")
    parent.SetProperty(prop)
    parent._parent_ship = ship
    ship._torpedo_system = parent

    for i in range(num_tubes):
        tube = TorpedoTube("Torpedo %d" % i)
        tube._max_ready = 1
        tube._num_ready = 1
        tube._reload_delay = 40.0
        parent.AddChildSubsystem(tube)
    return parent, ship


def make_ship_with_two_tubes():
    """A ship with a 2-tube TorpedoSystem (both tubes facing +Y — the
    default Direction — with an identity ship rotation), for Task 7's
    fire-gate tests.  Returns (ship, system, (tube1, tube2))."""
    system, ship = system_with_tubes(2, rot=identity_rotation())
    t1 = system.GetChildSubsystem(0)
    t2 = system.GetChildSubsystem(1)
    return ship, system, (t1, t2)


def make_target_at(pos: TGPoint3) -> LiveTarget:
    """A live target at the given world position."""
    return LiveTarget(pos.x, pos.y, pos.z)


def pos_at_bearing_deg(bearing_deg: float, distance: float = 500.0) -> TGPoint3:
    """A world position `distance` GU out, `bearing_deg` degrees off the
    tube's forward (+Y) axis, swept toward +X (tube Right).  bearing 0.0 is
    dead ahead; 30.0 sits exactly on the cone boundary."""
    a = _math.radians(bearing_deg)
    return TGPoint3(distance * _math.sin(a), distance * _math.cos(a), 0.0)


def advance_game_clock_to(t: float) -> float:
    """Set the GAME clock (the one _game_time() in weapon_subsystems.py
    reads) to an absolute value.  Returns the value set."""
    import App
    App.g_kTimerManager._time = float(t)
    return float(t)


def advance_game_clock_by(dt: float) -> float:
    """Advance the GAME clock by a relative delta.  Returns the new value."""
    import App
    now = float(getattr(App.g_kTimerManager, "_time", 0.0)) + float(dt)
    App.g_kTimerManager._time = now
    return now
