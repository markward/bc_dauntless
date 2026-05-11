"""With show_subsystems=True, M2Objects rows render populated subsystem buttons."""
import pytest

from engine.appc import ship_lifecycle
from engine.ui import UiPanel, bindings as bindings_module
from engine.ui._dom import FakeDom
from engine.ui.target_list import TargetListController, populated_subsystems


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


def test_subsystem_buttons_render_for_each_ship(fake_dom):
    from engine.host_loop import _setup_sdk, _init_mission, SHIP_GATE_MISSION
    _setup_sdk()
    import App

    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(
        panel,
        player_provider=lambda: App.Game_GetCurrentPlayer(),
        show_subsystems=True,
    )
    _init_mission(SHIP_GATE_MISSION)
    ctrl.rebuild_from_snapshot()

    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    wrappers = fake_dom.children(body_id)
    assert len(wrappers) == 2

    for wrapper in wrappers:
        children_container = fake_dom.children(wrapper)[1]
        button_ids = fake_dom.children(children_container)
        # ShipClass_Create populates 7 default subsystem instances; Hull stays
        # None unless a HullProperty is loaded, so 7-8 buttons per Galaxy.
        assert 1 <= len(button_ids) <= 8


def test_subsystem_click_routes_to_set_target_subsystem(fake_dom):
    from engine.host_loop import _setup_sdk, _init_mission, SHIP_GATE_MISSION
    _setup_sdk()
    import App

    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(
        panel,
        player_provider=lambda: App.Game_GetCurrentPlayer(),
        show_subsystems=True,
    )
    _init_mission(SHIP_GATE_MISSION)
    ctrl.rebuild_from_snapshot()

    player = App.Game_GetCurrentPlayer()
    assert player is not None

    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    first_wrapper = fake_dom.children(body_id)[0]
    children_container = fake_dom.children(first_wrapper)[1]
    first_button_id = fake_dom.children(children_container)[0]
    # UiButton is a single div whose on_click handler IS the click target —
    # no nested text element (see engine/ui/button.py:23-25).
    fake_dom.fire_click(first_button_id)

    target_sub = player.GetTargetSubsystem()
    assert target_sub is not None
    candidates = set()
    for ship in ship_lifecycle.snapshot():
        if ship is player:
            continue
        for _, sub in populated_subsystems(ship):
            candidates.add(id(sub))
    assert id(target_sub) in candidates
