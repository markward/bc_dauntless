"""Continuity against the REAL bridge menus (sensor continuity/occlusion spec,
Continuity): the Science Scan Object button follows `shows_identity`, and lost
track drops the Hail button through the SDK's own
`Bridge.HelmMenuHandlers.ExitedSet` -- not a synthetic ET_EXITED_SET.

Unit-level menus do not exist, so these drive LoadBridge.Load -> CreateMenus,
exactly as tests/integration/test_science_scan_unknown_labels.py does (its
fixture is mirrored here), and leave `sensor_contacts._helm_exited_set`
un-patched so the real SDK function runs.
"""
import sys

import pytest

import App
import LoadBridge
import MissionLib
from engine.appc.windows import TacticalControlWindow
from engine.appc.target_menu import _reset_target_menu_singleton
from engine.appc.tg_ui import st_widgets
from engine.appc.ships import ShipClass_Create
from engine.appc import (contact_index, science_scan_labels, sensor_contacts,
                         unknown_labels)
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.rocks import far_tier
from tests.helpers.rocks import make_major_rock

SCAN_MENU = "Scan Object"
_exited = []


def _on_exited(dest, event):
    _exited.append(event.GetDestination())


@pytest.fixture
def world():
    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    st_widgets._reset_module_state()
    App.g_kSetManager._sets.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
    unknown_labels.reset()
    sensor_contacts.reset()
    contact_index.reset()
    _exited.clear()
    game, ep, mission = Game(), Episode(), Mission()
    ep.SetCurrentMission(mission)
    game.SetCurrentEpisode(ep)
    _set_current_game(game)
    for name in list(sys.modules):
        if name.startswith("Bridge.") and "StubModule" in type(sys.modules[name]).__name__:
            sys.modules.pop(name)
    try:
        LoadBridge.Load("GalaxyBridge")
        player = ShipClass_Create("Dauntless")
        player.SetName("Dauntless")
        sensors = player.GetSensorSubsystem()
        sensors._max_condition = 100.0
        sensors._condition = 100.0
        sensors.SetBaseSensorRange(2000.0)
        game.SetPlayer(player)
        science_scan_labels.install()
        db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
        science = TacticalControlWindow.GetInstance().FindMenu(db.GetString("Science"))
        scan = science.GetSubmenuW(db.GetString(SCAN_MENU))
        App.g_kLocalizationManager.Unload(db)
        assert scan is not None, "Science -> Scan Object submenu was not built"
        hail = MissionLib.GetCharacterSubmenu("Helm", "Hail")
        assert hail is not None, "Helm -> Hail submenu was not built"
        pSet = App.SetClass_Create()
        App.g_kSetManager.AddSet(pSet, "TestSet")
        pSet.AddObjectToSet(player, "player")
        yield player, pSet, scan, hail
    finally:
        _set_current_game(None)
        unknown_labels.reset()
        sensor_contacts.reset()


def _labels(menu):
    return [c.GetLabel() for c in menu._children]


def _known_bird_with_buttons(player, pSet, x=500.0):
    """A ship the player has identified, with its real-named Scan Object
    button (via ET_TARGET_LIST_OBJECT_ADDED, as the target list posts it)
    and its Hail button (the SDK's own AddHailButton)."""
    import Bridge.HelmMenuHandlers as helm
    bird = ShipClass_Create("Vagabond")
    bird.SetName("Vagabond")
    bird.SetTranslateXYZ(float(x), 0.0, 0.0)
    pSet.AddObjectToSet(bird, "Vagabond")
    player.GetSensorSubsystem().AddKnownObject(bird)
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_TARGET_LIST_OBJECT_ADDED)
    evt.SetDestination(bird)
    App.g_kEventManager.AddEvent(evt)
    helm.AddHailButton(None, bird.GetObjID())
    return bird


