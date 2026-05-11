"""Loading M2Objects populates the Targets panel with Galaxy 1 + Galaxy 2,
and excludes the player."""
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


def _row_titles(fake_dom, panel) -> list[str]:
    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    wrappers = fake_dom.children(body_id)
    titles = []
    for w in wrappers:
        header = fake_dom.children(w)[0]
        title_id = fake_dom.children(header)[1]
        titles.append(fake_dom.element(title_id).text)
    return titles


def test_m2objects_loads_with_galaxy_rows_and_no_player(fake_dom):
    from engine.host_loop import _setup_sdk, _init_mission, SHIP_GATE_MISSION
    _setup_sdk()
    import App

    panel = UiPanel(id="targets", title="Targets")
    target_list = TargetListController(
        panel,
        player_provider=lambda: App.Game_GetCurrentPlayer(),
    )

    _init_mission(SHIP_GATE_MISSION)
    target_list.rebuild_from_snapshot()

    titles = _row_titles(fake_dom, panel)
    assert set(titles) == {"Galaxy 1", "Galaxy 2"}
    assert "player" not in titles


def test_m2objects_affiliations(fake_dom):
    from engine.host_loop import _setup_sdk, _init_mission, SHIP_GATE_MISSION
    _setup_sdk()
    import App

    panel = UiPanel(id="targets", title="Targets")
    target_list = TargetListController(
        panel,
        player_provider=lambda: App.Game_GetCurrentPlayer(),
    )
    _init_mission(SHIP_GATE_MISSION)
    target_list.rebuild_from_snapshot()

    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    title_to_aff = {}
    for wrapper in fake_dom.children(body_id):
        header = fake_dom.children(wrapper)[0]
        title_id = fake_dom.children(header)[1]
        title = fake_dom.element(title_id).text
        aff = next((c for c in fake_dom.element(header).classes
                    if c.startswith("aff-")), None)
        title_to_aff[title] = aff
    assert title_to_aff == {"Galaxy 1": "aff-friendly", "Galaxy 2": "aff-enemy"}
