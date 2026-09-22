"""ShipClass alert level — defaults, accessors, and display formatting.

BC's alert system: GREEN (powered-down), YELLOW (shields up, defensive),
RED (shields + weapons up, combat). The SDK calls
``pPlayer.SetAlertLevel(App.ShipClass.GREEN_ALERT)`` on mission start
(``MissionLib.py:605``) and ``BridgeHandlers.py`` reads
``pShip.GetAlertLevel()`` to drive crew behavior. Side effects live
downstream in the XO menu chain — not in scope for this shim.
"""
from engine.appc.ships import ShipClass
from engine.host_loop import _format_alert_level


def test_default_alert_level_is_red():
    """Every non-player object in the mission-scene captures reads alert 2
    at t = 0 (stbc-oracle bible §13 N2); the player is green only because
    MissionLib.CreatePlayerShip sets it so."""
    s = ShipClass()
    assert s.GetAlertLevel() == ShipClass.RED_ALERT


def test_set_alert_level_persists():
    s = ShipClass()
    s.SetAlertLevel(ShipClass.YELLOW_ALERT)
    assert s.GetAlertLevel() == ShipClass.YELLOW_ALERT
    s.SetAlertLevel(ShipClass.RED_ALERT)
    assert s.GetAlertLevel() == ShipClass.RED_ALERT
    s.SetAlertLevel(ShipClass.GREEN_ALERT)
    assert s.GetAlertLevel() == ShipClass.GREEN_ALERT


def test_format_alert_level_maps_constants_to_names():
    assert _format_alert_level(ShipClass.GREEN_ALERT) == "Green"
    assert _format_alert_level(ShipClass.YELLOW_ALERT) == "Yellow"
    assert _format_alert_level(ShipClass.RED_ALERT) == "Red"


def test_format_alert_level_handles_unknown():
    assert _format_alert_level(99) == "---"
