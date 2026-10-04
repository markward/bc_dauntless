"""Sensor contact identification — feeds the SDK bridge menus.

The player-only contact manager (``engine.appc.sensor_contacts``) walks the
player's set, buckets contacts into near/far bands, and arms a passive
identification once a contact is near and detectable — due one
identification time (BC: 4.0 s) later. Scans (``SensorSubsystem.IdentifyObject``,
``ScanAllObjects``) arm the same deferred identification, unconditional on
range/detectability, so a scan always lands once its dwell elapses.
``_identify_one`` in this module is the single commit point for all three
paths: it marks the contact known (``SensorSubsystem.AddKnownObject``) and
broadcasts ``ET_SENSORS_SHIP_IDENTIFIED``. That drives the SDK's
``Bridge/HelmMenuHandlers.ShipIdentified`` (per-target Hail / fleet-command
buttons) and ``ScienceMenuHandlers.ShipIdentified`` (scan buttons), and unlocks
target-info panels that gate on ``IsObjectKnown``.

Without this the SDK's ``ObjectEnteredSet`` only ever identifies *commandable
fleet* ships (``IsObjectKnown`` was always 0), so planets, stations and neutral
contacts never received a hail button — clicking the empty "Hail" menu did
nothing. See docs/plans and the E1M2 hail investigation.

Identification is one-shot per contact: ``AddKnownObject`` de-dupes so each
contact fires the identify event once, and a contact stays known once seen
(the SDK's ``ExitedSet`` removes its button on ``ET_EXITED_SET`` at set exit).
"""

import App
import engine.dev_mode as dev_mode


def _identify_one(sensors, obj) -> bool:
    """Identify a single contact to *sensors*: localize its display name, mark
    it known, and broadcast ``ET_SENSORS_SHIP_IDENTIFIED`` once.

    The single commit point for every identification path: the passive
    per-tick dwell and both scan paths (``SensorSubsystem.IdentifyObject``,
    ``ScanAllObjects`` via ``schedule_area_scan``), all funneled through
    ``engine.appc.sensor_contacts``. De-dupes on ``IsObjectKnown`` so no path
    can ever double-fire for one contact.

    Returns True if *obj* was newly identified, False if it was already known,
    None/invalid, or *sensors* is None."""
    if sensors is None or obj is None:
        return False
    try:
        if sensors.IsObjectKnown(obj):
            return False
    except Exception:
        return False

    # Localize the contact's display name before it gets a Hail button / target
    # row (both read GetDisplayName). Covers objects created after the
    # mission-load batch pass (e.g. a system set that loads on warp-in).
    try:
        from engine.appc import display_names
        display_names.apply_display_name(obj)
    except Exception as _e:
        dev_mode.log_swallowed("identify display-name", _e)

    sensors.AddKnownObject(obj)
    try:
        evt = App.TGEvent_Create()
        evt.SetEventType(App.ET_SENSORS_SHIP_IDENTIFIED)
        # The SDK's ShipIdentified reads pEvent.GetDestination() as the
        # identified object.
        evt.SetDestination(obj)
        App.g_kEventManager.AddEvent(evt)
    except Exception as _e:
        dev_mode.log_swallowed("sensor identify broadcast", _e)
    return True


def _resolve_sensors_and_set(player):
    """Return ``(sensors, pSet)`` for *player*, or ``(None, None)`` if either the
    sensor subsystem or a set with GetObjectList is unavailable. Shared by the
    passive sweep and the active area scan."""
    if player is None:
        return None, None
    sensors = (player.GetSensorSubsystem()
               if hasattr(player, "GetSensorSubsystem") else None)
    if sensors is None:
        return None, None
    pSet = (player.GetContainingSet()
            if hasattr(player, "GetContainingSet") else None)
    if pSet is None or not hasattr(pSet, "GetObjectList"):
        return None, None
    return sensors, pSet


def schedule_area_scan(player) -> int:
    """Active area scan: arm a scan identification for every unknown ship /
    station / planet in *player*'s set, ignoring range, one identification
    time apart (BC's ScanAllObjects spaces its scan actions by
    GetIdentificationTime). Returns how many were armed."""
    sensors, pSet = _resolve_sensors_and_set(player)
    if sensors is None:
        return 0
    from engine.appc.ships import ShipClass
    from engine.appc.planet import Planet
    from engine.appc import sensor_contacts
    dwell = sensors.GetIdentificationTime()
    n = 0
    for obj in pSet.GetObjectList():
        if obj is None or obj is player or not isinstance(obj, (ShipClass, Planet)):
            continue
        if sensors.IsObjectKnown(obj):
            continue
        n += 1
        sensor_contacts.schedule_scan(obj, dwell * n)
    return n


def ScanAllObjectsAction(pAction, iShipID) -> int:
    """TGScriptAction entry played by the ScanAllObjects sequence. Re-looks up
    the scanning ship by id (SDK idiom) and arms the area scan. Returns 0 so
    TGScriptAction.Play auto-completes."""
    try:
        ship = App.TGObject_GetTGObjectPtr(iShipID)
        if ship is not None:
            schedule_area_scan(ship)
    except Exception as _e:
        dev_mode.log_swallowed("ScanAllObjectsAction", _e)
    return 0
