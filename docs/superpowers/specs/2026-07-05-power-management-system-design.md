# Power Management System — Design

**Date**: 2026-07-05
**Status**: Approved for planning
**Scope decision**: All three layers in one phased plan — (1) EPS simulation
core, (2) efficiency-driven gameplay effects, (3) SDK-driven Engineering
power-grid UI.

## Sources of truth

| Source | Role |
|---|---|
| `sdk/Build/scripts/App.py` (PoweredSubsystem 5696–5708, PowerSubsystem 5739–5756, PowerProperty 9793–9802, PoweredSubsystemProperty 9169–9170, EngPowerCtrl 8636–8649) | Exact Python-visible method surface — the contract dauntless must satisfy |
| `sdk/Build/scripts/Bridge/PowerDisplay.py` | The Engineering panel: EngPowerCtrl construction, 0.5 s refresh, battery readouts, `AdjustPower` auto-balance, tractor/cloak siphon rendering |
| `docs/original_game_reference/gameplay/ship-subsystems.md` § Power and reactor | RE'd binary internals: tick math, conduit asymmetry, draw modes, constants, per-ship deficit table |
| `docs/original_game_reference/gameplay/power-system.md` | Manual-derived player-facing intent (banded Power Used bar, 125% rule, alert-state behaviour) |
| `sdk/Build/scripts/ships/Hardpoints/*.py` (e.g. galaxy.py) | Authored values: `PowerProperty_Create` + `SetNormalPowerPerSecond` per consumer |

## Decisions made during brainstorming

1. **One class, full semantics.** The binary internally splits a damageable
   reactor (`ship+0x2C4`) from a hidden "Powered master" EPS distributor
   (`ship+0x2B0`), but the SDK only ever sees the single
   `ship.GetPowerSubsystem()` handle wearing both hats — missions damage/
   destroy/target it and read `GetConditionPercentage()`, while
   PowerDisplay/`ConditionPowerBelow`/dock-repair read and write batteries,
   conduits, and output through the same handle. Dauntless extends its
   existing `engine/appc/subsystems.py:PowerSubsystem` into the complete
   model; no separate distributor object.
2. **Tractor draws main-first (mode 0).** The manual, the in-game siphon
   line, and `PowerDisplay.py`'s main-power colouring all say Main Battery;
   the RE doc's claim of mode 1 (backup-first, `ship-subsystems.md:184`) is
   treated as a mislabel. All three draw modes are implemented and the
   per-class assignment is a single data constant, so flipping tractor to
   mode 1 later is a one-line change if live behaviour disproves this.
3. **SDK-driven UI.** `Bridge/PowerDisplay.py` runs unmodified against
   Python widget shims; a CEF panel renders the shim state. Follows the
   crew-menu precedent and the "SDK drives everything" project rule.

## 1. Simulation core

### 1.1 Property layer

`engine/appc/properties.py` gains:

- **`PowerProperty`** — `PowerOutput`, `MainBatteryLimit`,
  `BackupBatteryLimit`, `MainConduitCapacity`, `BackupConduitCapacity`,
  each with Get/Set; `App.PowerProperty_Create(name)` constructs it and
  `CT_POWER_SUBSYSTEM` identifies it. Reference values (Galaxy): output
  1000, main 250 000, backup 80 000, conduits 1200 / 200.
- **`PoweredSubsystemProperty`** — `Get/SetNormalPowerPerSecond`, made a
  base of every consumer property (impulse, warp, shields, phasers,
  torpedoes, pulse, sensors, tractor, cloak, repair) so hardpoint
  `SetNormalPowerPerSecond(...)` calls stop being silent `_NamedStub`
  no-ops.

`ShipSubsystem.SetProperty` / `Ship.SetupProperties` mirror the new fields
onto live subsystems exactly as existing property fields are mirrored.

### 1.2 PowerSubsystem (reactor + EPS grid, one object)

State: `main_battery_power`, `backup_battery_power`, per-interval conduit
budgets `main_conduit_current` / `backup_conduit_current`,
`available_power`, `power_dispensed`, `last_update_time`, and an ordered
consumer list (registration order = draw priority, mirroring BC's
linked-list order).

**Interval tick** (INTERVAL = 1.0 s of game time, matching constant
`0x892E20`):

