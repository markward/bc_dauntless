# Repair System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement BC's repair system faithfully: the per-ship `RepairSubsystem` queue and tick, subsystem disabled/destroyed/operational threshold events, the `EngRepairPane` repair-queue UI, and end-to-end firing of Brex's seven Engineering emitters.

**Architecture:** All repair state lives on the ship's `RepairSubsystem` object in `engine/appc/subsystems.py` (Approach A of the spec). Threshold events emit from the `ShipSubsystem` base condition path, so every subsystem class gets them for free. SDK scripts (`Bridge/EngineerCharacterHandlers.py`, `Bridge/EngineerMenuHandlers.py`) run **unmodified** — we only make the engine surface they call real. UI is a CEF projection of the SDK-created `EngRepairPane` widget through the existing `CrewMenuPanel`.

**Tech Stack:** Python (engine + root `App.py` shim), pytest, vanilla JS/CSS in `native/assets/ui-cef/` (CEF), no new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-05-repair-system-design.md`

## Global Constraints

- **SDK is never modified.** Nothing under `sdk/` changes. Ever.
- **Depends on power-management** (`docs/superpowers/specs/2026-07-05-power-management-system-design.md`, implemented first). If the power feature restructured the per-ship subsystem pass in `engine/core/loop.py` (currently lines 48–59), add repair to *that* pass — same ships, same `TICK_DELTA`.
- **Repair rate is NOT power-efficiency-scaled.** The RE formula scales only by the repair bay's own condition percentage. Do not multiply by `efficiency`.
- **Gate before merge:** `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs against `tests/known_failures.txt`). `scripts/run_tests.sh` alone is NOT sufficient.
- **The `_Stub` trap:** the root `App.py` module `__getattr__` returns a fresh `_NamedStub` for any missing name, and `TGObject.__getattr__` vends silent no-op `_Stub`s. A missing export never crashes — it silently does nothing. Every SDK-touched name must be proven real by test.
- **Event constants continue the private `0x13xx` block** in `App.py` (existing block ends at `ET_REPAIR_CANNOT_BE_COMPLETED = 0x131D`, `App.py:928`).
- **Update tests in the same change** when a signature or output shape changes. Never call a failure "pre-existing" without the gate saying so.
- New-code conventions: match `engine/appc/subsystems.py` style — raise-safe event emission via lazy `import App` inside methods (circular-import guard; see `CloakingSubsystem._fire`, `subsystems.py:1651`), `dev_mode.log_swallowed(...)` for swallowed exceptions.

## Reference: the RE-verified repair tick

From `docs/original_game_reference/gameplay/ship-subsystems.md` §Repair:

```
rawRepair = MaxRepairPoints * (bay.condition / bay.maxCondition) * dt
divisor   = min(queueCount, NumRepairTeams)
perItem   = rawRepair / divisor
hpGain_i  = perItem / target_i.RepairComplexity
```

Destroyed entries are skipped (not removed), fire `ET_REPAIR_CANNOT_BE_COMPLETED` once, and don't consume a team. Priority click is a binary toggle: actively-repaired → demote to tail; waiting → promote to head. Worked example (Sovereign: 50 pts, healthy bay, 2 queued, dt=0.033): raw = 1.65, perItem = 0.825, phaser (complexity 3.0) → +0.275 HP, tractor (7.0) → +0.118 HP.

## Event payload contracts (used by every task below)

| Event | Type | Source | ObjPtr | Destination |
|---|---|---|---|---|
| `ET_SUBSYSTEM_DISABLED` | `TGEvent` | subsystem | — | owning ship (fallback: subsystem) |
| `ET_SUBSYSTEM_DESTROYED` | `TGEvent` | subsystem | — | owning ship |
| `ET_SUBSYSTEM_OPERATIONAL` | `TGEvent` | subsystem | — | owning ship |
| `ET_ADD_TO_REPAIR_LIST` | `TGObjPtrEvent` | target subsystem | target subsystem | repair subsystem |
| `ET_REPAIR_COMPLETED` | `TGObjPtrEvent` | target subsystem | target subsystem | owning ship |
| `ET_REPAIR_CANNOT_BE_COMPLETED` | `TGObjPtrEvent` | target subsystem | target subsystem | owning ship |
| `ET_REPAIR_INCREASE_PRIORITY` | `TGObjPtrEvent` | (any) | target subsystem | repair subsystem |

Why: `EngineerCharacterHandlers.SubsystemDisabled` dereferences `pEvent.GetSource().GetObjID()` and filters `pEvent.GetDestination().GetObjID() != pPlayer.GetObjID()` (sdk `EngineerCharacterHandlers.py:831–878`). The (stock-disabled) `RepairCompleted` body dereferences BOTH `pEvent.GetSource()` and `pEvent.GetObjPtr()` (`EngineerCharacterHandlers.py:294–336`) — emit `TGObjPtrEvent` so every dereference pattern works.

---

### Task 1: App shim surface — event constants, casts, no-stub audit

**Files:**
- Modify: `App.py` (constants block ends at line 928; casts region at lines 363–474)
- Test: `tests/unit/test_repair_app_surface.py` (create)

**Interfaces:**
- Produces: `App.ET_SUBSYSTEM_OPERATIONAL = 0x131E`, `App.ET_REPAIR_INCREASE_PRIORITY = 0x131F`, `App.ET_ADD_TO_REPAIR_LIST = 0x1320`; casts `SensorSubsystem_Cast`, `ImpulseEngineSubsystem_Cast`, `WarpEngineSubsystem_Cast`, `TractorBeamProjector_Cast`, `RepairSubsystem_Cast` — each `(obj) -> obj | None`. (`ShipSubsystem_Cast`, `PhaserSystem_Cast`, `TorpedoSystem_Cast`, `ShieldClass_Cast`, `PowerSubsystem_Cast` already exist at `App.py:369–473`.)

- [ ] **Step 1: Write the failing tests**

```python
"""Repair-feature App surface: constants + casts EngineerCharacterHandlers needs.

Guards the _Stub trap: App.__getattr__ vends a fresh _NamedStub for missing
names, so a missing export silently no-ops. Every name on the engineer
announce/report path must resolve to something real.
"""
import App


# Every App.* name Bridge/EngineerCharacterHandlers.py touches on the
# emitter paths (registration, announce handlers, Report/Communicate).
_ENGINEER_HANDLER_APP_NAMES = [
    # events
    "ET_REPORT", "ET_COMMUNICATE",
    "ET_TACTICAL_SHIELD_LEVEL_CHANGE", "ET_TACTICAL_HULL_LEVEL_CHANGE",
    "ET_TACTICAL_SHIELD_0_LEVEL_CHANGE", "ET_TACTICAL_SHIELD_1_LEVEL_CHANGE",
    "ET_TACTICAL_SHIELD_2_LEVEL_CHANGE", "ET_TACTICAL_SHIELD_3_LEVEL_CHANGE",
    "ET_TACTICAL_SHIELD_4_LEVEL_CHANGE", "ET_TACTICAL_SHIELD_5_LEVEL_CHANGE",
    "ET_SUBSYSTEM_DISABLED", "ET_SUBSYSTEM_DESTROYED",
    "ET_SUBSYSTEM_OPERATIONAL",
    "ET_REPAIR_COMPLETED", "ET_REPAIR_CANNOT_BE_COMPLETED",
    "ET_REPAIR_INCREASE_PRIORITY", "ET_ADD_TO_REPAIR_LIST",
    "ET_MAIN_BATTERY_LEVEL_CHANGE", "ET_BACKUP_BATTERY_LEVEL_CHANGE",
    # casts used by AnnounceSystemDisabled / AnnounceSystemDestroyed /
    # RepairCompleted (EngineerCharacterHandlers.py:918-932, 294-336)
    "PhaserSystem_Cast", "ShieldClass_Cast", "SensorSubsystem_Cast",
    "TorpedoSystem_Cast", "TractorBeamProjector_Cast",
    "ImpulseEngineSubsystem_Cast", "WarpEngineSubsystem_Cast",
    "PowerSubsystem_Cast", "ShipSubsystem_Cast", "RepairSubsystem_Cast",
    # machinery
    "TGObject_GetTGObjectPtr", "CharacterClass_GetObject",
    "TGSequence_Create", "CharacterAction_Create", "TGScriptAction_Create",
    "TGFloatEvent_Create", "CSP_SPONTANEOUS", "FloatRangeWatcher",
]


def test_engineer_handler_names_are_real_not_stubs():
    missing = []
    for name in _ENGINEER_HANDLER_APP_NAMES:
        val = getattr(App, name)
        if isinstance(val, App._NamedStub):
            missing.append(name)
    assert not missing, "App names still stubbed: %r" % missing


def test_new_event_constants_are_distinct_ints():
    values = {
        App.ET_SUBSYSTEM_OPERATIONAL,
        App.ET_REPAIR_INCREASE_PRIORITY,
        App.ET_ADD_TO_REPAIR_LIST,
        App.ET_SUBSYSTEM_DISABLED,
        App.ET_SUBSYSTEM_DESTROYED,
        App.ET_REPAIR_COMPLETED,
        App.ET_REPAIR_CANNOT_BE_COMPLETED,
    }
    assert len(values) == 7
    assert all(isinstance(v, int) for v in values)


def test_new_casts_pass_matching_reject_other():
    from engine.appc.subsystems import (
        SensorSubsystem, ImpulseEngineSubsystem, WarpEngineSubsystem,
        RepairSubsystem,
    )
    from engine.appc.weapon_subsystems import TractorBeam
    pairs = [
        (App.SensorSubsystem_Cast, SensorSubsystem("s")),
        (App.ImpulseEngineSubsystem_Cast, ImpulseEngineSubsystem("i")),
        (App.WarpEngineSubsystem_Cast, WarpEngineSubsystem("w")),
        (App.RepairSubsystem_Cast, RepairSubsystem("r")),
        (App.TractorBeamProjector_Cast, TractorBeam("t")),
    ]
    for cast, obj in pairs:
        assert cast(obj) is obj
        assert cast(object()) is None
        assert cast(None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_repair_app_surface.py -v`
