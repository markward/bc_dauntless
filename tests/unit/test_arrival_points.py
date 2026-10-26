"""A default warp into DryDock arrives beside the Dry Dock, not inside it.

DryDock's "Player Start" is one unit from the Dry Dock home station, so the
region gets its own arrival point 20 GU forward and 30 GU left of it, facing
the same way (Mark, live 2026-10-26). A placement a mission linked is kept.
"""
import pytest

import App
from engine.appc import dash, warp
from engine.systems import arrival_points as ap
from tests.helpers.fresh_world import _fresh_world


@pytest.fixture
def drydock():
    _fresh_world()
    import Systems.DryDock.DryDock as region
    region.Initialize()
    return App.g_kSetManager.GetSet("DryDock")


def _xyz(p):
    return (round(p.x, 4), round(p.y, 4), round(p.z, 4))


def test_drydock_gets_a_point_forward_and_left_of_player_start(drydock):
    start = drydock.GetObject("Player Start")
    point = drydock.GetObject(ap.NAME)
    assert point is not None
    # "Player Start" is the origin facing +Y with +Z up, so left is -X.
    assert _xyz(start.GetWorldLocation()) == (0.0, 0.0, 0.0)
    assert _xyz(point.GetWorldLocation()) == (-30.0, 20.0, 0.0)
    for i in range(3):
        assert _xyz(point.GetWorldRotation().GetCol(i)) == \
            _xyz(start.GetWorldRotation().GetCol(i))


def test_the_point_is_clear_of_the_dry_dock(drydock):
    dock = drydock.GetObject("DryDock Start").GetWorldLocation()
    point = drydock.GetObject(ap.NAME).GetWorldLocation()
    d = ((dock.x - point.x) ** 2 + (dock.y - point.y) ** 2
         + (dock.z - point.z) ** 2) ** 0.5
    assert d > 30.0


def test_a_region_with_no_entry_gets_no_point():
    _fresh_world()
    import Systems.Starbase12.Starbase12 as region
    region.Initialize()
    assert App.g_kSetManager.GetSet("Starbase12").GetObject(ap.NAME) is None


def test_running_the_region_again_keeps_one_point(drydock):
    first = drydock.GetObject(ap.NAME)
    ap.add_for_set(drydock, "DryDock")
    assert drydock.GetObject(ap.NAME) is first


def test_only_the_default_placement_is_swapped(drydock):
    assert ap.placement_in(drydock, "Player Start") == ap.NAME
    assert ap.placement_in(drydock, "DryDock2") == "DryDock2"
    assert ap.placement_in(None, "Player Start") == "Player Start"


def test_a_tunnel_warp_arrives_at_the_point(drydock):
    player = App.ShipClass_Create()
    player.SetName("player")
    warp._PlacePlayerAction(player, "DryDock", "Player Start").Play()
    assert drydock.GetObject("player") is player
    assert _xyz(player.GetWorldLocation()) == (-30.0, 20.0, 0.0)


def test_a_linked_placement_still_wins_in_a_tunnel_warp(drydock):
    player = App.ShipClass_Create()
    player.SetName("player")
    warp._PlacePlayerAction(player, "DryDock", "DryDock Start").Play()
    assert _xyz(player.GetWorldLocation()) == (1.0, 1.0, 1.0)


def test_a_dash_plans_to_the_point(drydock, monkeypatch):
    from engine.systems import frames
    seen = []

    def system_position(obj):
        seen.append(obj)
        return None                  # stop before planning: no dash starts

    monkeypatch.setattr(frames, "system_position", system_position)
    player = App.ShipClass_Create()
    assert dash.start_set_course(player, drydock, "Player Start", {}) is False
    assert seen[0] is drydock.GetObject(ap.NAME)
