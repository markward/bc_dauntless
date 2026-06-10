# Sensor-damage detection scaling — design

**Date:** 2026-06-10
**Status:** Approved, pre-implementation

## Goal

When a ship's sensors are damaged, the range at which it can detect targets is
reduced in proportion to the sensor subsystem's condition. When the sensors are
offline (disabled or destroyed) the ship detects nothing:

- **Player:** no contacts on the target list.
- **AI:** no candidate targets to select from.

The gate is symmetric — both the player and every AI ship read their own
sensor subsystem's condition.

## Current state

- `SensorSubsystem` (`engine/appc/subsystems.py:1792`) carries
  `GetBaseSensorRange()`, populated from each ship's `SensorProperty` during
  `ShipClass.SetupProperties` (`engine/appc/ships.py:720`). Stock values:
  Galaxy = 2000 GU (≈350 km), `GenericTemplate` = 1000 GU.
- **Player list:** `update_target_list_visibility()`
  (`engine/appc/subsystems.py:2176`) already hides every row when the player's
  sensor subsystem is `_is_offline`, otherwise does a range check against a
  **hardcoded 30000 GU** default — neither the ship's real sensor range nor
  condition-scaled. Called from `host_loop.py:2328`. The radar panel,
  `TargetListView`, and `sensors_panel` all filter on `row.IsVisible()`.
- **AI:** the SDK's `SelectTarget.UpdateTargetInfo`
  (`sdk/Build/scripts/AI/Preprocessors.py:1432`) enumerates candidates via
  `self.pTargetGroup.GetActiveObjectTupleInSet(pSet)` (our shim,
  `engine/appc/objects.py:415`) with **no sensor filtering**. The SDK's
  `bIgnoreSensors` flag defaults to `1` (ignore) and is never read in the
  Python path — the real filtering lived in the C++ engine. The method has
  shortcuts (`len==1 → choose it`, `len==0 → None`) that bypass the rating
  loop, so gating must happen on the candidate list, not via `GetTargetRating`.
- `SensorSubsystem` has an unused `_known_objects` set + `IsObjectKnown` /
  `AddKnownObject` API.

## Decisions

1. **Baseline range:** the ship's real `SensorProperty.BaseSensorRange` is the
   100%-condition range (not the 30000 GU placeholder).
2. **Scaling curve:** `effective_range = base × GetConditionPercentage()`, with a
   hard cutoff to `0` once the sensor crosses the disabled threshold
   (`_is_offline`, ≤25% condition = `DisabledPercentage`) or is destroyed.
3. **AI:** symmetric with the player, reading each AI ship's own sensor
   condition. This deliberately overrides stock BC's `bIgnoreSensors=1` default.

## Design

### 1. Core formula — `engine/appc/sensor_detection.py`

A new focused module (keeping the already-2254-line `subsystems.py` from
growing) exposing two pure functions:

```python
FALLBACK_RANGE_GU = 30000.0

def effective_sensor_range(ship) -> float:
    sensors = ship.GetSensorSubsystem() if ship is not None else None
    if sensors is None:        return FALLBACK_RANGE_GU   # legacy / no-sensor fixtures: full sight
    if _is_offline(sensors):   return 0.0                 # disabled (≤25%) OR destroyed → blind
    base = sensors.GetBaseSensorRange()
    if base <= 0.0:            return FALLBACK_RANGE_GU    # no sensor hardpoint data
    return base * sensors.GetConditionPercentage()

def can_detect(observer, target) -> bool:
    r = effective_sensor_range(observer)
    if r <= 0.0:               return False
    return _distance(observer, target) <= r
```

`FALLBACK_RANGE_GU` preserves today's player-list distance for ships/fixtures
that don't model a sensor subsystem or have no `BaseSensorRange`, so existing
tests stay green and ships without sensor hardpoints don't go blind.

`_is_offline` is reused from `engine/appc/subsystems.py` (single source of truth
for the disabled-or-destroyed gate). Distance uses the same world-location
accessor pattern as `subsystems._get_xyz`.

Net behavior: full `BaseSensorRange` undamaged → shrinks linearly with
condition → snaps to 0 at the disabled threshold or on destruction. There is an
intentional discontinuity (≈0.25×base → 0) at the disabled line.

### 2. Player target list

`update_target_list_visibility()` keeps its `_is_offline` early-return (clear,
and handles the range-0 case) and replaces its range source: instead of the
`30000.0` default parameter, it uses `effective_sensor_range(player)`. Rows
beyond effective range get `SetNotVisible()`. The `range_units` parameter keeps
its `30000.0` default for direct callers/tests; the host-loop call site
(`host_loop.py:2328`) lets the function compute the range from the player ship.

No UI changes — the panels already filter on `row.IsVisible()`.

### 3. AI target selection

A two-part monkeypatch installed once at engine init — no fork of the SDK file,
no reimplementation of the selection logic:

1. Wrap `SelectTarget.UpdateTargetInfo` to stash `self.pCodeAI.GetShip()` in a
   module global for the duration of the call (`try/finally`).
2. Wrap `ObjectGroup.GetActiveObjectTupleInSet` so that **when that global is
   set**, it filters its result through `can_detect(observer_ship, obj)`.

Single-threaded Python (CLAUDE.md `setcheckinterval`) makes the global safe. The
filter is a no-op for every other caller of `GetActiveObjectTupleInSet`
(E1M2 proximity, MissionLib's player scan) because the global is `None` outside
AI target selection.

Result: an AI ship with offline sensors gets an empty candidate list →
`SelectTarget` returns `None` → no target; a sensor-damaged AI ship only sees
contacts inside its own shrunken range.

**Rejected alternative:** a per-tick sweep populating
`SensorSubsystem._known_objects` + `IsObjectKnown` filtering. More faithful to
BC's real architecture, but adds per-tick cost and persistent state to keep in
sync (staleness, dead-object cleanup) for zero behavioral gain over the
on-demand filter. The unused `_known_objects` API is left as-is.

## Testing (all headless / TDD)

**`effective_sensor_range` / `can_detect` (unit):**
- Undamaged → `BaseSensorRange`; 60% condition → `0.6 × BaseSensorRange`.
- Condition ≤ disabled threshold → `0.0`; destroyed → `0.0`.
- No sensor subsystem / `BaseSensorRange == 0` → `FALLBACK_RANGE_GU`.
- `can_detect` true just inside effective range, false just outside, false at 0.

**Player list (`update_target_list_visibility`):**
- Healthy: contact inside `BaseSensorRange` visible, beyond it hidden.
- Damaged: a contact visible at full condition becomes hidden once condition
  drops enough that it falls outside the scaled range.
- Offline: every row hidden (existing test, re-asserted).

**AI gate (integration, two ships in a set):**
- Healthy AI ship with two in-range candidates selects one.
- Sole candidate pushed beyond scaled range after sensor damage → `None`.
- AI ship with offline sensors → `None` even with candidates present.
- Non-AI caller of `GetActiveObjectTupleInSet` (global unset) returns unfiltered
  results.

## Scope / non-goals

- No sensor jamming, ECM, cloak interaction, or stealth — pure range × condition.
- No `_known_objects` sweep.
- No rebalancing of `BaseSensorRange` hardpoint values.