Expected: FAIL — `test_engineer_handler_names_are_real_not_stubs` lists the missing casts (and possibly other names the audit exposes); constants test fails on missing `ET_SUBSYSTEM_OPERATIONAL`.

- [ ] **Step 3: Add the constants**

In `App.py`, immediately after `ET_REPAIR_CANNOT_BE_COMPLETED     = 0x131D` (line 928):

```python
# Repaired back above the disabled threshold. Consumed by the AI Conditions
# classes (ConditionSystemDisabled/ConditionTorpsReady/ConditionPulseReady
# register broadcast handlers for it) as well as the engineer report path.
ET_SUBSYSTEM_OPERATIONAL          = 0x131E
# EngRepairPane click -> binary head/tail toggle on the repair queue.
ET_REPAIR_INCREASE_PRIORITY       = 0x131F
# A damaged subsystem entered the repair queue.
ET_ADD_TO_REPAIR_LIST             = 0x1320
```

- [ ] **Step 4: Add the casts**

In `App.py`, after `PowerSubsystem_Cast` (line ~463–473), following its lazy-import pattern:

```python
def SensorSubsystem_Cast(obj):
    """EngineerCharacterHandlers.AnnounceSystemDisabled:924 —
    `App.SensorSubsystem_Cast(pSource)` decides the "SensorsDisabled" line."""
    from engine.appc.subsystems import SensorSubsystem
    return obj if isinstance(obj, SensorSubsystem) else None


def ImpulseEngineSubsystem_Cast(obj):
    from engine.appc.subsystems import ImpulseEngineSubsystem
    return obj if isinstance(obj, ImpulseEngineSubsystem) else None


def WarpEngineSubsystem_Cast(obj):
    from engine.appc.subsystems import WarpEngineSubsystem
    return obj if isinstance(obj, WarpEngineSubsystem) else None


def RepairSubsystem_Cast(obj):
    from engine.appc.subsystems import RepairSubsystem
    return obj if isinstance(obj, RepairSubsystem) else None


def TractorBeamProjector_Cast(obj):
    """SDK class = the individual tractor projector. Our engine models the
    projector as TractorBeam (weapon_subsystems.py:1583) under a
    TractorBeamSystem; the disabled/destroyed event source may be either,
    so match both — the announce line is the same ("TractorDisabled")."""
    from engine.appc.weapon_subsystems import TractorBeam, TractorBeamSystem
    return obj if isinstance(obj, (TractorBeam, TractorBeamSystem)) else None
```

- [ ] **Step 5: Re-run; export anything else the audit test names**

