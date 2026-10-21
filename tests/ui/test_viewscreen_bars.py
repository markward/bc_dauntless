"""Viewscreen target bars: data builder (name + range/speed + affiliation)."""
import re

import pytest

import App
from engine.appc import contact_index, sensor_contacts, unknown_labels
from engine.appc.math import TGPoint3
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.core.game import Mission
from engine.ui import reticle_text, viewscreen_bars


def _mission(friendly=(), enemy=(), neutral=()):
    m = Mission()
    for n in friendly:
        m.GetFriendlyGroup().AddName(n)
    for n in enemy:
        m.GetEnemyGroup().AddName(n)
    for n in neutral:
        m.GetNeutralGroup().AddName(n)
    return m


def _ship(pSet, name, y=0.0):
    s = ShipClass_Create("Galaxy")
    s.SetName(name)
    s.SetTranslateXYZ(0.0, y, 0.0)
    pSet.AddObjectToSet(s, name)
    return s


@pytest.fixture
def scene(monkeypatch):
    contact_index.reset()
    App._reset_target_menu_singleton()
    pSet = SetClass()
    player = _ship(pSet, "player")
    state = {"mission": _mission()}
    monkeypatch.setattr(viewscreen_bars, "_current_mission",
                        lambda: state["mission"])
    monkeypatch.setattr(sensor_contacts, "shows_identity",
                        lambda *a, **k: True)
    return pSet, player, state


def test_enemy_target_gets_the_red_dot_and_its_name(scene):
    pSet, player, state = scene
    t = _ship(pSet, "Kessok", y=200.0)
    state["mission"] = _mission(enemy=["Kessok"])
    d = viewscreen_bars.build_viewscreen_bars(player, t)
    assert d["visible"] is True
    assert d["dot_rgb"] == (216, 43, 43)
    assert d["name"] == "Kessok"
    # Text is always white on the native side: no per-affiliation text colour.
    assert set(d) == {"visible", "name", "detail", "dot_rgb"}


def test_friendly_and_neutral_colours(scene):
    pSet, player, state = scene
    f = _ship(pSet, "Ally", y=100.0)
    n = _ship(pSet, "Bystander", y=300.0)
    state["mission"] = _mission(friendly=["Ally"], neutral=["Bystander"])
    df = viewscreen_bars.build_viewscreen_bars(player, f)
    dn = viewscreen_bars.build_viewscreen_bars(player, n)
    assert df["dot_rgb"] == (80, 112, 230)
    assert dn["dot_rgb"] == (255, 255, 175)


def test_ungrouped_object_is_grey(scene):
    pSet, player, _ = scene
    t = _ship(pSet, "Loner", y=200.0)
    d = viewscreen_bars.build_viewscreen_bars(player, t)
    assert d["dot_rgb"] == (128, 128, 128)


def test_unidentified_contact_shows_its_placeholder_and_grey(scene, monkeypatch):
    pSet, player, state = scene
    t = _ship(pSet, "SecretName", y=200.0)
    state["mission"] = _mission(enemy=["SecretName"])
    monkeypatch.setattr(sensor_contacts, "shows_identity",
                        lambda *a, **k: False)
    d = viewscreen_bars.build_viewscreen_bars(player, t)
    assert d["name"] == unknown_labels.placeholder(t)
    assert d["dot_rgb"] == (128, 128, 128)
    assert "SecretName" not in repr(d)


def test_subsystem_lock_still_shows_the_ship_name(scene):
    from engine.appc.subsystems import ShipSubsystem
    pSet, player, state = scene
    t = _ship(pSet, "Kessok", y=200.0)
    state["mission"] = _mission(enemy=["Kessok"])
    sub = ShipSubsystem("Phasers")
    player.SetTargetSubsystem(sub)
    assert player.GetTargetSubsystem() is sub
    assert sub.GetDisplayName() == "Phasers"
    d = viewscreen_bars.build_viewscreen_bars(player, t)
    assert d["name"] == "Kessok"
    assert d["name"] != sub.GetDisplayName()


def test_detail_uses_the_reticle_numbers(scene):
    pSet, player, _ = scene
    t = _ship(pSet, "Kessok", y=200.0)
    t.SetVelocity(TGPoint3(0.0, 2.0, 0.0))
    d = viewscreen_bars.build_viewscreen_bars(player, t)
    km, kph = reticle_text.readout_values(t, player)
    assert kph > 0.0
    assert d["detail"] == "DST: %.2f km  SPD: %.0f kph" % (km, kph)
    assert reticle_text.readout_line(t, player) == "%.2f km / %.0f kph" % (km, kph)
    assert re.match(r"^DST: \d+\.\d\d km  SPD: \d+ kph$", d["detail"])


def test_planet_reads_zero_speed_and_grey(scene):
    from engine.appc.planet import Planet
    pSet, player, _ = scene
    p = Planet(90.0, "planet.nif")
    p.SetName("Haven")
    p.SetWorldLocation(TGPoint3(0.0, 500.0, 0.0))
    pSet.AddObjectToSet(p, "Haven")
    d = viewscreen_bars.build_viewscreen_bars(player, p)
    assert d["detail"].endswith("SPD: 0 kph")
    assert d["dot_rgb"] == (128, 128, 128)


def test_no_target_or_dead_target_is_hidden(scene, monkeypatch):
    pSet, player, _ = scene
    assert viewscreen_bars.build_viewscreen_bars(player, None) == {"visible": False}
    t = _ship(pSet, "Kessok", y=200.0)
    from engine.appc import camera_modes
    monkeypatch.setattr(camera_modes, "_target_alive", lambda o: False)
    assert viewscreen_bars.build_viewscreen_bars(player, t) == {"visible": False}


@pytest.fixture
def real_game():
    from engine.core.game import Episode, Game, _set_current_game
    mission = _mission(enemy=["Kessok"])
    episode = Episode()
    episode.SetCurrentMission(mission)
    game = Game()
    game.SetCurrentEpisode(episode)
    _set_current_game(game)
    yield mission
    _set_current_game(None)


def test_real_current_mission_drives_the_dot(real_game, monkeypatch):
    contact_index.reset()
    pSet = SetClass()
    player = _ship(pSet, "player")
    t = _ship(pSet, "Kessok", y=200.0)
    monkeypatch.setattr(sensor_contacts, "shows_identity",
                        lambda *a, **k: True)
    assert viewscreen_bars._current_mission() is real_game
    d = viewscreen_bars.build_viewscreen_bars(player, t)
    assert d["dot_rgb"] == (216, 43, 43)


def test_no_current_game_means_no_mission_and_a_grey_dot(monkeypatch):
    from engine.core.game import _set_current_game
    _set_current_game(None)
    contact_index.reset()
    pSet = SetClass()
    player = _ship(pSet, "player")
    t = _ship(pSet, "Kessok", y=200.0)
    monkeypatch.setattr(sensor_contacts, "shows_identity",
                        lambda *a, **k: True)
    assert viewscreen_bars._current_mission() is None
    assert viewscreen_bars.build_viewscreen_bars(player, t)["dot_rgb"] == (128, 128, 128)


def test_real_identity_path_with_no_player_sensors_reads_unknown():
    from engine.core.game import _set_current_game
    _set_current_game(None)
    contact_index.reset()
    pSet = SetClass()
    player = _ship(pSet, "player")
    t = _ship(pSet, "SecretName", y=200.0)
    d = viewscreen_bars.build_viewscreen_bars(player, t)
    assert d["name"] == unknown_labels.placeholder(t)
    assert d["dot_rgb"] == (128, 128, 128)
    assert "SecretName" not in repr(d)
