"""Unknown contacts: listed and targetable, but captioned "Unknown N", grey
(UNKNOWN affiliation) and without subsystem rows until identified."""
import json
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.sets import SetClass
from engine.appc import perception
from engine.appc.target_menu import STSubsystemMenu, STTargetMenu_CreateW
from tests.helpers.sensor_time import settle_identification


def _world():
    s = SetClass()
    player = ShipClass_Create("Galaxy")
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(2000.0)
    player.SetSensorSubsystem(sensors)
    s.AddObjectToSet(player, "player")
    bird = ShipClass_Create("BirdOfPrey")
    bird.SetTranslateXYZ(500.0, 0.0, 0.0)
    s.AddObjectToSet(bird, "Bird")
    return s, player, sensors, bird


def _contact(player, ship):
    return next(c for c in perception.perceived_by(player) if c.ship is ship)


def test_contact_reports_identified_and_restricts_subsystems():
    s, player, sensors, bird = _world()
    c = _contact(player, bird)
    assert c.perceivable and c.targetable
    assert c.identified is False
    assert c.subsystems_targetable is False
    sensors.AddKnownObject(bird)
    c = _contact(player, bird)
    assert c.identified is True and c.subsystems_targetable is True


def test_row_caption_and_affiliation_while_unknown():
    row = STSubsystemMenu(None, "IKS Korvat")
    row.SetAffiliation("ENEMY")
    row.ShowUnknownName("Unknown 3")
    assert row.GetCaption() == "Unknown 3"
    assert row.GetLabel() == "IKS Korvat"         # SDK lookups keep the real name
    assert row.GetAffiliation() == "UNKNOWN"
    row.ShowRealName()
    assert row.GetCaption() == "IKS Korvat"
    assert row.GetAffiliation() == "ENEMY"


def test_set_contacts_drives_the_caption():
    s, player, sensors, bird = _world()
    menu = STTargetMenu_CreateW("Targets")
    menu.set_contacts(perception.perceived_by(player))
    row = menu.GetObjectEntry(bird)
    assert row.GetCaption().startswith("Unknown ")
    sensors.AddKnownObject(bird)
    menu.set_contacts(perception.perceived_by(player))
    assert row.GetCaption() == bird.GetDisplayName()


def test_reset_affiliation_colors_keeps_unknown_rows_unknown():
    s, player, sensors, bird = _world()
    menu = STTargetMenu_CreateW("Targets")
    menu.set_contacts(perception.perceived_by(player))
    menu.ResetAffiliationColors()
    assert menu.GetObjectEntry(bird).GetAffiliation() == "UNKNOWN"


def test_identifying_a_targeted_contact_keeps_the_lock():
    s, player, sensors, bird = _world()
    menu = STTargetMenu_CreateW("Targets")
    menu.set_contacts(perception.perceived_by(player))
    player.SetTarget(bird)
    sensors.AddKnownObject(bird)
    menu.set_contacts(perception.perceived_by(player))
    assert player.GetTarget() is bird


def test_payload_carries_label_and_keeps_name_as_key():
    from engine.ui.target_list_view import TargetListView
    from engine.core.game import Game, _set_current_game

    App._reset_target_menu_singleton()
    menu = STTargetMenu_CreateW("Targets")
    s, player, sensors, bird = _world()
    game = Game()
    game.SetPlayer(player)
    _set_current_game(game)
    try:
        menu.set_contacts(perception.perceived_by(player))

        view = TargetListView()
        script = view.render_payload()
        assert script is not None
        body = script[len("setTargetList("):-2]
        state = json.loads(body)
        row = next(r for r in state["rows"] if r["name"] == bird.GetName())
        assert row["label"] == "Unknown 1"
        assert row["name"] == bird.GetName()

        sensors.AddKnownObject(bird)
        menu.set_contacts(perception.perceived_by(player))
        view.invalidate()
        script2 = view.render_payload()
        assert script2 is not None
        body2 = script2[len("setTargetList("):-2]
        state2 = json.loads(body2)
        row2 = next(r for r in state2["rows"] if r["name"] == bird.GetName())
        assert row2["label"] == bird.GetDisplayName()
    finally:
        _set_current_game(None)
