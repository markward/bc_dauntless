"""TargetListController mirrors ship_lifecycle into a UiPanel."""
import pytest

from engine.appc import ship_lifecycle
from engine.appc.ships import ShipClass
from engine.ui import UiPanel
from engine.ui.target_list import TargetListController


@pytest.fixture(autouse=True)
def _reset_hub():
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()
    yield
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()


class _FakeMission:
    class _Group:
        def __init__(self, names):
            self._names = set(names)
        def IsNameInGroup(self, name):
            return 1 if name in self._names else 0
    def __init__(self, friendly=(), enemy=(), neutral=()):
        self._f = self._Group(friendly)
        self._e = self._Group(enemy)
        self._n = self._Group(neutral)
    def GetFriendlyGroup(self): return self._f
    def GetEnemyGroup(self):    return self._e
    def GetNeutralGroup(self):  return self._n


class _FakeEpisode:
    def __init__(self, mission): self._m = mission
    def GetCurrentMission(self): return self._m


class _FakeGame:
    def __init__(self, mission): self._ep = _FakeEpisode(mission)
    def GetCurrentEpisode(self): return self._ep


@pytest.fixture
def install_game(monkeypatch):
    def _install(mission):
        from engine.core import game as game_module
        monkeypatch.setattr(game_module, "_current_game", _FakeGame(mission))
    return _install


def _make_ship(name: str) -> ShipClass:
    s = ShipClass()
    s.SetName(name)
    return s


def test_controller_adds_row_when_ship_published(fake_dom, install_game):
    install_game(_FakeMission(enemy=["Galaxy 2"]))
    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(panel, player_provider=lambda: None)
    s = _make_ship("Galaxy 2")
    ship_lifecycle.publish_added(s)
    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    wrappers = fake_dom.children(fake_dom.children(body_id)[0])
    assert len(wrappers) == 1
    assert "bc-collapsible" in fake_dom.element(wrappers[0]).classes


def test_controller_removes_row_when_ship_destroyed(fake_dom, install_game):
    install_game(_FakeMission(enemy=["E"]))
    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(panel, player_provider=lambda: None)
    s = _make_ship("E")
    ship_lifecycle.publish_added(s)
    ship_lifecycle.publish_destroyed(s)
    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    assert fake_dom.children(fake_dom.children(body_id)[0]) == []


def test_controller_excludes_player(fake_dom, install_game):
    install_game(_FakeMission(friendly=["player", "Galaxy 1"]))
    panel = UiPanel(id="targets", title="Targets")
    player = _make_ship("player")
    ctrl = TargetListController(panel, player_provider=lambda: player)
    galaxy1 = _make_ship("Galaxy 1")
    ship_lifecycle.publish_added(player)
    ship_lifecycle.publish_added(galaxy1)
    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    wrappers = fake_dom.children(fake_dom.children(body_id)[0])
    assert len(wrappers) == 1
    title_id = fake_dom.children(fake_dom.children(wrappers[0])[0])[1]
    assert fake_dom.element(title_id).text == "Galaxy 1"


def test_controller_assigns_affiliation_class(fake_dom, install_game):
    install_game(_FakeMission(friendly=["F"], enemy=["E"], neutral=["N"]))
    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(panel, player_provider=lambda: None)
    ship_lifecycle.publish_added(_make_ship("F"))
    ship_lifecycle.publish_added(_make_ship("E"))
    ship_lifecycle.publish_added(_make_ship("N"))
    ship_lifecycle.publish_added(_make_ship("U"))
    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    wrappers = fake_dom.children(fake_dom.children(body_id)[0])
    headers = [fake_dom.children(w)[0] for w in wrappers]
    classes_per_header = [fake_dom.element(h).classes for h in headers]
    found = set()
    for cls in classes_per_header:
        for c in cls:
            if c.startswith("aff-"):
                found.add(c)
    assert found == {"aff-friendly", "aff-enemy", "aff-neutral", "aff-unknown"}


def test_controller_routes_row_click_to_set_target(fake_dom, install_game):
    install_game(_FakeMission(enemy=["E"]))
    panel = UiPanel(id="targets", title="Targets")
    player = _make_ship("player")
    ctrl = TargetListController(panel, player_provider=lambda: player)
    enemy = _make_ship("E")
    ship_lifecycle.publish_added(enemy)
    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    wrapper = fake_dom.children(fake_dom.children(body_id)[0])[0]
    header = fake_dom.children(wrapper)[0]
    title_id = fake_dom.children(header)[1]
    fake_dom.fire_click(title_id)
    assert player.GetTarget() is enemy


def test_controller_does_not_render_subsystems_in_stage_1(fake_dom, install_game):
    """show_subsystems=False (default) must not add child buttons even when
    every Get*Subsystem() returns a real instance (which ShipClass_Create
    arranges by default)."""
    from engine.appc.ships import ShipClass_Create
    install_game(_FakeMission(enemy=["X"]))
    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(panel, player_provider=lambda: None)
    ship = ShipClass_Create("X")
    ship.SetName("X")
    ship_lifecycle.publish_added(ship)
    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    wrapper = fake_dom.children(fake_dom.children(body_id)[0])[0]
    children_container = fake_dom.children(wrapper)[1]
    assert fake_dom.children(children_container) == []


def test_controller_destroy_unsubscribes(fake_dom, install_game):
    install_game(_FakeMission())
    panel = UiPanel(id="targets", title="Targets")
    ctrl = TargetListController(panel, player_provider=lambda: None)
    ctrl.destroy()
    assert ship_lifecycle._subscribers == []
    ship_lifecycle.publish_added(_make_ship("noone"))


def test_rebuild_from_snapshot_filters_player_added_before_player_provider_resolves(
    fake_dom, install_game
):
    """Models the first-mission-load race: player ship is published BEFORE
    Game.SetPlayer is called. rebuild_from_snapshot() rerun after the
    player is set must drop the player's row."""
    install_game(_FakeMission(friendly=["player"]))
    panel = UiPanel(id="targets", title="Targets")
    player = _make_ship("player")
    other  = _make_ship("Galaxy 1")
    player_holder = {"p": None}
    ctrl = TargetListController(
        panel,
        player_provider=lambda: player_holder["p"],
    )
    ship_lifecycle.publish_added(player)
    ship_lifecycle.publish_added(other)
    player_holder["p"] = player
    ctrl.rebuild_from_snapshot()
    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    wrappers = fake_dom.children(fake_dom.children(body_id)[0])
    title_ids = [fake_dom.children(fake_dom.children(w)[0])[1] for w in wrappers]
    titles = [fake_dom.element(t).text for t in title_ids]
    assert titles == ["Galaxy 1"]
