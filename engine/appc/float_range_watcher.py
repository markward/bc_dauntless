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
    The SDK conditions only pass these constants opaquely, and ``_crossed``
    below compares against this same class's own attributes, so the exact
    int values are otherwise an internal choice; they are BC's measured
    ones (q13 dump, CLASS_CONSTANTS["FloatRangeWatcher"] in
    engine/appc/constants_generated.py). ``FRW_NONE`` is not defined here --
    it is auto-added onto App.FloatRangeWatcher by
    engine.appc.constants_apply.apply_constants, since this class never
    defined it itself and nothing here consumes it.
    """

    FRW_BELOW: int = 2
    FRW_ABOVE: int = 1
    FRW_BOTH: int = 3

    # The object whose ``_watch_checks`` follows this watcher's check count
    # (a PulseWeapon: the native charging kernel runs ``_update``'s Python
    # only for a watcher with checks). None: nobody. A class default, so an
    # unowned watcher's instance dict is unchanged.
    _owner = None

    def __init__(self, initial_value: float = 0.0, event_manager=None,
                 owner=None) -> None:
        if owner is not None:
            self._owner = owner
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
        if self._owner is not None:
            self._owner._watch_checks = len(self._checks)
        return check_id

    def RemoveRangeCheck(self, check_id: int) -> None:
        """Stop firing the check with the given id (no-op if already gone)."""
        self._checks.pop(check_id, None)
        if self._owner is not None:
            self._owner._watch_checks = len(self._checks)

    def GetWatchedVariable(self) -> float:
        """Return the latest watched value."""
        return self._value

    def _update(self, new_value: float) -> None:
        """Push a new value; fire any check whose threshold was crossed.

        Crossing is evaluated against the *previous* value, so a check only
        fires on the tick the boundary is actually traversed — not while the
        value lingers on one side.

        A weapon's charge watcher (one with an owner: only a weapon is ever
        one) inside the combat effect queue's scope commits the value at
        once and queues WATCH(self, old, new); delivery runs _fire_crossed
        against the checks registered then (engine/appc/effect_queue.py,
        spec 2026-11-02-combat-fire-events §4.2, ruling E3). Every other
        watcher -- shields, condition, batteries -- fires here, as before.
        """
        new_value = float(new_value)
        if not self._checks:
            self._value = new_value
            return
        old_value = self._value
        if self._owner is not None:
            from engine.appc import effect_queue
            if effect_queue.deferring():
                self._value = new_value
                effect_queue.post(effect_queue.WATCH, self, old_value,
                                  new_value)
                return
        self._fire_crossed(old_value, new_value)
        self._value = new_value

    def _fire_crossed(self, old_value: float, new_value: float) -> None:
        """Fire every check crossed between the two values."""
        # Snapshot so a handler that mutates the check set mid-dispatch can't
        # corrupt iteration.
        for threshold, direction, pEvent in list(self._checks.values()):
            if self._crossed(old_value, new_value, threshold, direction):
                self._fire(pEvent, new_value)

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
