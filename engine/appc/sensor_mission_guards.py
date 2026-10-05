"""SDK/mission guards for re-identification (sensor continuity spec, Guards).

Sub-project 2 can identify a ship more than once (lost track -> found again),
which stock BC never did. Two SDK handlers were audited as unsafe for that
(roadmap "Re-identification audit"):

  * E5M2.ShipIdentified (E5M2.py:610) replays dialogue and re-adds a goal on
    every Outpost identification. Only the first Outpost identification per
    mission runs the mission body; later ones are skipped.
  * HelmMenuHandlers.AddHailButton (HelmMenuHandlers.py:568) runs 1 s after
    identification (queued via a TGSequence/TGScriptAction) and never
    re-checks; a track lost inside that second would still get a button.
    Re-checked against the player's known set at the moment it actually runs.

Both wrap by module attribute -- handlers resolve by name at dispatch
(engine/appc/events.py:_resolve_handler). install() is idempotent and is
re-run on mission swap (the SDK modules may be re-imported, or may simply
persist in sys.modules with their globals reset by the mission's own
Initialize()).

CallNextHandler note: ET_SENSORS_SHIP_IDENTIFIED reaches E5M2.ShipIdentified
as a BROADCAST func handler (registered via AddBroadcastPythonFuncHandler).
Broadcast handlers are NOT chained in this engine --
TGEventManager.AddEvent (engine/appc/events.py) walks a flat snapshot list
and calls every registered handler for the event type unconditionally;
CallNextHandler only advances a PER-OBJECT dispatch frame pushed by
TGEventHandlerObject.ProcessEvent, which this broadcast path never pushes
onto the mission object. So calling pObject.CallNextHandler(pEvent) from the
guard's "already seen" branch would be an inert no-op (same as the SDK's own
tail-call in the non-Outpost branch) -- the guard just returns instead, which
is both correct and clearer about what's actually happening.
"""
import sys

import engine.dev_mode as dev_mode

_outpost_seen = False


def reset() -> None:
    """Clear the Outpost first-identification latch. Called from
    host_loop._reset_sensor_state on every mission (re)load, mirroring
    E5M2.Initialize's own reset of g_bBaseID/g_bSequenceAppended -- the SDK
    module's globals and this module's latch must go stale together."""
    global _outpost_seen
    _outpost_seen = False


def _wrap_e5m2(orig):
    def ShipIdentified(pObject, pEvent):
        global _outpost_seen
        try:
            import App
            ship = App.ShipClass_Cast(pEvent.GetDestination())
            is_outpost = ship is not None and ship.GetName() == "Outpost"
        except Exception as e:
            dev_mode.log_swallowed("E5M2 guard", e)
            is_outpost = False
        if is_outpost and _outpost_seen:
            # See the module docstring: broadcast func handlers are not
            # chained here, so there is no "pass it on" call needed or
            # possible -- every other handler for this event type still
            # runs regardless of what this one returns.
            return None
        if is_outpost:
            _outpost_seen = True
        return orig(pObject, pEvent)
    ShipIdentified._sensor_guarded = True
    return ShipIdentified


def _wrap_add_hail(orig):
    def AddHailButton(pAction, idObject):
        try:
            import App
            from engine.appc import sensor_contacts
            obj = App.ObjectClass_Cast(App.TGObject_GetTGObjectPtr(idObject))
            if obj is not None and not sensor_contacts.player_knows(obj):
                return 0
        except Exception as e:
            dev_mode.log_swallowed("AddHailButton guard", e)
        return orig(pAction, idObject)
    AddHailButton._sensor_guarded = True
    return AddHailButton


def install() -> None:
    """Idempotent: safe to call at boot (before any mission is loaded, when
    E5M2 is simply absent from sys.modules) and again on every mission
    (re)load."""
    try:
        import Bridge.HelmMenuHandlers as helm
        if not getattr(helm.AddHailButton, "_sensor_guarded", False):
            helm.AddHailButton = _wrap_add_hail(helm.AddHailButton)
    except ImportError:
        pass
    e5m2 = sys.modules.get("Maelstrom.Episode5.E5M2.E5M2")
    if e5m2 is not None and not getattr(e5m2.ShipIdentified, "_sensor_guarded", False):
        e5m2.ShipIdentified = _wrap_e5m2(e5m2.ShipIdentified)
