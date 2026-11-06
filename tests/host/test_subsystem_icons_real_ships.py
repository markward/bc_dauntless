"""Subsystem icon keys on real ships (weapon constructors need a ship)."""
import pytest

import App
import loadspacehelper

from engine.ui import subsystem_icons as si


@pytest.fixture(autouse=True)
def reset_sets():
    App.g_kSetManager._sets.clear()
    yield
    App.g_kSetManager._sets.clear()


def _find(ship, name):
    found = []

    def walk(sub):
        if sub.GetName() == name:
            found.append(sub)
        for i in range(sub.GetNumChildSubsystems()):
            walk(sub.GetChildSubsystem(i))

    seen = []
    it = ship.StartGetSubsystemMatch(App.CT_SHIP_SUBSYSTEM)
    sub = ship.GetNextSubsystemMatch(it)
    while sub is not None:
        seen.append(sub)
        sub = ship.GetNextSubsystemMatch(it)
    ship.EndGetSubsystemMatch(it)
    for s in seen:
        walk(s)
    assert found, name
    return found[0]


@pytest.mark.parametrize("ship_class,name,key", [
    ("Akira", "Phasers", "laser"),
    ("Akira", "Dorsal Phaser 1", "laser"),
    ("Akira", "Torpedoes", "test-tubes"),
    ("Akira", "Forward Torp 1", "test-tubes"),
    ("Akira", "Tractors", "wand-sparkles"),
    ("Akira", "Forward Tractor", "wand-sparkles"),
    ("Akira", "Port Impulse", "chevrons-up"),
    ("Akira", "Port Warp", "warp-pod"),
    ("Akira", "Warp Core", "zap"),
    ("Warbird", "Cloaking Device", "eye-off"),
    ("Warbird", "Disruptor Cannons", "loader"),
    ("Warbird", "Port Cannon 1", "loader"),
    ("Warbird", "Disruptor Beam", "laser"),
    ("Warbird", "Disruptor", "laser"),
])
def test_real_ship_icon_keys(ship_class, name, key):
    ship = loadspacehelper.CreateShip(ship_class, None, "s", None, 0, 0)
    assert ship is not None
    assert si.icon_key_for(_find(ship, name)) == key