def test_scan_button_follows_shows_identity_in_and_out_of_a_field(world, monkeypatch):
    from engine.appc.perception import perceived_by
    player, pSet, scan, hail = world
    bird = _known_bird_with_buttons(player, pSet)
    assert _labels(scan) == ["Vagabond"]
    strength = {"v": 0.0}
    monkeypatch.setattr(far_tier, "field_strength_at",
                        lambda obj: strength["v"] if obj is bird else 0.0)

    sensor_contacts.tick(player, 0.0)
    assert _labels(scan) == ["Vagabond"]

    strength["v"] = 1.0                                  # into the field
    sensor_contacts.tick(player, 1.0)
    placeholder = unknown_labels.current(bird)
    assert placeholder is not None and placeholder.startswith("Unknown ")
    assert _labels(scan) == [placeholder]
    assert scan.GetButtonW(placeholder) is not None
    assert scan.GetButtonW("Vagabond") is None
    # The list and the Science label give the same answer.
    (c,) = [c for c in perceived_by(player) if c.ship is bird]
    assert c.identified is False
    assert science_scan_labels._unknown_label(bird) == placeholder
    assert player.GetSensorSubsystem().IsObjectKnown(bird) == 1

    strength["v"] = 0.0                                  # out again in time
    sensor_contacts.tick(player, 2.0)
    assert _labels(scan) == ["Vagabond"]
    assert scan.GetButtonW("Vagabond") is not None
    (c,) = [c for c in perceived_by(player) if c.ship is bird]
    assert c.identified is True
    assert hail.GetButtonW("Vagabond") is not None     # track never lost


def test_lost_track_in_a_field_keeps_a_placeholder_scan_button_and_drops_hail(world, monkeypatch):
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_EXITED_SET, None, __name__ + "._on_exited")
    player, pSet, scan, hail = world
    bird = _known_bird_with_buttons(player, pSet)
    assert hail.GetButtonW("Vagabond") is not None
    monkeypatch.setattr(far_tier, "field_strength_at",
                        lambda obj: 1.0 if obj is bird else 0.0)
    for t in range(0, 5):
        sensor_contacts.tick(player, float(t))
        assert hail.GetButtonW("Vagabond") is not None, t
    sensor_contacts.tick(player, 5.0)
    assert player.GetSensorSubsystem().IsObjectKnown(bird) == 0
    assert hail.GetButtonW("Vagabond") is None          # real Helm ExitedSet ran
    placeholder = unknown_labels.current(bird)
    assert placeholder is not None
    assert _labels(scan) == [placeholder]               # still listed, scannable
    assert _exited == []                                # no synthetic event


def test_unknown_namesake_never_relabels_a_known_ships_button(world):
    """Scan buttons are keyed by label. An unknown contact sharing a known
    ship's display name must not have the KNOWN ship's real-named button
    renamed to its placeholder on its first sweep."""
    player, pSet, scan, hail = world
    known = _known_bird_with_buttons(player, pSet)          # "Vagabond"
    stranger = ShipClass_Create("Vagabond")
    stranger.SetTranslateXYZ(1500.0, 0.0, 0.0)              # far band: no passive id
    pSet.AddObjectToSet(stranger, "Vagabond2")
    stranger.SetDisplayName("Vagabond")
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_TARGET_LIST_OBJECT_ADDED)
    evt.SetDestination(stranger)
    App.g_kEventManager.AddEvent(evt)
    ph = unknown_labels.current(stranger)
    assert sorted(_labels(scan)) == sorted(["Vagabond", ph])
    for t in (0.0, 1.0, 2.0):
        sensor_contacts.tick(player, t)
    assert sorted(_labels(scan)) == sorted(["Vagabond", ph])
    assert scan.GetButtonW("Vagabond") is not None
    assert player.GetSensorSubsystem().IsObjectKnown(known) == 1


def test_lost_track_behind_a_rock_drops_the_hail_button(world):
    player, pSet, scan, hail = world
    bird = _known_bird_with_buttons(player, pSet)
    make_major_rock(pSet, "Rock", at=(250.0, 0.0, 0.0), radius_gu=3.0)
    for t in range(0, 5):
        sensor_contacts.tick(player, float(t))
    assert hail.GetButtonW("Vagabond") is not None
    sensor_contacts.tick(player, 5.0)
    assert player.GetSensorSubsystem().IsObjectKnown(bird) == 0
    assert hail.GetButtonW("Vagabond") is None
    assert "Vagabond" not in _labels(hail)
    # Re-identified later: the SDK's own AddHailButton (dedupes by label via
    # CreateHailButton's GetButtonW) must be able to add it back.
    import Bridge.HelmMenuHandlers as helm
    helm.AddHailButton(None, bird.GetObjID())
    assert hail.GetButtonW("Vagabond") is not None
    assert _labels(hail) == ["Vagabond"]
