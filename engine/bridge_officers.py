"""SDK bridge-officer configuration — LoadBridge.ConfigureForShip, guarded.

The SDK wires each station's menu to its officer at mission load:
LoadBridge.Load builds the menus (Bridge/*MenuHandlers.CreateMenus), then
LoadBridge.ConfigureForShip(pBridgeSet, pShip) runs each character's
ConfigureForShip (Bridge/Characters/<name>.py), whose AttachMenuTo<station>
registers the officer's acknowledgement handlers on those menus (for Helm:
Report / SetCourse / HelmDock / AllStop on the top menu, OrbitPlanet on the
Orbit Planet submenu — sdk/Build/scripts/Bridge/HelmCharacterHandlers.py).

The SDK function (LoadBridge.py:271) is five sequential unguarded calls, so
the first officer that raises silently costs every later station its voice.
We iterate the same five calls in the same order, each behind its own guard:
one station's unimplemented Appc surface must not abort bridge load or the
other stations. Helm (Kiska) is the station this increment must land.
"""

from __future__ import annotations

from engine import dev_mode

# (SDK Bridge/Characters module, object name in the bridge set), in the
# LoadBridge.ConfigureForShip call order.
_STATIONS = (
    ("Felix", "Tactical"),
    ("Kiska", "Helm"),
    ("Saffi", "XO"),
    ("Miguel", "Science"),
    ("Brex", "Engineer"),
)

_COMMUNICATE_HANDLER = __name__ + ".CommunicateToReport"


def configure_bridge_officers(bridge_set, player):
    """Run each Bridge.Characters.<name>.ConfigureForShip, individually guarded.

    Returns {character_module_name: None | exception} so callers (and the dev
    log) can see which stations wired cleanly. Safe to call on every mission
    load: menus and characters are recreated per load, and AttachMenuTo*
    self-detaches before re-registering.
    """
    results = {}
    for char_name, object_name in _STATIONS:
        try:
            module = __import__("Bridge.Characters." + char_name,
                                fromlist=[char_name])
            module.ConfigureForShip(bridge_set, player)
            _wire_communicate_to_report(bridge_set, object_name)
            results[char_name] = None
        except Exception as exc:
            results[char_name] = exc
            dev_mode.log_swallowed(
                "bridge officer ConfigureForShip %s (%s)"
                % (char_name, object_name), exc)
    return results


def _wire_communicate_to_report(bridge_set, object_name) -> None:
    """Register the Communicate→Report conversion on the officer's menu.

    Every station menu's "Report" row is the SDK Communicate button
    (BridgeMenus.CreateCommunicateButton): its activation event is
    ET_COMMUNICATE with the menu as destination, NOT ET_REPORT. In stock BC
    the Appc C++ side consumed ET_COMMUNICATE (turning the officer to camera)
    and dispatched ET_REPORT to the officer's menu, which is what the
    station's *CharacterHandlers.Report actually listens for. This shim is
    that missing Appc behaviour. Registered AFTER AttachMenuTo* so LIFO
    dispatch runs it before the SDK's NothingToAdd fallback (registered at
    menu-build time by CreateMenus).
    """
    import App
    char = App.CharacterClass_Cast(bridge_set.GetObject(object_name))
    menu = char.GetMenu() if char is not None else None
    if not menu:
        return
    menu.RemoveHandlerForInstance(App.ET_COMMUNICATE, _COMMUNICATE_HANDLER)
    menu.AddPythonFuncHandlerForInstance(App.ET_COMMUNICATE,
                                         _COMMUNICATE_HANDLER)


def CommunicateToReport(pMenu, pEvent):
    """ET_COMMUNICATE instance handler: re-dispatch as ET_REPORT.

    Falls through to the next handler (the SDK's CommonAnimations.NothingToAdd
    "nothing to add" fallback) when no Report handler is registered on the
    menu, matching BC where officers without a report say exactly that.
    """
    import App
    if pMenu._handlers.get(App.ET_REPORT):
        evt = App.TGIntEvent_Create()
        evt.SetEventType(App.ET_REPORT)
        evt.SetInt(0)
        evt.SetSource(pEvent.GetSource())
        evt.SetDestination(pMenu)
        App.g_kEventManager.AddEvent(evt)
        return
    pMenu.CallNextHandler(pEvent)


def wire_after_mission_load() -> None:
    """The post-load officer wiring — called by host_loop's
    _after_mission_loaded (and by the host-level tests, so the tested path IS
    the live path). Two triggers: configure now when the player already
    exists (story missions create it during loader.load()), and on
    ET_SET_PLAYER for players created later (the boot QuickBattle spawns the
    ship at battle start and on every restart). Broadcast registration must
    re-run per load: reset_sdk_globals wipes it.
    """
    import App
    import MissionLib
    bridge = App.g_kSetManager.GetSet("bridge")
    player = MissionLib.GetPlayer()
    if bridge is not None and player is not None:
        configure_bridge_officers(bridge, player)
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_SET_PLAYER, None, __name__ + ".OnSetPlayer")


def OnSetPlayer(pObject, pEvent):
    """ET_SET_PLAYER broadcast handler — (re)configure officers for the player.

    Registered per mission load by host_loop's post-load hook. This, not the
    load-time call, is the path the boot QuickBattle actually takes: QB creates
    the player LATE (StartSimulation2 -> RecreatePlayer -> CreatePlayerShip ->
    SetPlayer, after ET_PRELOAD_DONE) and recreates it on every battle restart,
    so the officers must re-wire to the new ship each time — which is also
    stock-BC behaviour (ConfigureForShip takes pShip; Appc re-ran it on player
    assignment).
    """
    import App
    game = App.Game_GetCurrentGame()
    player = game.GetPlayer() if game is not None else None
    bridge = App.g_kSetManager.GetSet("bridge")
    if bridge is not None and player is not None:
        configure_bridge_officers(bridge, player)


def announce_course_set() -> None:
    """Fire ET_SET_COURSE (non-intercept) at the Helm menu.

    In stock BC the SortedRegionMenu's course buttons carried this event; the
    CEF Set Course modal replaced that menu and dispatches no SDK event, so
    the host calls this after a destination is picked. Non-intercept subtype:
    HelmCharacterHandlers.SetCourse speaks gh075 / sets ReadyToWarp, and
    HelmMenuHandlers.SetCourse ignores anything but EST_SET_COURSE_INTERCEPT.
    """
    import App
    bridge = App.g_kSetManager.GetSet("bridge")
    char = (App.CharacterClass_GetObject(bridge, "Helm")
            if bridge is not None else None)
    menu = char.GetMenu() if char is not None else None
    if not menu:
        return
    evt = App.TGIntEvent_Create()
    evt.SetEventType(App.ET_SET_COURSE)
    evt.SetInt(App.CharacterClass.EST_SET_COURSE_TO_MISSION_AREA)
    evt.SetDestination(menu)
    App.g_kEventManager.AddEvent(evt)