```
recharge = PowerOutput * conditionPct * elapsed        # reactor health scales output
main_battery += recharge          (cap MainBatteryLimit)
backup_battery += overflow        (cap BackupBatteryLimit; rest discarded)

main_conduit_current   = min(main_battery,   MainConduitCapacity * conditionPct * elapsed)
backup_conduit_current = min(backup_battery, BackupConduitCapacity * elapsed)
available_power        = main + backup conduit budgets
```

The asymmetry is deliberate and RE-verified: **main conduit is
health-scaled, backup conduit is not** — a damaged reactor reduces main
delivery only.

**Per-frame consumer draw** (replaces today's `_compute_idle_drain`
aggregate): every registered consumer with `IsOn()` (tractor gated on
firing, cloak on trying/engaged — preserving the current gates) computes

```
power_wanted  = NormalPowerPerSecond * power_percentage_wanted * dt
power_received = draw per powerMode                # depletes conduit budget AND battery
efficiency     = power_received / power_wanted     # 0.0–1.0, stored on the consumer
```

Draw modes (all three implemented; assignment is one data constant):

| Mode | Behaviour | Assigned to |
|---|---|---|
| 0 | main conduit first, backup fallback | everything by default, **including tractor** |
| 1 | backup first, main fallback | *(unassigned — kept for fidelity/flippability)* |
| 2 | backup only, no fallback | cloak |

