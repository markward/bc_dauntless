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
    wrappers = fake_dom.children(fake_dom.children(body_id)[0])
    assert len(wrappers) == 2

    for wrapper in wrappers:
        children_container = fake_dom.children(wrapper)[1]
        slot_ids = fake_dom.children(children_container)
        # Galaxy hardpoint registers 10 subsystem-bearing templates: hull,
        # shield, sensors, power, repair, impulse, warp, phaser, torpedo,
        # tractor (no pulse). Pass 3 of SetupProperties scrubs slots the
        # hardpoint never claimed, so the slot count equals the hardpoint
        # contribution exactly. Of those 10, the three weapon parents
        # (Phasers, Torpedoes, Tractors) render as nested collapsibles
        # containing per-emitter child buttons; the other 7 are flat
        # buttons.
        assert len(slot_ids) == 10
        # The last three wrappers are nested collapsibles — each contains
        # a header + a children container with at least one child button.
        nested = slot_ids[-3:]
        for nested_id in nested:
            inner_kids = fake_dom.children(nested_id)
            assert len(inner_kids) == 2  # header + children container
            inner_container = inner_kids[1]
            assert len(fake_dom.children(inner_container)) >= 1


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
    first_wrapper = fake_dom.children(fake_dom.children(body_id)[0])[0]
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
