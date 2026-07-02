"""CloakingSubsystem._fire routes cloak events to the OWNING SHIP as both
source and destination — mirroring ship_death._broadcast_destroyed.

Why the destination matters: SelectTarget registers its cloak-drop handler with

    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_CLOAK_COMPLETED, self.pEventHandler, "TargetGone", pNewTarget)

(sdk/Build/scripts/AI/Preprocessors.py). The event manager only fires that
method handler when ``event.GetDestination() is pNewTarget`` (the ship). A
cloak event sourced from the subsystem with no destination silently skips the
handler, so the AI never learns its target cloaked. This test pins that cloak
events now carry the ship, exactly like ET_OBJECT_DESTROYED.
"""
import App

from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import CloakingSubsystem


def _reset_handlers():
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


class _Sink:
    """Records cloak-completion events routed to it via a target-scoped
    method handler (the SelectTarget registration shape)."""
    def __init__(self):
        self.events = []

    def OnCloakCompleted(self, event):
        self.events.append(event)


def _register_target_scoped(event_type, target):
    """Register a target-scoped ET_CLOAK_COMPLETED method handler exactly the
    way SelectTarget.UpdateTargetInfo does, and return the sink."""
    sink = _Sink()
    wrapper = App.TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(sink)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        event_type, wrapper, "OnCloakCompleted", target)
    return sink


def test_completion_event_reaches_target_scoped_handler():
    _reset_handlers()
    ship = ShipClass_Create("Warbird")
    cloak = CloakingSubsystem("Cloaking Device")
    ship.SetCloakingSubsystem(cloak)

    sink = _register_target_scoped(App.ET_CLOAK_COMPLETED, ship)

    cloak.InstantCloak()

    assert len(sink.events) == 1
    evt = sink.events[0]
    assert evt.GetDestination() is ship
    assert evt.GetSource() is ship
    _reset_handlers()


def test_transition_completion_reaches_handler():
    """Same routing for the timed transition (not just InstantCloak)."""
    _reset_handlers()
    ship = ShipClass_Create("Warbird")
    cloak = CloakingSubsystem("Cloaking Device")
    ship.SetCloakingSubsystem(cloak)

    sink = _register_target_scoped(App.ET_CLOAK_COMPLETED, ship)

    cloak.StartCloaking()
    cloak.Update(cloak._transition_duration + 0.01)

    assert len(sink.events) == 1
    assert sink.events[0].GetDestination() is ship
    _reset_handlers()


def test_event_not_delivered_to_other_ship_handler():
    """A handler scoped to a DIFFERENT ship must NOT receive the event —
    confirms destination-identity gating still discriminates."""
    _reset_handlers()
    ship = ShipClass_Create("Warbird")
    cloak = CloakingSubsystem("Cloaking Device")
    ship.SetCloakingSubsystem(cloak)

    other = ShipClass_Create("Galaxy")
    sink_other = _register_target_scoped(App.ET_CLOAK_COMPLETED, other)

    cloak.InstantCloak()

    assert sink_other.events == []
    _reset_handlers()


def test_parentless_subsystem_falls_back_to_self():
    """A bare subsystem with no parent ship keeps the old source==self
    behaviour (relied on by test_cloaking_subsystem.py's global handlers)."""
    _reset_handlers()
    captured = []
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_CLOAK_COMPLETED, captured, __name__ + "._append_source")

    cloak = CloakingSubsystem("Cloaking Device")  # no parent ship
    cloak.InstantCloak()

    assert captured == [cloak]
    App.g_kEventManager.RemoveBroadcastHandler(
        App.ET_CLOAK_COMPLETED, captured, __name__ + "._append_source")
    _reset_handlers()


def _append_source(handler, event):
    handler.append(event.GetSource())
