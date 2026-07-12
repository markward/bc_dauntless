"""EngRepairPane snapshot + click routing."""
import App
from engine.appc.tg_ui.widgets import ensure_widget_id
from engine.ui import ui_attention
from engine.ui.eng_repair_pane import repair_pane_snapshot


def _ship_with_queue():
    from engine.appc.ships import ShipClass_Create
    from engine.appc.subsystems import ShipSubsystem, RepairSubsystem
    from engine.appc.properties import RepairSubsystemProperty

    ship = ShipClass_Create("UI")

    bay = RepairSubsystem("Engineering")
    prop = RepairSubsystemProperty("Engineering")
    prop.SetMaxRepairPoints(50.0)
    prop.SetNumRepairTeams(2)
    bay.SetProperty(prop)
    ship.SetRepairSubsystem(bay)

    for attr, name, mx in (
        ("SetSensorSubsystem", "Sensors", 8000.0),
        ("SetImpulseEngineSubsystem", "Impulse Engines", 3000.0),
        ("SetWarpEngineSubsystem", "Warp Engines", 8000.0),
        ("SetShieldSubsystem", "Shield Generator", 1000.0),
    ):
        sub = ShipSubsystem(name)
        sub.SetMaxCondition(mx)
        getattr(ship, attr)(sub)
    return ship


def test_snapshot_splits_repair_waiting_destroyed():
    ship = _ship_with_queue()
    ship.GetSensorSubsystem().SetCondition(4000.0)        # queued (active)
    ship.GetImpulseEngineSubsystem().SetCondition(1500.0) # queued (active)
    ship.GetWarpEngineSubsystem().SetCondition(4000.0)    # queued (waiting)
    ship.GetShieldSubsystem().SetCondition(0.0)           # destroyed (stays 0)
    reg = {}
    snap = repair_pane_snapshot(ship, reg.setdefault)
    assert len(snap["repair"]) == 2          # NumRepairTeams = 2
    assert len(snap["waiting"]) == 1
    assert any(r["pct"] == 50 for r in snap["repair"])
    destroyed_labels = [r["label"] for r in snap["destroyed"]]
    assert "Shield Generator" in destroyed_labels
    for row in snap["repair"] + snap["waiting"] + snap["destroyed"]:
        assert set(row) == {"id", "label", "icon", "pct", "highlighted"}


def test_snapshot_none_ship_or_bay_is_empty():
    assert repair_pane_snapshot(None, lambda *_: None) == {
        "repair": [], "waiting": [], "destroyed": []}


def test_destroyed_queue_entries_hidden_from_repair_and_waiting():
    ship = _ship_with_queue()
    sensors = ship.GetSensorSubsystem()
    sensors.SetCondition(4000.0)                          # queued
    sensors._condition = 0.0                              # dies while queued
    snap = repair_pane_snapshot(ship, lambda *_: None)
    labels = [r["label"] for r in snap["repair"] + snap["waiting"]]
    assert sensors.GetName() not in labels
    assert sensors.GetName() in [r["label"] for r in snap["destroyed"]]


def test_click_action_posts_priority_event(monkeypatch):
    from engine.ui.crew_menu_panel import CrewMenuPanel
    from engine.core.game import Game, _set_current_game

    ship = _ship_with_queue()
    ship.GetSensorSubsystem().SetCondition(4000.0)
    ship.GetWarpEngineSubsystem().SetCondition(4000.0)
    ship.GetImpulseEngineSubsystem().SetCondition(1500.0)

    game = Game()
    game.SetPlayer(ship)
    _set_current_game(game)

    panel = CrewMenuPanel()
    # Register subsystem ids the way render does, then click the waiting row.
    reg = panel._widgets_by_id
    snap = repair_pane_snapshot(ship, reg.__setitem__)
    waiting_id = snap["waiting"][0]["id"]
    panel.dispatch_event("repair:%d" % waiting_id)
    bay = ship.GetRepairSubsystem()
    assert bay._queue[0] is reg[waiting_id]               # promoted to head


