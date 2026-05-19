# BuilderAI Activation + ConditionScript Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `BuilderAI` actually construct AI trees from its captured dependency graph, and make `ConditionScript_Create` actually instantiate the SDK condition class so events drive `SetStatus`. Two specific conditions (`ConditionExists`, `ConditionInRange`) are pinned end-to-end with regression tests; the remaining 28 SDK conditions try-eager-fallback-lazy. Integration smoke loads `CallDamageAI` and confirms its 53-block tree builds cleanly.

**Architecture:** Eager first-tick BuilderAI activation via topological sort + module-function dispatch in [engine/appc/ai_driver.py](../../../engine/appc/ai_driver.py); `ConditionScript.__init__` does `cls(self, *args)` with try/except fallback in [engine/appc/ai.py](../../../engine/appc/ai.py); the SDK conditions wire their own event handlers, so this slice adds the engine primitives they need: `ObjectGroup.GetActiveObjectTuple` + single-arg `SetEventFlag`, `TGEventManager.AddBroadcastPythonMethodHandler`, `TGPythonInstanceWrapper`, event-type constants, and a per-tick `ProximityCheck` evaluator that fires boundary-crossing events.

**Tech Stack:** Python 3, pytest, the existing event-manager (`engine/appc/events.py`'s `TGEventHandlerObject` + `TGEventManager.AddBroadcastPythonFuncHandler` as templates), real SDK `Conditions/*.py` modules loaded via `_SDKFinder` in [tests/conftest.py](../../../tests/conftest.py).

**Spec:** [docs/superpowers/specs/2026-05-18-builder-ai-conditions-design.md](../specs/2026-05-18-builder-ai-conditions-design.md) — read first; non-goals and risks are authoritative.

---

## File Structure

| File | Responsibility |
|---|---|
| [`engine/appc/events.py`](../../../engine/appc/events.py) (modify) | Add `TGPythonInstanceWrapper` + `TGEventManager.AddBroadcastPythonMethodHandler` (instance-method dispatch, mirrors existing `AddBroadcastPythonFuncHandler`). New event-type constants. Mission-swap clearing hook. |
| [`engine/appc/objects.py`](../../../engine/appc/objects.py) (modify) | `ObjectGroup` gains `GetActiveObjectTuple()` (no-arg, walks `g_kSetManager._sets`) and single-arg `SetEventFlag(flag)` (group-level). |
| [`engine/appc/planet.py`](../../../engine/appc/planet.py) (modify) | `ProximityCheck` gets a per-tick `Evaluate(pSet)` that compares each watched object's distance against `_proximity_radius` and fires `_event_type` events when transitions occur (inside ↔ outside). `ProximityManager.GetNearObjects(point, radius)` filters by real distance. |
| [`engine/core/loop.py`](../../../engine/core/loop.py) (modify) | One added call between `tick_all_ai` and `tick_all_ship_motion`: `evaluate_proximity_checks()` walks every active set's checks and fires transition events. |
| [`engine/appc/ai.py`](../../../engine/appc/ai.py) (modify) | `BuilderAI` gains `_activated`, `_activation_failed`, `_activation_error` fields. `ConditionScript.__init__` does eager `cls(self, *args)` with try/except + records `_init_error`. Helper `_import_dotted(path)`. |
| [`engine/appc/ai_driver.py`](../../../engine/appc/ai_driver.py) (modify) | `_tick_builder(ai, game_time)` branch dispatched before `_tick_preprocessing`. Topological sort + module-function lookup on first tick; delegates to standard preprocessing thereafter. |
| [`engine/host_loop.py`](../../../engine/host_loop.py) (modify) | One line in `reset_sdk_globals()` (or its equivalent): clear `App.g_kEventManager._broadcast_handlers` so stale handlers from a prior mission don't fire. |
| `tests/unit/test_event_manager_method_handler.py` (new) | Broadcast method-handler dispatch + target filtering. ~5 tests. |
| `tests/unit/test_object_group_active.py` (new) | `GetActiveObjectTuple` walks all sets; single-arg `SetEventFlag`. ~5 tests. |
| `tests/unit/test_proximity_manager_distance.py` (new) | Real-distance filter in `GetNearObjects`. ~4 tests. |
| `tests/unit/test_proximity_check_evaluator.py` (new) | Per-tick `Evaluate` fires transition events when objects cross the boundary. ~5 tests. |
| `tests/unit/test_builder_ai_activation.py` (new) | Synthetic 3-block graph builds; idempotent; failure modes. ~10 tests. |
| `tests/unit/test_condition_script_instantiate.py` (new) | Real class instantiated; fallback paths; SetStatus drives ConditionalAI. ~6 tests. |
| `tests/unit/test_condition_exists.py` (new) | End-to-end: object exists → 1, deleted → 0, enters later → 1, SetTarget swaps watched object. ~4 tests. |
| `tests/unit/test_condition_in_range.py` (new) | End-to-end: within fDistance → 1, out → 0, missing → 0, SetTarget swaps. ~4 tests. |
| `tests/integration/test_builder_ai_call_damage_smoke.py` (new) | Load `AI.Compound.CallDamageAI`, run one tick, assert activation succeeded and `_contained_ai` is non-None. 2 tests. |
| [`docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md`](../deferred/2026-05-18-ship-ai-runtime.md) (modify) | Strike Step 6 ConditionScript items closed by this slice; note Slice B–E forward refs. |

---

## Task 1: Event-manager method handler + `TGPythonInstanceWrapper`

The SDK condition classes use `TGPythonInstanceWrapper` to bridge between the event manager (which only knows about `TGEventHandlerObject` destinations) and per-instance method dispatch. They also use `AddBroadcastPythonMethodHandler`, which is the method-based sibling of the existing `AddBroadcastPythonFuncHandler`.

**Files:**
- Modify: [`engine/appc/events.py`](../../../engine/appc/events.py)
- Test: `tests/unit/test_event_manager_method_handler.py` (new)

- [ ] **Step 1.1: Write the failing test**

Create `tests/unit/test_event_manager_method_handler.py`:

```python
"""Unit tests for TGEventManager.AddBroadcastPythonMethodHandler +
TGPythonInstanceWrapper — instance-method dispatch from the event bus.

The SDK conditions (Conditions/Condition*.py) use this pattern:
    self.pEventHandler = App.TGPythonInstanceWrapper()
    self.pEventHandler.SetPyWrapper(self)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_DELETE_OBJECT_PUBLIC, self.pEventHandler, "Deleted", target_obj)
The wrapper holds the Python instance; the event manager dispatches
`getattr(instance, "Deleted")(evt)` when matching events fire.
"""
import App
from engine.appc.events import (
    TGEvent, TGEvent_Create, TGEventManager, TGPythonInstanceWrapper,
)


def _fresh_manager():
    return TGEventManager()


def test_method_handler_dispatches_named_method_on_wrapper():
    class Spy:
        def __init__(self):
            self.calls = []
        def Hit(self, evt):
            self.calls.append(evt.GetEventType())

    spy = Spy()
    wrapper = TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(spy)

    mgr = _fresh_manager()
    mgr.AddBroadcastPythonMethodHandler(42, wrapper, "Hit")

    evt = TGEvent_Create()
    evt.SetEventType(42)
    mgr.AddEvent(evt)

    assert spy.calls == [42]


def test_method_handler_filters_by_target():
    """When a target object is passed, the handler fires ONLY for events
    whose destination matches that target. None target → matches all."""
    fired_with = []

    class Spy:
        def Hit(self, evt):
            fired_with.append(evt.GetDestination())

    spy = Spy()
    wrapper = TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(spy)

    target_obj = object()  # arbitrary identity-comparable target
    other_obj = object()

    mgr = _fresh_manager()
    mgr.AddBroadcastPythonMethodHandler(7, wrapper, "Hit", target_obj)

    e_match = TGEvent_Create(); e_match.SetEventType(7)
    e_match.SetDestination(target_obj)
    mgr.AddEvent(e_match)

    e_other = TGEvent_Create(); e_other.SetEventType(7)
    e_other.SetDestination(other_obj)
    mgr.AddEvent(e_other)

    assert fired_with == [target_obj]


def test_method_handler_no_target_matches_all():
    fired = []

    class Spy:
        def Hit(self, evt):
            fired.append(1)

    spy = Spy()
    wrapper = TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(spy)

    mgr = _fresh_manager()
    mgr.AddBroadcastPythonMethodHandler(5, wrapper, "Hit")  # no target

    e1 = TGEvent_Create(); e1.SetEventType(5); e1.SetDestination(object())
    mgr.AddEvent(e1)
    e2 = TGEvent_Create(); e2.SetEventType(5)  # no destination
    mgr.AddEvent(e2)

    assert len(fired) == 2


def test_remove_broadcast_handler_unregisters():
    fired = []

    class Spy:
        def Hit(self, evt):
            fired.append(1)

    spy = Spy()
    wrapper = TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(spy)

    mgr = _fresh_manager()
    mgr.AddBroadcastPythonMethodHandler(9, wrapper, "Hit")
    mgr.RemoveBroadcastHandler(9, wrapper, "Hit")

    evt = TGEvent_Create(); evt.SetEventType(9)
    mgr.AddEvent(evt)

    assert fired == []


def test_unrelated_event_does_not_fire():
    fired = []

    class Spy:
        def Hit(self, evt):
            fired.append(1)

    spy = Spy()
    wrapper = TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(spy)

    mgr = _fresh_manager()
    mgr.AddBroadcastPythonMethodHandler(1, wrapper, "Hit")

    evt = TGEvent_Create(); evt.SetEventType(2)  # different type
    mgr.AddEvent(evt)

    assert fired == []
```

- [ ] **Step 1.2: Run to verify it fails**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_event_manager_method_handler.py -v`

Expected: 5 FAILs with `ImportError: cannot import name 'TGPythonInstanceWrapper'` (or similar — the wrapper class doesn't exist yet).

- [ ] **Step 1.3: Implement `TGPythonInstanceWrapper`**

In [`engine/appc/events.py`](../../../engine/appc/events.py), add after the existing `TGEventHandlerObject` class (around line 150):

```python
class TGPythonInstanceWrapper(TGEventHandlerObject):
    """Bridge between TGEventHandlerObject (the event-manager's destination
    type) and a Python instance's named methods. SDK conditions use this to
    receive events at a wrapper and dispatch to a method on the wrapped
    Python instance.

    Pattern (from sdk/.../Conditions/ConditionExists.py):
        self.pEventHandler = App.TGPythonInstanceWrapper()
        self.pEventHandler.SetPyWrapper(self)
        App.g_kEventManager.AddBroadcastPythonMethodHandler(
            App.ET_DELETE_OBJECT_PUBLIC, self.pEventHandler, "Deleted", obj)
    """
    def __init__(self):
        super().__init__()
        self._py_wrapper = None

    def SetPyWrapper(self, instance) -> None:
        self._py_wrapper = instance

    def GetPyWrapper(self):
        return self._py_wrapper

    def AddPythonMethodHandlerForInstance(self, event_type: int, method_name: str) -> None:
        """Register a self-targeted method handler. Used by SDK conditions
        that listen for events sent directly to the wrapper (e.g. timer
        events) rather than broadcast across the bus."""
        existing = getattr(self, "_method_handlers", None)
        if existing is None:
            self._method_handlers = {}
            existing = self._method_handlers
        existing.setdefault(event_type, []).append(method_name)

    def ProcessEvent(self, event):
        """Dispatch a direct-to-wrapper event to the registered method on
        the wrapped Python instance. Overrides the parent's qualified-
        function dispatch since this wrapper uses instance methods."""
        handlers = getattr(self, "_method_handlers", {})
        names = handlers.get(event.GetEventType(), [])
        py = self._py_wrapper
        if py is None:
            return
        for name in names:
            fn = getattr(py, name, None)
            if fn is not None:
                fn(event)
```

- [ ] **Step 1.4: Implement `AddBroadcastPythonMethodHandler`**

In the same file, inside the `TGEventManager` class, add (after the existing `RemoveBroadcastHandlerForInstance = RemoveBroadcastHandler` line):

```python
    def AddBroadcastPythonMethodHandler(
        self, event_type: int, wrapper: "TGPythonInstanceWrapper",
        method_name: str, target=None,
    ) -> None:
        """Method-based broadcast handler. Mirrors AddBroadcastPythonFuncHandler
        but dispatches `getattr(wrapper.GetPyWrapper(), method_name)(evt)`
        instead of a module-qualified function. `target` (if given) restricts
        dispatch to events whose destination matches `target` by identity;
        None matches all events of `event_type`."""
        method_handlers = getattr(self, "_method_handlers", None)
        if method_handlers is None:
            self._method_handlers = {}
            method_handlers = self._method_handlers
        method_handlers.setdefault(event_type, []).append((wrapper, method_name, target))
```

Update `RemoveBroadcastHandler` (which is aliased to `RemoveBroadcastHandlerForInstance`) to also handle method registrations. Replace the existing method:

```python
    def RemoveBroadcastHandler(
        self, event_type: int, dest_or_wrapper, qualified_name_or_method: str,
        target=None,
    ) -> None:
        """Remove a previously-added broadcast handler.

        Supports both `(eType, dest, qualified_name)` (func handler, legacy)
        and `(eType, wrapper, method_name[, target])` (method handler, new).
        Falls through to the func-handler list first; if not found there,
        tries the method-handler list."""
        # Func handlers: (dest, qualified_name) tuples.
        func_handlers = self._broadcast_handlers.get(event_type, [])
        entry = (dest_or_wrapper, qualified_name_or_method)
        if entry in func_handlers:
            func_handlers.remove(entry)
            return
        # Method handlers: (wrapper, method_name, target) tuples.
        method_handlers = getattr(self, "_method_handlers", {}).get(event_type, [])
        entry_m = (dest_or_wrapper, qualified_name_or_method, target)
        if entry_m in method_handlers:
            method_handlers.remove(entry_m)

    RemoveBroadcastHandlerForInstance = RemoveBroadcastHandler
```

And update `AddEvent` to also dispatch method handlers:

```python
    def AddEvent(self, event: TGEvent) -> None:
        dest = event.GetDestination()
        if dest is not None:
            dest.ProcessEvent(event)
        # Func-broadcast handlers (existing).
        for bd, name in self._broadcast_handlers.get(event.GetEventType(), []):
            fn = _resolve_handler(name)
            if fn is not None:
                fn(bd, event)
        # Method-broadcast handlers (new).
        for wrapper, method_name, target in getattr(self, "_method_handlers", {}).get(
            event.GetEventType(), []
        ):
            if target is not None and event.GetDestination() is not target:
                continue
            py = wrapper.GetPyWrapper()
            if py is not None:
                method = getattr(py, method_name, None)
                if method is not None:
                    method(event)
```

- [ ] **Step 1.5: Run the tests; expect all 5 to pass**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_event_manager_method_handler.py -v`

Expected: 5 PASS.

If `test_method_handler_filters_by_target` fails because the existing `TGEvent` doesn't have `SetDestination`, check [engine/appc/events.py:11-37](../../../engine/appc/events.py#L11-L37) — the `TGEvent` class should already have `SetDestination` and `GetDestination` from prior slices. If it doesn't, add them with the obvious implementation (instance field).

- [ ] **Step 1.6: Run the full event-manager test set to confirm no regressions**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_appc_events.py tests/unit/test_event_manager_method_handler.py -q`

Expected: green (existing tests + 5 new = full event-manager set passes).

- [ ] **Step 1.7: Commit**

```bash
git add engine/appc/events.py tests/unit/test_event_manager_method_handler.py
git commit -m "feat(events): TGPythonInstanceWrapper + AddBroadcastPythonMethodHandler"
```

---

## Task 2: Event-type constants for conditions + mission-swap handler clearing

The SDK conditions reference `App.ET_DELETE_OBJECT_PUBLIC`, `App.ET_OBJECT_GROUP_OBJECT_ENTERED_SET`, `App.ET_OBJECT_GROUP_OBJECT_EXITED_SET`, and `App.ET_CONDITION_ATK_FORGIVE`. `ET_WEAPON_HIT` already exists.

**Files:**
- Modify: [`App.py`](../../../App.py)
- Modify: [`engine/host_loop.py`](../../../engine/host_loop.py)
- Test: extend `tests/unit/test_event_manager_method_handler.py`

- [ ] **Step 2.1: Find the existing event-type constants block in App.py**

Run: `grep -n "^ET_\|# ── Event-type constants" /Users/mward/Documents/Projects/bc_dauntless/App.py | head -10`

Locate the constants block (around line 372 in the current `App.py`). Confirm what's there — `ET_AI_TIMER`, `ET_ACTION_COMPLETED`, `ET_MISSION_START`, etc. — and pick the next unused integer values.

- [ ] **Step 2.2: Add the four new constants**

In [`App.py`](../../../App.py), inside the existing event-type constants block, add:

```python
# Used by Conditions/Condition*.py — broadcast events the SDK conditions
# subscribe to. Values arbitrary but stable; keep contiguous with the
# existing ET_* block so future grep finds them all in one place.
ET_DELETE_OBJECT_PUBLIC = 200
ET_OBJECT_GROUP_OBJECT_ENTERED_SET = 201
ET_OBJECT_GROUP_OBJECT_EXITED_SET = 202
ET_CONDITION_ATK_FORGIVE = 203
```

(If 200-203 are already taken by an existing block, pick the next free range.)

- [ ] **Step 2.3: Find the mission-swap reset path**

Run: `grep -n "def reset_sdk_globals\|reset_sdk_globals" engine/host_loop.py engine/core/*.py 2>&1 | head -5`

Locate the function. It's called during `HostController._drain_pending_swap` between teardown and the next mission's load.

- [ ] **Step 2.4: Write a failing test for handler-clearing on mission swap**

Append to `tests/unit/test_event_manager_method_handler.py`:

```python
def test_reset_clears_broadcast_handlers():
    """After reset_sdk_globals (called on mission swap), broadcast handlers
    from the prior mission must NOT fire. Conditions register handlers on
    g_kEventManager during mission init; without clearing, stale handlers
    leak across missions and fire against wrong objects."""
    import App
    from engine.host_loop import reset_sdk_globals

    fired = []

    class Spy:
        def Hit(self, evt):
            fired.append(1)

    spy = Spy()
    wrapper = TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(spy)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(50, wrapper, "Hit")

    reset_sdk_globals()

    evt = TGEvent_Create(); evt.SetEventType(50)
    App.g_kEventManager.AddEvent(evt)

    assert fired == [], "stale handler from prior mission fired after reset"
```

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_event_manager_method_handler.py::test_reset_clears_broadcast_handlers -v`
Expected: FAIL — handler still registered.

- [ ] **Step 2.5: Hook handler-clearing into `reset_sdk_globals`**

In [`engine/host_loop.py`](../../../engine/host_loop.py) (or wherever `reset_sdk_globals` is defined), add inside the function body:

```python
    # Clear the event manager's handler tables so stale handlers from the
    # prior mission don't fire against the new mission's state. SDK
    # conditions register handlers on g_kEventManager during mission init.
    App.g_kEventManager._broadcast_handlers.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()
```

- [ ] **Step 2.6: Run; expect pass**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_event_manager_method_handler.py -v`
Expected: 6 PASS (5 from Task 1 + 1 new).

- [ ] **Step 2.7: Commit**

```bash
git add App.py engine/host_loop.py tests/unit/test_event_manager_method_handler.py
git commit -m "feat(events): event-type constants for conditions + mission-swap handler clearing"
```

---

## Task 3: ObjectGroup `GetActiveObjectTuple` + single-arg `SetEventFlag`

`ObjectGroup` already has `GetActiveObjectTupleInSet(pSet)` and `SetEventFlag(name, flag)` (two-arg). The SDK conditions call the no-arg and single-arg variants.

**Files:**
- Modify: [`engine/appc/objects.py`](../../../engine/appc/objects.py)
- Test: `tests/unit/test_object_group_active.py` (new)

- [ ] **Step 3.1: Write the failing tests**

Create `tests/unit/test_object_group_active.py`:

```python
"""Unit tests for ObjectGroup.GetActiveObjectTuple (no-arg, walks all sets)
and single-arg ObjectGroup.SetEventFlag (group-level flag)."""
import App
from engine.appc.objects import ObjectGroup
from engine.appc.ships import ShipClass


def _fresh_set_manager():
    App.g_kSetManager._sets.clear()


def test_get_active_object_tuple_empty_when_no_sets():
    _fresh_set_manager()
    g = ObjectGroup()
    g.AddName("anything")
    assert g.GetActiveObjectTuple() == ()


def test_get_active_object_tuple_finds_named_object_in_a_set():
    _fresh_set_manager()
    pSet = App.SetClass_Create()
    pSet.SetName("X")
    ship = ShipClass()
    pSet.AddObjectToSet(ship, "Bart")
    App.g_kSetManager._sets["X"] = pSet

    g = ObjectGroup()
    g.AddName("Bart")
    result = g.GetActiveObjectTuple()
    assert len(result) == 1
    assert result[0] is ship


def test_get_active_object_tuple_walks_multiple_sets():
    _fresh_set_manager()
    s1 = App.SetClass_Create(); s1.SetName("S1")
    s2 = App.SetClass_Create(); s2.SetName("S2")
    ship_a = ShipClass(); s1.AddObjectToSet(ship_a, "A")
    ship_b = ShipClass(); s2.AddObjectToSet(ship_b, "B")
    App.g_kSetManager._sets.update({"S1": s1, "S2": s2})

    g = ObjectGroup()
    g.AddName("A"); g.AddName("B")
    result = g.GetActiveObjectTuple()
    assert set(result) == {ship_a, ship_b}


def test_get_active_object_tuple_skips_missing_names():
    _fresh_set_manager()
    pSet = App.SetClass_Create(); pSet.SetName("X")
    ship = ShipClass(); pSet.AddObjectToSet(ship, "Bart")
    App.g_kSetManager._sets["X"] = pSet

    g = ObjectGroup()
    g.AddName("Bart"); g.AddName("Lisa")  # Lisa doesn't exist
    result = g.GetActiveObjectTuple()
    assert result == (ship,)


def test_set_event_flag_single_arg_marks_all_names():
    """Single-arg form sets the flag at the GROUP level — applies to all
    watched names. SDK conditions use this pattern."""
    g = ObjectGroup()
    g.AddName("A"); g.AddName("B")
    g.SetEventFlag(ObjectGroup.ENTERED_SET)
    # Both names should see the flag set.
    assert g.IsEventFlagSet("A", ObjectGroup.ENTERED_SET) == 1
    assert g.IsEventFlagSet("B", ObjectGroup.ENTERED_SET) == 1
```

- [ ] **Step 3.2: Run to verify it fails**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_object_group_active.py -v`
Expected: 5 FAILs — `GetActiveObjectTuple` (no-arg) doesn't exist; single-arg `SetEventFlag` raises `TypeError`.

- [ ] **Step 3.3: Add `GetActiveObjectTuple` + dispatch single-arg `SetEventFlag`**

In [`engine/appc/objects.py`](../../../engine/appc/objects.py), inside the `ObjectGroup` class, locate the existing `GetActiveObjectTupleInSet` method (around line 398). Right after it, add:

```python
    def GetActiveObjectTuple(self) -> tuple:
        """No-arg variant: walk every live set in g_kSetManager looking for
        any object whose name matches one of our watched names. SDK
        conditions use this when they don't know which set their target
        lives in yet."""
        import App
        result = []
        for pSet in App.g_kSetManager._sets.values():
            for name in self._names:
                obj = pSet.GetObject(name) if hasattr(pSet, "GetObject") else None
                if obj is not None and obj not in result:
                    result.append(obj)
        return tuple(result)
```

Then modify the existing `SetEventFlag(self, name, flag)` (around line 415) to also accept a single-arg form:

```python
    def SetEventFlag(self, *args) -> None:
        """Two forms:
            SetEventFlag(name, flag)  → per-name flag (legacy callers)
            SetEventFlag(flag)        → group-level: apply to all watched names
        SDK conditions use the single-arg form to mark "I want enter/exit
        events for everything in my group."
        """
        if len(args) == 1:
            flag = int(args[0])
            for name in self._names:
                self._event_flags.setdefault(name, set()).add(flag)
        elif len(args) == 2:
            name, flag = args
            self._event_flags.setdefault(name, set()).add(int(flag))
```

- [ ] **Step 3.4: Run; expect pass**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_object_group_active.py -v`
Expected: 5 PASS.

- [ ] **Step 3.5: Regression sweep — confirm two-arg callers still work**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit -q -k "object_group or appc_objects"`
Expected: green. The two-arg form is still supported via the `len(args) == 2` branch.

- [ ] **Step 3.6: Commit**

```bash
git add engine/appc/objects.py tests/unit/test_object_group_active.py
git commit -m "feat(objects): ObjectGroup.GetActiveObjectTuple + single-arg SetEventFlag"
```

---

## Task 4: ProximityManager real distance filter + per-tick ProximityCheck evaluator

`ProximityManager.GetNearObjects` currently returns the full `_objects` tuple (no distance filtering). `ProximityCheck` records watch-list configuration but never evaluates per-tick. `ConditionInRange` will need both.

**Files:**
- Modify: [`engine/appc/planet.py`](../../../engine/appc/planet.py)
- Modify: [`engine/core/loop.py`](../../../engine/core/loop.py)
- Test: `tests/unit/test_proximity_manager_distance.py` (new)
- Test: `tests/unit/test_proximity_check_evaluator.py` (new)

- [ ] **Step 4.1: Write failing tests for the distance filter**

Create `tests/unit/test_proximity_manager_distance.py`:

```python
"""Unit tests for ProximityManager.GetNearObjects — real-distance filter."""
import pytest

import App
from engine.appc.math import TGPoint3
from engine.appc.planet import ProximityManager
from engine.appc.ships import ShipClass


def _make_ship_at(x, y, z):
    s = ShipClass()
    s.SetTranslateXYZ(x, y, z)
    return s


def test_get_near_objects_returns_empty_when_manager_is_empty():
    pm = ProximityManager()
    assert pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0) == ()


def test_get_near_objects_includes_within_radius():
    pm = ProximityManager()
    s_close = _make_ship_at(10.0, 0.0, 0.0)
    s_far = _make_ship_at(500.0, 0.0, 0.0)
    pm.AddObject(s_close); pm.AddObject(s_far)
    result = pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0)
    assert s_close in result
    assert s_far not in result


def test_get_near_objects_includes_exactly_at_radius():
    pm = ProximityManager()
    s_edge = _make_ship_at(100.0, 0.0, 0.0)
    pm.AddObject(s_edge)
    result = pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0)
    assert s_edge in result


def test_get_near_objects_diagonal_distance():
    """Pythagorean — make sure we're using sqrt(x²+y²+z²) not max-norm."""
    pm = ProximityManager()
    # distance = sqrt(60² + 80²) = 100
    s = _make_ship_at(60.0, 80.0, 0.0)
    pm.AddObject(s)
    assert s in pm.GetNearObjects(TGPoint3(0, 0, 0), 100.0)
    assert s not in pm.GetNearObjects(TGPoint3(0, 0, 0), 99.0)
```

- [ ] **Step 4.2: Run; expect fails**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_proximity_manager_distance.py -v`
Expected: 3 FAILs (the empty-manager test may pass trivially since it already returns `()`).

- [ ] **Step 4.3: Implement the distance filter**

In [`engine/appc/planet.py`](../../../engine/appc/planet.py), replace the existing `GetNearObjects` (around line 212-215):

```python
    def GetNearObjects(self, point, radius) -> tuple:
        """Return objects within `radius` world-space units of `point`.
        Used by SDK conditions (ConditionInRange) to gate on proximity."""
        r2 = float(radius) * float(radius)
        result = []
        for obj in self._objects:
            loc = obj.GetWorldLocation() if hasattr(obj, "GetWorldLocation") else None
            if loc is None:
                continue
            dx = loc.x - point.x
            dy = loc.y - point.y
            dz = loc.z - point.z
            if dx * dx + dy * dy + dz * dz <= r2:
                result.append(obj)
        return tuple(result)
```

- [ ] **Step 4.4: Run; expect pass**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_proximity_manager_distance.py -v`
Expected: 4 PASS.

- [ ] **Step 4.5: Write failing tests for the ProximityCheck per-tick evaluator**

Create `tests/unit/test_proximity_check_evaluator.py`:

```python
"""Unit tests for ProximityCheck per-tick evaluation.

The SDK conditions (ConditionInRange) create a ProximityCheck via
App.ProximityCheck_Create(eEventType), add watched objects with
AddObjectToCheckList, and rely on the engine to fire `eEventType` events
when objects cross the radius boundary. This per-tick evaluator runs from
GameLoop.tick between tick_all_ai and tick_all_ship_motion.
"""
import App
from engine.appc.events import TGEvent_Create, TGEventManager
from engine.appc.planet import ProximityCheck
from engine.appc.ships import ShipClass


def test_evaluate_fires_event_when_object_enters_radius():
    """Watched object initially outside radius. After moving it inside
    and calling Evaluate, an event of the configured type is emitted to
    the watched object's destination."""
    pCheck = ProximityCheck(event_type=999)
    pCheck.SetRadius(100.0)

    anchor = ShipClass()
    anchor.SetTranslateXYZ(0.0, 0.0, 0.0)

    target = ShipClass()
    target.SetTranslateXYZ(500.0, 0.0, 0.0)  # outside
    pCheck.AddObjectToCheckList(target, ProximityCheck.TT_INSIDE)

    fired = []
    saved_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: fired.append(evt.GetEventType())
    try:
        # Evaluate before move — no fire (still outside).
        pCheck.Evaluate(anchor)
        # Move inside.
        target.SetTranslateXYZ(50.0, 0.0, 0.0)
        pCheck.Evaluate(anchor)
    finally:
        App.g_kEventManager.AddEvent = saved_add

    assert 999 in fired


def test_evaluate_does_not_re_fire_while_object_stays_inside():
    """Once an object has crossed inside, repeated Evaluate calls while it
    stays inside don't re-fire the event. Only transitions fire."""
    pCheck = ProximityCheck(event_type=999)
    pCheck.SetRadius(100.0)
    anchor = ShipClass(); anchor.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass(); target.SetTranslateXYZ(50.0, 0.0, 0.0)  # inside
    pCheck.AddObjectToCheckList(target, ProximityCheck.TT_INSIDE)

    fired = []
    saved_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: fired.append(1)
    try:
        pCheck.Evaluate(anchor)  # initial transition outside→inside
        pCheck.Evaluate(anchor)  # no transition; should not fire
        pCheck.Evaluate(anchor)  # no transition; should not fire
    finally:
        App.g_kEventManager.AddEvent = saved_add
    assert len(fired) == 1


def test_evaluate_fires_again_on_exit_then_re_enter():
    """Object enters → fire. Exits → no fire (we only watch INSIDE
    transitions here). Re-enters → fire again."""
    pCheck = ProximityCheck(event_type=999)
    pCheck.SetRadius(100.0)
    anchor = ShipClass(); anchor.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass(); target.SetTranslateXYZ(50.0, 0.0, 0.0)
    pCheck.AddObjectToCheckList(target, ProximityCheck.TT_INSIDE)

    fired = []
    saved_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: fired.append(1)
    try:
        pCheck.Evaluate(anchor)             # inside; fire
        target.SetTranslateXYZ(500.0, 0.0, 0.0)
        pCheck.Evaluate(anchor)             # outside; no fire
        target.SetTranslateXYZ(50.0, 0.0, 0.0)
        pCheck.Evaluate(anchor)             # re-entered; fire
    finally:
        App.g_kEventManager.AddEvent = saved_add
    assert len(fired) == 2


def test_evaluate_skips_objects_with_no_location():
    """Defensive: watched object whose GetWorldLocation is missing or
    returns None is silently skipped, not crashed on."""
    pCheck = ProximityCheck(event_type=999)
    pCheck.SetRadius(100.0)
    anchor = ShipClass(); anchor.SetTranslateXYZ(0.0, 0.0, 0.0)

    class Stripped:
        pass

    pCheck.AddObjectToCheckList(Stripped(), ProximityCheck.TT_INSIDE)
    # Must not raise.
    pCheck.Evaluate(anchor)


def test_evaluate_event_destination_is_the_watched_object():
    """The fired event's destination is the watched object so SDK handlers
    that filter by target (ET_DELETE_OBJECT_PUBLIC pattern) match
    correctly."""
    pCheck = ProximityCheck(event_type=999)
    pCheck.SetRadius(100.0)
    anchor = ShipClass(); anchor.SetTranslateXYZ(0.0, 0.0, 0.0)
    target = ShipClass(); target.SetTranslateXYZ(50.0, 0.0, 0.0)
    pCheck.AddObjectToCheckList(target, ProximityCheck.TT_INSIDE)

    captured = []
    saved_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda evt: captured.append(evt.GetDestination())
    try:
        pCheck.Evaluate(anchor)
    finally:
        App.g_kEventManager.AddEvent = saved_add
    assert captured == [target]
```

- [ ] **Step 4.6: Run; expect fails**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_proximity_check_evaluator.py -v`
Expected: 5 FAILs — `Evaluate` method doesn't exist on `ProximityCheck`.

- [ ] **Step 4.7: Implement `ProximityCheck.Evaluate`**

In [`engine/appc/objects.py`](../../../engine/appc/objects.py) (or wherever `ProximityCheck` lives — grep `class ProximityCheck` to confirm; per the codebase it's in `engine/appc/ai.py:546-633` based on earlier reads), inside the `ProximityCheck` class, add after the existing `Remove*` methods (~line 627):

```python
    def Evaluate(self, anchor_obj) -> None:
        """Per-tick: for each watched object, test whether it's inside
        the proximity radius around `anchor_obj` and fire the configured
        event type when an inside-transition occurs.

        Called by GameLoop.tick between tick_all_ai and tick_all_ship_motion.
        Only TT_INSIDE transitions fire events in this slice — TT_OUTSIDE
        and group/type-based variants land when the proximity subsystem
        gets full SDK fidelity.
        """
        import App
        from engine.appc.events import TGEvent_Create

        # _inside_set tracks objects currently inside, so we only fire on
        # transitions (not every tick while inside).
        inside_now = getattr(self, "_inside_set", None)
        if inside_now is None:
            self._inside_set = set()
            inside_now = self._inside_set

        anchor_loc = anchor_obj.GetWorldLocation() if hasattr(anchor_obj, "GetWorldLocation") else None
        if anchor_loc is None:
            return
        r2 = self._proximity_radius * self._proximity_radius

        new_inside: set = set()
        for obj, trigger_type in self._check_objects:
            loc = obj.GetWorldLocation() if hasattr(obj, "GetWorldLocation") else None
            if loc is None:
                continue
            dx = loc.x - anchor_loc.x
            dy = loc.y - anchor_loc.y
            dz = loc.z - anchor_loc.z
            is_inside = (dx * dx + dy * dy + dz * dz) <= r2
            if is_inside:
                new_inside.add(id(obj))
                if trigger_type == ProximityCheck.TT_INSIDE and id(obj) not in inside_now:
                    # Outside → inside transition. Fire.
                    evt = TGEvent_Create()
                    evt.SetEventType(self._event_type)
                    evt.SetDestination(obj)
                    App.g_kEventManager.AddEvent(evt)
        self._inside_set = new_inside
```

- [ ] **Step 4.8: Run; expect pass**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_proximity_check_evaluator.py -v`
Expected: 5 PASS.

- [ ] **Step 4.9: Wire per-tick evaluation into GameLoop**

In [`engine/core/loop.py`](../../../engine/core/loop.py), inside `GameLoop.tick`, add a call between `tick_all_ai` and `tick_all_ship_motion`:

```python
        tick_all_ai(game_time=game_time)
        # NEW: per-tick proximity evaluation. SDK conditions like
        # ConditionInRange register ProximityChecks; the per-tick sweep
        # fires events when objects cross the radius boundary.
        from engine.appc.planet import evaluate_proximity_checks
        evaluate_proximity_checks()
        tick_all_ship_motion(TICK_DELTA)
```

Then add the `evaluate_proximity_checks` function to [`engine/appc/planet.py`](../../../engine/appc/planet.py) at module scope (after the `ProximityManager` class):

```python
def evaluate_proximity_checks() -> None:
    """Walk every live ProximityManager and dispatch each ProximityCheck's
    per-tick evaluation. Called from GameLoop.tick between tick_all_ai and
    tick_all_ship_motion so the SDK conditions see fresh transitions
    before the motion integrator advances ships further."""
    import App
    for pSet in App.g_kSetManager._sets.values():
        pm = pSet.GetProximityManager() if hasattr(pSet, "GetProximityManager") else None
        if pm is None:
            continue
        checks = getattr(pm, "_proximity_checks", ())
        for check, anchor in checks:
            check.Evaluate(anchor)
```

And add a way for `ProximityCheck` instances to register themselves with a manager. In [`engine/appc/planet.py`](../../../engine/appc/planet.py)'s `ProximityManager` class, add:

```python
    def AddProximityCheck(self, check, anchor_obj) -> None:
        """Register a ProximityCheck for per-tick evaluation against an
        anchor object (typically the ship that owns the check). The
        anchor's world location is the center of the proximity radius."""
        checks = getattr(self, "_proximity_checks", None)
        if checks is None:
            self._proximity_checks = []
            checks = self._proximity_checks
        entry = (check, anchor_obj)
        if entry not in checks:
            checks.append(entry)
```

- [ ] **Step 4.10: Run the full proximity + loop suite**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_proximity_manager_distance.py tests/unit/test_proximity_check_evaluator.py tests/unit/test_loop.py -q`

Expected: green (4 + 5 + existing loop tests).

- [ ] **Step 4.11: Commit**

```bash
git add engine/appc/planet.py engine/core/loop.py tests/unit/test_proximity_manager_distance.py tests/unit/test_proximity_check_evaluator.py
git commit -m "feat(proximity): real distance filter + per-tick ProximityCheck evaluator"
```

---

## Task 5: BuilderAI activation (synthetic graphs)

The core of the slice. Walk the dependency graph eagerly on the first AI tick, call `BuilderCreateN` functions from the BuilderAI's owning module, and set the last block's result as `_contained_ai`.

**Files:**
- Modify: [`engine/appc/ai.py`](../../../engine/appc/ai.py) — BuilderAI activation fields
- Modify: [`engine/appc/ai_driver.py`](../../../engine/appc/ai_driver.py) — `_tick_builder` branch
- Test: `tests/unit/test_builder_ai_activation.py` (new)

- [ ] **Step 5.1: Write the failing tests**

Create `tests/unit/test_builder_ai_activation.py`:

```python
"""Unit tests for BuilderAI activation — first-tick topological build."""
import sys
import types

import pytest

import App
from engine.appc.ai import BuilderAI_Create, PlainAI_Create, SequenceAI_Create
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass


def _make_module_with_builders(**funcs) -> str:
    """Register a synthetic module containing BuilderCreateN functions.
    Returns the module name so the caller can pass it to BuilderAI_Create."""
    name = f"_test_builder_{id(funcs)}"
    mod = types.ModuleType(name)
    for fn_name, fn in funcs.items():
        setattr(mod, fn_name, fn)
    sys.modules[name] = mod
    return name


def test_synthetic_3block_graph_builds_in_dep_order():
    """Block C depends on A and B. Activation builds A and B first,
    then C(pShip, a_result, b_result). C's result becomes _contained_ai."""
    order = []

    def BuilderCreate1(pShip):
        order.append("A")
        return PlainAI_Create(pShip, "A")

    def BuilderCreate2(pShip):
        order.append("B")
        return PlainAI_Create(pShip, "B")

    def BuilderCreate3(pShip, a_ai, b_ai):
        order.append("C")
        seq = SequenceAI_Create(pShip, "C")
        seq.AddAI(a_ai); seq.AddAI(b_ai)
        return seq

    mod_name = _make_module_with_builders(
        BuilderCreate1=BuilderCreate1,
        BuilderCreate2=BuilderCreate2,
        BuilderCreate3=BuilderCreate3,
    )

    ship = ShipClass()
    builder = BuilderAI_Create(ship, "TestRoot", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")
    builder.AddAIBlock("B", "BuilderCreate2")
    builder.AddAIBlock("C", "BuilderCreate3")
    builder.AddDependency("C", "A")
    builder.AddDependency("C", "B")

    tick_ai(builder, game_time=0.01)

    assert order == ["A", "B", "C"] or order == ["B", "A", "C"]
    assert builder._activated is True
    assert builder._activation_failed is False
    assert builder._contained_ai is not None
    assert builder._contained_ai.GetName() == "C"


def test_activation_idempotent_no_rebuild_on_second_tick():
    """Once activated, subsequent ticks don't re-call builders."""
    calls = []

    def BuilderCreate1(pShip):
        calls.append(1)
        return PlainAI_Create(pShip, "A")

    mod_name = _make_module_with_builders(BuilderCreate1=BuilderCreate1)
    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")

    tick_ai(builder, game_time=0.01)
    tick_ai(builder, game_time=0.5)
    tick_ai(builder, game_time=1.0)

    assert calls == [1]


def test_dep_objects_passed_as_kwargs():
    """AddDependencyObject(block, attr, value) → kwarg attr=value at build."""
    captured = {}

    def BuilderCreate1(pShip, **kwargs):
        captured.update(kwargs)
        return PlainAI_Create(pShip, "A")

    mod_name = _make_module_with_builders(BuilderCreate1=BuilderCreate1)
    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")
    builder.AddDependencyObject("A", "sTarget", "player")
    builder.AddDependencyObject("A", "fDistance", 295.0)

    tick_ai(builder, game_time=0.01)
    assert captured == {"sTarget": "player", "fDistance": 295.0}


def test_dep_results_passed_in_declaration_order():
    """AddDependency calls in order (X→A) then (X→B) → builder receives
    (a_result, b_result) as positional args."""
    received = []

    def BuilderCreate1(pShip):
        return PlainAI_Create(pShip, "A")

    def BuilderCreate2(pShip):
        return PlainAI_Create(pShip, "B")

    def BuilderCreate3(pShip, *deps):
        received.extend(d.GetName() for d in deps)
        return PlainAI_Create(pShip, "C")

    mod_name = _make_module_with_builders(
        BuilderCreate1=BuilderCreate1, BuilderCreate2=BuilderCreate2,
        BuilderCreate3=BuilderCreate3,
    )

    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")
    builder.AddAIBlock("B", "BuilderCreate2")
    builder.AddAIBlock("C", "BuilderCreate3")
    builder.AddDependency("C", "A")
    builder.AddDependency("C", "B")

    tick_ai(builder, game_time=0.01)
    assert received == ["A", "B"]


def test_missing_builder_function_sets_activation_failed():
    mod_name = _make_module_with_builders()  # no functions
    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")

    tick_ai(builder, game_time=0.01)
    assert builder._activation_failed is True
    assert "BuilderCreate1" in builder._activation_error[1]


def test_cyclic_dependency_sets_activation_failed():
    """A depends on B; B depends on A. Topological sort can't resolve."""
    def BuilderCreate1(pShip, b): return PlainAI_Create(pShip, "A")
    def BuilderCreate2(pShip, a): return PlainAI_Create(pShip, "B")

    mod_name = _make_module_with_builders(
        BuilderCreate1=BuilderCreate1, BuilderCreate2=BuilderCreate2,
    )
    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")
    builder.AddAIBlock("B", "BuilderCreate2")
    builder.AddDependency("A", "B")
    builder.AddDependency("B", "A")

    tick_ai(builder, game_time=0.01)
    assert builder._activation_failed is True


def test_builder_raising_sets_activation_failed():
    def BuilderCreate1(pShip):
        raise RuntimeError("boom")

    mod_name = _make_module_with_builders(BuilderCreate1=BuilderCreate1)
    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")

    tick_ai(builder, game_time=0.01)
    assert builder._activation_failed is True
    assert "boom" in builder._activation_error[1]


def test_builder_returning_none_for_last_block_fails_activation():
    def BuilderCreate1(pShip):
        return None

    mod_name = _make_module_with_builders(BuilderCreate1=BuilderCreate1)
    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")

    tick_ai(builder, game_time=0.01)
    assert builder._activation_failed is True


def test_intermediate_none_does_not_fail_activation():
    """A returns None mid-graph. Dependents of A get None as the dep arg
    (it's the builder function's job to handle that). The graph as a
    whole only fails if the LAST block returns None."""
    def BuilderCreate1(pShip):
        return None

    def BuilderCreate2(pShip, a):
        return PlainAI_Create(pShip, "B")

    mod_name = _make_module_with_builders(
        BuilderCreate1=BuilderCreate1, BuilderCreate2=BuilderCreate2,
    )
    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")
    builder.AddAIBlock("B", "BuilderCreate2")
    builder.AddDependency("B", "A")

    tick_ai(builder, game_time=0.01)
    assert builder._activated is True
    assert builder._activation_failed is False
    assert builder._contained_ai.GetName() == "B"


def test_failed_activation_short_circuits_subsequent_ticks():
    """After activation_failed, tick_ai must short-circuit without
    re-invoking the builder."""
    calls = []

    def BuilderCreate1(pShip):
        calls.append(1)
        raise RuntimeError("boom")

    mod_name = _make_module_with_builders(BuilderCreate1=BuilderCreate1)
    builder = BuilderAI_Create(ShipClass(), "R", mod_name)
    builder.AddAIBlock("A", "BuilderCreate1")

    tick_ai(builder, game_time=0.01)
    tick_ai(builder, game_time=0.5)
    assert len(calls) == 1
```

- [ ] **Step 5.2: Run; expect fails**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_builder_ai_activation.py -v`
Expected: 10 FAILs (or mix of fails + errors — `_activated` field doesn't exist yet, `tick_ai` doesn't branch on BuilderAI).

- [ ] **Step 5.3: Add activation fields to `BuilderAI`**

In [`engine/appc/ai.py`](../../../engine/appc/ai.py), inside `BuilderAI.__init__` (around line 504), add after the existing field initializations:

```python
        # Activation state — set by ai_driver._tick_builder on first tick.
        self._activated: bool = False
        self._activation_failed: bool = False
        self._activation_error: tuple[str, str] | None = None  # (exc_type, msg)
```

- [ ] **Step 5.4: Implement `_tick_builder` in the AI driver**

In [`engine/appc/ai_driver.py`](../../../engine/appc/ai_driver.py), add the `BuilderAI` import to the existing import block at the top:

```python
from engine.appc.ai import (
    ArtificialIntelligence, PlainAI, PriorityListAI, SequenceAI,
    ConditionalAI, PreprocessingAI, BuilderAI,
)
```

Then add the `BuilderAI` branch to `tick_ai` (around the existing `if isinstance(ai, PreprocessingAI)` check). Since `BuilderAI` extends `PreprocessingAI`, the BuilderAI check must come FIRST:

```python
def tick_ai(ai, game_time: float) -> int:
    """Tick one AI subtree at the given game time. Returns the resulting status."""
    if ai is None:
        return US_DONE
    if isinstance(ai, BuilderAI):
        return _tick_builder(ai, game_time)
    if isinstance(ai, PreprocessingAI):
        return _tick_preprocessing(ai, game_time)
    # ... rest unchanged
```

Then add the `_tick_builder` function:

```python
def _tick_builder(ai: BuilderAI, game_time: float) -> int:
    """First-tick activation: topologically sort the block graph, call
    BuilderCreateN functions in dependency order, set the last block's
    result as _contained_ai. Subsequent ticks delegate to standard
    PreprocessingAI dispatch."""
    if ai._activation_failed:
        return US_DONE
    if not ai._activated:
        _activate_builder(ai)
        if ai._activation_failed:
            return US_DONE
    return _tick_preprocessing(ai, game_time)


def _activate_builder(ai: BuilderAI) -> None:
    """Kahn's-algorithm topological sort + dependency-injected build."""
    import sys

    try:
        # Build adjacency lists. blocks: {name: (builder_func_name, [dep_names])}.
        block_names = list(ai._blocks.keys())
        builder_funcs = dict(ai._blocks)  # name → func_name (str)

        deps_by_block: dict[str, list[str]] = {n: [] for n in block_names}
        for child, parent in ai._dependencies:
            # ai._dependencies stores (block_name, dep_block_name). The
            # block depends on dep_block_name being built first.
            deps_by_block.setdefault(child, []).append(parent)

        dep_objects_by_block: dict[str, dict] = {n: {} for n in block_names}
        for block, attr, value in ai._dep_objects:
            dep_objects_by_block.setdefault(block, {})[attr] = value

        # Topological sort (Kahn).
        in_degree = {n: len(deps_by_block[n]) for n in block_names}
        queue = [n for n in block_names if in_degree[n] == 0]
        sorted_names: list[str] = []
        while queue:
            n = queue.pop(0)
            sorted_names.append(n)
            for child in block_names:
                if n in deps_by_block.get(child, ()):
                    in_degree[child] -= 1
                    if in_degree[child] == 0:
                        queue.append(child)
        if len(sorted_names) != len(block_names):
            unresolved = [n for n in block_names if n not in sorted_names]
            raise RuntimeError(f"cyclic dependency in BuilderAI: {unresolved}")

        # Resolve the owning module.
        mod = sys.modules.get(ai._module_name)
        if mod is None:
            mod = __import__(ai._module_name)

        # Build each block.
        results: dict[str, object] = {}
        for name in sorted_names:
            func_name = builder_funcs[name]
            fn = getattr(mod, func_name, None)
            if fn is None:
                raise AttributeError(f"module {ai._module_name!r} has no function {func_name!r}")
            dep_args = [results[d] for d in deps_by_block[name]]
            kwargs = dep_objects_by_block.get(name, {})
            results[name] = fn(ai._ship, *dep_args, **kwargs)

        # Last block in topological order becomes the contained AI.
        last = sorted_names[-1] if sorted_names else None
        last_result = results.get(last) if last else None
        if last_result is None:
            raise RuntimeError(f"BuilderAI root block {last!r} returned None")
        ai._contained_ai = last_result
        ai._activated = True
    except Exception as e:
        ai._activation_failed = True
        ai._activation_error = (type(e).__name__, str(e))
        ai._status = US_DONE
```

- [ ] **Step 5.5: Run; expect pass**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_builder_ai_activation.py -v`
Expected: 10 PASS.

If `test_synthetic_3block_graph_builds_in_dep_order` fails because `BuilderAI._blocks` is a dict mapping name → AI (not name → str), check the current `BuilderAI.AddAIBlock` signature in [engine/appc/ai.py:514](../../../engine/appc/ai.py#L514). The SDK pattern is `AddAIBlock(name, func_name_string)`. If our implementation stores `name → ai_instance`, refactor it now so the test fixture's `_make_module_with_builders` approach works. The plan code above assumes `_blocks` is `{name: func_name_str}`.

If a refactor is needed, also update `AddAIBlock`'s docstring + any caller in tests.

- [ ] **Step 5.6: Regression sweep**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_ai_driver.py tests/unit/test_ai_primitives.py -q`
Expected: green. The `BuilderAI` isinstance branch lands BEFORE `PreprocessingAI`, so existing PreprocessingAI tests should continue to work.

- [ ] **Step 5.7: Commit**

```bash
git add engine/appc/ai.py engine/appc/ai_driver.py tests/unit/test_builder_ai_activation.py
git commit -m "feat(ai): BuilderAI first-tick activation via topological sort + module dispatch"
```

---

## Task 6: ConditionScript eager instantiation + fallback

`ConditionScript_Create` currently stores `(module_name, class_name, args)` but never imports the module or constructs the class. After this task, the SDK class is instantiated eagerly with try/except fallback.

**Files:**
- Modify: [`engine/appc/ai.py`](../../../engine/appc/ai.py)
- Test: `tests/unit/test_condition_script_instantiate.py` (new)

- [ ] **Step 6.1: Write the failing tests**

Create `tests/unit/test_condition_script_instantiate.py`:

```python
"""Unit tests for ConditionScript eager instantiation + fallback."""
import sys
import types

import pytest

import App
from engine.appc.ai import (
    ConditionScript, ConditionScript_Create, ConditionalAI_Create,
)


def _install_synthetic_condition(name: str, *, raise_in_init=False):
    """Register a synthetic Conditions/<name>.py module with a class
    named <name> that stores its args. Returns the qualified module name."""
    mod_name = f"Conditions.{name}"
    mod = types.ModuleType(mod_name)
    captured = {"args": None, "init_count": 0}

    class _Synthetic:
        def __init__(self, pCodeCondition, *args):
            captured["args"] = args
            captured["init_count"] += 1
            if raise_in_init:
                raise RuntimeError("synthetic-failure")
            self.pCodeCondition = pCodeCondition

    _Synthetic.__name__ = name
    setattr(mod, name, _Synthetic)
    sys.modules[mod_name] = mod
    # Also register the parent package so __import__ walks it.
    pkg_name = "Conditions"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = []  # mark as package
        sys.modules[pkg_name] = pkg
    setattr(sys.modules[pkg_name], name, mod)
    return mod_name, captured


def test_create_instantiates_real_class():
    mod_name, captured = _install_synthetic_condition("SynthCond1")
    cs = ConditionScript_Create(mod_name, "SynthCond1", 1.0, "x")
    assert cs._instance is not None
    assert captured["args"] == (1.0, "x")
    assert captured["init_count"] == 1


def test_create_falls_back_to_none_on_missing_module():
    cs = ConditionScript_Create("Conditions.DoesNotExist", "DoesNotExist", 0)
    assert cs._instance is None
    assert cs._init_error is not None
    # Error captured for introspection.
    assert "DoesNotExist" in cs._init_error[1] or cs._init_error[0] in (
        "ImportError", "ModuleNotFoundError", "AttributeError",
    )


def test_create_falls_back_on_missing_class_within_module():
    """Module exists but doesn't have the named class."""
    mod_name = "Conditions._test_no_class"
    mod = types.ModuleType(mod_name)
    sys.modules[mod_name] = mod
    if "Conditions" not in sys.modules:
        pkg = types.ModuleType("Conditions"); pkg.__path__ = []
        sys.modules["Conditions"] = pkg
    setattr(sys.modules["Conditions"], "_test_no_class", mod)

    cs = ConditionScript_Create(mod_name, "NoSuchClass")
    assert cs._instance is None
    assert cs._init_error[0] == "AttributeError"


def test_create_falls_back_on_constructor_raise():
    mod_name, _ = _install_synthetic_condition("SynthCondRaiser", raise_in_init=True)
    cs = ConditionScript_Create(mod_name, "SynthCondRaiser", 1.0)
    assert cs._instance is None
    assert cs._init_error[0] == "RuntimeError"
    assert "synthetic-failure" in cs._init_error[1]


def test_create_success_does_not_set_init_error():
    mod_name, _ = _install_synthetic_condition("SynthCondClean")
    cs = ConditionScript_Create(mod_name, "SynthCondClean")
    assert cs._instance is not None
    assert cs._init_error is None


def test_set_status_from_instance_drives_conditional_ai_handler():
    """The instance's SetStatus calls back into the ConditionScript which
    fires registered TGConditionHandlers. ConditionalAI subscribes to its
    conditions; flipping status should trigger ConditionChanged."""
    mod_name, _ = _install_synthetic_condition("SynthCondReporter")
    cs = ConditionScript_Create(mod_name, "SynthCondReporter")

    # Wire into a ConditionalAI to confirm the handler chain fires.
    from engine.appc.ships import ShipClass
    cai = ConditionalAI_Create(ShipClass(), "C")
    cai.AddCondition(cs)
    cs.SetActive()  # ConditionalAI's ConditionChanged only fires when active

    # Drive a status flip from the instance side.
    cs.SetStatus(1)
    assert cs.GetStatus() == 1
    # ConditionalAI's _status reflects activity but the gate is on
    # condition status — we just need the handler chain to not blow up.
```

- [ ] **Step 6.2: Run; expect fails**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_condition_script_instantiate.py -v`
Expected: 6 FAILs — `ConditionScript` doesn't have `_instance` set or `_init_error` attribute.

- [ ] **Step 6.3: Implement eager instantiation in `ConditionScript`**

In [`engine/appc/ai.py`](../../../engine/appc/ai.py), replace the existing `ConditionScript.__init__` (around line 102-107):

```python
class ConditionScript(TGCondition):
    """Python-script-backed condition (sdk/.../Conditions/*).

    Eager-instantiation pattern: on construction, try to __import__ the
    named module, walk dotted parts, getattr the class, and instantiate
    it with (self, *args). Fall back to a data-bag if anything fails;
    SDK call sites guard with `if pCondition.IsActive():` so a quiet
    fallback is safe.
    """
    def __init__(self, module_name: str = "", class_name: str = "", *args):
        super().__init__()
        self._module_name = module_name
        self._class_name = class_name
        self._args = args
        self._instance = None
        self._init_error: tuple[str, str] | None = None
        if module_name and class_name:
            try:
                mod = _import_dotted(module_name)
                cls = getattr(mod, class_name)
                self._instance = cls(self, *args)
            except Exception as e:
                self._instance = None
                self._init_error = (type(e).__name__, str(e))
```

Add the `_import_dotted` helper at module scope (after the `TGConditionHandler` class, before `ConditionScript`):

```python
def _import_dotted(qualified: str):
    """`__import__('Conditions.ConditionInRange')` returns the top-level
    `Conditions` package. Walk the dotted path to get the leaf module."""
    mod = __import__(qualified)
    for part in qualified.split(".")[1:]:
        mod = getattr(mod, part)
    return mod
```

- [ ] **Step 6.4: Run; expect pass**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_condition_script_instantiate.py -v`
Expected: 6 PASS.

- [ ] **Step 6.5: Regression sweep — confirm no existing condition users break**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit -q -k "condition or ai_primitives"`
Expected: green. The fallback path keeps the existing behavior for code that didn't depend on a real instance.

- [ ] **Step 6.6: Commit**

```bash
git add engine/appc/ai.py tests/unit/test_condition_script_instantiate.py
git commit -m "feat(ai): ConditionScript eager class instantiation + fallback"
```

---

## Task 7: `ConditionExists` end-to-end

Make the SDK's `Conditions.ConditionExists` actually work: object exists → status 1; deleted → 0; enters later → 1; `SetTarget` swaps the watched object name.

**Files:**
- Test: `tests/unit/test_condition_exists.py` (new)
- May require tweaks to Task 1-6 engine surfaces if a gap surfaces during this end-to-end check.

- [ ] **Step 7.1: Read the SDK ConditionExists source so the test matches its API**

Run: `head -90 sdk/Build/scripts/Conditions/ConditionExists.py`

Confirm its `__init__(self, pCodeCondition, sObject)` signature. Confirm `SetTarget(sTarget)` is exposed.

- [ ] **Step 7.2: Write the failing tests**

Create `tests/unit/test_condition_exists.py`:

```python
"""End-to-end tests for SDK Conditions.ConditionExists running against
our engine. The condition class is loaded via _SDKFinder; the engine
surfaces it touches (ObjectGroup, g_kEventManager, TGPythonInstanceWrapper)
must all be in place for this to work."""
import App
from engine.appc.ai import ConditionScript_Create
from engine.appc.events import TGEvent_Create
from engine.appc.ships import ShipClass


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


def test_condition_exists_initial_status_when_object_present():
    """Object 'Bart' is already in a set when the condition is created →
    status should be 1 immediately."""
    _reset_app_state()
    pSet = App.SetClass_Create(); pSet.SetName("S")
    ship = ShipClass(); pSet.AddObjectToSet(ship, "Bart")
    App.g_kSetManager._sets["S"] = pSet

    cs = ConditionScript_Create("Conditions.ConditionExists",
                                "ConditionExists", "Bart")
    assert cs._instance is not None, (
        f"ConditionExists failed to instantiate: {cs._init_error}"
    )
    assert cs.GetStatus() == 1


def test_condition_exists_initial_status_when_object_absent():
    """Object 'Bart' is NOT in any set → status 0."""
    _reset_app_state()
    cs = ConditionScript_Create("Conditions.ConditionExists",
                                "ConditionExists", "Bart")
    assert cs._instance is not None, cs._init_error
    assert cs.GetStatus() == 0


def test_condition_exists_flips_to_zero_on_delete_event():
    """Object exists, condition is 1. Fire ET_DELETE_OBJECT_PUBLIC for it
    → condition flips to 0."""
    _reset_app_state()
    pSet = App.SetClass_Create(); pSet.SetName("S")
    ship = ShipClass(); pSet.AddObjectToSet(ship, "Bart")
    App.g_kSetManager._sets["S"] = pSet

    cs = ConditionScript_Create("Conditions.ConditionExists",
                                "ConditionExists", "Bart")
    assert cs.GetStatus() == 1

    # Simulate the delete event.
    evt = TGEvent_Create()
    evt.SetEventType(App.ET_DELETE_OBJECT_PUBLIC)
    evt.SetDestination(ship)
    App.g_kEventManager.AddEvent(evt)

    assert cs.GetStatus() == 0


def test_condition_exists_flips_to_one_on_entered_set_event():
    """Object isn't in any set yet → condition is 0. Add the object to a
    set and fire ET_OBJECT_GROUP_OBJECT_ENTERED_SET → condition flips to 1."""
    _reset_app_state()
    cs = ConditionScript_Create("Conditions.ConditionExists",
                                "ConditionExists", "Bart")
    assert cs.GetStatus() == 0

    pSet = App.SetClass_Create(); pSet.SetName("S")
    ship = ShipClass(); pSet.AddObjectToSet(ship, "Bart")
    App.g_kSetManager._sets["S"] = pSet

    # The condition's ObjectGroup is registered for ENTERED_SET events.
    # Fire the event; destination is the ObjectGroup.
    pGroup = cs._instance.pObjectGroup
    evt = TGEvent_Create()
    evt.SetEventType(App.ET_OBJECT_GROUP_OBJECT_ENTERED_SET)
    evt.SetDestination(pGroup)
    App.g_kEventManager.AddEvent(evt)

    assert cs.GetStatus() == 1
```

- [ ] **Step 7.3: Run; expect fails or escalations**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_condition_exists.py -v`

Expected outcomes:
- `test_condition_exists_initial_status_when_object_present` — should PASS (engine surfaces from Tasks 1-3 cover the constructor's `GetActiveObjectTuple` call).
- `test_condition_exists_initial_status_when_object_absent` — should PASS for the same reason; constructor sees no objects, calls `SetStatus(0)`.
- `test_condition_exists_flips_to_zero_on_delete_event` — depends on the method-handler dispatch (Task 1) firing the condition's `Deleted` method. Likely PASS.
- `test_condition_exists_flips_to_one_on_entered_set_event` — depends on method-handler target-filtering (Task 1) matching the ObjectGroup. Likely PASS.

**If a NOVEL engine gap surfaces** (a method ConditionExists calls that doesn't exist yet), follow the escalation pattern from the Intercept slice: STOP and report rather than silently patching. Likely candidates that may need stubs:
- `App.TGEvent.GetTarget()` — some condition handlers may call this; if missing, return `GetDestination()` as a fallback or add a separate field.
- `App.ObjectGroup.GetObjID()` — already exists via parent class.
- `App.g_kEventManager.RemoveBroadcastHandlerForInstance(...)` — already aliased in Task 1's diff.

If everything passes on the first run: great, ship it. If not, escalate for each gap as a separate small commit before continuing.

- [ ] **Step 7.4: Run regression sweep**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit -q -k "condition or builder_ai or event_manager or object_group or proximity"`
Expected: green.

- [ ] **Step 7.5: Commit**

```bash
git add tests/unit/test_condition_exists.py
git commit -m "test(conditions): ConditionExists end-to-end against real SDK class"
```

(If you had to add engine surfaces during 7.3 to make tests pass, include those in this commit OR land each engine fix as a separate commit and then this one as the test commit. Either pattern is fine — keep commits small and bisect-friendly.)

---

## Task 8: `ConditionInRange` end-to-end

Same shape as Task 7 but for the more demanding `ConditionInRange`, which uses `ProximityCheck` + the per-tick evaluator from Task 4. This is the highest-risk task for surfacing engine gaps — proximity tracking has more moving parts than simple object-existence.

**Files:**
- Test: `tests/unit/test_condition_in_range.py` (new)
- May require tweaks to Task 4's `ProximityCheck.Evaluate` if the SDK condition uses APIs we didn't anticipate.

- [ ] **Step 8.1: Read the SDK ConditionInRange source**

Run: `head -120 sdk/Build/scripts/Conditions/ConditionInRange.py`

Note especially how the condition creates the ProximityCheck and registers watched objects. The condition needs an anchor (`sObject1`) and a list of names it watches against (`*lsObjectNames`).

- [ ] **Step 8.2: Write the failing tests**

Create `tests/unit/test_condition_in_range.py`:

```python
"""End-to-end tests for SDK Conditions.ConditionInRange.

Depends on ProximityCheck + the per-tick evaluator (Task 4). The
condition watches sObject1's position; when any of lsObjectNames is
within fDistance, status flips to 1."""
import App
from engine.appc.ai import ConditionScript_Create
from engine.appc.planet import evaluate_proximity_checks
from engine.appc.ships import ShipClass


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


def _place_two_ships(d):
    """Anchor 'Anchor' at origin; target 'Target' at (d, 0, 0)."""
    _reset_app_state()
    pSet = App.SetClass_Create(); pSet.SetName("S")
    anchor = ShipClass(); anchor.SetTranslateXYZ(0.0, 0.0, 0.0)
    pSet.AddObjectToSet(anchor, "Anchor")
    target = ShipClass(); target.SetTranslateXYZ(d, 0.0, 0.0)
    pSet.AddObjectToSet(target, "Target")
    App.g_kSetManager._sets["S"] = pSet
    return anchor, target


def test_initial_status_one_when_inside_radius():
    anchor, target = _place_two_ships(d=50.0)
    cs = ConditionScript_Create("Conditions.ConditionInRange",
                                "ConditionInRange", 100.0, "Anchor", "Target")
    assert cs._instance is not None, cs._init_error
    # Initial state is 0; the proximity check fires on first evaluation.
    evaluate_proximity_checks()
    assert cs.GetStatus() == 1


def test_initial_status_zero_when_outside_radius():
    anchor, target = _place_two_ships(d=500.0)
    cs = ConditionScript_Create("Conditions.ConditionInRange",
                                "ConditionInRange", 100.0, "Anchor", "Target")
    evaluate_proximity_checks()
    assert cs.GetStatus() == 0


def test_status_flips_when_target_moves_into_range():
    anchor, target = _place_two_ships(d=500.0)
    cs = ConditionScript_Create("Conditions.ConditionInRange",
                                "ConditionInRange", 100.0, "Anchor", "Target")
    evaluate_proximity_checks()
    assert cs.GetStatus() == 0

    target.SetTranslateXYZ(50.0, 0.0, 0.0)
    evaluate_proximity_checks()
    assert cs.GetStatus() == 1


def test_status_zero_when_target_missing():
    """Anchor exists but Target doesn't → no proximity events → status 0."""
    _reset_app_state()
    pSet = App.SetClass_Create(); pSet.SetName("S")
    anchor = ShipClass(); pSet.AddObjectToSet(anchor, "Anchor")
    App.g_kSetManager._sets["S"] = pSet

    cs = ConditionScript_Create("Conditions.ConditionInRange",
                                "ConditionInRange", 100.0, "Anchor", "Target")
    evaluate_proximity_checks()
    assert cs.GetStatus() == 0
```

- [ ] **Step 8.3: Run; expect fails or escalations**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit/test_condition_in_range.py -v`

Expected outcomes vary. Likely escalation candidates:
- `App.ProximityCheck_Create(eEventType)` — exists from prior slices.
- The condition expects `pSet.GetProximityManager().AddObject(...)` to register an object for tracking, then ties its ProximityCheck to that manager. Walk the ConditionInRange source line-by-line to see what calls happen at `__init__` time, and whether any need engine support we haven't built.
- The condition may rely on **anchor's** proximity manager rather than the global one. Verify by reading the source.

**If novel gaps surface**, STOP and report. Risk #7 from the spec explicitly authorizes splitting `ConditionInRange` into a Slice A.5 if the gap is bigger than ~150 LOC.

- [ ] **Step 8.4: Run regression sweep**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit -q -k "condition or builder_ai or event_manager or object_group or proximity"`
Expected: green.

- [ ] **Step 8.5: Commit**

```bash
git add tests/unit/test_condition_in_range.py
git commit -m "test(conditions): ConditionInRange end-to-end against real SDK class"
```

---

## Task 9: `CallDamageAI` integration smoke

Load the real SDK `AI.Compound.CallDamageAI`, build its tree via BuilderAI activation, run one GameLoop tick, assert no crash and `_contained_ai` is non-None.

**Files:**
- Test: `tests/integration/test_builder_ai_call_damage_smoke.py` (new)

- [ ] **Step 9.1: Read CallDamageAI to understand its CreateAI signature + dependencies**

Run: `head -25 sdk/Build/scripts/AI/Compound/CallDamageAI.py`

The signature should be `CreateAI(pShip)` (single-arg). It creates a `BuilderAI` and registers ~50 blocks.

- [ ] **Step 9.2: Write the failing tests**

Create `tests/integration/test_builder_ai_call_damage_smoke.py`:

```python
"""Integration smoke: load AI.Compound.CallDamageAI, run one tick,
assert BuilderAI activates without crashing.

This is the smallest real SDK Compound that uses BuilderAI. Doesn't
assert per-tick behaviour or sub-tree correctness — that's Slice E
once FireScript / SelectTarget / sub-graphs are in place."""
import App
from engine.appc.ai import BuilderAI
from engine.appc.ai_driver import tick_ai
from engine.appc.ships import ShipClass


def _reset_app_state():
    App.g_kSetManager._sets.clear()
    App.g_kEventManager._broadcast_handlers.clear()
    if hasattr(App.g_kEventManager, "_method_handlers"):
        App.g_kEventManager._method_handlers.clear()


def test_call_damage_ai_activates_without_crashing():
    _reset_app_state()
    pSet = App.SetClass_Create(); pSet.SetName("S")
    ship = ShipClass(); pSet.AddObjectToSet(ship, "Test")
    App.g_kSetManager._sets["S"] = pSet

    import AI.Compound.CallDamageAI as call_damage_mod
    builder = call_damage_mod.CreateAI(ship)
    assert isinstance(builder, BuilderAI)

    tick_ai(builder, game_time=0.01)
    assert builder._activated is True, (
        f"BuilderAI activation failed: {builder._activation_error}"
    )
    assert builder._activation_failed is False
    assert builder._contained_ai is not None


def test_call_damage_ai_second_tick_does_not_rebuild():
    _reset_app_state()
    pSet = App.SetClass_Create(); pSet.SetName("S")
    ship = ShipClass(); pSet.AddObjectToSet(ship, "Test")
    App.g_kSetManager._sets["S"] = pSet

    import AI.Compound.CallDamageAI as call_damage_mod
    builder = call_damage_mod.CreateAI(ship)
    tick_ai(builder, game_time=0.01)
    # Snapshot contained AI; second tick must reuse it.
    snapshot = builder._contained_ai
    tick_ai(builder, game_time=0.5)
    assert builder._contained_ai is snapshot
```

- [ ] **Step 9.3: Run; expect fails or escalations**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/integration/test_builder_ai_call_damage_smoke.py -v`

Expected outcomes:
- BuilderAI activation runs through CallDamageAI's `BuilderCreate1..53` functions. Each function may call SDK APIs we haven't fully covered. Escalation candidates:
  - `ConditionScript_Create("Conditions.XYZ", ...)` for conditions other than the two pinned in Tasks 7-8. These should silently fall back via the Task 6 try/except — `_instance` is None, status stays 0 — and the BuilderCreateN function should still return a valid AI structure built around the dormant condition.
  - References to `App.AddBroadcastPythonFuncHandler` etc. — already exist.
  - Specific SDK type calls (e.g. `App.TGTimerManager.AddTimer(...)`) — should be present from prior slices.

**If a NOVEL gap surfaces**, STOP and report. Don't silently patch CallDamageAI's path beyond the slice scope.

- [ ] **Step 9.4: Run the full slice's test suite as a final regression check**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit tests/integration -q -k "condition or builder_ai or event_manager or object_group or proximity or ai_driver or ai_primitives"`
Expected: green.

- [ ] **Step 9.5: Commit**

```bash
git add tests/integration/test_builder_ai_call_damage_smoke.py
git commit -m "test(ai): CallDamageAI integration smoke — BuilderAI builds 53-block tree"
```

---

## Task 10: Update deferred AI-runtime doc

Strike the items this slice closes; reference the spec/plan from the deferred follow-ups.

**Files:**
- Modify: [`docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md`](../deferred/2026-05-18-ship-ai-runtime.md)

- [ ] **Step 10.1: Update the Step 6 ConditionScript section**

In [`docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md`](../deferred/2026-05-18-ship-ai-runtime.md), find the Step 6 section (around line 109):

```markdown
### Step 6 — `ConditionScript` actually evaluates

`ConditionScript_Create("Conditions.ConditionInRange", "ConditionInRange", *args)` should `__import__` the module, instantiate the class with `*args`, and feed its evaluator into `SetStatus`. ...
```

Replace it with:

```markdown
### Step 6 — `ConditionScript` actually evaluates

✅ Mechanism done in [BuilderAI + Conditions plan](../plans/2026-05-18-builder-ai-conditions.md). `ConditionScript_Create` now eagerly imports the module, instantiates the named class, and falls back to a data-bag on failure. Two SDK conditions pinned end-to-end with regression tests: `ConditionExists` and `ConditionInRange`. The remaining 28 conditions try-eager-fallback-lazy — future slices add them one at a time as their consumers (FireScript, SelectTarget, sub-graphs) demand them.
```

- [ ] **Step 10.2: Update the "What's in the SDK we need to drive" / BuilderAI mention**

Find the relevant paragraph (around the BuilderAI description, in the primitive class surface section). Add or update:

```markdown
- **`BuilderAI`** (subclass of PreprocessingAI) — ✅ lazy-construction active in [BuilderAI + Conditions plan](../plans/2026-05-18-builder-ai-conditions.md). On first AI tick, the activator does a topological sort over `_dependencies` and calls each block's `BuilderCreateN` function in `_module_name`. Dep results pass as positional args; `_dep_objects` pass as kwargs. The last block becomes `_contained_ai`. Cyclic/failing graphs mark `_activation_failed` and short-circuit.
```

- [ ] **Step 10.3: Add a note about Slices B–E in the follow-up section**

Find the "Follow-up after Intercept" section (around line 103) and add a new section before it:

```markdown
### Follow-up after BuilderAI + ConditionScript (Slice A complete)

The BasicAttack roadmap now has its foundation. Next slices, in order:
- **Slice B**: `SelectTarget` preprocessor port (~600 LOC from `sdk/.../AI/Preprocessors.py`).
- **Slice C**: `FireScript` preprocessor port (~1000 LOC).
- **Slice D**: PlainAI sub-graphs that FedAttack/NonFedAttack splice in (`TorpRun`, `StationaryAttack`, `TurnToAttack`, `SweepPhasers`, `ICOMove`, `WarpBeforeDeath`, `EvadeTorps`).
- **Slice E**: `NonFedAttack`/`FedAttack` `CreateAI` assembly + visible mission where a hostile flies in and opens fire.
```

- [ ] **Step 10.4: Run all suites a final time**

Run: `unset VIRTUAL_ENV && uv run --extra dev pytest tests/unit tests/integration -q -k "condition or builder_ai or event_manager or object_group or proximity or ai_driver or ai_primitives or stay or goforward or turn or intercept or ship_motion"`
Expected: green.

- [ ] **Step 10.5: Commit**

```bash
git add docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md
git commit -m "docs(deferred): close Step 6 + add Slices B–E forward refs"
```

---

## Out of scope (deferred to Slices B–E)

- `SelectTarget` preprocessor — Slice B.
- `FireScript` preprocessor — Slice C.
- Compound sub-graphs (`TorpRun`, `StationaryAttack`, `TurnToAttack`, `SweepPhasers`, `ICOMove`, `WarpBeforeDeath`, `EvadeTorps`) — Slice D.
- `FedAttack`/`NonFedAttack` `CreateAI` assembly + visible smoke (hostile opens fire) — Slice E.
- 28 SDK conditions beyond `ConditionExists` + `ConditionInRange` — incremental as later slices demand them.
- Renderer warp visuals (still flagged in the deferred doc; orthogonal to this slice).
- Real obstacle avoidance (still flagged; orthogonal).

These remain in [docs/superpowers/deferred/2026-05-18-ship-ai-runtime.md](../deferred/2026-05-18-ship-ai-runtime.md).
