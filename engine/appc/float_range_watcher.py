"""FloatRangeWatcher — threshold-crossing watcher for a single float value.

Several SDK Condition classes drive their state off a `FloatRangeWatcher`
they obtain from a subsystem getter (e.g. ``pPower.GetMainBatteryWatcher()``,
``pShields.GetShieldWatcher(side)``, ``pWeapon.GetChargeWatcher()``):

    pEvent = App.TGFloatEvent_Create()
    pEvent.SetEventType(ET_POWER_FRACTION_CHANGED)
    pEvent.SetSource(pPower)
    pEvent.SetDestination(self.pEventHandler)
    self.idWatcher = pWatcher.AddRangeCheck(
        self.fFraction, App.FloatRangeWatcher.FRW_BOTH, pEvent)
    ...
    pWatcher.RemoveRangeCheck(self.idWatcher)
    fNow = pWatcher.GetWatchedVariable()

See sdk/Build/scripts/Conditions/ConditionPowerBelow.py:62-72,
ConditionSingleShieldBelow.py:113-122, ConditionPulseReady.py:158-167.

In the original Appc engine the watcher lived in C++ and the owning
subsystem pushed new values each tick. Here the owner calls
:meth:`_update` with the latest value; on a registered threshold crossing in
the watched direction the watcher stamps the value onto ``pEvent`` (via
``SetFloat``) and broadcasts it through the event manager — exactly the path
``g_kEventManager.AddEvent`` takes (engine/appc/events.py:TGEventManager.AddEvent),
so the event reaches ``pEvent``'s destination handler.

Subsystem getters that hand a watcher to these conditions are wired in a
later task (W1.T2); this module only provides the watcher itself.
"""
from typing import Optional


class FloatRangeWatcher:
    """Watches a single float; fires registered events on threshold crossings.

    Direction constants control which crossings fire:
      * ``FRW_BELOW`` — fires when the value goes from ``>= threshold`` to
        ``< threshold`` (a downward crossing).
      * ``FRW_ABOVE`` — fires on the reverse (an upward crossing).
      * ``FRW_BOTH``  — fires on either crossing.
    The SDK conditions only pass these constants opaquely, so the exact int
    values are an internal choice; they are kept distinct and stable.
    """

    FRW_BELOW: int = 0
    FRW_ABOVE: int = 1
    FRW_BOTH: int = 2

    def __init__(self, initial_value: float = 0.0, event_manager=None) -> None:
        self._value: float = float(initial_value)
        self._checks: dict = {}  # id -> (threshold, direction, pEvent)
        self._next_id: int = 1
        # The event manager used to broadcast crossing events. Defaults to the
        # global App.g_kEventManager so subsystem-created watchers reach the
        # same bus the SDK conditions register their handlers on.
        self._event_manager = event_manager

    def AddRangeCheck(self, threshold: float, direction: int, pEvent) -> int:
        """Register a threshold check and return an opaque id.

        ``pEvent`` is broadcast (with the crossing value stamped via SetFloat)
        whenever the watched value crosses ``threshold`` in ``direction``.
        """
        check_id = self._next_id
        self._next_id += 1
        self._checks[check_id] = (float(threshold), int(direction), pEvent)
        return check_id

    def RemoveRangeCheck(self, check_id: int) -> None:
        """Stop firing the check with the given id (no-op if already gone)."""
        self._checks.pop(check_id, None)

    def GetWatchedVariable(self) -> float:
        """Return the latest watched value."""
        return self._value

    def _update(self, new_value: float) -> None:
        """Push a new value; fire any check whose threshold was crossed.

        Crossing is evaluated against the *previous* value, so a check only
        fires on the tick the boundary is actually traversed — not while the
        value lingers on one side.
        """
        new_value = float(new_value)
        old_value = self._value
        # Snapshot so a handler that mutates the check set mid-dispatch can't
        # corrupt iteration.
        for threshold, direction, pEvent in list(self._checks.values()):
            if self._crossed(old_value, new_value, threshold, direction):
                self._fire(pEvent, new_value)
        self._value = new_value

    @staticmethod
    def _crossed(old_value: float, new_value: float, threshold: float,
                 direction: int) -> bool:
        downward = old_value >= threshold > new_value
        upward = old_value < threshold <= new_value
        if direction == FloatRangeWatcher.FRW_BELOW:
            return downward
        if direction == FloatRangeWatcher.FRW_ABOVE:
            return upward
        # FRW_BOTH (and any unknown direction defaults to firing on either).
        return downward or upward

    def _fire(self, pEvent, value: float) -> None:
        """Stamp the value onto pEvent and broadcast it to its destination."""
        pEvent.SetFloat(value)
        mgr = self._resolve_manager()
        if mgr is not None:
            mgr.AddEvent(pEvent)

    def _resolve_manager(self):
        if self._event_manager is not None:
            return self._event_manager
        # Lazily fall back to the global event manager; imported here to avoid
        # an import cycle (App imports this module).
        try:
            import App
            return App.g_kEventManager
        except Exception:
            return None
