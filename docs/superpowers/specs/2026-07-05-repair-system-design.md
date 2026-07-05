# Repair System — Design

**Date:** 2026-07-05
**Status:** Approved (Approach A — faithful in-engine RepairSubsystem)

## Goal

Implement BC's ship repair system faithfully in dauntless: the per-ship
`RepairSubsystem` queue and tick, the subsystem disabled/destroyed/operational
threshold events, the Engineering repair-queue UI (`EngRepairPane`), and the
plumbing that makes all seven of Brex's Engineering emitters fire end-to-end:

> SubsystemDisabled, SubsystemDestroyed, ShieldLevelChange, HullLevelChange,
> SpecificShieldLevelChange (×6 faces), Report, Communicate

All SDK scripts run **unmodified**. The work is entirely on the engine side:
make the surface the SDK calls real, and emit the events the SDK listens for.

## Ground truth

| Source | What it pins down |
|---|---|
| `sdk/Build/scripts/App.py:6639–6662` | `RepairSubsystem(PoweredSubsystem)` — exactly three own methods: `AddSubsystem`, `AddToRepairList`, `IsBeingRepaired` |
| `sdk/Build/scripts/App.py:9714–9734` | `RepairSubsystemProperty(PoweredSubsystemProperty)` — `Get/SetMaxRepairPoints`, `Get/SetNumRepairTeams` |
| `sdk/Build/scripts/App.py:5671` | `ShipSubsystem.Repair(fRepairPoints)` on every subsystem |
| `docs/original_game_reference/gameplay/ship-subsystems.md` §Repair | RE-verified tick formula, queue semantics, priority toggle, event flow, `EngRepairPane` areas |
| `sdk/Build/scripts/Bridge/EngineerCharacterHandlers.py` | All seven emitters: registration (lines 66–95), watcher setup (145–200), handlers + voice-line keys |
| `sdk/Build/scripts/Bridge/EngineerMenuHandlers.py:84` | `App.EngRepairPane_Create(1.0, 0.4, 3)` attached to the Engineering menu |
| `sdk/Build/scripts/ships/Hardpoints/*.py` | Authoring: Galaxy 50 pts / 3 teams / complexity 2.0; Keldon 20 / 2 / 4.0; Sovereign 50 pts, complexity 1.0. Every subsystem property authors `SetRepairComplexity` + `SetDisabledPercentage`. |
| `sdk/Build/scripts/Conditions/{ConditionSystemDisabled,ConditionTorpsReady,ConditionPulseReady}.py` | AI consumers of `ET_SUBSYSTEM_OPERATIONAL` (and disabled/destroyed) — emitting these closes a known AI silent-degradation gap |

### The RE-verified repair tick (ship-subsystems.md §Repair)

```
rawRepair = MaxRepairPoints * (repairBay.condition / repairBay.maxCondition) * dt
divisor   = min(queueCount, NumRepairTeams)
perItem   = rawRepair / divisor
hpGain_i  = perItem / target_i.RepairComplexity
```

Properties: the repair bay's own health scales output; up to `NumRepairTeams`
targets repaired simultaneously; `RepairComplexity` is a final divisor;
destroyed entries are **skipped, not removed** (fire
`ET_REPAIR_CANNOT_BE_COMPLETED`, consume no team). Worked example (Sovereign,
healthy bay, 2 queued, 30 fps): raw = 50·1.0·0.033 = 1.65; per-item 0.825;
phaser (complexity 3.0) → +0.275 HP/tick; tractor (7.0) → +0.118 HP/tick.

## Current gaps (audited 2026-07-05)

1. `RepairSubsystem` in `engine/appc/subsystems.py:1396` is an empty
   placeholder — no queue, no tick, no events.
2. `ET_SUBSYSTEM_DISABLED` / `ET_SUBSYSTEM_DESTROYED` are defined
   (`App.py:925–926`) but **nothing ever emits them** (in stock BC they are
   posted by C++ on condition crossings).
3. `ET_REPAIR_COMPLETED` / `ET_REPAIR_CANNOT_BE_COMPLETED` defined, never
   emitted. `ET_REPAIR_INCREASE_PRIORITY`, `ET_ADD_TO_REPAIR_LIST`,
   `ET_SUBSYSTEM_OPERATIONAL` don't exist in our shim at all.
