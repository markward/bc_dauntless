"""The pins are drawn from a CACHED world position, and the cache has to be
built in the pose the viewer is showing.

THE THIRD STORE. The previous two rounds unified the node overrides and
`ship._articulation_angles`. Both were right, and the pins still floated,
because nothing draws from either at pin time: `build_descriptors` resolves
`subsystem_world_position` ONCE and stores the answer as
`descriptor["world_pos"]`. `subsystem_pins()` hands that tuple to the renderer
and `pick_pin` picks against it.

So the pose has to be settled BEFORE the cache is built, and the cache has to
be refreshed whenever the pose is re-forced.

These tests assert on `_descriptors[i]["world_pos"]` and on `subsystem_pins()`
-- the last thing before the screen. The round that cleared the previous fix
asserted on `subsystems.subsystem_world_position` instead, which resolves live
and was genuinely correct; the pins never call it. That is the same escape,
one layer down, twice.
"""
import pytest

from engine.appc import articulation
from engine.appc.math import TGMatrix3, TGPoint3
from engine.ui.ship_property_viewer_panel import ShipPropertyViewerPanel

LEAF = "birdofprey"
# The starboard wingtip disruptor cannon, as hardpoint_overrides authors it.
CANNON_BODY = (1.008, 0.450, -0.670)


class _Sub:
    def __init__(self, name, pos):
        self._name = name
        self._pos = TGPoint3(*pos)

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
        self._articulation_angles = {
            p.GetName(): p.angle_for(state)
            for p in articulation.rig_for(LEAF)
        }
        self._hull = _Sub("Hull", (0.0, 0.0, 0.0))
        self._cannon = _Sub("Starboard Disruptor", CANNON_BODY)

    def GetHull(self):
        return self._hull

    def GetPulseWeaponSystem(self):
        return self._cannon

    def GetWorldLocation(self):
        return TGPoint3(0.0, 0.0, 0.0)

    def GetWorldRotation(self):
        return TGMatrix3()


def _raised_cannon(ship):
    """Where the cannon is DRAWN with the wings up -- the position the pins
    were stuck at."""
    part = next(p for p in articulation.rig_for(LEAF)
                if p.GetName() == "left wing01")
    return articulation.point_at_angle(part, CANNON_BODY,
                                       part.angle_for("cruise"))


@pytest.fixture
def panel(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: None)
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: LEAF)
    holder = {"ship": _Ship()}
    p = ShipPropertyViewerPanel(ship_getter=lambda: holder["ship"])
    # No render instance headlessly, so the Model Parts walk finds nothing.
    monkeypatch.setattr(p, "_fetch_model_part_nodes", lambda: [])
    return p, holder


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
    assert articulation.angle_for_part(
        ship, next(p for p in articulation.rig_for(LEAF)
                   if p.GetName() == "left wing01")) != 0.0


def test_opening_the_viewer_CACHES_the_pin_at_the_ANCHOR_pose(panel):
    """THE LIVE BUG. `open()` built the descriptor cache before forcing the
    anchor pose, so every `world_pos` was captured with the wings still up and
    the pins drew clear of the hull -- which is exactly what Mark saw, twice."""
    p, _holder = panel
    p.open()
    assert _cannon_world(p) == pytest.approx(CANNON_BODY), (
        "the pin must be cached at the authored rest mount, not the raised one")
    assert _cannon_pin(p) == pytest.approx(CANNON_BODY)


def test_previewing_a_state_MOVES_the_cached_pin(panel):
    """Preview forces the pose and the mesh follows; the cache has to follow
    too, or the wings swing out from under stationary pins."""
    p, holder = panel
    p.open()
    assert _cannon_world(p) == pytest.approx(CANNON_BODY)   # anchor

    p.dispatch_event("part/preview:cruise")

    assert _cannon_world(p) == pytest.approx(_raised_cannon(holder["ship"])), (
        "the cached pin must move to where the wing is now drawn")
    assert _cannon_pin(p) == pytest.approx(_raised_cannon(holder["ship"]))


def test_previewing_back_to_the_ANCHOR_state_returns_the_pin(panel):
    """Not a one-way trip. 'red' is the BoP's NIF pose (angle 0)."""
    p, _holder = panel
    p.open()
    p.dispatch_event("part/preview:cruise")
    p.dispatch_event("part/preview:red")
    assert _cannon_world(p) == pytest.approx(CANNON_BODY)


def test_the_refresh_does_not_RENUMBER_the_descriptors(panel):
    """`_descriptors` is indexed by position everywhere -- `_pending_pos`,
    `_pending_radius`, `_pending_light`, `selected_index` and the transform
    targets are all keyed by index. A refresh that reordered or resized them
    would silently repoint every staged edit at a different subsystem."""
    p, _holder = panel
    p.open()
    before_names = [d["name"] for d in p._descriptors]
    p.selected_index = len(before_names) - 1
    p.set_subsystem_position(p.selected_index, (9.0, 9.0, 9.0))

    p.dispatch_event("part/preview:cruise")

    assert [d["name"] for d in p._descriptors] == before_names
    assert p.selected_index == len(before_names) - 1
    assert p._pending_pos[p.selected_index] == (9.0, 9.0, 9.0)


def test_an_unrigged_ship_is_unaffected(panel, monkeypatch):
    """The overwhelming majority of hulls. Forcing a pose on a ship with no
    rig must leave every cached pin exactly where it was."""
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")
    p, holder = panel
    holder["ship"]._articulation_leaf = "galaxy"
    p.open()
    before = _cannon_world(p)
    p.dispatch_event("part/preview:cruise")
    assert _cannon_world(p) == pytest.approx(before)