Run: `uv run pytest tests/unit/test_repair_app_surface.py -v`
If `test_engineer_handler_names_are_real_not_stubs` still lists names (e.g. `TGObject_GetTGObjectPtr` if it isn't exported from `engine/appc/actions.py:936`), add the export to `App.py` (`from engine.appc.actions import TGObject_GetTGObjectPtr` alongside the existing actions imports) and re-run until PASS.

- [ ] **Step 6: Run the neighbouring suites**

Run: `uv run pytest tests/unit/test_repair_app_surface.py tests/unit/test_subsystems.py -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add App.py tests/unit/test_repair_app_surface.py
git commit -m "feat(repair): App surface — repair/operational event constants + engineer-handler casts, no-stub audit"
```

---

### Task 2: ShipSubsystem.Repair() + RepairComplexity seeding

**Files:**
- Modify: `engine/appc/subsystems.py` (`ShipSubsystem`: fields ~line 213, accessors ~line 742, `GetRepairPointsNeeded` at 469)
- Modify: `engine/appc/ships.py` (`_copy_powered_subsystem_fields` at 1186–1203; generic receiver copy-loop at ~898; engine-pod block at ~1157–1167)
- Test: `tests/unit/test_repair_subsystem.py` (create)

**Interfaces:**
- Produces: `ShipSubsystem.Repair(points: float) -> None` (clamped condition increase through `SetCondition`); `ShipSubsystem.GetRepairComplexity() -> float` (default 1.0) / `SetRepairComplexity(v)`. Hardpoint `SetRepairComplexity(...)` values reach live subsystems via `SetupProperties`.
- Consumes: property data-bag `GetRepairComplexity()` (returns authored value or None — the same mechanism `GetDisabledPercentage` uses at `ships.py:1202`).

- [ ] **Step 1: Write the failing tests**

```python
"""RepairSubsystem queue/tick + ShipSubsystem repair surface."""
import App
from engine.appc.subsystems import ShipSubsystem


def _sub(name="Phasers", max_condition=1000.0, condition=None,
         complexity=None, disabled_pct=0.25):
    s = ShipSubsystem(name)
    s.SetMaxCondition(max_condition)
    s.SetDisabledPercentage(disabled_pct)
    if condition is not None:
        s.SetCondition(condition)
    if complexity is not None:
        s.SetRepairComplexity(complexity)
    return s


def test_repair_adds_condition_clamped_to_max():
    s = _sub(max_condition=1000.0, condition=400.0)
    s.Repair(100.0)
    assert s.GetCondition() == 500.0
    s.Repair(10000.0)
    assert s.GetCondition() == 1000.0


def test_repair_ignores_none_zero_negative():
    s = _sub(max_condition=1000.0, condition=400.0)
    s.Repair(None)
    s.Repair(0.0)
    s.Repair(-5.0)
    assert s.GetCondition() == 400.0


def test_repair_complexity_default_and_roundtrip():
    s = _sub()
    assert s.GetRepairComplexity() == 1.0
    s.SetRepairComplexity(3.0)
    assert s.GetRepairComplexity() == 3.0
```

And the seeding test (append to the same file):

```python
def test_setup_properties_seeds_repair_complexity():
    from engine.appc.ships import ShipClass_CreateWithSubsystems
    from engine.appc.properties import SensorSubsystemProperty
    ship = ShipClass_CreateWithSubsystems("TestShip")
    prop = SensorSubsystemProperty("Sensor Array")
    prop.SetMaxCondition(8000.0)
    prop.SetRepairComplexity(4.0)          # data-bag setter, like hardpoints
    ship.GetPropertySet().AddProperty(prop)
    ship.SetupProperties()
    assert ship.GetSensorSubsystem().GetRepairComplexity() == 4.0
```

NOTE for the implementer: check the actual factory/property names before
running — the ship factory is at `ships.py:1450–1474` (`from engine.appc.subsystems import ...` block; the public creation helper is right above `ShipClass_GetObject`). If the sensor property class has a different name in `engine/appc/properties.py`, use that class; the assertion is what matters. If `SetupProperties` requires a property-set attach step different from `GetPropertySet().AddProperty`, mirror how `tests/unit/test_setup_properties_*.py` builds ships — those files are the convention.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_repair_subsystem.py -v`
Expected: FAIL — `Repair` resolves to a silent `_Stub` (calls do nothing but `GetRepairComplexity` equality fails), or AttributeError on `SetRepairComplexity`.

- [ ] **Step 3: Implement Repair + complexity on ShipSubsystem**

In `engine/appc/subsystems.py`. Field in `ShipSubsystem.__init__` (next to `self._disabled_percentage`, line ~213):

```python
        # Repair-time divisor mirrored from the hardpoint property
        # (SubsystemProperty.SetRepairComplexity — every stock hardpoint
        # authors it). Higher = slower repair. Default 1.0 = neutral.
        self._repair_complexity: float = 1.0
```

Accessors next to `GetDisabledPercentage` (line ~742):

```python
    def GetRepairComplexity(self) -> float:            return self._repair_complexity
    def SetRepairComplexity(self, v) -> None:
        v = float(v)
        self._repair_complexity = v if v > 0.0 else 1.0
```

`Repair` next to `GetRepairPointsNeeded` (line ~469):

```python
    def Repair(self, points) -> None:
        """SDK App.py:5671 — add repair points to condition, clamped to
        [current, max]. Routed through SetCondition so the condition
        watchers and threshold state machine react."""
        if points is None:
            return
        points = float(points)
        if points <= 0.0:
            return
        self.SetCondition(min(self.GetMaxCondition(), self._condition + points))
```

- [ ] **Step 4: Seed complexity in SetupProperties**

In `engine/appc/ships.py`, `_copy_powered_subsystem_fields` (line 1186), add after the `GetDisabledPercentage` copy:

```python
        rc = prop.GetRepairComplexity()
        if rc is not None: subsystem.SetRepairComplexity(rc)
```

Do the same in the OTHER two copy sites so hull/engine-pod/child subsystems seed too:
- the generic `(prop.GetX, receiver.SetX)` tuple loop at `ships.py:~898` — add `(prop.GetRepairComplexity,  receiver.SetRepairComplexity),`
- the engine-pod tuple loop at `ships.py:1157–1164` — add `(prop.GetRepairComplexity, pod.SetRepairComplexity),`

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_repair_subsystem.py tests/unit/test_setup_properties_* -q`
Expected: PASS (setup_properties suites confirm no regression from the extra copy).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystems.py engine/appc/ships.py tests/unit/test_repair_subsystem.py
git commit -m "feat(repair): ShipSubsystem.Repair() + RepairComplexity seeded from hardpoint properties"
```

---

### Task 3: Threshold events — disabled / destroyed / operational

**Files:**
- Modify: `engine/appc/subsystems.py` (`ShipSubsystem.__init__` ~line 213, `_condition_changed` at 444–451; new helpers after `GetCombinedPercentageWatcher` ~line 706)
- Test: `tests/unit/test_subsystem_threshold_events.py` (create)

**Interfaces:**
- Produces: broadcasts of `App.ET_SUBSYSTEM_DISABLED` / `ET_SUBSYSTEM_DESTROYED` / `ET_SUBSYSTEM_OPERATIONAL` per the payload-contract table (TGEvent, source=subsystem, dest=owning ship). Internal: `ShipSubsystem._owning_ship() -> ship | None` (walks `_parent_ship` then the `_parent_subsystem` chain — child subsystems have no `_parent_ship`; `AddChildSubsystem` at `subsystems.py:732` sets only `_parent_subsystem`). Later tasks (4, 5, 6) reuse `_owning_ship`.
- Consumes: Task 1 constants; `App.TGEvent_Create` (`engine/appc/events.py:39`); `App.g_kEventManager.AddEvent`.

- [ ] **Step 1: Write the failing tests**

```python
"""Threshold-crossing events on ShipSubsystem condition changes."""
import App
from engine.appc.subsystems import ShipSubsystem


def _capture(monkeypatch):
    fired = []
    orig = App.g_kEventManager.AddEvent
    def spy(evt):
        fired.append(evt)
        orig(evt)
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", spy)
    return fired


def _types(fired):
    return [e.GetEventType() for e in fired]


def _sub(max_condition=1000.0, disabled_pct=0.25):
    s = ShipSubsystem("Sensors")
    s.SetMaxCondition(max_condition)
    s.SetDisabledPercentage(disabled_pct)
    return s


def test_crossing_into_disabled_fires_once(monkeypatch):
    s = _sub()
    fired = _capture(monkeypatch)
    s.SetCondition(200.0)          # 20% <= 25% -> disabled
    assert _types(fired) == [App.ET_SUBSYSTEM_DISABLED]
    s.SetCondition(150.0)          # still disabled -> no re-fire
    assert _types(fired) == [App.ET_SUBSYSTEM_DISABLED]


def test_destroyed_fires_and_beats_disabled(monkeypatch):
    s = _sub()
    fired = _capture(monkeypatch)
    s.SetCondition(0.0)            # straight to destroyed
    assert _types(fired) == [App.ET_SUBSYSTEM_DESTROYED]


def test_repair_back_above_threshold_fires_operational(monkeypatch):
    s = _sub()
    s.SetCondition(100.0)          # disabled
    fired = _capture(monkeypatch)
    s.Repair(400.0)                # 50% -> operational
    assert App.ET_SUBSYSTEM_OPERATIONAL in _types(fired)


def test_destroyed_to_disabled_is_silent(monkeypatch):
    s = _sub()
    s.SetCondition(0.0)
    fired = _capture(monkeypatch)
    s.Repair(100.0)                # 10% — above 0, still <= 25%
    assert _types(fired) == []     # no event for destroyed->disabled


def test_event_shape_source_sub_dest_ship(monkeypatch):
    from engine.appc.ships import ShipClass_CreateWithSubsystems
    ship = ShipClass_CreateWithSubsystems("Shape")
    sensors = ship.GetSensorSubsystem()
    sensors.SetMaxCondition(1000.0)
    fired = _capture(monkeypatch)
    sensors.SetCondition(0.0)
    destroyed = [e for e in fired
                 if e.GetEventType() == App.ET_SUBSYSTEM_DESTROYED]
    assert len(destroyed) == 1
    assert destroyed[0].GetSource() is sensors
    assert destroyed[0].GetDestination() is ship


def test_child_subsystem_resolves_ship_via_parent_chain(monkeypatch):
    from engine.appc.ships import ShipClass_CreateWithSubsystems
    ship = ShipClass_CreateWithSubsystems("Chain")
    parent = ship.GetSensorSubsystem()
    child = ShipSubsystem("Sensor Dish")
    child.SetMaxCondition(500.0)
    parent.AddChildSubsystem(child)
    fired = _capture(monkeypatch)
    child.SetCondition(0.0)
    destroyed = [e for e in fired
                 if e.GetEventType() == App.ET_SUBSYSTEM_DESTROYED]
    assert destroyed and destroyed[0].GetDestination() is ship
```

(Adjust the ship factory name to the real one at `ships.py:1450–1474` as in Task 2.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_subsystem_threshold_events.py -v`
Expected: FAIL — no events fired (`_types(fired) == []` where events expected).

- [ ] **Step 3: Implement the state machine**

In `engine/appc/subsystems.py`. Module-level constants above `class ShipSubsystem` (line ~130):

```python
# Threshold states for the disabled/destroyed/operational event machine.
_THRESHOLD_OPERATIONAL = 0
_THRESHOLD_DISABLED    = 1
_THRESHOLD_DESTROYED   = 2
```

Field in `__init__` (next to `_disabled_percentage`):

```python
        # Current threshold state; transitions fire ET_SUBSYSTEM_DISABLED /
        # DESTROYED / OPERATIONAL (stock BC posts these from C++
        # ShipSubsystem::SetCondition; EngineerCharacterHandlers +
        # AI Conditions consume them).
        self._threshold_state: int = _THRESHOLD_OPERATIONAL
```

Extend `_condition_changed` (line 444) — keep the watcher push, add the transition check:

```python
    def _condition_changed(self) -> None:
        """Push the fresh condition FRACTION into the combined watcher (if one
        was ever handed out) so its registered threshold crossings fire, then
        advance the disabled/destroyed/operational state machine."""
        if self._combined_watcher is not None:
            self._combined_watcher._update(self.GetConditionPercentage())
        new_state = self._threshold_state_now()
        old_state = self._threshold_state
        if new_state != old_state:
            self._threshold_state = new_state
            if new_state == _THRESHOLD_DESTROYED:
                self._fire_threshold_event("ET_SUBSYSTEM_DESTROYED")
            elif new_state == _THRESHOLD_DISABLED and old_state == _THRESHOLD_OPERATIONAL:
                self._fire_threshold_event("ET_SUBSYSTEM_DISABLED")
            elif new_state == _THRESHOLD_OPERATIONAL:
                self._fire_threshold_event("ET_SUBSYSTEM_OPERATIONAL")
            # destroyed -> disabled (partial repair from zero) is silent.

    def _threshold_state_now(self) -> int:
        if self._condition <= 0.0 and self._max_condition > 0.0:
            return _THRESHOLD_DESTROYED
        if self.IsDisabled():
            return _THRESHOLD_DISABLED
        return _THRESHOLD_OPERATIONAL
```

Helpers after `GetCombinedPercentageWatcher` (~line 706):

```python
    def _owning_ship(self):
        """Resolve the ship owning this subsystem. Top-level subsystems have
        _parent_ship set by ShipClass._attach_subsystem; child subsystems
        (AddChildSubsystem) only have _parent_subsystem — walk up."""
        obj, hops = self, 0
        while obj is not None and hops < 16:
            ship = getattr(obj, "_parent_ship", None)
            if ship is not None:
                return ship
            obj = getattr(obj, "_parent_subsystem", None)
            hops += 1
        return None

    def _fire_threshold_event(self, event_attr: str) -> None:
        """Broadcast a threshold event: source=this subsystem, destination=
        owning ship (EngineerCharacterHandlers filters destination against the
        player; AI Conditions match the ship). Raise-safe, same pattern as
        CloakingSubsystem._fire — a missing event manager never breaks
        condition mutation (unit fixtures mutate subsystems with no App)."""
        try:
            import App
            ship = self._owning_ship()
            evt = App.TGEvent_Create()
            evt.SetEventType(getattr(App, event_attr))
            evt.SetSource(self)
            evt.SetDestination(ship if ship is not None else self)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("subsystem threshold event", _e)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_subsystem_threshold_events.py -v`
Expected: PASS.

- [ ] **Step 5: Run the wider unit suite (event spam / ship-death interactions)**

Run: `uv run pytest tests/unit -q -x -k "subsystem or shield or apply_hit or death or cloak"`
Expected: PASS. If a ship-death test now sees extra events: the SDK handlers all guard `IsDying()` so extra broadcasts are correct behaviour — fix the *test expectation* only if it asserted an exact event list, and say so in the commit message.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_subsystem_threshold_events.py
git commit -m "feat(repair): ET_SUBSYSTEM_DISABLED/DESTROYED/OPERATIONAL fire from the ShipSubsystem condition path"
```

---

### Task 4: RepairSubsystem queue core

**Files:**
- Modify: `engine/appc/subsystems.py` (replace the placeholder `class RepairSubsystem` at line 1396–1401)
- Test: `tests/unit/test_repair_subsystem.py` (extend)

**Interfaces:**
- Produces: `RepairSubsystem.AddToRepairList(sub) -> int` (1 added / 0 rejected), `AddSubsystem = AddToRepairList`, `IsBeingRepaired(sub) -> int`, `GetMaxRepairPoints() -> float`, `GetNumRepairTeams() -> int`, internal `._queue: list`, `._fire_repair_event(event_attr, sub, dest)` (reused by Tasks 6/7). `IsOn()` defaults to 1.
- Consumes: `RepairSubsystemProperty` data-bag accessors `GetMaxRepairPoints()` / `GetNumRepairTeams()` (authored by hardpoints, e.g. Galaxy 50.0/3 — property binding already done at `ships.py:969–974`); `App.TGObjPtrEvent_Create` (`engine/appc/actions.py:932`).

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_repair_subsystem.py`)

