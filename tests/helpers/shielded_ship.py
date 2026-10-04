"""A bare ShipClass with a hull, a four-facing shield generator, a mass and
a cached hull box (the shield bubble's geometry): the fixture ship for the
rock-vs-shield collision tests (tests/unit/test_rock_shield_collision.py,
tests/unit/test_scenery_contact.py)."""
import math

from engine.appc.ships import ShipClass, ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem

DEFAULT_HALF = (1.0, 3.0, 0.5)


def make_shielded_ship(name="Target", face_max=1.0e5, hull_max=1.0e6,
                       shields_up=True, half=DEFAULT_HALF, radius=None):
    """Shields up = YELLOW alert (combat.shields_block true), down = GREEN.
    The hull box is centred at the origin with half extents `half`; the
    radius defaults to |half|."""
    ship = ShipClass_Create(name)
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(hull_max)
    ship._hull = hull
    ss = ShieldSubsystem("Shield Generator")
    ss.SetMaxCondition(100.0)
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, face_max)
    ship.SetShieldSubsystem(ss)
    ship.SetRadius(radius if radius is not None
                   else math.sqrt(sum(h * h for h in half)))
    ship.SetMass(1000.0)
    ship._shield_hull_box = ((0.0, 0.0, 0.0), tuple(half))
    ship.SetAlertLevel(ShipClass.YELLOW_ALERT if shields_up
                       else ShipClass.GREEN_ALERT)
    return ship
