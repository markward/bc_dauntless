# A Python method process stops when its owner goes — design (2026-11-03)

**Status:** approved direction (Mark, 2026-11-03: "go for it"). Branch `ws/process-replace`, off `project/combat_threading` at `6dda2f24b`.
**Roadmap:** `2026-11-01-threaded-weapons-combat-roadmap.md` §7, "a replaced SDK process keeps running until garbage collection".

## 1. The bug

The SDK attaches a repeating process to an owner object and keeps the process on that owner. All six stock users follow this pattern, and the owner is always `self`:

| SDK file | Owner holds | Process calls |
|---|---|---|
| `Bridge/PowerDisplay.py:73-98` | `ProcessWrapper.pProcess` | `ProcessFunc` → `RefreshTimer` |
| `Bridge/HelmMenuHandlers.py` (`ProcessWrapper`) | `pProcess` | `ProcessFunc` → `CollisionAlertCheck` |
| `Conditions/ConditionFacingToward.py:118-121` | `pTimerProcess` | `PeriodicCheck` |
| `Conditions/ConditionInPhaserFiringArc.py` | `pTimerProcess` | (periodic check) |
| `Conditions/FriendliesInPlayerSetStronger.py:67-71` | `pTimerProcess` | `EvaluateState` |
| `Conditions/ConditionIncomingTorps.py` | `pTimerProcess` | (periodic check) |

Each one is a reference cycle: owner → process → owner (`SetInstance(self)`). The SDK stops a process by dropping its owner (`g_pPowerRefreshProcess = None`, `PowerDisplay.py:362-363`; a new `ProcessWrapper` replacing the global, `PowerDisplay.py:329`) or by dropping the process (`self.pTimerProcess = None`).

Ours: `engine/appc/time_slice.py`. The manager holds processes weakly, as BC's C++ destructor unregisters them, but `PythonMethodProcess` holds its instance **strongly**. A dropped owner is unreachable but still alive inside its cycle. It keeps firing until Python's cyclic collector happens to run.

**Measured** (scratch probe, collector disabled, 90 s headless per mission, then `gc.collect()`):
- After loading E2M2, 3 `PowerDisplay` refresh processes are live; after E3M2, E5M2 or E6M1, 4 are live. A collect leaves 1. HelmMenuHandlers' wrapper stays at 1, since it is created only when none exists.
- With the instance held weakly (probe monkeypatch), 1 is live after every load before any collect.
- No condition-script process showed up in those runs; their cycle is the same shape.

**Effect:** the dropped refresh copies fire `AdjustPower`, which posts duplicate `ET_SUBSYSTEM_POWER_CHANGED` (presentation-RNG spec §10). The event stream depends on when the collector runs, which depends on allocation history. A dropped condition owner keeps evaluating its AI condition until collected (**inferred**, not observed).

## 2. What BC does

BC embeds Python 1.5, which has **no cyclic collector** (it arrived in Python 2.0). So in BC this cycle can never be freed "later". One of these two must hold:
- **(a) The C++ process does not own its instance** (a borrowed reference). Dropping the owner frees it at once, its `pProcess` shadow's `__del__` deletes the C++ process (SDK `App.py` `PythonMethodProcess.__del__`), and the destructor unregisters it. The process stops immediately.
- **(b) The C++ process owns its instance.** Nothing ever frees the cycle, and every replaced process fires forever.

"Fires until the collector runs" is neither. The live binary's surface has `SetInstance` (`tools/probes/results/q13d_signatures.txt:12571`); the SDK's `App.py` predates it. Its body has not been read: the clean-room reference server was unavailable this session. **Ruling (mine, under Mark's standing rule to take the script reading that lets the sim run cleanly):** (a). It is the reading the scripts are written for:
- `ProcessWrapper` exists "to wrap the functionality we want", and its lifetime is the process's;
- `g_pPowerRefreshProcess = None` means "stop", and under (b) it would do nothing;
- the condition scripts' `__setstate__` drop their process to stop it.

Cost if wrong: under (b), BC would accumulate duplicate refresh timers; we would not reproduce that leak.

## 3. The change

`PythonMethodProcess` holds its instance **weakly** whenever the instance supports weak references, for both `SetInstance(instance)` and the two-argument `SetFunction(instance, name)`. An instance that cannot be weakly referenced is held strongly, as today.

- When the instance has died, `Update` does nothing. The process itself is usually freed in the same moment: its only strong holder was the owner.
- The manager, its weak queue, the first-fire rule and priorities are unchanged.
- No SDK file is edited and no engine caller changes. A grep of `engine/` finds no other constructor of `PythonMethodProcess`.

**Deliberate consequence:** a caller whose instance is held **only** by its process now stops at once. No stock script does this. Under reading (a) the same call would leave BC with a dangling pointer, so a script cannot have relied on it.

## 4. Tests

- **Unit** (`tests/unit/test_time_slice_self_register.py` or a new `test_time_slice_owner_lifetime.py`):
  - with the collector disabled, an owner holding its process (the `ProcessWrapper` shape) stops firing the moment its last outside reference is dropped, and the manager count falls by one, with no `gc.collect()`;
  - the same holds for the two-argument `SetFunction(instance, name)` form;
  - an instance without weak-reference support still fires;
  - a live owner keeps firing on its delay.
- **SDK** (headless, collector disabled): loading a mission leaves exactly one live `PowerDisplay` refresh process, and a second load still leaves one.
- **Mutation:** going back to a strong instance reference fails the unit and SDK tests.
- **Regression set:** `tests/unit/test_time_slice.py`, `test_time_slice_self_register.py`, `test_condition_timer_end_to_end.py`, `test_timers.py`, `test_loop.py`, and the K1 game-loop differential, `tests/integration/test_native_k1_differential.py`.

## 5. Docs

- Roadmap §7: the item is resolved, pointing here; §7 gains the open item in §7 of this spec.
- `lock-map.md` (the line about conditions in reference cycles): only the process half is superseded. The conditions' own cycle (§7) stays.
- This spec's §6 outcome.

## 6. Outcome

(Filled in when built.)

## 7. Not covered: a condition script and its engine wrapper hold each other

`engine/appc/ai.py` `ConditionScript.__init__` builds the SDK instance with `cls(self, ...)` and keeps it as `_instance`. Every stock condition stores that argument as `self.pCodeCondition`, so a dropped condition is a cycle too. Its `__del__` (eight stock conditions define one, `lock-map.md` point 2) and, through it, its process wait for the collector.

In BC the C++ code condition owns the instance. The instance's `pCodeCondition` is a non-owning SWIG pointer shadow, so no cycle exists (**inferred**).

**Not observed:** in the same probe (four mission loads, 60 s each, collector disabled), the live condition count was identical before and after `gc.collect()` every time. No condition became collectable.

**Fix shape, if taken:** hand the instance a non-owning handle to its code condition. It would compare by identity, which `ConditionIncomingTorps` needs: it keeps code conditions in a list and `remove`s them, including in `__del__`. Not built here: it touches every condition and needs its own reproduction. Recorded in roadmap §7 for Mark.