```python
from engine.appc.subsystems import RepairSubsystem


def _bay(points=50.0, teams=3):
    from engine.appc.properties import RepairSubsystemProperty
    bay = RepairSubsystem("Engineering")
    bay.SetMaxCondition(8000.0)
    prop = RepairSubsystemProperty("Engineering")
    prop.SetMaxRepairPoints(points)   # data-bag setters, as hardpoints do
    prop.SetNumRepairTeams(teams)
    bay.SetProperty(prop)
    return bay


def test_bay_is_on_by_default():
    assert RepairSubsystem("Engineering").IsOn() == 1


def test_property_readers_with_and_without_property():
    assert _bay(50.0, 3).GetMaxRepairPoints() == 50.0
    assert _bay(50.0, 3).GetNumRepairTeams() == 3
    bare = RepairSubsystem("Engineering")
    assert bare.GetMaxRepairPoints() == 0.0
    assert bare.GetNumRepairTeams() == 0


def test_add_accepts_damaged_rejects_dup_destroyed_undamaged():
    bay = _bay()
    damaged = _sub(condition=400.0)
    assert bay.AddToRepairList(damaged) == 1
    assert bay.AddToRepairList(damaged) == 0          # duplicate
    assert bay.AddToRepairList(_sub(condition=0.0)) == 0    # destroyed
    assert bay.AddToRepairList(_sub()) == 0           # undamaged (full)
    assert bay.AddToRepairList(None) == 0
    assert len(bay._queue) == 1


def test_add_fires_add_to_repair_list_event(monkeypatch):
    import App
    fired = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent",
                        lambda evt: fired.append(evt))
    bay = _bay()
    damaged = _sub(condition=400.0)
    bay.AddToRepairList(damaged)
    assert [e.GetEventType() for e in fired] == [App.ET_ADD_TO_REPAIR_LIST]
    assert fired[0].GetSource() is damaged
    assert fired[0].GetObjPtr() is damaged
    assert fired[0].GetDestination() is bay


def test_is_being_repaired_is_first_num_teams_entries():
    bay = _bay(teams=2)
    subs = [_sub(name="s%d" % i, condition=100.0) for i in range(4)]
    for s in subs:
        bay.AddToRepairList(s)
    assert bay.IsBeingRepaired(subs[0]) == 1
    assert bay.IsBeingRepaired(subs[1]) == 1
    assert bay.IsBeingRepaired(subs[2]) == 0    # waiting
    assert bay.IsBeingRepaired(subs[3]) == 0
    assert bay.IsBeingRepaired(_sub(condition=1.0)) == 0  # not queued


def test_add_subsystem_is_the_sdk_alias():
    bay = _bay()
    damaged = _sub(condition=400.0)
    assert bay.AddSubsystem(damaged) == 1
    assert bay.IsBeingRepaired(damaged) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_repair_subsystem.py -v`
Expected: FAIL — `IsOn()` returns 0 (PoweredSubsystem default is off), `AddToRepairList` is a `_Stub`.

- [ ] **Step 3: Implement the queue core**

Replace `engine/appc/subsystems.py:1396–1401` with:

```python
class RepairSubsystem(PoweredSubsystem):
    """Engineering / damage-control subsystem — the per-ship repair queue.

    SDK surface (App.py:6639-6662): AddSubsystem, AddToRepairList,
    IsBeingRepaired, plus the inherited ShipSubsystem/PoweredSubsystem
    methods. Queue semantics + tick formula are RE-verified
    (docs/original_game_reference/gameplay/ship-subsystems.md §Repair):
    duplicates rejected, destroyed (condition<=0) rejected, undamaged
    rejected; first NumRepairTeams entries are "being repaired".
    """

    def __init__(self, name: str = ""):
        super().__init__(name)
        # RE layout: +0x9C (isOn) inits to 1 — the bay ticks and draws
        # power without ever being switched on.
        self._is_on = True
        # Ordered repair queue (head = active). Python list of subsystem
        # refs; identity comparisons throughout (TGObject __eq__ is not
        # trusted).
        self._queue: list = []
        # id(sub) values already notified ET_REPAIR_CANNOT_BE_COMPLETED
        # (destroyed-while-queued fires once, not per tick).
        self._cannot_complete_notified: set = set()

    # ── Property readers (RepairSubsystemProperty data-bag) ────────────────
    def GetMaxRepairPoints(self) -> float:
        prop = self._property
        if prop is not None:
            v = prop.GetMaxRepairPoints()
            if v is not None:
                return float(v)
        return 0.0

    def GetNumRepairTeams(self) -> int:
        prop = self._property
        if prop is not None:
            v = prop.GetNumRepairTeams()
            if v is not None:
                return int(v)
        return 0

    # ── Queue ───────────────────────────────────────────────────────────────
    def AddToRepairList(self, sub) -> int:
        """Queue a damaged subsystem for repair. Returns 1 on add, 0 on
        reject (None / duplicate / destroyed / undamaged) — mirrors stock
        AddSubsystem which walks the list before insertion and explicitly
        checks condition > 0."""
        if sub is None or sub is True or sub is False:
            return 0
        if not hasattr(sub, "GetCondition"):
            return 0
        if any(s is sub for s in self._queue):
            return 0
        cond = sub.GetCondition()
        if cond <= 0.0:
            return 0
        if cond >= sub.GetMaxCondition():
            return 0
        self._queue.append(sub)
        self._fire_repair_event("ET_ADD_TO_REPAIR_LIST", sub, dest=self)
        return 1

    # SDK exposes both spellings for the same insert (App.py:6660-6661).
    AddSubsystem = AddToRepairList

    def IsBeingRepaired(self, sub) -> int:
        """True iff sub is within the first NumRepairTeams queue entries —
        stock walks exactly that many nodes (FUN_00565890)."""
        n = self.GetNumRepairTeams()
        return 1 if any(s is sub for s in self._queue[:n]) else 0

    # ── Event emission ──────────────────────────────────────────────────────
    def _fire_repair_event(self, event_attr: str, sub, dest=None) -> None:
        """TGObjPtrEvent with source=sub AND objptr=sub: the SDK
        RepairCompleted handler dereferences BOTH GetSource() and
        GetObjPtr() (EngineerCharacterHandlers.py:294-336). dest defaults
        to the owning ship (player filtering)."""
        try:
            import App
            if dest is None:
                ship = self._owning_ship()
                dest = ship if ship is not None else self
            evt = App.TGObjPtrEvent_Create()
            evt.SetEventType(getattr(App, event_attr))
            evt.SetSource(sub)
            evt.SetObjPtr(sub)
            evt.SetDestination(dest)
            App.g_kEventManager.AddEvent(evt)
        except Exception as _e:
            dev_mode.log_swallowed("repair event broadcast", _e)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_repair_subsystem.py tests/unit/test_ship_power_repair_slots.py tests/unit/test_power_repair_subsystems.py -v`
Expected: PASS (the two existing repair-slot suites confirm the placeholder replacement kept the slot contract).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_repair_subsystem.py
git commit -m "feat(repair): RepairSubsystem queue — add/reject rules, IsBeingRepaired, ET_ADD_TO_REPAIR_LIST"
```

---

### Task 5: Auto-enqueue on damage

**Files:**
- Modify: `engine/appc/subsystems.py` (`ShipSubsystem.SetCondition` at 412–415)
- Test: `tests/unit/test_repair_subsystem.py` (extend)

**Interfaces:**
- Produces: any condition *decrease* below max on a subsystem with a resolvable owning ship calls `ship.GetRepairSubsystem().AddToRepairList(self)` (our synchronous equivalent of stock's `SetCondition → ET_SUBSYSTEM_HIT → RepairSubsystem::HandleHitEvent` chain).
- Consumes: Task 3 `_owning_ship()`; Task 4 `AddToRepairList` (validation lives there — destroyed/duplicate/undamaged all reject, so this hook stays dumb).

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_repair_subsystem.py`)

```python
def _damaged_ship():
    from engine.appc.ships import ShipClass_CreateWithSubsystems
    from engine.appc.properties import RepairSubsystemProperty
    ship = ShipClass_CreateWithSubsystems("AutoQ")
    prop = RepairSubsystemProperty("Engineering")
    prop.SetMaxRepairPoints(50.0)
    prop.SetNumRepairTeams(3)
    ship.GetRepairSubsystem().SetProperty(prop)
    ship.GetSensorSubsystem().SetMaxCondition(8000.0)
    return ship


def test_damage_auto_enqueues_subsystem():
    ship = _damaged_ship()
    sensors = ship.GetSensorSubsystem()
    sensors.SetCondition(4000.0)                      # damage
    assert ship.GetRepairSubsystem().IsBeingRepaired(sensors) == 1


def test_repair_increase_does_not_enqueue():
    ship = _damaged_ship()
    sensors = ship.GetSensorSubsystem()
    sensors.SetCondition(4000.0)
    ship.GetRepairSubsystem()._queue.clear()
    sensors.Repair(100.0)                             # increase only
    assert ship.GetRepairSubsystem()._queue == []


def test_destroying_hit_does_not_enqueue():
    ship = _damaged_ship()
    sensors = ship.GetSensorSubsystem()
    sensors.SetCondition(0.0)                         # straight to destroyed
    assert ship.GetRepairSubsystem()._queue == []


def test_bay_enqueues_itself_when_damaged():
    ship = _damaged_ship()
    bay = ship.GetRepairSubsystem()
    bay.SetMaxCondition(8000.0)
    bay.SetCondition(4000.0)
    assert any(s is bay for s in bay._queue)


def test_orphan_subsystem_damage_is_safe():
    s = _sub(condition=500.0)     # no ship anywhere
    s.SetCondition(100.0)         # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_repair_subsystem.py -v -k "auto or enqueue or orphan or itself"`
Expected: FAIL — queue stays empty after damage.

- [ ] **Step 3: Implement the hook**

Replace `SetCondition` (`subsystems.py:412–415`):

```python
    def SetCondition(self, value: float) -> None:
        """Floor at zero. Combat damage routes through here (see
        engine/appc/objects.py). A decrease below max auto-enqueues this
        subsystem on the owning ship's repair bay — the synchronous
        equivalent of stock's ET_SUBSYSTEM_HIT -> RepairSubsystem::
        HandleHitEvent chain. AddToRepairList owns all validation
        (duplicate / destroyed / undamaged reject)."""
        old = self._condition
        self._condition = max(0.0, float(value))
        self._condition_changed()
        if self._condition < old:
            self._auto_enqueue_for_repair()

    def _auto_enqueue_for_repair(self) -> None:
        ship = self._owning_ship()
        if ship is None:
            return
        try:
            bay = ship.GetRepairSubsystem()
            if bay is not None and hasattr(bay, "AddToRepairList"):
                bay.AddToRepairList(self)
        except Exception as _e:
            dev_mode.log_swallowed("repair auto-enqueue", _e)
```

- [ ] **Step 4: Run tests + the damage suites**

Run: `uv run pytest tests/unit/test_repair_subsystem.py tests/unit -q -k "apply_hit or damage"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_repair_subsystem.py
git commit -m "feat(repair): damaged subsystems auto-enqueue on the owning ship's repair bay"
```

---

### Task 6: Repair tick — Update(dt), completion, cannot-complete, loop wiring

