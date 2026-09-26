"""The pins are drawn from a CACHED world position, and the cache has to be
built in the pose the viewer is showing.

THE THIRD STORE. The previous two rounds unified the node overrides and
`ship._articulation_poses`. Both were right, and the pins still floated,
because nothing draws from either at pin time: `build_descriptors` resolves
`subsystem_world_position` ONCE and stores the answer as
`descriptor["world_pos"]`. `subsystem_pins()` hands that tuple to the renderer
and `pick_pin` picks against it.

So the pose has to be settled BEFORE the cache is built, and the cache has to
be refreshed whenever the pose is re-forced -- which, since the Preview buttons
went (spec 2026-09-25 section 7.5), is whenever a part's {State}
Transformation node is selected or left.

These tests assert on `_descriptors[i]["world_pos"]` and on `subsystem_pins()`
-- the last thing before the screen. The round that cleared the previous fix
asserted on `subsystems.subsystem_world_position` instead, which resolves live
and was genuinely correct; the pins never call it. That is the same escape,
one layer down, twice.
"""
import pytest

from engine.appc import articulation, part_pose
from engine.appc.math import TGMatrix3, TGPoint3
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel

LEAF = "birdofprey"
# The starboard wingtip disruptor cannon, as hardpoint_overrides authors it.
CANNON_BODY = (1.008, 0.450, -0.670)
# A second mount on the same wing, inboard of the cannon.
CANNON_NEIGHBOUR = (0.85, 0.200, -0.500)


class _Sub:
    def __init__(self, name, pos):
        self._name = name
        self._pos = TGPoint3(*pos)

    def GetRadius(self):
        return 0.3

    def GetName(self):
        return self._name

    def GetPosition(self):
        return self._pos

    def GetProperty(self):
        return None

    def GetNumChildSubsystems(self):
        return 0

    def GetParentSubsystem(self):
        return None


class _Ship:
    """Identity rotation at the origin, so a world position IS the body
    offset and the test can read the articulation straight off it."""

    def __init__(self, state="cruise"):
        self._articulation_leaf = LEAF
        self._articulation_poses = {
            p.GetName(): p.pose_for(state)
            for p in articulation.rig_for(LEAF)
        }
        self._hull = _Sub("Hull", (0.0, 0.0, 0.0))
        self._cannon = _Sub("Starboard Disruptor", CANNON_BODY)
        # A SECOND mount on the SAME wing, so the selected-vs-unselected
        # comparison has something to compare against.
        self._tube = _Sub("Starboard Torpedo", CANNON_NEIGHBOUR)

    def GetHull(self):
        return self._hull

    def GetTorpedoSystem(self):
        return self._tube

    def GetPulseWeaponSystem(self):
        return self._cannon

    def GetWorldLocation(self):
        return TGPoint3(0.0, 0.0, 0.0)

    def GetWorldRotation(self):
        return TGMatrix3()


def _raised(body_point=CANNON_BODY):
    """Where a starboard-wing body point is DRAWN with the wings up."""
    part = next(p for p in articulation.rig_for(LEAF)
                if p.GetName() == "left wing01")
    return part_pose.apply(part.pose_for("cruise"), body_point)


def _raised_cannon(ship):
    """Where the cannon is DRAWN with the wings up -- the position the pins
    were stuck at."""
    return _raised(CANNON_BODY)


@pytest.fixture
def panel(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: None)
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: LEAF)
    holder = {"ship": _Ship()}
    p = ShipPropertyViewerPanel(ship_getter=lambda: holder["ship"])
    # No render instance headlessly, so stand in for the Model Parts walk:
    # the starboard wing is the part the cannon and its neighbour ride on.
    monkeypatch.setattr(p, "_fetch_model_part_nodes", lambda: [
        {"name": "left wing01", "parent": "Scene Root", "candidate": True,
         "bounds_min": (0.1236, -0.6777, -0.7125),
         "bounds_max": (1.0258, 0.5344, 0.1862)}])
    return p, holder


def _pose_starboard_wing(p, state="cruise"):
    """Select the starboard wing's {State} Transformation node -- the event
    edge that forces that part's pose now."""
    assert p.dispatch_event(
        'part/select_node:{"name":"left wing01","kind":"%s"}' % state) is True


def _back_to_nif(p):
    """Select the part row -- anything but a State node returns the rig to
    the NIF pose."""
    assert p.dispatch_event("model_parts/select:left wing01") is True


def _cannon_world(panel_obj):
    for d in panel_obj._descriptors:
        if d["name"] == "Starboard Disruptor":
            return d["world_pos"]
    raise AssertionError("the cannon descriptor vanished; fixture is broken")


def _cannon_pin(panel_obj):
    """What `subsystem_pins()` actually hands the renderer for the cannon --
    the last value before the screen."""
    want = _cannon_world(panel_obj)
    for world_pos, _icon, _sel in panel_obj.subsystem_pins():
        if tuple(world_pos) == tuple(want):
            return tuple(world_pos)
    raise AssertionError("the cannon pin is not in subsystem_pins()")


