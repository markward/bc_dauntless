"""Every consumer reads the same distance, computed once.

Before this, the player-to-contact vector was derived independently by
engine.ui.reticle_text (via GetWorldLocation) and by
engine.ui.ship_display_panel._range_and_speed_to (via GetTranslate), each
re-applying BC's subtract-the-bounding-radius convention. Both now read
`surface_gu` off the frame's perception.Contact record.

The two accessors happen to return the same number on our ObjectClass
(both read `_position`), so equality alone cannot tell a migrated reader
from an un-migrated one. The discriminating tests move the ship WITHOUT
re-pushing: the readout must follow the pushed record, because the record
is the frame's answer. In production _pump_contacts runs every frame
before PanelRegistry.render_all (host_loop.py:7028 vs :7046), so the two
never actually diverge on screen.
"""
import math

import pytest

import App
from engine.appc import contact_index
from engine.appc.perception import perceived_by
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.ui.reticle_text import _ReticleCam
from engine.units import GU_TO_KM


def _observer(pSet):
    """A player-shaped ship with a REAL sensor subsystem — mirrors
    tests/unit/test_perceived_by.py::_observer."""
    ship = ShipClass_Create("Galaxy")
    ship.SetName("player")
    ship.SetTranslateXYZ(0.0, 0.0, 0.0)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = 100.0
    sensors._condition = 100.0
    sensors.SetBaseSensorRange(2000.0)
    ship.SetSensorSubsystem(sensors)
    pSet.AddObjectToSet(ship, "player")
    return ship


def _placed(pSet, name, y=0.0, radius=0.0):
    """A contact at (0, y, 0) — down the camera axis used below."""
    s = ShipClass_Create("Galaxy")
    s.SetName(name)
    s.SetTranslateXYZ(0.0, y, 0.0)
    if radius:
        s.SetRadius(radius)
    pSet.AddObjectToSet(s, name)
    return s


def _pump(player):
    """One frame of the host loop's contact push (host_loop._pump_contacts)."""
    App._reset_target_menu_singleton()
    menu = App.STTargetMenu_CreateW("Targets")
    contacts = perceived_by(player)
    menu.set_contacts(contacts)
    return menu, contacts


def _camera():
    # Eye at (0,-50,0) looking down +Y, so a contact at +Y is on-screen.
    # Same shape as tests/unit/test_reticle_text.py::_cam_facing_target.
    return _ReticleCam(eye=(0.0, -50.0, 0.0), target=(0.0, 0.0, 0.0),
                       up=(0.0, 0.0, 1.0), fov_y_rad=math.radians(60.0),
                       near=1.0, far=5000.0)


def _viewport():
    return (1280, 720)


def _scene():
    contact_index.reset()
    App._reset_target_menu_singleton()
    pSet = SetClass()
    player = _observer(pSet)
    target = _placed(pSet, "Galor", y=205.0, radius=5.0)
    return pSet, player, target


# ── ship_display_panel ───────────────────────────────────────────────────────

def test_ship_display_range_matches_the_contact_record():
    """ship_display_panel derived its own distance via GetTranslate();
    reticle_text used GetWorldLocation(). Both now read one record."""
    from engine.ui.ship_display_panel import _range_and_speed_to

    _pSet, player, target = _scene()
    _menu, contacts = _pump(player)
    contact = contacts[0]

    # NOTE the argument order: _range_and_speed_to(ship, player).
    rng_km, _speed = _range_and_speed_to(target, player)

    assert rng_km == pytest.approx(contact.surface_gu * GU_TO_KM)


def test_ship_display_range_reads_the_record_not_the_world_position():
    """The discriminator: with the record pushed, moving the ship without
    re-pushing must not move the readout. A reader that re-derives the
    vector from GetTranslate() would follow the ship."""
    from engine.ui.ship_display_panel import _range_and_speed_to

    _pSet, player, target = _scene()
    _menu, contacts = _pump(player)
    pushed_km = contacts[0].surface_gu * GU_TO_KM

    target.SetTranslateXYZ(0.0, 905.0, 0.0)   # no re-push
    rng_km, _speed = _range_and_speed_to(target, player)

    assert rng_km == pytest.approx(pushed_km)


def test_ship_display_range_falls_back_without_a_record():
    """A targeted PLANET is an ObjectClass, and contact_index buckets ships
    only — so it never has a record. The local read must survive."""
    from engine.ui.ship_display_panel import _range_and_speed_to

    contact_index.reset()
    App._reset_target_menu_singleton()
    pSet = SetClass()
    player = _observer(pSet)
    lone = _placed(pSet, "Galor", y=205.0, radius=5.0)
    # Nothing pushed: no target menu at all.
    rng_km, _speed = _range_and_speed_to(lone, player)

    assert rng_km == pytest.approx(200.0 * GU_TO_KM)


# ── reticle_text ─────────────────────────────────────────────────────────────

def test_reticle_range_matches_the_contact_record():
    """reticle_text renders range into a formatted string
    (line2 = "%.2f km / %.0f kph"), so parse it back out rather than
    inventing a payload key that does not exist."""
    from engine.ui.reticle_text import build_reticle_text

    _pSet, player, target = _scene()
    player.SetTarget(target)
    _menu, contacts = _pump(player)
    contact = contacts[0]

    payload = build_reticle_text(player, _camera(), _viewport())
    shown_km = float(payload["line2"].split(" km")[0])

    assert shown_km == pytest.approx(contact.surface_gu * GU_TO_KM, abs=0.01)


def test_reticle_range_reads_the_record_not_the_world_position():
    from engine.ui.reticle_text import build_reticle_text

    _pSet, player, target = _scene()
    player.SetTarget(target)
    _menu, contacts = _pump(player)
    pushed_km = contacts[0].surface_gu * GU_TO_KM

    target.SetTranslateXYZ(0.0, 905.0, 0.0)   # no re-push
    payload = build_reticle_text(player, _camera(), _viewport())
    shown_km = float(payload["line2"].split(" km")[0])

    assert shown_km == pytest.approx(pushed_km, abs=0.01)


def test_bulk_rebuild_synthesises_no_distance_at_all():
    """RebuildShipMenus takes a SET, not an observer, so it cannot answer
    distance — and contact_for cannot tell its synthesised value from a real
    one. Its records therefore carry NaN, so a reader that wrongly trusts them
    renders "nan km" instead of a perfectly believable "0.00 km"."""
    from engine.ui.ship_display_panel import _range_and_speed_to

    contact_index.reset()
    App._reset_target_menu_singleton()
    pSet = SetClass()
    player = _observer(pSet)
    target = _placed(pSet, "Galor", y=205.0, radius=5.0)

    menu = App.STTargetMenu_CreateW("Targets")
    menu.RebuildShipMenus(pSet)

    assert math.isnan(menu.contact_for(target).surface_gu)
    assert math.isnan(menu.contact_for(target).dist_sq_gu)
    rng_km, _speed = _range_and_speed_to(target, player)
    assert math.isnan(rng_km)


def test_the_two_readouts_agree():
    """The point of the stage: one number, two panels."""
    from engine.ui.reticle_text import build_reticle_text
    from engine.ui.ship_display_panel import _range_and_speed_to

    _pSet, player, target = _scene()
    player.SetTarget(target)
    _pump(player)

    rng_km, _speed = _range_and_speed_to(target, player)
    shown_km = float(
        build_reticle_text(player, _camera(), _viewport())["line2"]
        .split(" km")[0])

    assert shown_km == pytest.approx(rng_km, abs=0.01)