**Files:**
- Modify: `engine/appc/subsystems.py` (`RepairSubsystem` from Task 4)
- Modify: `engine/core/loop.py` (per-ship subsystem pass, currently lines 48–59 — **if the power feature moved this pass, edit its new home instead; the shape is identical**)
- Test: `tests/unit/test_repair_subsystem.py` (extend), `tests/unit/test_gameloop_repair_tick.py` (create)

**Interfaces:**
- Produces: `RepairSubsystem.Update(dt: float) -> None` — the RE tick; emits `ET_REPAIR_COMPLETED` (target removed from queue) and `ET_REPAIR_CANNOT_BE_COMPLETED` (destroyed-while-queued, once). `GameLoop.tick()` calls it for every ship.
- Consumes: Task 2 `Repair`/`GetRepairComplexity`; Task 4 queue + `_fire_repair_event`.

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_repair_subsystem.py`)

```python
def test_tick_formula_matches_re_worked_example():
    # Sovereign: 50 pts, healthy bay, 2 queued, 30fps tick (dt=0.033):
    # raw=1.65, perItem=0.825; phaser c=3.0 -> +0.275; tractor c=7.0 -> +0.118
    bay = _bay(points=50.0, teams=3)
    phaser  = _sub(name="Phasers", max_condition=1000.0, condition=500.0,
                   complexity=3.0)
    tractor = _sub(name="Tractor", max_condition=1000.0, condition=500.0,
                   complexity=7.0)
    bay.AddToRepairList(phaser)
    bay.AddToRepairList(tractor)
    bay.Update(0.033)
    assert abs(phaser.GetCondition()  - 500.275) < 1e-6
    assert abs(tractor.GetCondition() - (500.0 + 0.825 / 7.0)) < 1e-6


def test_bay_health_scales_output():
    bay = _bay(points=50.0, teams=3)
    bay.SetCondition(4000.0)                    # 50% bay health
    target = _sub(condition=500.0, complexity=1.0)
    bay.AddToRepairList(target)
    bay.Update(1.0)
    # raw = 50 * 0.5 * 1.0 = 25, one item -> +25
    assert abs(target.GetCondition() - 525.0) < 1e-6


def test_destroyed_bay_repairs_nothing():
    bay = _bay()
    target = _sub(condition=500.0)
    bay.AddToRepairList(target)
    bay.SetCondition(0.0)
    bay.Update(1.0)
    assert target.GetCondition() == 500.0


def test_team_cap_and_divisor_with_queue_longer_than_teams():
    bay = _bay(points=60.0, teams=2)
    subs = [_sub(name="s%d" % i, condition=100.0, complexity=1.0)
            for i in range(3)]
    for s in subs:
        bay.AddToRepairList(s)
    bay.Update(1.0)
    # raw=60, divisor=min(3,2)=2, perItem=30: first two get +30, third waits
    assert abs(subs[0].GetCondition() - 130.0) < 1e-6
    assert abs(subs[1].GetCondition() - 130.0) < 1e-6
    assert subs[2].GetCondition() == 100.0


def test_completion_removes_and_fires(monkeypatch):
    import App
    fired = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent",
                        lambda e: fired.append(e))
    bay = _bay(points=50.0, teams=3)
    nearly = _sub(condition=999.9, complexity=1.0)
    bay.AddToRepairList(nearly)
    bay.Update(1.0)
    assert nearly.GetCondition() == 1000.0
    assert not any(s is nearly for s in bay._queue)
    assert App.ET_REPAIR_COMPLETED in [e.GetEventType() for e in fired]


def test_destroyed_while_queued_skipped_notified_once(monkeypatch):
    import App
    fired = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent",
                        lambda e: fired.append(e))
    bay = _bay(points=50.0, teams=2)
    doomed = _sub(name="doomed", condition=500.0)
    other  = _sub(name="other",  condition=500.0, complexity=1.0)
    bay.AddToRepairList(doomed)
    bay.AddToRepairList(other)
    doomed._condition = 0.0                     # destroyed in place, bypass hooks
    bay.Update(1.0)
    bay.Update(1.0)
    cannot = [e for e in fired
              if e.GetEventType() == App.ET_REPAIR_CANNOT_BE_COMPLETED]
    assert len(cannot) == 1                     # once, not per tick
    assert cannot[0].GetSource() is doomed
    assert any(s is doomed for s in bay._queue)  # skipped, NOT removed
    # 'other' still got a full team's share: raw=50*1*1=50, divisor=min(2,2)=2
    assert abs(other.GetCondition() - 525.0) < 1e-6


def test_self_repair_bay_queued_on_itself():
    bay = _bay(points=50.0, teams=3)
    bay.SetCondition(4000.0)                    # auto-enqueue needs a ship; add manually
    bay.AddToRepairList(bay)
    before = bay.GetCondition()
    bay.Update(1.0)
    assert bay.GetCondition() > before
```

And `tests/unit/test_gameloop_repair_tick.py`:

```python
"""GameLoop drives RepairSubsystem.Update for every simulated ship."""


def test_gameloop_ticks_repair(monkeypatch):
    from engine.core.loop import GameLoop, TICK_DELTA
    import engine.appc.ship_iter as ship_iter

    ticked = []

    class _Bay:
        def Update(self, dt):
            ticked.append(dt)

    class _Ship:
        def GetShieldSubsystem(self): return None
        def GetPowerSubsystem(self): return None
        def GetCloakingSubsystem(self): return None
        def GetRepairSubsystem(self): return self._bay
        def __init__(self): self._bay = _Bay()

    monkeypatch.setattr("engine.core.loop.iter_ships", lambda: [_Ship()])
    GameLoop().tick()
    assert ticked == [TICK_DELTA]
```

(If the power feature renamed/moved the subsystem pass, monkeypatch the
`iter_ships` symbol at its actual import site in `engine/core/loop.py` —
the test's assertion is the contract.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_repair_subsystem.py tests/unit/test_gameloop_repair_tick.py -v`
Expected: FAIL — `Update` is inherited no-op (`_Stub` or missing), conditions unchanged.

- [ ] **Step 3: Implement Update(dt)**

Add to `RepairSubsystem` (after `IsBeingRepaired`):

```python
    def Update(self, dt) -> None:
        """The RE-verified repair tick (ship-subsystems.md §Repair):

            raw     = MaxRepairPoints * bayConditionPct * dt
            perItem = raw / min(queueCount, NumRepairTeams)
            gain_i  = perItem / target_i.RepairComplexity

        Walks from the head assigning up to NumRepairTeams teams to
        non-destroyed entries. Destroyed entries are skipped (stay queued,
        per stock), fire ET_REPAIR_CANNOT_BE_COMPLETED once, and consume
        no team. Completion removes the entry and fires
        ET_REPAIR_COMPLETED. NO power-efficiency term — output scales
        only by the bay's own health (spec + power spec agree)."""
        if dt is None or dt <= 0.0 or not self._queue:
            return
        if self.GetCondition() <= 0.0:
            return
        teams = self.GetNumRepairTeams()
        points = self.GetMaxRepairPoints()
        if teams <= 0 or points <= 0.0:
            return
        raw = points * self.GetConditionPercentage() * float(dt)
        per_item = raw / min(len(self._queue), teams)
        assigned = 0
        completed = []
        for sub in list(self._queue):
            if assigned >= teams:
                break
            if sub.GetCondition() <= 0.0:
                if id(sub) not in self._cannot_complete_notified:
                    self._cannot_complete_notified.add(id(sub))
                    self._fire_repair_event(
                        "ET_REPAIR_CANNOT_BE_COMPLETED", sub)
                continue
            self._cannot_complete_notified.discard(id(sub))
            assigned += 1
            complexity = sub.GetRepairComplexity()
            if complexity <= 0.0:
                complexity = 1.0
            sub.Repair(per_item / complexity)
            if sub.GetCondition() >= sub.GetMaxCondition():
                completed.append(sub)
        for sub in completed:
            self._queue = [s for s in self._queue if s is not sub]
            self._fire_repair_event("ET_REPAIR_COMPLETED", sub)
```

- [ ] **Step 4: Wire the loop**

In `engine/core/loop.py`, extend the per-ship pass (after the cloak block at lines 55–59; or wherever the power feature moved this pass):

```python
            # Repair bay: advance the repair queue (RE tick — see
            # RepairSubsystem.Update). AI ships repair themselves too.
            rs = ship.GetRepairSubsystem()
            if rs is not None:
                rs.Update(TICK_DELTA)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_repair_subsystem.py tests/unit/test_gameloop_repair_tick.py tests/unit/test_gameloop_shield_regen.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystems.py engine/core/loop.py \
    tests/unit/test_repair_subsystem.py tests/unit/test_gameloop_repair_tick.py
git commit -m "feat(repair): RE-verified repair tick — team split, complexity divisor, completed/cannot-complete events, loop wiring"
```

---

### Task 7: Priority toggle — ET_REPAIR_INCREASE_PRIORITY

**Files:**
- Modify: `engine/appc/subsystems.py` (`RepairSubsystem.__init__` + new method + module-level handler)
- Test: `tests/unit/test_repair_subsystem.py` (extend)

**Interfaces:**
- Produces: `RepairSubsystem.HandleIncreasePriority(sub) -> None` (binary toggle: being-repaired → tail; waiting → head; not-queued → no-op); module function `engine.appc.subsystems.HandleRepairPriorityEvent(pObject, pEvent)` registered as an instance handler so a `TGObjPtrEvent` with `destination=repair subsystem` + `objptr=target` posted via `App.g_kEventManager.AddEvent` performs the toggle (`AddEvent` routes destination instance handlers through `ProcessEvent`, `events.py:351–360`). Task 8's UI posts exactly that event.
- Consumes: Task 1 `ET_REPAIR_INCREASE_PRIORITY`; `TGEventHandlerObject.AddPythonFuncHandlerForInstance(event_type, qualified_name)` (`events.py:192`).

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_repair_subsystem.py`)

```python
def _queued_bay(teams=2, n=4):
    bay = _bay(teams=teams)
    subs = [_sub(name="s%d" % i, condition=100.0) for i in range(n)]
    for s in subs:
        bay.AddToRepairList(s)
    return bay, subs