def test_the_fixture_actually_articulates():
    """Guard. If the BoP rig or the cannon mount ever stops resolving, every
    test below passes vacuously by comparing rest against rest."""
    ship = _Ship()
    raised = _raised_cannon(ship)
    assert raised != pytest.approx(CANNON_BODY)
    assert not part_pose.is_identity(articulation.pose_for_part(
        ship, next(p for p in articulation.rig_for(LEAF)
                   if p.GetName() == "left wing01")))


def test_opening_the_viewer_CACHES_the_pin_at_the_ANCHOR_pose(panel):
    """THE LIVE BUG. `open()` built the descriptor cache before forcing the
    anchor pose, so every `world_pos` was captured with the wings still up and
    the pins drew clear of the hull -- which is exactly what Mark saw, twice."""
    p, _holder = panel
    p.open()
    assert _cannon_world(p) == pytest.approx(CANNON_BODY), (
        "the pin must be cached at the authored rest mount, not the raised one")
    assert _cannon_pin(p) == pytest.approx(CANNON_BODY)


def test_posing_a_state_MOVES_the_cached_pin(panel):
    """Selecting a State Transformation forces the pose and the mesh
    follows; the cache has to follow too, or the wing swings out from under
    stationary pins."""
    p, holder = panel
    p.open()
    assert _cannon_world(p) == pytest.approx(CANNON_BODY)   # anchor

    _pose_starboard_wing(p)

    assert _cannon_world(p) == pytest.approx(_raised_cannon(holder["ship"])), (
        "the cached pin must move to where the wing is now drawn")
    assert _cannon_pin(p) == pytest.approx(_raised_cannon(holder["ship"]))


def test_leaving_the_state_node_returns_the_pin(panel):
    """Not a one-way trip: leaving the State node puts the rig back at the
    NIF pose, and the cached pin with it."""
    p, _holder = panel
    p.open()
    _pose_starboard_wing(p)
    assert _cannon_world(p) != pytest.approx(CANNON_BODY), "fixture check"
    _back_to_nif(p)
    assert _cannon_world(p) == pytest.approx(CANNON_BODY)


def test_the_refresh_does_not_RENUMBER_the_descriptors(panel):
    """`_descriptors` is indexed by position everywhere -- `_pending_pos`,
    `_pending_radius`, `_pending_light`, `selected_index` and the transform
    targets are all keyed by index. A refresh that reordered or resized them
    would silently repoint every staged edit at a different subsystem."""
    p, _holder = panel
    p.open()
    before_names = [d["name"] for d in p._descriptors]
    # Pose first: selecting a State node clears the mount selection by
    # design, so the index-keyed state is set up AFTER it, and the refresh
    # under test is the RE-force a changed staged pose triggers on the next
    # event edge.
    _pose_starboard_wing(p)
    posed = _cannon_world(p)
    p.selected_index = len(before_names) - 1
    p.set_subsystem_position(p.selected_index, (9.0, 9.0, 9.0))
    spec = dict(p._effective_part("left wing01"))
    spec["poses"] = dict(spec["poses"], cruise=(0.0, 0.0, 0.2, 0.0, -30.0, 0.0))
    p._pending_part["left wing01"] = spec
    p.dispatch_event("model_parts/toggle")      # any event edge
    assert _cannon_world(p) != pytest.approx(posed), (
        "fixture check: the re-forced pose must have refreshed the cache")

    assert [d["name"] for d in p._descriptors] == before_names
    assert p.selected_index == len(before_names) - 1
    assert p._pending_pos[p.selected_index] == (9.0, 9.0, 9.0)


# ---------------------------------------------------------------------------
# THE SELECTED pin takes a DIFFERENT road. Everything above rides the cached
# `descriptor["world_pos"]`; the moment a subsystem is selected,
# `subsystem_pins()`, `selected_subsystem_sphere()` and the transform gizmo
# all switch to `_effective_world_pos`, so a staged/dragged position can move
# them live. That road went straight to `world_from_body` -- body -> world
# with NO articulation at all. So selecting a wingtip cannon under a previewed
# pose snapped its pin back to rest while every neighbour stayed on the wing.
#
# Same defect as the cache ordering, one layer over: a fix for "pins don't
# follow the part" that leaves the SELECTED pin not following the part is not
# a fix.
# ---------------------------------------------------------------------------

def _cannon_index(p):
    for i, d in enumerate(p._descriptors):
        if d["name"] == "Starboard Disruptor":
            return i
    raise AssertionError("the cannon descriptor vanished; fixture is broken")


def _select_cannon_previewing_cruise(p):
    """Open at the anchor pose, pose the starboard wing in `cruise`, select
    the cannon, and arm the transform tool -- the state of Mark's retest step
    3. Selecting the State node clears (and locks) mount selection, so the
    cannon is selected directly: these tests pin the SELECTED-pin road's
    articulation, whatever put a pose and a selection together."""
    p.open()
    _pose_starboard_wing(p)
    i = _cannon_index(p)
    p.selected_index = i
    p.active_tool = "transform"
    return i