4. Missing App casts used by the announce handlers (`ShipSubsystem_Cast`,
   `SensorSubsystem_Cast`, `ImpulseEngineSubsystem_Cast`,
   `WarpEngineSubsystem_Cast`, `TractorBeamProjector_Cast`,
   `RepairSubsystem_Cast`) — today they fall through to `_Stub` no-ops, so
   Brex would silently say nothing (the known stub-list divergence trap).
5. `EngRepairPane_Create` returns a bare `_DisplayWidget` — no repair-queue UI.

Already working (needs regression tests, not new code): shield watchers
(`GetShieldWatcher(0..6)`), hull `GetCombinedPercentageWatcher`, battery
watchers, `FloatRangeWatcher.AddRangeCheck` broadcasting, `TGFloatEvent`,
Communicate→Report conversion in `engine/bridge_officers.py`, the
`TGSequence`/`SayLine`/CrewSpeechBus speech pipeline, hardpoint property
data-bag round-trip of `MaxRepairPoints`/`NumRepairTeams`/`RepairComplexity`.

## Design

### 1. ShipSubsystem base — Repair() and threshold events

`engine/appc/subsystems.py`:

- **`Repair(points)`** — raises condition, clamped to `[0, max]`, routed
  through the existing `SetCondition` path so `_condition_changed()` and the
  combined-percentage watcher fire as usual.
- **Threshold state machine.** Each subsystem tracks one of three states
  derived from condition: `operational`, `disabled`
  (`conditionPct ≤ DisabledPercentage`), `destroyed` (`condition ≤ 0`).
  On transition, broadcast via `App.g_kEventManager`:
  - into disabled → `ET_SUBSYSTEM_DISABLED`
  - into destroyed → `ET_SUBSYSTEM_DESTROYED`
  - back above the disabled threshold (repair) → `ET_SUBSYSTEM_OPERATIONAL`

  Event shape: `TGEvent` with `SetSource(subsystem)`,
  `SetDestination(parent ship)` — matches what
  `EngineerCharacterHandlers.SubsystemDisabled` dereferences
  (`pEvent.GetSource().GetObjID()`, destination filtered against the player)
  and what the AI `Conditions` classes match on. Broadcast for **all** ships;
  consumers filter. Exactly one event per crossing — no re-fire while the
  state holds. `ET_SUBSYSTEM_REBUILT` / `ET_SUBSYSTEM_COMPLETELY_*` have no
  SDK Python consumers and are **not** emitted (explicit non-goal).
- **Auto-enqueue.** When a condition *decrease* leaves a subsystem below max,
  the parent ship's repair subsystem (if any) gets
  `AddToRepairList(subsystem)`. The hull enqueues like any other subsystem
  (stock repairs hull — voice line ge111); ship death at hull 0 remains
  combat's concern, independent of the queue. This
  is the synchronous equivalent of stock's
  `SetCondition → ET_SUBSYSTEM_HIT → RepairSubsystem::HandleHitEvent` chain.
  We do not emit `ET_SUBSYSTEM_HIT` itself (no SDK Python consumer).
- **RepairComplexity seeding.** `setup_properties` copies
  `GetRepairComplexity()` from the property onto the subsystem (same pattern
  as `DisabledPercentage` at `engine/appc/ships.py:1202`), exposed as
  `ShipSubsystem.GetRepairComplexity()`. Default 1.0 when unauthored.

### 2. RepairSubsystem — queue and tick