def test_toggle_demotes_active_to_tail():
    bay, subs = _queued_bay()
    bay.HandleIncreasePriority(subs[0])          # active (idx 0 < teams 2)
    assert bay._queue[-1] is subs[0]
    assert bay.IsBeingRepaired(subs[0]) == 0


def test_toggle_promotes_waiting_to_head():
    bay, subs = _queued_bay()
    bay.HandleIncreasePriority(subs[3])          # waiting
    assert bay._queue[0] is subs[3]
    assert bay.IsBeingRepaired(subs[3]) == 1


def test_toggle_unqueued_is_noop():
    bay, subs = _queued_bay()
    before = list(bay._queue)
    bay.HandleIncreasePriority(_sub(condition=1.0))
    assert bay._queue == before


def test_priority_event_routes_to_toggle():
    import App
    bay, subs = _queued_bay()
    evt = App.TGObjPtrEvent_Create()
    evt.SetEventType(App.ET_REPAIR_INCREASE_PRIORITY)
    evt.SetDestination(bay)
    evt.SetObjPtr(subs[3])
    App.g_kEventManager.AddEvent(evt)
    assert bay._queue[0] is subs[3]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_repair_subsystem.py -v -k toggle or priority`
Expected: FAIL — `HandleIncreasePriority` is a `_Stub` no-op.

- [ ] **Step 3: Implement the toggle + instance handler**

Add to `RepairSubsystem`:

```python
    def HandleIncreasePriority(self, sub) -> None:
        """Stock's binary toggle (FUN_00565B50), NOT move-up-one: an entry
        within the first NumRepairTeams nodes (actively repaired) demotes
        to tail; a waiting entry promotes to head; unqueued is a no-op."""
        idx = next((i for i, s in enumerate(self._queue) if s is sub), None)
        if idx is None:
            return
        active = idx < self.GetNumRepairTeams()
        del self._queue[idx]
        if active:
            self._queue.append(sub)
        else:
            self._queue.insert(0, sub)
```

In `RepairSubsystem.__init__`, register the instance handler (lazy App import — App itself imports this module at load, see `CloakingSubsystem._fire` for the precedent):

```python
        # ET_REPAIR_INCREASE_PRIORITY posted with destination=this bay
        # (EngRepairPane click) routes to the toggle via the instance-
        # handler chain. Lazy-guarded: during App's own import the constant
        # isn't there yet; runtime construction always has App loaded.
        try:
            import App
            self.AddPythonFuncHandlerForInstance(
                App.ET_REPAIR_INCREASE_PRIORITY,
                "engine.appc.subsystems.HandleRepairPriorityEvent")
        except Exception as _e:
            dev_mode.log_swallowed("repair priority handler registration", _e)
```

Module-level handler (bottom of `subsystems.py`, near the other module helpers):

```python
def HandleRepairPriorityEvent(pObject, pEvent):
    """Instance handler for ET_REPAIR_INCREASE_PRIORITY on a RepairSubsystem.
    Signature matches TGEventHandlerObject dispatch: fn(dest_object, event)."""
    sub = pEvent.GetObjPtr() if hasattr(pEvent, "GetObjPtr") else None
    if isinstance(pObject, RepairSubsystem) and sub is not None:
        pObject.HandleIncreasePriority(sub)
    pObject.CallNextHandler(pEvent)
```

If `_resolve_handler` (`engine/appc/events.py`) can't resolve the dotted
`engine.appc.subsystems.` prefix, check how it splits module/function
(read `_resolve_handler` in `events.py`) and use the format it expects —
the SDK convention is `"ModuleName.func"` with the module importable by
that name; `engine.appc.subsystems` is importable, so last-dot splitting
works. Verify with the routing test.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_repair_subsystem.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_repair_subsystem.py
git commit -m "feat(repair): binary priority toggle wired to ET_REPAIR_INCREASE_PRIORITY instance handler"
```

---

### Task 8: EngRepairPane — CEF repair-queue UI

**Files:**
- Modify: `App.py` (`class EngRepairPane` at 1328, `EngRepairPane_Create` at 1586)
- Create: `engine/ui/eng_repair_pane.py`
- Modify: `engine/ui/crew_menu_panel.py` (`_snapshot_node` at 69–95, `dispatch_event` at 97+)
- Modify: `native/assets/ui-cef/js/crew_menus.js` (row renderer, click wiring at ~lines 60–70)
- Modify: `native/assets/ui-cef/css/hello.css` (crew-menu styles live with the shared sheet)
- Test: `tests/unit/test_eng_repair_pane.py` (create)

**Interfaces:**
- Consumes: `App.EngRepairPane_Create(width, height, rows)` call from stock `EngineerMenuHandlers.py:84` (`pEngineeringMenu.AddChild(pRepairPane, ...)`); Task 4 queue + Task 7 event; `engine.ui.damage_icons.icon_num_for_subsystem` (glyph number); `ensure_widget_id` (`engine/appc/tg_ui/widgets.py`); `dauntlessEvent("crew-menu/<action>")` JS convention (`crew_menus.js:67-69`).
- Produces: `App.EngRepairPaneWidget` (the widget class, subclassing `_DisplayWidget` so all SDK layout calls keep working); `engine.ui.eng_repair_pane.repair_pane_snapshot(ship, register) -> dict` returning `{"repair": [...], "waiting": [...], "destroyed": [...]}` with rows `{"id": int, "label": str, "icon": int, "pct": int}`; CrewMenuPanel node `{"type": "repair-pane", ...areas}`; click action `repair:<id>`.

- [ ] **Step 1: Write the failing tests**

```python
"""EngRepairPane snapshot + click routing."""
import App
from engine.ui.eng_repair_pane import repair_pane_snapshot


def _ship_with_queue():
    from engine.appc.ships import ShipClass_CreateWithSubsystems
    from engine.appc.properties import RepairSubsystemProperty
    ship = ShipClass_CreateWithSubsystems("UI")
    prop = RepairSubsystemProperty("Engineering")
    prop.SetMaxRepairPoints(50.0)
    prop.SetNumRepairTeams(2)
    ship.GetRepairSubsystem().SetProperty(prop)
    for getter, mx in (
        (ship.GetSensorSubsystem, 8000.0),
        (ship.GetImpulseEngineSubsystem, 3000.0),
        (ship.GetWarpEngineSubsystem, 8000.0),
    ):
        getter().SetMaxCondition(mx)
    return ship


def test_snapshot_splits_repair_waiting_destroyed():
    ship = _ship_with_queue()
    ship.GetSensorSubsystem().SetCondition(4000.0)        # queued (active)
    ship.GetImpulseEngineSubsystem().SetCondition(1500.0) # queued (active)
    ship.GetWarpEngineSubsystem().SetCondition(4000.0)    # queued (waiting)
    ship.GetShieldSubsystem().SetMaxCondition(1000.0)
    ship.GetShieldSubsystem().SetCondition(0.0)           # destroyed
    reg = {}
    snap = repair_pane_snapshot(ship, reg.setdefault)
    assert len(snap["repair"]) == 2          # NumRepairTeams = 2
    assert len(snap["waiting"]) == 1
    assert any(r["pct"] == 50 for r in snap["repair"])
    destroyed_labels = [r["label"] for r in snap["destroyed"]]
    assert "Shield Generator" in destroyed_labels
    for row in snap["repair"] + snap["waiting"] + snap["destroyed"]:
        assert set(row) == {"id", "label", "icon", "pct"}


def test_snapshot_none_ship_or_bay_is_empty():
    assert repair_pane_snapshot(None, lambda *_: None) == {
        "repair": [], "waiting": [], "destroyed": []}


def test_destroyed_queue_entries_hidden_from_repair_and_waiting():
    ship = _ship_with_queue()
    sensors = ship.GetSensorSubsystem()
    sensors.SetCondition(4000.0)                          # queued
    sensors._condition = 0.0                              # dies while queued
    snap = repair_pane_snapshot(ship, lambda *_: None)
    labels = [r["label"] for r in snap["repair"] + snap["waiting"]]
    assert sensors.GetName() not in labels
    assert sensors.GetName() in [r["label"] for r in snap["destroyed"]]


def test_click_action_posts_priority_event(monkeypatch):
    from engine.ui.crew_menu_panel import CrewMenuPanel
    ship = _ship_with_queue()
    ship.GetSensorSubsystem().SetCondition(4000.0)
    ship.GetWarpEngineSubsystem().SetCondition(4000.0)
    ship.GetImpulseEngineSubsystem().SetCondition(1500.0)
    monkeypatch.setattr(App, "Game_GetCurrentPlayer", lambda: ship)
    panel = CrewMenuPanel()
    # Register subsystem ids the way render does, then click the waiting row.
    reg = panel._widgets_by_id
    snap = repair_pane_snapshot(ship, reg.__setitem__)
    waiting_id = snap["waiting"][0]["id"]
    panel.dispatch_event("repair:%d" % waiting_id)
    bay = ship.GetRepairSubsystem()
    assert bay._queue[0] is reg[waiting_id]               # promoted to head
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_eng_repair_pane.py -v`
Expected: FAIL with `ModuleNotFoundError: engine.ui.eng_repair_pane`.

- [ ] **Step 3: Implement the snapshot module**

Create `engine/ui/eng_repair_pane.py`:

