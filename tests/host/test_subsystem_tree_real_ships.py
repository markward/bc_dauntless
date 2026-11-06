"""build_families on stock hardpoint ships."""
import App
import loadspacehelper
import pytest

from engine.ui.subsystem_tree import build_families


@pytest.fixture(autouse=True)
def reset_sets():
    App.g_kSetManager._sets.clear()
    yield
    App.g_kSetManager._sets.clear()


def _by_name(fams):
    return {f.name: f for f in fams}


def test_akira_families():
    ship = loadspacehelper.CreateShip("Akira", None, "a", None, 0, 0)
    fams = _by_name(build_families(ship))
    assert set(fams) == {"Sensor Array", "Impulse Engines", "Warp Engines",
                         "Torpedoes", "Phasers", "Tractors",
                         "Shield Generator", "Warp Core"}
    assert len(fams["Phasers"].members) == 8
    assert len(fams["Torpedoes"].members) == 6
    port_warp = next(m for m in fams["Warp Engines"].members
                     if m.name == "Port Warp")
    assert (port_warp.x_px, port_warp.y_px) == (4.0, 90.0)


def test_warbird_families():
    ship = loadspacehelper.CreateShip("Warbird", None, "w", None, 0, 0)
    fams = _by_name(build_families(ship))
    assert len(fams) == 10
    cloak = fams["Cloaking Device"]
    assert cloak.icon_key == "eye-off" and cloak.members == ()
    beam = fams["Disruptor Beam"]
    assert beam.lockable is False
    assert [m.name for m in beam.members] == ["Disruptor"]
    cannons = fams["Disruptor Cannons"]
    assert len(cannons.members) == 4 and cannons.icon_key == "loader"