Replaces the placeholder class. State: an ordered Python list of subsystem
refs (faithful *semantics*; we don't replicate the C++ node pool).

- **`AddToRepairList(sub)` / `AddSubsystem(sub)`** — one core: reject
  duplicates (walk the list), reject destroyed (`condition ≤ 0`), reject
  undamaged (`condition ≥ max`); append at tail; on success broadcast
  `ET_ADD_TO_REPAIR_LIST` (source = sub, destination = this repair
  subsystem). Both SDK spellings map to it.
- **`IsBeingRepaired(sub)`** — true iff `sub` is among the first
  `NumRepairTeams` queue entries.
- **`Update(dt)`** — the RE formula above. Per tick:
  1. If own condition ≤ 0 or queue empty → no-op.
  2. `raw = MaxRepairPoints × GetConditionPercentage() × dt`;
     `perItem = raw / min(len(queue), NumRepairTeams)`.
  3. Walk from head; assign teams to the first up-to-`NumRepairTeams`
     entries whose condition > 0. A destroyed entry is skipped — it stays
     in the queue (stock: "skipped, not removed"), fires
     `ET_REPAIR_CANNOT_BE_COMPLETED` **once** (dedupe flag reset if it is
     ever repaired externally above 0), and does not consume a team.
  4. Each assigned target: `target.Repair(perItem / target.GetRepairComplexity())`.
  5. Target reaching max condition → remove from queue, broadcast
     `ET_REPAIR_COMPLETED` (source = target, destination = this repair
     subsystem's parent ship — verified in implementation against what the
     real `RepairCompleted` handler dereferences, with a test running the
     actual SDK handler).
  - **No power-efficiency term** — the RE-verified formula scales only by
    the bay's own health. Power draw stays as today
    (`_IDLE_DRAIN_SLOTS` in `PowerSubsystem`).
- **Priority toggle.** Instance handler for `ET_REPAIR_INCREASE_PRIORITY`
  (obj-ptr event carrying the target subsystem): if `IsBeingRepaired(sub)` →
  move to tail (demote); else → move to head (promote). Stock's binary
  toggle, not move-up-one.
- **Tick integration.** `RepairSubsystem.Update(dt)` joins the existing
  per-tick subsystem update loop (alongside shields/power/cloak) for every
  simulated ship (`iter_ships`, sim scope — AI ships repair themselves, as
  stock). Respects `frame_dt = 0` pause for free.
- **`MaxRepairPoints` / `NumRepairTeams`** read from the bound
  `RepairSubsystemProperty` (data-bag accessors already round-trip hardpoint
  authoring). Defaults when unauthored: 0 points / 0 teams (a ship without an
  authored repair subsystem repairs nothing).

### 3. App shim surface

`App.py` (root shim):

- New constants continuing our series: `ET_SUBSYSTEM_OPERATIONAL = 0x131E`,
  `ET_REPAIR_INCREASE_PRIORITY = 0x131F`, `ET_ADD_TO_REPAIR_LIST = 0x1320`.
- New casts: `ShipSubsystem_Cast`, `SensorSubsystem_Cast`,
  `ImpulseEngineSubsystem_Cast`, `WarpEngineSubsystem_Cast`,
  `TractorBeamProjector_Cast`, `RepairSubsystem_Cast` (isinstance-style,
  matching existing cast helpers).
- **Full audit of `Bridge/EngineerCharacterHandlers.py` +
  `Bridge/EngineerMenuHandlers.py`**: every `App.*` name they touch must
  resolve to something real (not `_NamedStub`) — this is the stub-trap
  lesson from the Helm speech work. `App.TGObject_GetTGObjectPtr` export
  verified against `engine/appc/actions.py:936`.

### 4. EngRepairPane — repair-queue UI

`App.EngRepairPane_Create(width, height, rows)` returns a real pane object
(new `engine/ui/eng_repair_pane.py`) instead of a bare `_DisplayWidget`,
rendered by the Engineering crew menu's CEF panel — the same
SDK-creates-widget / CEF-renders split as `ShipDisplayPanel`. Stock
`EngineerMenuHandlers.py:84` attaches it unmodified.

Three areas, mirroring stock's `EngRepairPane`:

| Area | Content | Click |
|---|---|---|
| REPAIR | First `NumRepairTeams` queue entries | post `ET_REPAIR_INCREASE_PRIORITY` (demotes) |
| WAITING | Remaining queue entries | post `ET_REPAIR_INCREASE_PRIORITY` (promotes) |
| DESTROYED | Ship subsystems at 0 condition | inert |

Destroyed entries still sitting in the queue (skipped by the tick) are
excluded from the REPAIR/WAITING rows; they appear only in DESTROYED, which
is derived from the ship's subsystem list, not the queue.

Rows: damage glyph (`engine/ui/damage_icons.py`) + subsystem name +
condition %. Data source: per-frame snapshot of the player ship's repair
subsystem + subsystem list, re-rendered on change (snapshot-diff pattern).
The click posts the same event the engine-side toggle handles, so UI and
engine stay decoupled.

### 5. The seven Engineering emitters

No SDK edits. With sections 1–4 in place:

| Emitter | Trigger path | New work |
|---|---|---|
| SubsystemDisabled | threshold event (§1) → SDK handler → TGSequence → `AnnounceSystemDisabled` → `SayLine` | event emission + casts |
| SubsystemDestroyed | same, destroyed crossing | same |
| ShieldLevelChange | shield combined watcher + SDK `AddRangeCheck` (already live) | regression test only |
| HullLevelChange | hull combined watcher (already live) | regression test only |
| SpecificShieldLevelChange ×6 | per-face watchers 0–5 (already live) | regression test only |
| Report | `ET_REPORT` menu instance handler (already wired via Communicate→Report) | regression test only |
| Communicate | `ET_COMMUNICATE` menu instance handler (already wired) | regression test only |

Plus (not in the required list but firing from the same machinery, with SDK
handlers already registered): `RepairCompleted`, `RepairCannotBeCompleted`,
`MainBatteryLevelChange`, `BackupBatteryLevelChange`.

### 6. Developer verification hook

Stock's debug quick-repair (Caps+R → `ET_INPUT_DEBUG_QUICK_REPAIR` →
`TacticalInterfaceHandlers.RepairShip`) wired as a `--developer` keybinding
via `dev_mode.register_dev_keybinding(...)` (requires the App/input
constant + GLFW plumbing per the keyboard-constants gotcha). Gives a live
lever: damage the ship (Damage Preview / combat), watch the queue fill and
Brex speak, quick-repair, watch completions.