```python
"""EngRepairPane — snapshot + click logic for the CEF repair-queue UI.

Widget identity lives in App.py (EngRepairPaneWidget, created by the
UNMODIFIED sdk Bridge/EngineerMenuHandlers.py:84 via EngRepairPane_Create
and added as a child of the Engineering STTopLevelMenu). CrewMenuPanel
projects it into CEF using this module's snapshot; clicks post
ET_REPAIR_INCREASE_PRIORITY back at the player's repair bay.

Spec: docs/superpowers/specs/2026-07-05-repair-system-design.md §4.
Three areas mirror stock (ship-subsystems.md §Engineering panel UI):
REPAIR = first NumRepairTeams queue entries, WAITING = the rest,
DESTROYED = ship subsystems at zero condition (derived from the ship's
subsystem list, NOT the queue; destroyed-but-still-queued entries are
excluded from REPAIR/WAITING).
"""
from __future__ import annotations

from engine.appc.tg_ui.widgets import ensure_widget_id
from engine.ui.damage_icons import icon_num_for_subsystem


def _row(sub, register) -> dict:
    wid = ensure_widget_id(sub)
    register(wid, sub)
    mx = sub.GetMaxCondition()
    pct = int(round(100.0 * sub.GetCondition() / mx)) if mx > 0 else 0
    return {
        "id": wid,
        "label": sub.GetName() or "",
        "icon": icon_num_for_subsystem(sub),
        "pct": pct,
    }


def _iter_ship_subsystems(ship):
    """Every top-level subsystem with a condition bar. Mirrors the damage
    subview's walk (engine/ui/ship_display_panel.py:_iter_damage_subsystems)
    — reuse that helper if its shape fits; otherwise walk the ship getters."""
    from engine.ui.ship_display_panel import _iter_damage_subsystems
    return _iter_damage_subsystems(ship)


def repair_pane_snapshot(ship, register) -> dict:
    """Build the three-area snapshot. `register(wid, sub)` records the
    id->subsystem mapping in the caller's click-dispatch table."""
    empty = {"repair": [], "waiting": [], "destroyed": []}
    if ship is None:
        return empty
    bay = ship.GetRepairSubsystem() if hasattr(ship, "GetRepairSubsystem") else None
    if bay is None or not hasattr(bay, "_queue"):
        return empty
    teams = bay.GetNumRepairTeams()
    live = [s for s in bay._queue if s.GetCondition() > 0.0]
    destroyed = [s for s in _iter_ship_subsystems(ship) if s.IsDestroyed()]
    return {
        "repair":    [_row(s, register) for s in live[:teams]],
        "waiting":   [_row(s, register) for s in live[teams:]],
        "destroyed": [_row(s, register) for s in destroyed],
    }
```

Implementation note: `icon_num_for_subsystem` and `_iter_damage_subsystems`
exist (`engine/ui/damage_icons.py`, `engine/ui/ship_display_panel.py:444`) —
verify their exact names/signatures when wiring and adapt the two import
lines (NOT the row shape) if they differ.

- [ ] **Step 4: Give the widget a real identity in App.py**

Replace `EngRepairPane_Create` (`App.py:1586`):

```python
class EngRepairPaneWidget(_DisplayWidget):
    """The live repair-queue pane. Created by the unmodified SDK
    (EngineerMenuHandlers.py:84) and added as a child of the Engineering
    menu; CrewMenuPanel detects this class and projects the queue via
    engine.ui.eng_repair_pane.repair_pane_snapshot."""
    def __init__(self, width=0.0, height=0.0, rows=0):
        super().__init__("EngRepairPane")
        self._pane_width, self._pane_height, self._pane_rows = width, height, rows


def EngRepairPane_Create(width=0.0, height=0.0, n=0) -> "EngRepairPaneWidget":
    pane = EngRepairPaneWidget(width, height, n)
    # Pre-seed one child (index 0 = DIVIDER) so GetNthChild(DIVIDER).Layout()
    # keeps working (SDK layout path).
    from engine.appc.tg_ui.widgets import TGPane
    pane.AddChild(TGPane())
    return pane
```

(Keep the existing `class EngRepairPane` constants at `App.py:1328` — SDK code references `App.EngRepairPane.DIVIDER`.)

- [ ] **Step 5: Project it through CrewMenuPanel**

In `engine/ui/crew_menu_panel.py` `_snapshot_node` (line 69), add a branch BEFORE the unrecognised-widget fallthrough:

```python
        import App as _App
        if isinstance(widget, _App.EngRepairPaneWidget):
            from engine.ui.eng_repair_pane import repair_pane_snapshot
            wid = ensure_widget_id(widget)
            self._widgets_by_id[wid] = widget
            player = _App.Game_GetCurrentPlayer()
            areas = repair_pane_snapshot(player, self._widgets_by_id.__setitem__)
            return {"id": wid, "type": "repair-pane",
                    "label": "Damage Control", "enabled": True,
                    "visible": bool(widget.IsVisible()), **areas}
```

In `dispatch_event`, add an action branch (same shape as `expand:`/`toggle:`):

```python
        if action.startswith("repair:"):
            try:
                wid = int(action[len("repair:"):])
            except ValueError:
                _logger.info("crew-menu: malformed repair action %r", action)
                return True
            sub = self._widgets_by_id.get(wid)
            player = None
            import App as _App
            player = _App.Game_GetCurrentPlayer()
            bay = player.GetRepairSubsystem() if player is not None else None
            if sub is None or bay is None:
                _logger.info("crew-menu: stale repair id %d dropped", wid)
                return True
            evt = _App.TGObjPtrEvent_Create()
            evt.SetEventType(_App.ET_REPAIR_INCREASE_PRIORITY)
            evt.SetDestination(bay)
            evt.SetObjPtr(sub)
            _App.g_kEventManager.AddEvent(evt)
            self._last_pushed = None      # force re-render with new order
            return True
```

- [ ] **Step 6: Run the Python tests**

Run: `uv run pytest tests/unit/test_eng_repair_pane.py tests/unit/test_crew_menu_* -q`
Expected: PASS.

- [ ] **Step 7: Render in JS**

In `native/assets/ui-cef/js/crew_menus.js`, in the node renderer where `node.type` is switched (buttons at ~line 60–70), add a `repair-pane` case:

```javascript
      if (node.type === "repair-pane") {
        const pane = document.createElement("div");
        pane.className = "crew-repair-pane";
        const areas = [
          ["REPAIRING",  node.repair,    true],
          ["WAITING",    node.waiting,   true],
          ["DESTROYED",  node.destroyed, false],
        ];
        for (const [title, rows, clickable] of areas) {
          if (!rows || !rows.length) continue;
          const h = document.createElement("div");
          h.className = "crew-repair-area-title";
          h.textContent = title;
          pane.appendChild(h);
          for (const r of rows) {
            const row = document.createElement("div");
            row.className = "crew-repair-row" + (clickable ? "" : " inert");
            row.textContent = r.label + " — " + r.pct + "%";
            if (clickable) {
              row.onclick = () => dauntlessEvent("crew-menu/repair:" + r.id);
            }
            pane.appendChild(row);
          }
        }
        container.appendChild(pane);
        return;   // match the surrounding early-return style per node type
      }
```

Adapt variable names (`container`, the per-node early-return shape) to the
actual renderer structure in `crew_menus.js` — the behaviour contract is:
three titled areas, clickable rows in REPAIRING/WAITING emitting
`crew-menu/repair:<id>`, inert DESTROYED rows.

In `native/assets/ui-cef/css/hello.css`, add (next to the crew-menu styles):

```css
.crew-repair-pane { padding: 2px 6px; }
.crew-repair-area-title {
  font-size: 10px; letter-spacing: 1px; opacity: 0.7; margin-top: 4px;
}
.crew-repair-row { cursor: pointer; padding: 1px 4px; }
.crew-repair-row:hover { background: rgba(255, 153, 0, 0.25); }
.crew-repair-row.inert { cursor: default; opacity: 0.5; }
```

- [ ] **Step 8: Full suite + commit**

Run: `uv run pytest tests/unit -q`
Expected: PASS (no regressions).

```bash
git add App.py engine/ui/eng_repair_pane.py engine/ui/crew_menu_panel.py \
    native/assets/ui-cef/js/crew_menus.js native/assets/ui-cef/css/hello.css \
    tests/unit/test_eng_repair_pane.py
git commit -m "feat(repair): EngRepairPane CEF projection — repair/waiting/destroyed areas, click-to-toggle priority"
```

---

### Task 9: Developer quick-repair keybinding

**Files:**
- Modify: `engine/dev_keybindings.py` (registration block, pattern at lines 61–105)
- Test: `tests/unit/test_repair_subsystem.py` (extend)