**`SetPowerPercentageWanted(pct)`** — clamp to [0.0, 1.25]; rescale
`power_wanted` by `pct / old` (BC's exact semantics); post
`ET_SUBSYSTEM_POWER_CHANGED`.

**Init**: batteries full, every consumer at 100% (BC's spawn sequence).

**Watchers**: existing `FloatRangeWatcher`s for main/backup battery
fractions are kept — `ConditionPowerBelow` and
`EngineerCharacterHandlers` (Brex's drain warnings) depend on
`GetMainBatteryWatcher()` / `GetBackupBatteryWatcher()`.

**Warp-core breach**: reactor condition reaching 0 destroys the ship
(manual p. 16; RE self-destruct cascade agrees), routed through the
existing `DestroySystem` path.

**Host-loop wiring**: the interval tick and per-frame draws run for **all**
ships via `iter_ships` (sim-scoped, not render-scoped), closing the
"`PowerSubsystem.Update` is never called" gap.

### 1.3 App.py surface completed

`PowerProperty_Create`, `PoweredSubsystemProperty` + `_Cast`,
`EngPowerCtrl_Create` / `EngPowerCtrl_GetPowerCtrl` /
`EngPowerDisplay_GetPowerDisplay` become real (see § 3), and the
`PowerSubsystem` methods missing today are filled in against the SDK
surface: `GetPowerOutput`, `GetMain/BackupBatteryLimit`,
`GetMaxMainConduitCapacity`, `GetMain/BackupConduitCapacity`,
`StealPower` (main only), `StealPowerFromReserve` (backup only),
`GetPowerWanted`, `GetPowerDispensed`. Consumers gain `GetPowerWanted` /
`SetPowerWanted`, `GetNormalPowerWanted`, `GetPowerReceived`,
`GetPowerPercentage`, `GetNormalPowerPercentage`, `SetPowerSource`.

## 2. Gameplay effects of efficiency

Each consumer stores `efficiency` every frame; behaviour scales at the
existing point of use. At full power `efficiency = 1.0`, so behaviour is
unchanged until a ship actually runs a deficit (regression guard). The
0–125% slider raises/lowers `power_wanted`, which both changes the drain
and (for engines) raises the effective caps.

| Consumer | Effect | Hook |
|---|---|---|
| Impulse engines | max speed / accel / turn rates × efficiency; slider >100% raises effective caps | `ship_motion.py` + `_PlayerControl` reads of `GetMaxSpeed/GetMaxAccel/GetMaxAngularVelocity` |
| Shield generator | per-face recharge rate × efficiency | `ShieldSubsystem.Update` regen pass |
| Phasers / pulse | charge (re-arm) rate × efficiency | existing charge/re-arm timers |
| Torpedoes | reload rate × efficiency | torpedo reload timer |
| Sensor array | effective sensor range × efficiency; drives Target-List appearance/drop-off distance | sensor range reads feeding the target list |
| Cloak | backup-only draw; efficiency below auto-decloak threshold ⇒ forced decloak | `CloakingSubsystem.Update` (existing forced-decloak path) |
| Tractor | drains while firing (mode 0); hold strength NOT power-scaled in v1 (undocumented in BC) | existing tractor firing gate |

Preserved BC behaviours: **graceful degradation** (no hard cutoff at low
power; a subsystem only turns off via `TurnOff`/damage) and **draw-order
priority** (first-registered consumer gets first claim on a starved
conduit).

The manual's "auto-rebalance on warp-core damage" is not engine logic —
it is `PowerDisplay.AdjustPower` (client-side SDK Python) and arrives for
free with § 3.

## 3. Engineering power-grid UI (SDK-driven)

**Principle**: `Bridge/PowerDisplay.py` runs unmodified and owns all panel
logic — construction, the 0.5 s refresh timer, battery % readouts,
`AdjustPower` (proportional throttle on deficit, 20% floor, weapons and
engines grouped), and the tractor/cloak siphon handling
(`ET_TRACTOR_BEAM_STARTED_FIRING` / `ET_CLOAK_BEGINNING` handlers colour
the siphon with the main-power green / backup-power red globals).

- **Widget shims** (Python, `engine/`): `EngPowerCtrl`
  (`EngPowerCtrl_Create(width)`, `EngPowerCtrl_GetPowerCtrl()`,
  `GetBarForSubsystem(sys)`, `Refresh()`), `STNumericBar`
  (value/range/colour), plus the panes/paragraphs/icons PowerDisplay
  touches. State-holding objects, no drawing. The exact call inventory of
  PowerDisplay.py is audited during planning; the commitment is "enough
  surface that PowerDisplay.py runs unmodified; everything else stays
  `_Stub`".
- **CEF render** (Panel/PanelRegistry + diff-based `render_payload()`
  pattern): snapshots the shim tree to JSON and renders BC's layout
  top-right over both tactical and bridge views — per-system sliders
  (0–125%, orange overload zone above 100%), the banded Power Used bar
  (blue = within warp-core output ⇒ charging; yellow = drawing Main;
  red = drawing Reserve), Warp Core / Main Battery / Reserve Power columns
  with live percentages, and the siphon lines for Tractor (→ Main, green)
  and Cloak (→ Reserve, red).
- **Inbound control**: CEF slider events → `SetPowerPercentageWanted`
  through the same path as the SDK's `EngineerMenuHandlers.ManagePower`
  keyboard handlers (hotkeys bound via `input_map`). `Refresh()` re-syncs
  shim bars from live subsystem state.
- **Visibility**: SDK-controlled — shows/hides with the SDK engineering
  display (Brex/F5 flow), same precedent as the crew-menu panels.

## 4. Testing & verification

- **Unit** (conventions of `tests/unit/test_power_*.py`): interval-tick
  math (recharge, main-fill/backup-spill/discard, conduit caps, the
  health-scaling asymmetry); all three draw modes + per-class assignments;
  125% clamp; `SetPowerPercentageWanted` rescale semantics; efficiency
  propagation into each effect site; warp-core breach; starbase-dock
  battery refill (`SetMainBatteryPower(limit)` path).
- **Reference-value tests**: the RE deficit table — e.g. Galaxy (output
  1000, combat draw 1651) drains its 250k main battery in ≈ 6 m 24 s;
  assert drain times within tolerance for 2–3 ships. Pins the whole
  pipeline end to end.
- **SDK-integration tests**: PowerDisplay.py boots against the shims with
  no stub fallbacks on its call path; `AdjustPower` throttles
  proportionally with the 20% floor and weapon/engine grouping;
  `ConditionPowerBelow` and `IsPowerDraining` work against the watchers.
- **Gate**: `scripts/check_tests.sh` (pytest + ctest) before merge.
- **Live-verify checklist**: grid renders top-right with correct bands;
  sliders move and change behaviour (impulse 0% = dead stop); red alert
  drains batteries, green recharges; tractor siphon appears while
  tractoring and drains Main; warp-core damage shrinks the blue band and
  triggers auto-rebalance.

## Out of scope

- Multiplayer/network propagation of power state (round-robin StateUpdate
  encoding) — dauntless has no MP layer yet.
- Repair-allocation gameplay (RepairSubsystem drains power here; repair
  logic is its own feature).
- Power-scaled tractor hold strength (undocumented in BC; revisit only if
  live play contradicts).
