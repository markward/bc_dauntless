"""E1M2 "Scan Area" regression: the Science-menu area scan must advance the
mission.

After Haven's second hail the player must click Science -> Scan Area to progress.
The button fires ET_SCAN / EST_SCAN_AREA at Miguel's Science menu, where E1M2's
own ``ScanHandler`` (registered LIFO ahead of the generic handler) flips
``g_bAreaScanDone``, disables the button, and calls ``ScanComplete()`` — which
does ``pSensors.ScanAllObjects().Play()`` with NO None guard.

``SensorSubsystem.ScanAllObjects`` was unimplemented, so it fell through to a
truthy ``_Stub``: the SDK got junk instead of a real, playable ``TGSequence``.
This drives the real menu-instance dispatch and asserts the mission advances and
the scan yields a genuine TGSequence.
"""
import App
from engine import host_loop
from tests.integration.test_sdk_bridge_load import _fresh_world


E1M2_MODULE = "Maelstrom.Episode1.E1M2.E1M2"


def _init_e1m2():
    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(E1M2_MODULE)
    return mod


def _arm_area_scan(mod):
    """Bring E1M2 to the point where an area scan advances the mission:
    player in Vesuvi6 (already so at load) and Haven's 2nd hail done.

    Note we do NOT touch sensor power — the player's sensors must already be ON
    at mission load (a functioning sensor array is on during normal operation).
    E1M2.ScanHandler bails to the generic 'yes sir' handler when IsOn()==0, so
    this is the crux of the live bug and we assert it below."""
    import MissionLib
    player = MissionLib.GetPlayer()
    sensors = player.GetSensorSubsystem()
    mod.g_bHavenSecondHail = 1       # narrative gate (set live by Haven's 2nd hail)
    mod.g_bAreaScanDone = 0
    return player, sensors


def test_player_sensors_are_on_at_mission_load():
    """The live blocker: sensors were never powered on, so ScanHandler's
    `if pSensors.IsOn() == FALSE: CallNextHandler` always fired -> generic
    acknowledgement instead of the mission scan. Guard the fix."""
    mod = _init_e1m2()
    import MissionLib
    sensors = MissionLib.GetPlayer().GetSensorSubsystem()
    assert sensors.IsOn() == 1


def test_scan_all_objects_returns_real_sequence_in_mission():
    """The engine method the SDK calls now returns a real TGSequence, not a
    _Stub — the distinguishing fix."""
    mod = _init_e1m2()
    player, sensors = _arm_area_scan(mod)
    seq = sensors.ScanAllObjects()
    assert isinstance(seq, App.TGSequence)   # NOT a _Stub
    seq.Play()                               # must not raise


def test_area_scan_advances_mission():
    mod = _init_e1m2()
    _arm_area_scan(mod)
    assert mod.g_bAreaScanDone == 0
    assert mod.g_bScanComplete == 0

    # Drive the real Science-menu instance-handler chain, exactly as the
    # "Scan Area" button does: ET_SCAN carrying EST_SCAN_AREA.
    import Bridge.BridgeUtils as BridgeUtils
    menu = BridgeUtils.GetBridgeMenu("Science")
    assert menu is not None
    evt = App.TGIntEvent_Create()
    evt.SetEventType(App.ET_SCAN)
    evt.SetInt(App.CharacterClass.EST_SCAN_AREA)
    evt.SetDestination(menu)
    menu.ProcessEvent(evt)               # must not raise on ScanAllObjects().Play()

    # E1M2.ScanHandler ran (flag flipped) and ScanComplete advanced the mission.
    assert mod.g_bAreaScanDone == 1
    assert mod.g_bScanComplete == 1