**Interfaces:**
- Produces: `engine.appc.subsystems.repair_ship_fully(ship) -> None` (mirrors sdk `Actions/ShipScriptActions.RepairShipFully` — every subsystem to max condition through `SetCondition`, queue cleared); a `--developer` keybinding on **F9** invoking it on the player ship (stock's Caps+R debug binding equivalent; we use the dev-keybinding registry instead of plumbing a new WC_* constant through input.py/GLFW — see the keyboard-constants-collapse gotcha).

- [ ] **Step 1: Write the failing test** (append to `tests/unit/test_repair_subsystem.py`)

```python
def test_repair_ship_fully_restores_everything_and_clears_queue():
    from engine.appc.subsystems import repair_ship_fully
    ship = _damaged_ship()
    sensors = ship.GetSensorSubsystem()
    sensors.SetCondition(100.0)              # damaged + auto-enqueued
    bay = ship.GetRepairSubsystem()
    assert bay._queue
    repair_ship_fully(ship)
    assert sensors.GetCondition() == sensors.GetMaxCondition()
    assert bay._queue == []
    repair_ship_fully(None)                  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_repair_subsystem.py -v -k fully`
Expected: FAIL — ImportError on `repair_ship_fully`.

- [ ] **Step 3: Implement**

Module-level function at the bottom of `engine/appc/subsystems.py`:

```python
def repair_ship_fully(ship) -> None:
    """Dev/debug full repair — mirrors sdk Actions/ShipScriptActions.py
    RepairShipFully: every subsystem back to max condition. Also clears
    the repair queue (nothing left to fix). Safe on None/partial ships."""
    if ship is None:
        return
    getters = (
        "GetHull", "GetShieldSubsystem", "GetSensorSubsystem",
        "GetImpulseEngineSubsystem", "GetWarpEngineSubsystem",
        "GetPowerSubsystem", "GetRepairSubsystem", "GetTorpedoSystem",
        "GetPhaserSystem", "GetPulseWeaponSystem", "GetTractorBeamSystem",
        "GetCloakingSubsystem",
    )
    for name in getters:
        try:
            sub = getattr(ship, name, lambda: None)()
            if sub is None:
                continue
            sub.SetCondition(sub.GetMaxCondition())
            for i in range(sub.GetNumChildSubsystems()):
                child = sub.GetChildSubsystem(i)
                if child is not None:
                    child.SetCondition(child.GetMaxCondition())
        except Exception as _e:
            dev_mode.log_swallowed("repair_ship_fully", _e)
    bay = getattr(ship, "GetRepairSubsystem", lambda: None)()
    if bay is not None and hasattr(bay, "_queue"):
        bay._queue.clear()
```

In `engine/dev_keybindings.py`, next to the existing registrations (pattern at lines 61–105; `player` and `_h` are in scope there):

```python
    # F9: quick-repair the player ship (stock BC's Caps+R debug binding,
    # ET_INPUT_DEBUG_QUICK_REPAIR -> TacticalInterfaceHandlers.RepairShip).
    # Live-verify lever for the repair feature: damage, watch the queue
    # fill + Brex speak, F9, watch it all clear.
    def _quick_repair() -> None:
        from engine.appc.subsystems import repair_ship_fully
        repair_ship_fully(player)

    dev_mode.register_dev_keybinding(
        _h.keys.KEY_F9, _quick_repair, "Quick-repair player ship (dev) — F9"
    )
```

Before choosing F9, grep `engine/dev_keybindings.py` for `KEY_F9` — if it's
taken, use the next free function key and update the description + this plan's
live-verify checklist.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_repair_subsystem.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py engine/dev_keybindings.py tests/unit/test_repair_subsystem.py
git commit -m "feat(repair): dev F9 quick-repair (stock Caps+R debug equivalent)"
```

---

### Task 10: Engineer emitter integration tests + gate

**Files:**
- Test: `tests/unit/test_engineer_emitters.py` (create)
- No production code expected; fix anything these tests flush out.

**Interfaces:**
- Consumes: everything above; the REAL `Bridge/EngineerCharacterHandlers.py` (loaded through the SDK finder, NOT stubbed — check `tests/conftest.py`'s stub list first: the runtime-vs-test stub divergence was the root cause of the Helm silence bug); `CharacterClass.SayLine` / `SpeakLine` (`engine/appc/characters.py`); the bridge-set fixture conventions in `tests/unit/test_live_speech_characters.py`.

- [ ] **Step 1: Write the tests**

The fixture builds the minimal world the handlers dereference: a player ship,
a "bridge" set containing an "Engineer" `CharacterClass`, and recorded
speech. **Copy the bridge/engineer fixture setup from
`tests/unit/test_live_speech_characters.py`** (it already solves set
registration, character construction, and database wiring); the new
assertions are below. If that file's fixture is a pytest fixture, import or
re-declare it per its own conventions.

```python
"""All seven Engineering emitters fire end-to-end against the REAL SDK
Bridge/EngineerCharacterHandlers.py — the regression guard the spec requires.

SubsystemDisabled / SubsystemDestroyed announce via a TGSequence with a 0.5s
TGScriptAction delay, so tests advance the GameLoop past that before
asserting speech.
"""
import App
import pytest


@pytest.fixture
def engineer_world(monkeypatch):
    # Build: player ship w/ authored repair bay, bridge set with Engineer
    # character (SayLine/SpeakLine recorded), MissionLib.GetPlayer -> ship,
    # then run the real registration:
    #   import Bridge.EngineerCharacterHandlers as ECH
    #   ECH.AttachMenuToEngineer(engineer)
    # Mirror tests/unit/test_live_speech_characters.py for the set/character
    # construction. Return (ship, engineer, spoken) where `spoken` is the
    # list of line keys passed to SayLine/SpeakLine.
    ...


def _advance(seconds=1.0):
    from engine.core.loop import GameLoop, TICK_RATE
    GameLoop().advance(int(seconds * TICK_RATE))


def test_subsystem_disabled_speaks_typed_line(engineer_world):
    ship, engineer, spoken = engineer_world
    sensors = ship.GetSensorSubsystem()
    sensors.SetCondition(sensors.GetMaxCondition() * 0.05)   # below disabled pct
    _advance(1.0)                                            # 0.5s announce delay
    assert "SensorsDisabled" in spoken


def test_subsystem_destroyed_speaks_typed_line(engineer_world):
    ship, engineer, spoken = engineer_world
    ship.GetSensorSubsystem().SetCondition(0.0)
    _advance(1.0)
    assert "SensorsDestroyed" in spoken


def test_shield_level_change_announces(engineer_world):
    ship, engineer, spoken = engineer_world
    shields = ship.GetShieldSubsystem()
    for f in range(6):
        shields.SetCurrentShields(f, shields.GetMaxShields(f) * 0.4)
    _advance(1.0)
    assert any(k.startswith("Shields") for k in spoken)


def test_specific_shield_face_announces(engineer_world):
    ship, engineer, spoken = engineer_world
    shields = ship.GetShieldSubsystem()
    shields.SetCurrentShields(0, shields.GetMaxShields(0) * 0.04)  # front < 5%
    _advance(1.0)
    assert any("FrontShield" in k for k in spoken)


def test_hull_level_change_announces(engineer_world):
    ship, engineer, spoken = engineer_world
    hull = ship.GetHull()
    hull.SetCondition(hull.GetMaxCondition() * 0.4)
    _advance(1.0)
    assert any(k.startswith("Hull") for k in spoken)


def test_report_speaks_hull_and_shield_status(engineer_world):
    ship, engineer, spoken = engineer_world
    menu = engineer.GetMenu()
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_REPORT)
    evt.SetDestination(menu)
    App.g_kEventManager.AddEvent(evt)
    _advance(0.5)
    assert any(k.startswith("Hull") for k in spoken)
    assert any(k.startswith("Shields") for k in spoken)


def test_communicate_routes_to_report(engineer_world):
    ship, engineer, spoken = engineer_world
    menu = engineer.GetMenu()
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_COMMUNICATE)
    evt.SetDestination(menu)
    App.g_kEventManager.AddEvent(evt)
    _advance(0.5)
    assert spoken  # Communicate either eggs or re-dispatches to Report


def test_repair_completed_event_runs_stock_handler_cleanly(engineer_world):
    # Stock RepairCompleted is an early-return stub — assert the event
    # DISPATCHES through the real handler without error (no speech expected).
    ship, engineer, spoken = engineer_world
    sensors = ship.GetSensorSubsystem()
    sensors.SetCondition(sensors.GetMaxCondition() - 1.0)
    ship.GetRepairSubsystem().Update(10.0)     # completes the repair
    _advance(0.2)                              # handler ran; no exception
```

Recording speech: monkeypatch `engine.appc.characters.CharacterClass.SayLine`
and `.SpeakLine` in the fixture to append the line-key argument to `spoken`
and then call the original (signatures: `SayLine(pDatabase, key, ...)` /
`SpeakLine(...)` — match the real parameter positions in
`engine/appc/characters.py` when writing the wrapper).

- [ ] **Step 2: Run and fix until green**

Run: `uv run pytest tests/unit/test_engineer_emitters.py -v`
Iterate: every failure here is a REAL integration gap (missing export, wrong
event shape, watcher not wired). Fix in the layer that owns it — do not
weaken the assertion. Two known legitimate adjustments: (a) exact line keys
depend on TGL databases; if the fixture has no database the SayLine key
argument is still recordable — assert on the key, not audio; (b) if
`AttachMenuToEngineer` needs `App.*` names not in Task 1's audit list, add
them to BOTH `App.py` and the audit list.

- [ ] **Step 3: Full gate**

Run: `scripts/check_tests.sh`
Expected: exits 0. Any failure not in `tests/known_failures.txt` is a regression from this feature — fix it now.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_engineer_emitters.py
git commit -m "test(repair): all seven Engineering emitters fire end-to-end through the real SDK handlers"
```

---

### Task 11: Live verification (manual, --developer)

**Files:** none (checklist only — record results in the PR/commit message).

- [ ] Build + run: `cmake --build build -j && ./build/dauntless -- --developer` (use the project's usual dev launch flags)
- [ ] QuickBattle vs a hostile; take fire until subsystems damage.
- [ ] Engineering crew menu shows the repair pane: REPAIRING (≤ NumRepairTeams rows), WAITING, ticking percentages.
- [ ] Click a WAITING row → it jumps to REPAIRING head; click a REPAIRING row → demotes.
- [ ] Brex speaks: shield-level lines while shields drain, specific-face line on a hammered facing, hull line, "…Disabled"/"…Destroyed" lines on threshold crossings.
- [ ] Communicate/Report on Brex's menu → hull + shields status lines.
- [ ] F9 → everything repairs, queue empties, disabled subsystems come back (AI Conditions re-arm — cloak/weapon doctrines resume if applicable).
- [ ] Note any tuning/wrongness in the PR description; file follow-ups rather than scope-creeping.

---

## Self-Review (completed at plan-writing time)

- **Spec coverage:** §1 base (Repair/threshold events/auto-enqueue/complexity seeding) → Tasks 2, 3, 5; §2 queue+tick+priority+loop → Tasks 4, 6, 7; §3 App surface → Task 1 (note: `ShipSubsystem_Cast` already existed — audit test still pins it); §4 UI → Task 8; §5 emitters → Task 10; §6 dev hook → Task 9; error-handling bullets → raise-safe emission (T3/T4), destroyed-bay stop (T6), orphan-subsystem safety (T5), pause via `frame_dt=0` (loop-level, T6); non-goals excluded throughout.
- **Type consistency:** `AddToRepairList(sub) -> int` used by T5/T8; `_queue` list-of-refs shape shared T4/T6/T7/T8/T9; `_fire_repair_event(attr, sub, dest=None)` defined T4, used T6; `_owning_ship()` defined T3, used T4/T5; `repair_pane_snapshot(ship, register)` defined and consumed in T8; event payloads follow the single contract table.
- **Known judgment calls (flagged, not hidden):** Task 8's JS renderer and Task 10's fixture adapt to existing structures (`crew_menus.js` renderer shape, `test_live_speech_characters.py` fixture) — the behavioural contracts are fully specified; the two integration points explicitly defer to in-repo conventions rather than inventing parallel ones.
