"""The REAL authored part data in hardpoint_overrides.py -- invariants only.

That file is authored data: the Ship Property Viewer's Save button rewrites
it. So nothing here may assert what someone authored (which parts exist, what
fraction shears them, which way a wing swings) -- a test that did would turn
the gate red on every legitimate SPV edit, which is exactly what happened when
the Bird of Prey's head was marked detachable in-game. The mechanism tests run
against a frozen fixture instead (conftest.bop_fixture_rig).

What IS asserted is what no authoring choice can make right: a break fraction
that shears a part on the first hit or never, a non-finite anchor, a
non-finite authored pose, a non-positive transition time, a pose authored
with no anchor to swing about, or a part naming a node the model does not
have (which accumulates nothing and so silently never detaches).

Reads the new pose surface (spec 2026-09-25 section 3) -- `anchor`,
`pose6_for`, `break_fraction`, `transition_seconds`, `authored_states` --
never the legacy `pivot`/`axis`/`angle_for`/`detach_fraction` readers, which
survive on `ArticulatedPartProperty` only for
`engine/ui/ship_property_viewer_panel.py` (spec section 7, not yet rewritten).
"""
import math

import pytest

from engine.appc import articulation, hardpoint_overrides
from engine.appc.articulated_part import ArticulatedPartProperty


def authored_part_problems(parts, node_names=None):
    """Every invariant violation in `parts`, as human-readable strings.

    `node_names` is the model's node set where known; None skips the node
    check rather than failing a ship the suite has no geometry for."""
    problems = []

    def finite(*xs):
        return all(math.isfinite(x) for x in xs)

    for p in parts:
        name = p.GetName()
        f = p.break_fraction
        if f is not None and not (0.0 < f <= 1.0):
            problems.append("%s: break fraction %r is not in (0, 1]" % (name, f))
        anchor = p.anchor
        if anchor is not None and not finite(*anchor):
            problems.append("%s: anchor %r is not finite" % (name, anchor))
        if not (p.transition_seconds > 0.0):
            problems.append("%s: transition seconds %r is not positive"
                            % (name, p.transition_seconds))
        states = p.authored_states()
        for state in states:
            p6 = p.pose6_for(state)
            if p6 is not None and not finite(*p6):
                problems.append("%s: %s pose %r is not finite" % (name, state, p6))
        if states and anchor is None:
            problems.append("%s: has an authored pose (%s) but no anchor to "
                            "swing about" % (name, ", ".join(states)))
        if node_names is not None and name not in node_names:
            problems.append("%s: no such node on the model (have %s)"
                            % (name, sorted(node_names)))
    return problems


def _authored_parts(leaf):
    """The ArticulatedPartProperty templates hardpoint_overrides registers for
    `leaf`, read the way production reads them (apply, then the local store)."""
    import App
    mgr = App.g_kModelPropertyManager
    mgr.ClearLocalTemplates()
    try:
        hardpoint_overrides.apply(leaf)
        return [p for p in getattr(mgr, "_local", {}).values()
                if isinstance(p, ArticulatedPartProperty)]
    finally:
        mgr.ClearLocalTemplates()


def _rigged_leaves():
    return sorted(leaf for leaf in hardpoint_overrides.OVERRIDES
                  if _authored_parts(leaf))


def _part(name, *, fraction=0.2, anchor=(-0.16, 0.0, 0.05),
          pose=(0.0, 0.0, 0.0, 0.0, 45.0, 0.0), transition=2.0):
    p = ArticulatedPartProperty(name)
    if transition is not None:
        p.SetTransitionSeconds(transition)
    if anchor is not None:
        p.SetAnchor(*anchor)
    if pose is not None:
        p.SetStatePose("cruise", *pose)
    if fraction is not None:
        p.SetBreakFraction(fraction)
    return p


# ── The checker itself: each case must be CAUGHT ─────────────────────────────

def test_a_sound_rig_has_no_problems():
    parts = [_part("left wing"),
             _part("head", fraction=None, anchor=None, pose=None)]
    assert authored_part_problems(parts, {"left wing", "head"}) == []


@pytest.mark.parametrize("fraction", [0.0, -0.1, 1.5, float("nan")])
def test_a_break_fraction_outside_zero_to_one_is_caught(fraction):
    """0.0 shears the part on the first hit; above 1.0 it can never shear."""
    assert authored_part_problems([_part("left wing", fraction=fraction)])


def test_a_non_finite_anchor_is_caught():
    assert authored_part_problems(
        [_part("left wing", anchor=(float("nan"), 0.0, 0.05))])


def test_a_non_finite_pose_value_is_caught():
    assert authored_part_problems(
        [_part("left wing", pose=(0.0, 0.0, 0.0, 0.0, float("inf"), 0.0))])


@pytest.mark.parametrize("seconds", [0.0, -1.0, float("nan")])
def test_a_non_positive_transition_seconds_is_caught(seconds):
    assert authored_part_problems([_part("left wing", transition=seconds)])


def test_a_pose_with_no_anchor_is_caught():
    """A rigged part swings about its anchor (spec section 2.3, 4.1) -- a
    pose authored with no anchor at all has no swing to compute."""
    assert authored_part_problems([_part("left wing", anchor=None)])


def test_a_part_naming_a_node_the_model_lacks_is_caught():
    """The template name IS the NIF node name. A typo gets no box, so the
    part accumulates no damage and silently never detaches."""
    assert authored_part_problems([_part("left wnig")], {"left wing"})


# ── The real file ────────────────────────────────────────────────────────────

def test_the_real_file_is_actually_being_checked():
    """Guard: if no leaf registers a part, everything below passes vacuously."""
    assert _rigged_leaves(), "no ship in hardpoint_overrides authors a part"


@pytest.mark.parametrize("leaf", _rigged_leaves())
def test_authored_parts_satisfy_every_invariant(leaf):
    # Node names measured off the model where the suite knows them (the
    # conftest seeds the BoP's from BirdOfPrey.nif); None skips that check.
    boxes = articulation._derived_boxes.get(leaf)
    nodes = set(boxes) if boxes else None
    assert authored_part_problems(_authored_parts(leaf), nodes) == []
