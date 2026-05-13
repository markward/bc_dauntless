"""When a top-level subsystem has children, the controller renders it as
a nested collapsible under the ship row instead of a flat button.
Clicking either the parent collapsible header or a child button routes
to player.SetTargetSubsystem(<that subsystem>)."""
import pytest

from engine.appc import ship_lifecycle
from engine.ui import UiPanel, bindings as bindings_module
from engine.ui._dom import FakeDom
from engine.ui.target_list import TargetListController


@pytest.fixture
def fake_dom(monkeypatch) -> FakeDom:
    dom = FakeDom()
    monkeypatch.setattr(bindings_module, "_active_dom", dom)
    return dom


@pytest.fixture(autouse=True)
def _reset_hub():
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()
    yield
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()


class _Child:
    def __init__(self, name): self._name = name
    def GetName(self): return self._name


class _Parent:
    def __init__(self, name, children):
        self._name = name
        self._children = [_Child(n) for n in children]
    def GetName(self): return self._name
    def GetNumChildSubsystems(self): return len(self._children)
    def GetChildSubsystem(self, i):
        if isinstance(i, int) and 0 <= i < len(self._children):
            return self._children[i]
        return None


class _Ship:
    def __init__(self):
        self._tractor = _Parent("Tractors", [
            "Aft Tractor 1", "Forward Tractor 1",
        ])
        self.target_subsystem = None
    def GetName(self):                   return "Dry Dock"
    def GetHull(self):                   return None
    def GetShieldSubsystem(self):        return None
    def GetSensorSubsystem(self):        return None
    def GetPowerSubsystem(self):         return None
    def GetRepairSubsystem(self):        return None
    def GetImpulseEngineSubsystem(self): return None
    def GetWarpEngineSubsystem(self):    return None
    def GetPhaserSystem(self):           return None
    def GetPulseWeaponSystem(self):      return None
    def GetTorpedoSystem(self):          return None
    def GetTractorBeamSystem(self):      return self._tractor
    def SetTarget(self, t): pass
    def SetTargetSubsystem(self, s): self.target_subsystem = s


def test_parent_with_children_renders_as_nested_collapsible(fake_dom):
    ship = _Ship()
    ship_lifecycle.publish_added(ship)
    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(
        panel,
        player_provider=lambda: None,
        show_subsystems=True,
    )
    ctrl.rebuild_from_snapshot()

    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    ship_wrapper = fake_dom.children(fake_dom.children(body_id)[0])[0]
    ship_children_container = fake_dom.children(ship_wrapper)[1]

    # The ship row's body should contain a nested collapsible (the
    # Tractors parent) — recognisable by having its own children > 0.
    nested_wrappers = fake_dom.children(ship_children_container)
    assert len(nested_wrappers) == 1
    nested_wrapper = nested_wrappers[0]
    # A nested collapsible has the header+body two-child shape.
    nested_children_container = fake_dom.children(nested_wrapper)[1]
    button_ids = fake_dom.children(nested_children_container)
    assert len(button_ids) == 2  # Aft Tractor 1, Forward Tractor 1


def test_click_on_child_subsystem_button_routes_to_set_target(fake_dom):
    """Firing click on a nested child button calls player.SetTargetSubsystem
    with that exact child instance."""
    target_subsystem_holder = {"value": None}

    class _Player:
        def SetTargetSubsystem(self, s):
            target_subsystem_holder["value"] = s

    player = _Player()
    ship = _Ship()
    ship_lifecycle.publish_added(ship)
    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(
        panel,
        player_provider=lambda: player,
        show_subsystems=True,
    )
    ctrl.rebuild_from_snapshot()

    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    ship_wrapper = fake_dom.children(fake_dom.children(body_id)[0])[0]
    ship_children_container = fake_dom.children(ship_wrapper)[1]
    nested_wrapper = fake_dom.children(ship_children_container)[0]
    nested_children_container = fake_dom.children(nested_wrapper)[1]
    first_child_button = fake_dom.children(nested_children_container)[0]
    fake_dom.fire_click(first_child_button)

    assert target_subsystem_holder["value"] is not None
    assert target_subsystem_holder["value"].GetName() == "Aft Tractor 1"
