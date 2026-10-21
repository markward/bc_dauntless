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


def test_enemy_target_gets_the_red_band_and_white_text(scene):
    pSet, player, state = scene
    t = _ship(pSet, "Kessok", y=200.0)
    state["mission"] = _mission(enemy=["Kessok"])
    d = viewscreen_bars.build_viewscreen_bars(player, t)
    assert d["visible"] is True
    assert d["band_rgb"] == (216, 43, 43)
    assert d["text_rgb"] == (255, 255, 255)
    assert d["top_text"] == "Kessok"


def test_friendly_and_neutral_colours(scene):
    pSet, player, state = scene
    f = _ship(pSet, "Ally", y=100.0)
    n = _ship(pSet, "Bystander", y=300.0)
    state["mission"] = _mission(friendly=["Ally"], neutral=["Bystander"])
    df = viewscreen_bars.build_viewscreen_bars(player, f)
    dn = viewscreen_bars.build_viewscreen_bars(player, n)
    assert (df["band_rgb"], df["text_rgb"]) == ((80, 112, 230), (255, 255, 255))
    assert (dn["band_rgb"], dn["text_rgb"]) == ((255, 255, 175), (0, 0, 0))


def test_ungrouped_object_is_grey(scene):
    pSet, player, _ = scene
    t = _ship(pSet, "Loner", y=200.0)
    d = viewscreen_bars.build_viewscreen_bars(player, t)
    assert d["band_rgb"] == (128, 128, 128)


def test_unidentified_contact_shows_its_placeholder_and_grey(scene, monkeypatch):
    pSet, player, state = scene
    t = _ship(pSet, "SecretName", y=200.0)
    state["mission"] = _mission(enemy=["SecretName"])
    monkeypatch.setattr(sensor_contacts, "shows_identity",
                        lambda *a, **k: False)
    d = viewscreen_bars.build_viewscreen_bars(player, t)
    assert d["top_text"] == unknown_labels.placeholder(t)
    assert d["band_rgb"] == (128, 128, 128)
    assert "SecretName" not in repr(d)


def test_subsystem_lock_still_shows_the_ship_name(scene):
    pSet, player, state = scene
    t = _ship(pSet, "Kessok", y=200.0)
    state["mission"] = _mission(enemy=["Kessok"])
    subs = list(t.GetSubsystems()) if hasattr(t, "GetSubsystems") else []
    if subs:
        player.SetTargetSubsystem(subs[0])
    d = viewscreen_bars.build_viewscreen_bars(player, t)
    assert d["top_text"] == "Kessok"


def test_bottom_text_equals_the_reticle_line(scene):
    pSet, player, _ = scene
    t = _ship(pSet, "Kessok", y=200.0)
    d = viewscreen_bars.build_viewscreen_bars(player, t)
    assert d["bottom_text"] == reticle_text.readout_line(t, player)
    assert re.match(r"^\d+\.\d\d km / \d+ kph$", d["bottom_text"])


def test_planet_reads_zero_speed_and_grey(scene):
    from engine.appc.planet import Planet
    pSet, player, _ = scene
    p = Planet(90.0, "planet.nif")
    p.SetName("Haven")
    p.SetWorldLocation(TGPoint3(0.0, 500.0, 0.0))
    pSet.AddObjectToSet(p, "Haven")
    d = viewscreen_bars.build_viewscreen_bars(player, p)
    assert d["bottom_text"].endswith(" 0 kph")
    assert d["band_rgb"] == (128, 128, 128)


def test_no_target_or_dead_target_is_hidden(scene, monkeypatch):
    pSet, player, _ = scene
    assert viewscreen_bars.build_viewscreen_bars(player, None) == {"visible": False}
    t = _ship(pSet, "Kessok", y=200.0)
    from engine.appc import camera_modes
    monkeypatch.setattr(camera_modes, "_target_alive", lambda o: False)
    assert viewscreen_bars.build_viewscreen_bars(player, t) == {"visible": False}