## Error handling

- A ship with no authored repair subsystem: auto-enqueue is a no-op; UI
  shows empty areas; no events.
- Repair subsystem destroyed: tick output scales to 0 via its own
  conditionPct (and hard-stops at condition ≤ 0); queue preserved so
  repairs resume if the bay itself is repaired (it can be queued and
  repaired like any subsystem — stock voice line ge139 confirms).
- Ship death / mission swap: queues live on the ship object and die with
  it; the TCW/menu re-registration path already handles handler re-wiring
  per mission load (known TCW-recreated-on-swap pattern).
- Events during teardown: emission guards on a live parent ship, matching
  existing degrade-to-None shutdown conventions.

## Testing

TDD (RED→GREEN→REFACTOR) per task; both suites via `scripts/check_tests.sh`.

- **Unit — queue:** duplicate/destroyed/undamaged rejection; auto-enqueue on
  damage; tail append order; toggle promote/demote both directions;
  `IsBeingRepaired` boundary at `NumRepairTeams`.
- **Unit — tick:** the RE worked example (Sovereign 50 pts, 2 queued,
  complexities 3.0/7.0, 30 fps → +0.275 / +0.118 HP per tick); bay-health
  scaling; destroyed-entry skip + single `ET_REPAIR_CANNOT_BE_COMPLETED`;
  completion removal + `ET_REPAIR_COMPLETED`; team cap with queue > teams;
  self-repair (bay queued on itself).
- **Unit — thresholds:** disabled/destroyed/operational crossings emit
  exactly once each way; event source/destination shape.
- **Integration — emitters:** run the **real**
  `EngineerCharacterHandlers.AttachMenuToEngineer` against a live player
  ship; drive damage/shield/hull changes and `ET_REPORT`/`ET_COMMUNICATE`;
  assert CrewSpeechBus receives the expected line keys for all seven
  emitters (guards against the runtime-stub divergence trap).
- **UI:** pane snapshot content for the three areas; click → priority event
  → queue reorder round-trip.
- **Live verify:** `--developer` QuickBattle: take damage, open Engineering
  menu (queue visible, clicks reorder), hear Brex disabled/destroyed/report
  lines, Caps+R quick-repair, completion lines.

## Non-goals

- Multiplayer opcodes 0x06/0x0B/0x11 (repair network paths) — no MP yet.
- `ET_SUBSYSTEM_REBUILT` / `ET_SUBSYSTEM_COMPLETELY_*` emission (no
  consumers).
- `ET_SUBSYSTEM_HIT` emission (C++-internal in stock; our enqueue is direct).
- Repair of the ship-death path (hull 0 = death cascade, already handled by
  combat).
- Power-efficiency scaling of repair rate (not in the RE formula).
