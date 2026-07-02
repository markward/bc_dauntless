"""Sensor contact identification — feeds the SDK bridge menus.

Each tick the player's sensors identify newly-detectable contacts in the
player's set: mark them known (``SensorSubsystem.AddKnownObject``) and broadcast
``ET_SENSORS_SHIP_IDENTIFIED``. That drives the SDK's
``Bridge/HelmMenuHandlers.ShipIdentified`` (per-target Hail / fleet-command
buttons) and ``ScienceMenuHandlers.ShipIdentified`` (scan buttons), and unlocks
target-info panels that gate on ``IsObjectKnown``.

Without this the SDK's ``ObjectEnteredSet`` only ever identifies *commandable
fleet* ships (``IsObjectKnown`` was always 0), so planets, stations and neutral
contacts never received a hail button — clicking the empty "Hail" menu did
nothing. See docs/plans and the E1M2 hail investigation.

Detection is range-gated and BC-faithful: a contact stays unknown until it comes
within the player's effective sensor range. Range / nebula / cloak gating reuses
``sensor_detection.can_detect`` (already used by the target list and AI target
selection), so identification and the rest of the sensor surface agree.

Identification is one-shot per contact: ``AddKnownObject`` de-dupes so each
contact fires the identify event once, and a contact stays known once seen
(the SDK's ``ExitedSet`` removes its button on ``ET_EXITED_SET`` at set exit).
"""

import App
from engine.appc.sensor_detection import can_detect
import engine.dev_mode as dev_mode


def _identify_one(sensors, obj) -> bool:
    """Identify a single contact to *sensors*: localize its display name, mark
    it known, and broadcast ``ET_SENSORS_SHIP_IDENTIFIED`` once.

    Shared by the passive per-tick sweep (``identify_contacts``), the active
    area scan (``identify_all_in_set`` / ``SensorSubsystem.ScanAllObjects``) and
    the single-target scan (``SensorSubsystem.IdentifyObject``). De-dupes on
    ``IsObjectKnown`` so the three paths can never double-fire for one contact.

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


def identify_contacts(player) -> None:
    """Identify newly-detectable contacts in *player*'s set to the player's
    sensors, firing ET_SENSORS_SHIP_IDENTIFIED for each. Cheap on steady state:
    only objects not already known and inside sensor range do any work."""
    sensors, pSet = _resolve_sensors_and_set(player)
    if sensors is None:
        return

    try:
        player_id = player.GetObjID()
    except Exception:
        player_id = None

    # Only real sensor contacts are identified — ships/stations (ShipClass) and
    # celestial bodies (Planet, incl. colonies like E1M2's Haven). A set also
    # holds lights, placement markers ("Player Start", "* Location"), and grids;
    # firing ET_SENSORS_SHIP_IDENTIFIED for those would spam the bridge Hail /
    # scan menus with non-contacts. (Lazy import to avoid an import cycle.)
    from engine.appc.ships import ShipClass
    from engine.appc.planet import Planet

    for obj in pSet.GetObjectList():
        if obj is None or obj is player:
            continue
        if not isinstance(obj, (ShipClass, Planet)):
            continue
        # Skip the player itself (id compare guards against a re-added handle).
        try:
            if player_id is not None and obj.GetObjID() == player_id:
                continue
        except Exception:
            continue
        # Already identified — the known-set de-dupes so we fire once per contact.
        if sensors.IsObjectKnown(obj):
            continue
        # BC-faithful gate: unknown until inside effective sensor range (also
        # honours nebula concealment and cloak). Guard so one bad handle can't
        # abort the whole sweep.
        try:
            detectable = can_detect(player, obj)
        except Exception as _e:
            dev_mode.log_swallowed("sensor identify can_detect", _e)
            continue
        if not detectable:
            continue

        _identify_one(sensors, obj)


def identify_all_in_set(player) -> int:
    """Active area scan: identify EVERY ship/station/planet in *player*'s set,
    ignoring sensor range — an active scan reveals the whole area, which is what
    distinguishes it from the passive per-tick sweep (``identify_contacts``).

    Reuses the same per-contact core (``_identify_one``), which de-dupes on
    ``IsObjectKnown``: contacts already identified in-range by the passive sweep
    are skipped, so the two paths never double-fire; the active scan only *adds*
    the out-of-range contacts. Returns the count newly identified.

    Drives ``SensorSubsystem.ScanAllObjects`` (Science menu "Scan Area" and
    E1M2's ScanComplete)."""
    sensors, pSet = _resolve_sensors_and_set(player)
    if sensors is None:
        return 0

    try:
        player_id = player.GetObjID()
    except Exception:
        player_id = None

    # Same contact filter as the passive sweep — ships/stations + celestial
    # bodies only, never lights / placement markers / grids.
    from engine.appc.ships import ShipClass
    from engine.appc.planet import Planet

    count = 0
    for obj in pSet.GetObjectList():
        if obj is None or obj is player:
            continue
        if not isinstance(obj, (ShipClass, Planet)):
            continue
        try:
            if player_id is not None and obj.GetObjID() == player_id:
                continue
        except Exception:
            continue
        if _identify_one(sensors, obj):
            count += 1
    return count


def ScanAllObjectsAction(pAction, iShipID) -> int:
    """TGScriptAction entry played by the ``ScanAllObjects`` sequence.

    Re-looks up the scanning ship by id (SDK idiom, matching
    ``Actions.ShipScriptActions.ScanObject``) and identifies every contact in
    its set. Returns 0 so ``TGScriptAction.Play`` auto-completes the action."""
    try:
        ship = App.TGObject_GetTGObjectPtr(iShipID)
        if ship is not None:
            identify_all_in_set(ship)
    except Exception as _e:
        dev_mode.log_swallowed("ScanAllObjectsAction", _e)
    return 0
