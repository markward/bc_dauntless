"""Selecting a model part DRAWS its derived box on the hull.

Mark, live: "when I select a model part it doesn't render any differently to
the rest of the mesh meaning I can't actually tell what I have selected."

`selected_box` reached the CEF payload and the JS read it -- to print numbers
in the pane. Nothing drew it. Spec 5.2: "Selecting a part draws its derived
bounding box on the hull, so you can see what severance will actually test
against."

The box has to follow a previewed pose, because the thing it claims to show
-- what `part_severance.part_for_live_point` tests against -- moves with the
part. And it must MERGE into the one existing `set_debug_boxes` call: a
second call would drop the glow-region overlay's boxes (see the warning at
the emitter-overlay merge in host_loop).
"""
import math

import pytest

from engine.appc import articulation, part_pose
from engine.ui.glow_region_overlay import build_part_box_overlay

LEAF = "birdofprey"
# The derived box for the port wing, as host_io.model_nodes reports it.
WING_BOX = ((-1.0258, -0.6777, -0.7125), (-0.1236, 0.5344, 0.1862))


class _Ship:
    """Identity rotation at the origin, so world space IS body space and the
    test can assert on the numbers it wrote."""

    def __init__(self, deflection=0.0):
        self._articulation_leaf = LEAF
        self._articulation_poses = {
            p.GetName(): part_pose.interpolate(
                part_pose.IDENTITY, p.pose_for("cruise"), p.anchor,
                deflection)
            for p in articulation.rig_for(LEAF)
        }

    def GetWorldLocation(self):
        from engine.appc.math import TGPoint3
        return TGPoint3(0.0, 0.0, 0.0)

    def GetWorldRotation(self):
        from engine.appc.math import TGMatrix3
        return TGMatrix3()


def _centre(box):
    lo, hi = box
    return tuple((lo[i] + hi[i]) / 2.0 for i in range(3))


def test_a_selected_part_contributes_a_box():
    boxes = build_part_box_overlay(_Ship(), "left wing", WING_BOX)
    assert len(boxes) == 1
    b = boxes[0]
    assert b["center"] == pytest.approx(_centre(WING_BOX))
    # Half-extents, as three axis vectors.
    assert b["ex"][0] == pytest.approx((WING_BOX[1][0] - WING_BOX[0][0]) / 2.0)
    assert b["ey"][1] == pytest.approx((WING_BOX[1][1] - WING_BOX[0][1]) / 2.0)
    assert b["ez"][2] == pytest.approx((WING_BOX[1][2] - WING_BOX[0][2]) / 2.0)


def test_nothing_selected_contributes_NO_box():
    assert build_part_box_overlay(_Ship(), None, None) == []
    assert build_part_box_overlay(_Ship(), "left wing", None) == []
    assert build_part_box_overlay(None, "left wing", WING_BOX) == []


def test_the_box_has_a_colour_of_its_own():
    """It has to read against the blue hologram AND not be mistaken for the
    orange glow-region wireframes it shares a payload with."""
    from engine.ui.glow_region_overlay import GLOW_COLOR
    b = build_part_box_overlay(_Ship(), "left wing", WING_BOX)[0]
    assert "color" in b
    assert tuple(b["color"]) != tuple(GLOW_COLOR)


def test_the_box_FOLLOWS_a_previewed_pose():
    """THE POINT of routing it through the articulation. A box left at the
    rest centre while the wing is drawn at 45 degrees points at empty space."""
    rest = build_part_box_overlay(_Ship(deflection=0.0), "left wing",
                                  WING_BOX)[0]
    posed = build_part_box_overlay(_Ship(deflection=1.0), "left wing",
                                   WING_BOX)[0]
    assert posed["center"] != pytest.approx(rest["center"])

    # It lands exactly where the shared pose dict says the part is -- the
    # same source the mesh and the mounts read.
    ship = _Ship(deflection=1.0)
    part = next(p for p in articulation.rig_for(LEAF)
                if p.GetName() == "left wing")
    expected = part_pose.apply(articulation.pose_for_part(ship, part),
                               _centre(WING_BOX))
    assert posed["center"] == pytest.approx(expected)


def test_the_box_ROTATES_with_the_part_not_just_slides():
    """A rest-axis-aligned box dragged to a rotated centre would not hug the
    wing -- and would not describe what severance tests, which is the REST box
    seen through the part's own rotation."""
    posed = build_part_box_overlay(_Ship(deflection=1.0), "left wing",
                                   WING_BOX)[0]
    # The hinge is the Y axis, so X and Z components mix and Y is untouched.
    assert posed["ex"][2] != pytest.approx(0.0)
    assert posed["ez"][0] != pytest.approx(0.0)
    assert posed["ey"] == pytest.approx((0.0,
                                         (WING_BOX[1][1] - WING_BOX[0][1]) / 2.0,
                                         0.0))
    # A rotation preserves length: the box is re-oriented, not resized.
    def _len(v):
        return math.sqrt(sum(c * c for c in v))
    rest = build_part_box_overlay(_Ship(deflection=0.0), "left wing",
                                  WING_BOX)[0]
    for k in ("ex", "ey", "ez"):
        assert _len(posed[k]) == pytest.approx(_len(rest[k]))


def test_an_unrigged_part_is_drawn_at_rest():
    """The head has a derived box but no hinge. It must still draw, unmoved,
    rather than vanish or raise."""
    head = ((-0.101, 0.1377, -0.0885), (0.101, 0.9044, 0.0747))
    b = build_part_box_overlay(_Ship(deflection=1.0), "head", head)[0]
    assert b["center"] == pytest.approx(_centre(head))


def test_the_overlay_MERGES_into_the_one_debug_box_call():
    """A second `set_debug_boxes` would drop the glow-region overlay's boxes.
    Checked on run()'s source, because that is where the merge has to happen
    and nothing else can observe it."""
    import ast
    import inspect
    from engine import host_loop
    tree = ast.parse(inspect.getsource(host_loop.run))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "attr", None) == "set_debug_boxes"]
    assert len(calls) == 1, (
        "expected exactly one set_debug_boxes call in run(); %d would mean "
        "one overlay drops the other's boxes" % len(calls))
    # ...and the single call must be additive, not a bare name. The boxes are
    # converted to render coordinates on the way (system-frames render
    # origin), so the sum may be wrapped in that one conversion call.
    arg = calls[0].args[0]
    if isinstance(arg, ast.Call) and arg.args:
        arg = arg.args[0]
    assert isinstance(arg, ast.BinOp), (
        "the part box must be MERGED into the glow-region boxes, not replace "
        "them or be pushed separately")