def test_the_SELECTED_pin_follows_its_part(panel):
    """THE POINT. `subsystem_pins()` is the last value before the screen."""
    p, _holder = panel
    _select_cannon_previewing_cruise(p)
    pins = p.subsystem_pins()
    assert len(pins) == 1, "selecting hides the others; fixture assumption"
    assert pins[0][2] is True, "...and marks this one selected"
    assert tuple(pins[0][0]) == pytest.approx(_raised()), (
        "the selected pin must sit where its wing is drawn, not at rest")


def test_the_selected_pin_AGREES_with_an_unselected_pin_on_the_same_part(panel):
    """The two roads must arrive at the same place. Selecting a pin must not
    MOVE it -- with no staged edit, `_effective_world_pos` and the cached
    `world_pos` are the same question."""
    p, _holder = panel
    i = _select_cannon_previewing_cruise(p)
    selected = tuple(p.subsystem_pins()[0][0])

    assert selected == pytest.approx(p._descriptors[i]["world_pos"])

    # ...and the neighbour on the SAME wing, which never left the cached road,
    # is articulated by the same hinge.
    p.selected_index = None
    by_name = {d["name"]: tuple(w) for (w, _i, _s), d
               in zip(p.subsystem_pins(), p._descriptors)}
    assert by_name["Starboard Disruptor"] == pytest.approx(selected)
    assert by_name["Starboard Torpedo"] == pytest.approx(
        _raised(CANNON_NEIGHBOUR))


def test_the_damage_SPHERE_follows_its_part(panel):
    p, _holder = panel
    _select_cannon_previewing_cruise(p)
    sphere = p.selected_subsystem_sphere()
    assert sphere is not None, "fixture must produce a sphere"
    assert tuple(sphere["center"]) == pytest.approx(_raised())


def test_the_GIZMO_origin_follows_its_part(panel):
    """A gizmo left at the rest mount would drag the wrong point -- the
    handle would not even be on the thing being moved."""
    p, _holder = panel
    _select_cannon_previewing_cruise(p)
    gizmo = p._active_gizmo()
    assert gizmo is not None, "fixture must arm the transform gizmo"
    assert tuple(gizmo["origin"]) == pytest.approx(_raised())


def test_a_STAGED_drag_is_articulated_too(panel):
    """`_effective_world_pos` exists so a staged/dragged body position moves
    the pin live. That staged point is authored in the model's UNROTATED
    frame like every other mount, so it has to go through the hinge on the
    way out -- not be handed to world_from_body raw."""
    p, _holder = panel
    i = _select_cannon_previewing_cruise(p)
    staged = (0.95, 0.30, -0.55)
    p.set_subsystem_position(i, staged)
    assert tuple(p.subsystem_pins()[0][0]) == pytest.approx(_raised(staged))


def test_at_the_ANCHOR_pose_the_selected_pin_is_UNCHANGED(panel):
    """The common case, and every unarticulated hull: at angle 0 the hinge is
    the identity, so all three readers must be byte-identical to before."""
    p, _holder = panel
    p.open()                                  # anchor pose, nothing previewed
    i = _cannon_index(p)
    p.selected_index = i
    p.active_tool = "transform"
    assert tuple(p.subsystem_pins()[0][0]) == pytest.approx(CANNON_BODY)
    assert tuple(p.selected_subsystem_sphere()["center"]) == pytest.approx(
        CANNON_BODY)
    assert tuple(p._active_gizmo()["origin"]) == pytest.approx(CANNON_BODY)


def test_the_selected_pin_on_an_UNRIGGED_hull_is_unchanged(panel, monkeypatch):
    """No rig, no hinge, no behaviour change -- the overwhelming majority."""
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")
    p, holder = panel
    holder["ship"]._articulation_leaf = "galaxy"
    p.open()
    p.selected_index = _cannon_index(p)
    assert tuple(p.subsystem_pins()[0][0]) == pytest.approx(CANNON_BODY)


def test_an_unrigged_ship_is_unaffected(panel, monkeypatch):
    """The overwhelming majority of hulls. Posing a freshly authored part on
    a ship with no rig must leave every cached pin exactly where it was."""
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")
    p, holder = panel
    holder["ship"]._articulation_leaf = "galaxy"
    p.open()
    before = _cannon_world(p)
    p.dispatch_event("part/add_anchor:left wing01")
    p.dispatch_event('part/add_state:{"name":"left wing01","state":"cruise"}')
    spec = dict(p._pending_part["left wing01"])
    spec["poses"] = {"cruise": (0.0, 0.0, 0.5, 0.0, 45.0, 0.0)}
    p._pending_part["left wing01"] = spec
    _pose_starboard_wing(p)
    assert _cannon_world(p) == pytest.approx(before)