def test_snapshot_node_projects_repair_pane_visible_true():
    """Regression guard: EngRepairPaneWidget has no real IsVisible tracking
    (it subclasses _DisplayWidget, which has none), so
    CrewMenuPanel._snapshot_node's `bool(widget.IsVisible())` used to
    silently collapse to False via _DisplayWidget.__getattr__'s
    lambda-returns-None catch-all. crew_menus.js skips any node with
    visible === false before it ever inspects node.type, so the pane never
    rendered. EngRepairPaneWidget.IsVisible() must return a truthy value."""
    from engine.ui.crew_menu_panel import CrewMenuPanel

    ship = _ship_with_queue()
    ship.GetSensorSubsystem().SetCondition(4000.0)        # queued (active)
    ship.GetWarpEngineSubsystem().SetCondition(4000.0)    # queued (waiting)

    widget = App.EngRepairPane_Create(1.0, 0.4, 3)
    panel = CrewMenuPanel()
    node = panel._snapshot_node(widget)

    assert node["type"] == "repair-pane"
    assert node["visible"] is True
    assert set(("repair", "waiting", "destroyed")) <= set(node)


def test_current_player_resolves_real_object_not_stub():
    """Stub-audit guard: _current_player() must resolve to a real ship
    object for the repair-pane branches, never App._NamedStub -- mirrors
    Task 1's no-stub discipline (see engine/ui/crew_menu_panel.py:_current_player
    and engine/ui/ship_display_panel.py:_get_player)."""
    from engine.core.game import Game, _set_current_game
    from engine.ui.crew_menu_panel import _current_player

    ship = _ship_with_queue()
    game = Game()
    game.SetPlayer(ship)
    _set_current_game(game)

    player = _current_player()
    assert player is ship
    assert not isinstance(player, App._NamedStub)


def test_repair_queue_row_highlighted_when_marked():
    """Task 3 gap: eng_repair_pane._row() built each row's own dict and never
    consulted ui_attention, so a repair-queue row could never be highlighted
    -- E2M0's ShowArrow(pWaitingArea, ...) / ShowArrow(pRepairArea, ...)
    (Maelstrom/Episode2/E2M0/E2M0.py:4059,4164) would silently render
    nothing for it."""
    ship = _ship_with_queue()
    sensors = ship.GetSensorSubsystem()
    sensors.SetCondition(4000.0)
    wid = ensure_widget_id(sensors)
    ui_attention.hide_pointer_arrows()
    ui_attention.show_pointer_arrow(None, sensors, 0, 0.0, None)
    try:
        snap = repair_pane_snapshot(ship, lambda *_a: None)
        row = snap["repair"][0]
        assert row["id"] == wid
        assert row["highlighted"] is True
    finally:
        ui_attention.hide_pointer_arrows()


def test_repair_queue_row_unhighlighted_by_default():
    ship = _ship_with_queue()
    ship.GetSensorSubsystem().SetCondition(4000.0)
    ui_attention.hide_pointer_arrows()
    snap = repair_pane_snapshot(ship, lambda *_a: None)
    assert snap["repair"][0]["highlighted"] is False


def test_repair_pane_widget_node_highlighted_when_marked():
    """Task 3 gap: the EngRepairPaneWidget branch in
    CrewMenuPanel._snapshot_node built and returned its own dict before ever
    reaching the shared node["highlighted"] lines, so the repair-pane node
    itself was id-bearing but un-highlightable."""
    from engine.ui.crew_menu_panel import CrewMenuPanel

    widget = App.EngRepairPane_Create(1.0, 0.4, 3)
    wid = ensure_widget_id(widget)
    ui_attention.hide_pointer_arrows()
    ui_attention.show_pointer_arrow(None, widget, 0, 0.0, None)
    try:
        panel = CrewMenuPanel()
        node = panel._snapshot_node(widget)
        assert node["id"] == wid
        assert node["highlighted"] is True
    finally:
        ui_attention.hide_pointer_arrows()


def test_repair_pane_widget_node_unhighlighted_by_default():
    from engine.ui.crew_menu_panel import CrewMenuPanel

    widget = App.EngRepairPane_Create(1.0, 0.4, 3)
    ui_attention.hide_pointer_arrows()
    panel = CrewMenuPanel()
    node = panel._snapshot_node(widget)
    assert node["highlighted"] is False
