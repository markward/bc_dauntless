"""Damage-row descriptor pipeline — hardpoint-driven walk over the
ship's subsystem tree, filtered to subsystems with a non-zero
Position2D, glyphed via the DamageIcons enum.

Fixture: Galaxy. Hardpoint (sdk/Build/scripts/ships/Hardpoints/galaxy.py)
declares Hull@(64,40), SensorArray@(64,10), ShieldGenerator@(64,40),
ImpulseEngines etc., plus per-bank phaser/torpedo positions.
"""
import pytest

import App
import loadspacehelper

from engine.core.game import Game, _set_current_game
from engine.ui import ship_display_panel as sdp


@pytest.fixture(autouse=True)
def reset_global_state():
    _set_current_game(None)
    App.g_kSetManager._sets.clear()
    yield
    _set_current_game(None)
    App.g_kSetManager._sets.clear()


@pytest.fixture
def galaxy_ship():
    App.g_kSetManager._sets.clear()
    ship = loadspacehelper.CreateShip("Galaxy", None, "player", None, 0, 0)
    assert ship is not None
    game = Game()
    game.SetPlayer(ship)
    _set_current_game(game)
    return ship


def test_damage_descriptors_emit_one_row_per_positioned_subsystem(galaxy_ship):
    rows = list(sdp._damage_icon_descriptors(galaxy_ship))
    assert len(rows) > 0
    for row in rows:
        assert (row["x_px"], row["y_px"]) != (0.0, 0.0)
        for k in ("x_px", "y_px", "icon_num", "state"):
            assert k in row


def test_galaxy_hull_emits_row_at_hardpoint_position(galaxy_ship):
    rows = list(sdp._damage_icon_descriptors(galaxy_ship))
    hulls = [r for r in rows if r["icon_num"] == 0]
    assert len(hulls) == 1
    # Galaxy hardpoint: Hull.SetPosition2D(64, 40)
    assert hulls[0]["x_px"] == pytest.approx(64.0)
    assert hulls[0]["y_px"] == pytest.approx(40.0)


def test_galaxy_sensor_array_emits_row_with_sensor_icon_num(galaxy_ship):
    rows = list(sdp._damage_icon_descriptors(galaxy_ship))
    sensors = [r for r in rows if r["icon_num"] == 4]
    assert len(sensors) == 1
    assert sensors[0]["x_px"] == pytest.approx(64.0)
    assert sensors[0]["y_px"] == pytest.approx(10.0)


def test_damage_descriptor_state_reflects_subsystem_condition(galaxy_ship):
    """A healthy subsystem reports state='healthy'; damaging it flips
    to 'damaged' / 'disabled' / 'destroyed' per IsDamaged/IsDisabled/IsDestroyed."""
    hull = galaxy_ship.GetHull()
    rows = list(sdp._damage_icon_descriptors(galaxy_ship))
    hull_row = next(r for r in rows if r["icon_num"] == 0)
    assert hull_row["state"] == "healthy"

    hull.SetCondition(hull.GetMaxCondition() * 0.5)
    rows = list(sdp._damage_icon_descriptors(galaxy_ship))
    hull_row = next(r for r in rows if r["icon_num"] == 0)
    assert hull_row["state"] == "damaged"
