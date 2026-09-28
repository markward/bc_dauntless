"""A cast light authored on an articulated part moves with it, and goes dark
when the part is shot off.

Lights leave Python body-frame and the renderer places them through the
HULL's matrix, which carries no node override -- so a wingtip light stayed at
its wings-down position while the wing was drawn raised. And the only thing
that ever darkened one on severance was its PARENT subsystem being destroyed:
a light authored on a wing but parented to a body subsystem (a running light
on Hull, say) kept shining where the wing used to be.

The part is decided from the LIGHT's own authored position, not its parent's
mount. Assertions are on `_build_emitter_light_render_data`'s output -- what
set_dynamic_lights actually receives -- not on a helper.
"""
import math

import pytest

from engine.appc import articulation, light_emitters
from engine.appc import part_severance as ps
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.properties import SubsystemProperty
from engine.host_loop import _build_emitter_light_render_data
from tests.helpers.viewed_set import release_viewed_set, viewed_set


@pytest.fixture(autouse=True)
def _viewed():
    # The emitter-light feed carries only ships in the viewed frame
    # (system-frames): give the stand-in ship a set to be viewed in.
    viewed_set()
    yield
    release_viewed_set()

IID = 42
STAR_TIP = (1.0, 0.45, -0.67)       # on 'left wing01' (starboard), rest pose
BODY_PT = (0.0, -0.33, 0.0)         # on the body


def _prop(kind, position, axis=(0.0, -1.0, 0.0), length=0.0):
    p = SubsystemProperty("sub")
    p.SetLightEmitterKind(0, kind)
    p.SetLightEmitterPosition(0, *position)
    p.SetLightEmitterAxis(0, *axis)
    p.SetLightEmitterLength(0, length)
    p.SetLightEmitterRadius(0, 0.2)
    p.SetLightEmitterColor(0, 1.0, 1.0, 1.0)
    p.SetLightEmitterIntensity(0, 1.0)
    return p


class _Sub:
    """A HEALTHY body subsystem -- so nothing but the light's own position
    can decide that it rides on a wing."""

    def __init__(self, prop):
        self._prop = prop

    def GetProperty(self):  return self._prop
    def IsDestroyed(self):  return False
    def IsDisabled(self):   return False


class _Ship:
    def __init__(self, wings_up=True, leaf="birdofprey"):
        self._articulation_leaf = leaf
        from engine.appc import part_pose
        self._articulation_poses = {
            p.GetName(): (p.pose_for("cruise") if wings_up
                          else part_pose.IDENTITY)
            for p in articulation.rig_for("birdofprey")
        }

    def GetWorldLocation(self):
        return TGPoint3(0.0, 0.0, 0.0)

    def GetContainingSet(self):
        return viewed_set()

    def GetWorldRotation(self):
        raise AssertionError("lights are body-frame; the renderer places them")


def _lights(ship, *props):
    entries = []
    for prop in props:
        spec = light_emitters.baked_emitters(prop)[0]
        entries.append((_Sub(prop), False, False, 0.0, spec,
                        light_emitters.emitter_spec_to_struct(spec)))
    return _build_emitter_light_render_data({ship: IID}, {IID: entries})


def _star_wing():
    return next(p for p in articulation.rig_for("birdofprey")
                if p.GetName() == "left wing01")


def _posed(point):
    from engine.appc import part_pose
    return part_pose.apply(_star_wing().pose_for("cruise"), point)


def test_the_fixture_light_is_on_the_starboard_wing():
    """Guard: if the tip stopped attributing to the wing, every test below
    would be about a body light and prove nothing."""
    assert ps.part_for_point("birdofprey", STAR_TIP, IID) == "left wing01"
    assert math.dist(_posed(STAR_TIP), STAR_TIP) > 0.5


def test_a_wingtip_light_rides_the_raised_wing():
    (d,) = _lights(_Ship(), _prop("point", STAR_TIP))
    assert d["position"] == pytest.approx(_posed(STAR_TIP))


def test_wings_down_the_light_is_exactly_where_it_was_authored():
    (d,) = _lights(_Ship(wings_up=False), _prop("point", STAR_TIP))
    assert d["position"] == STAR_TIP


def test_a_light_on_a_SEVERED_part_is_dropped_even_with_a_healthy_parent():
    """THE GAP. The parent subsystem is healthy and on the body; only the
    light's own position puts it on the wing that has gone."""
    ship = _Ship()
    ps.detached_parts(ship).add("left wing01")
    assert _lights(ship, _prop("point", STAR_TIP)) == []


def test_a_body_light_is_untouched_by_a_raised_or_severed_wing():
    ship = _Ship()
    ps.detached_parts(ship).add("left wing01")
    (d,) = _lights(ship, _prop("point", BODY_PT))
    assert d["position"] == BODY_PT


def test_a_strip_moves_BOTH_endpoints():
    (d,) = _lights(_Ship(), _prop("strip", STAR_TIP, axis=(0.0, 1.0, 0.0),
                                  length=0.1))
    a = (STAR_TIP[0], STAR_TIP[1] - 0.05, STAR_TIP[2])
    b = (STAR_TIP[0], STAR_TIP[1] + 0.05, STAR_TIP[2])
    assert d["position"] == pytest.approx(_posed(a))
    assert d["position_b"] == pytest.approx(_posed(b))


def test_a_cone_turns_with_the_wing():
    """A spot light on a wing must point where the wing now faces, not only
    sit where it now is. Direction and up rotate; neither translates."""
    (d,) = _lights(_Ship(), _prop("cone", STAR_TIP, axis=(0.0, 0.0, -1.0),
                                  length=0.5))
    # The cruise pose is a pure swing about +Y (the fore-aft hinge) by the
    # authored ry; right-handed about +Y, (0, 0, -1) goes to (-sin, 0, -cos).
    # Computed independently of part_pose so the test is not a tautology.
    ry = math.radians(_star_wing().pose6_for("cruise")[4])
    assert ry != pytest.approx(0.0)
    want_dir = (-math.sin(ry), 0.0, -math.cos(ry))
    assert d["position"] == pytest.approx(_posed(STAR_TIP))
    assert d["direction"] == pytest.approx(want_dir)
    assert math.hypot(*d["up"]) == pytest.approx(1.0)
    assert sum(x * y for x, y in zip(d["up"], d["direction"])) == pytest.approx(0.0, abs=1e-9)


def test_an_unrigged_ship_is_byte_identical():
    ship = _Ship(leaf="galaxy")
    (d,) = _lights(ship, _prop("point", STAR_TIP))
    assert d["position"] == STAR_TIP
