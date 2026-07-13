# Power Management System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faithfully reimplement BC's EPS power system — interval tick, conduit draws with three modes, efficiency-scaled gameplay, and the SDK-driven Engineering power-grid UI.

**Architecture:** One `PowerSubsystem` class carries both the damageable warp-core and EPS-distributor roles (matches the SDK's single `ship.GetPowerSubsystem()` handle). Consumers (`PoweredSubsystem` subclasses) draw per-frame from per-interval conduit budgets; their stored `power_factor` scales behaviour at existing effect sites. `Bridge/PowerDisplay.py` runs unmodified against widget shims; a CEF panel renders live state.

**Tech Stack:** Python (engine/appc), existing tg_ui widget-shim conventions, CEF Panel/PanelRegistry pattern, pytest.

**Spec:** `docs/superpowers/specs/2026-07-05-power-management-system-design.md`
**RE reference:** `docs/gameplay/ship-subsystems.md` § Power and reactor

## Global Constraints

- Slider clamp is **[0.0, 1.25]** everywhere (BC constant `1.25f` at `0x0088BEC0`).
- Power interval is **1.0 s of game time** (BC `INTERVAL` at `0x892E20`); consumer draws run **every sim tick** (`TICK_DELTA = 1/60`).
- Main conduit cap is **health-scaled**, backup conduit cap is **not** (RE-verified asymmetry).
- Tractor draw mode is **main-first (mode 0)** — user decision overriding RE doc's mode-1 claim; assignment must stay a single class constant.
- Cloak draw mode is **backup-only (mode 2)**.
- At full power every `power_factor == 1.0`; **existing behaviour must be byte-identical when no deficit exists**.
- Work on branch `feat/power-management` in the main checkout (sdk/ and game/ only exist there).
- After every task: run the task's tests; before merge: `scripts/check_tests.sh` (pytest + ctest gate).
- Python engine files: no `hasattr` guards against our own classes' new methods — implement the method instead (INVALID-hasattr gotcha from the E1M2 audit).
- New event constants go in root `App.py` near the other `ET_*` ints with a collision check (`grep " = <value>$" App.py`).

---

### Task 1: PoweredSubsystem — full SDK power surface

**Files:**
- Modify: `engine/appc/subsystems.py` (PoweredSubsystem, lines ~819–849)
- Modify: `App.py` (add `ET_SUBSYSTEM_POWER_CHANGED`)
- Test: `tests/unit/test_powered_subsystem_surface.py` (new)

**Interfaces:**
- Consumes: existing `ShipSubsystem` base, `App.g_kEventManager` event posting (mirror the seam `CloakingSubsystem` uses for `ET_DECLOAK_COMPLETED` — if its `_fire` helper is cloak-local, hoist it onto `ShipSubsystem` or `PoweredSubsystem`).
- Produces (later tasks rely on these exact names):
  - module constants `PSM_MAIN_FIRST = 0`, `PSM_BACKUP_FIRST = 1`, `PSM_BACKUP_ONLY = 2`
  - class constant `PoweredSubsystem.POWER_MODE = PSM_MAIN_FIRST`
  - `GetPowerWanted() -> float`, `SetPowerWanted(v)`, `GetNormalPowerWanted() -> float` (alias of `GetNormalPowerPerSecond`)
  - `GetPowerReceived() -> float`, `GetPowerPercentage() -> float` (efficiency, 0–1), `GetNormalPowerPercentage() -> float` (power factor, 0–1.25)
  - `SetPowerSource(src)`, `Turn(on)`
  - `SetPowerPercentageWanted(pct)` with clamp + rescale + event
  - `_wants_power() -> bool` (overridable draw gate; base = `IsOn()`)
  - `_update_power(dt, power)` (per-frame draw; body lands in Task 4 — this task adds the state fields it writes)

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_powered_subsystem_surface.py
import App
from engine.appc.subsystems import (
    PoweredSubsystem, PSM_MAIN_FIRST, PSM_BACKUP_FIRST, PSM_BACKUP_ONLY,
)


def test_draw_mode_constants():
    assert (PSM_MAIN_FIRST, PSM_BACKUP_FIRST, PSM_BACKUP_ONLY) == (0, 1, 2)
    assert PoweredSubsystem.POWER_MODE == PSM_MAIN_FIRST


def test_spawn_defaults_bc_faithful():
    ps = PoweredSubsystem("Sensors")
    # BC spawn sequence: every consumer starts at 100% wanted.
    assert ps.GetPowerPercentageWanted() == 1.0
    assert ps.GetPowerWanted() == 0.0
    assert ps.GetPowerReceived() == 0.0
    assert ps.GetNormalPowerPercentage() == 1.0


def test_set_power_percentage_clamps_and_rescales():
    ps = PoweredSubsystem("Phasers")
    ps.SetNormalPowerPerSecond(300.0)
    ps.SetPowerWanted(300.0)
    ps.SetPowerPercentageWanted(2.0)          # clamps to 1.25
    assert ps.GetPowerPercentageWanted() == 1.25
    # BC FUN_00562430: powerWanted rescales by pct/old (old was 1.0)
    assert abs(ps.GetPowerWanted() - 375.0) < 1e-9
    ps.SetPowerPercentageWanted(-1.0)         # clamps to 0.0
    assert ps.GetPowerPercentageWanted() == 0.0


def test_set_power_percentage_posts_event():
    seen = []
    ps = PoweredSubsystem("Shields")
    handler_events = []

    class _Sink:
        def ProcessEvent(self, ev):
            handler_events.append(ev)

    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_SUBSYSTEM_POWER_CHANGED, _Sink(), "ProcessEvent")
    ps.SetPowerPercentageWanted(0.5)
    # Delivery mechanics follow the existing event manager; the assertion is
    # simply that a constant exists and posting doesn't raise.
    assert isinstance(App.ET_SUBSYSTEM_POWER_CHANGED, int)


def test_turn_and_power_source():
    ps = PoweredSubsystem("Sensors")
    ps.Turn(1)
    assert ps.IsOn() == 1
    ps.Turn(0)
    assert ps.IsOn() == 0
    ps.SetPowerSource(1)      # stored, no behaviour yet
    assert ps.GetNormalPowerWanted() == ps.GetNormalPowerPerSecond()
```

Adapt `test_set_power_percentage_posts_event` to the real event-manager API you find (look at how `tests/unit/` tests assert `ET_DECLOAK_COMPLETED` delivery and copy that pattern exactly).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_powered_subsystem_surface.py -v`
Expected: FAIL — `ImportError: cannot import name 'PSM_MAIN_FIRST'`

- [ ] **Step 3: Implement**

In `engine/appc/subsystems.py`, above `PoweredSubsystem`:

```python
# BC draw modes (ship-subsystems.md:164-189). Per-class assignment below;
# tractor is deliberately mode 0 (manual/UI say Main; RE doc's mode-1 claim
# treated as mislabel — see spec "Decisions" §2).
PSM_MAIN_FIRST = 0
PSM_BACKUP_FIRST = 1
PSM_BACKUP_ONLY = 2
```

Extend `PoweredSubsystem.__init__` (keep every existing field):

```python
        self._power_percentage_wanted: float = 1.0   # BC spawns at 100%
        self._power_wanted: float = 0.0              # per-tick demand  (+0x8C)
        self._power_received: float = 0.0            # per-tick receipt (+0x88)
        self._efficiency: float = 1.0                # received/wanted  (+0x94)
        self._power_factor: float = 1.0              # received/(normal*dt) (+0x98)
        self._power_source = None
```

Add methods (class constant `POWER_MODE = PSM_MAIN_FIRST` at class level):

```python
    def SetPowerPercentageWanted(self, pct) -> None:
        pct = float(pct)
        if pct < 0.0:
            pct = 0.0
        if pct > 1.25:
            pct = 1.25
        old = self._power_percentage_wanted
        self._power_percentage_wanted = pct
        # BC FUN_00562430: rescale current demand in place.
        if old != 0.0:
            self._power_wanted = self._power_wanted * pct / old
        self._fire("ET_SUBSYSTEM_POWER_CHANGED")

    def GetPowerWanted(self) -> float:            return self._power_wanted
    def SetPowerWanted(self, v) -> None:          self._power_wanted = float(v)
    def GetNormalPowerWanted(self) -> float:      return self._normal_power
    def GetPowerReceived(self) -> float:          return self._power_received
    def GetPowerPercentage(self) -> float:        return self._efficiency
    def GetNormalPowerPercentage(self) -> float:  return self._power_factor
    def SetPowerSource(self, src) -> None:        self._power_source = src

    def Turn(self, on) -> None:
        if on:
            self.TurnOn()
        else:
            self.TurnOff()

    def _wants_power(self) -> bool:
        return bool(self._is_on)
```

`_fire`: reuse/hoist the cloak's event-post helper so both share one seam. Add to root `App.py` near `ET_MANAGE_POWER = 1067`:

```python
ET_SUBSYSTEM_POWER_CHANGED  = 1068   # SDK 0x0080008C; posted on slider change
```

(verify 1068 is unused first).

**Ripple check:** the default `_power_percentage_wanted` changed 0.0 → 1.0. Run the full unit suite; update any test that asserted the old 0.0 default in the same commit (no orphaned tests).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_powered_subsystem_surface.py tests/unit -x -q`
Expected: PASS (fix ripples per Step 3 note)

- [ ] **Step 5: Commit**

```bash
git add -A engine/appc/subsystems.py App.py tests/
git commit -m "feat(power): PoweredSubsystem full SDK surface + faithful slider semantics"
```

---

### Task 2: PowerSubsystem — batteries, conduits, health-scaled output

**Files:**
- Modify: `engine/appc/subsystems.py` (PowerSubsystem, lines ~1216–1394)
- Test: `tests/unit/test_power_subsystem_conduits.py` (new)

**Interfaces:**
- Consumes: `PowerProperty` data-bag (`engine/appc/properties.py` — `GetPowerOutput/GetMainBatteryLimit/GetBackupBatteryLimit/GetMainConduitCapacity/GetBackupConduitCapacity` already work via `__getattr__`), `ShipSubsystem.GetConditionPercentage()`.
- Produces:
  - `GetPowerOutput() -> float` — property output × conditionPct (health-scaled)
  - `GetMainBatteryLimit()/GetBackupBatteryLimit() -> float` — delegate to property (0.0 if none)
  - `GetMaxMainConduitCapacity() -> float` — raw property value
  - `GetMainConduitCapacity() -> float` — property × conditionPct
  - `GetBackupConduitCapacity() -> float` — raw property value (NOT health-scaled)
  - `GetPowerDispensed() -> float`, `GetPowerWanted() -> float` (sum of consumer wants this tick — filled by Task 4, field exists now: `_power_wanted_total`)
  - `SetProperty(prop)` override that fills both batteries to their limits (BC `FUN_005636D0`)
  - `StealPower(amount) -> float` (main only), `StealPowerFromReserve(amount) -> float` (backup only) — return the amount actually taken
  - internal fields `_main_conduit_current`, `_backup_conduit_current`, `_interval_elapsed`, `_power_dispensed`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_power_subsystem_conduits.py
from engine.appc.subsystems import PowerSubsystem
from engine.appc.properties import PowerProperty


def _bind(ps, output=1000.0, main=250000.0, backup=80000.0,
          main_conduit=1200.0, backup_conduit=200.0):
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(output)
    prop.SetMainBatteryLimit(main)
    prop.SetBackupBatteryLimit(backup)
    prop.SetMainConduitCapacity(main_conduit)
    prop.SetBackupConduitCapacity(backup_conduit)
    ps.SetProperty(prop)
    return prop


def test_set_property_fills_batteries():
    ps = PowerSubsystem("Warp Core")
    _bind(ps)
    assert ps.GetMainBatteryPower() == 250000.0
    assert ps.GetBackupBatteryPower() == 80000.0
    assert ps.GetMainBatteryLimit() == 250000.0
    assert ps.GetBackupBatteryLimit() == 80000.0


def test_output_and_main_conduit_scale_with_health_backup_does_not():
    ps = PowerSubsystem("Warp Core")
    _bind(ps)
    ps.SetMaxCondition(7000.0)
    ps.SetCondition(3500.0)          # 50% health
    assert abs(ps.GetPowerOutput() - 500.0) < 1e-6
    assert abs(ps.GetMainConduitCapacity() - 600.0) < 1e-6
    assert ps.GetMaxMainConduitCapacity() == 1200.0
    assert ps.GetBackupConduitCapacity() == 200.0    # NOT health-scaled


def test_steal_power_is_reservoir_specific():
    ps = PowerSubsystem("Warp Core")
    _bind(ps, main=100.0, backup=50.0)
    got = ps.StealPower(80.0)
    assert got == 80.0 and ps.GetMainBatteryPower() == 20.0
    got = ps.StealPower(50.0)                       # only 20 left in main
    assert got == 20.0 and ps.GetBackupBatteryPower() == 50.0  # backup untouched
    got = ps.StealPowerFromReserve(60.0)
    assert got == 50.0 and ps.GetBackupBatteryPower() == 0.0
```

Adapt `SetMaxCondition/SetCondition` to the real `ShipSubsystem` condition API found in the file (the existing tests in `tests/unit/test_power_subsystem_budget.py` show the convention).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_power_subsystem_conduits.py -v`
Expected: FAIL — `AttributeError`/wrong values (e.g. `GetMainBatteryLimit` missing, batteries start 0)

- [ ] **Step 3: Implement**

In `PowerSubsystem.__init__` add:

```python
        self._main_conduit_current: float = 0.0
        self._backup_conduit_current: float = 0.0
        self._interval_elapsed: float = 0.0
        self._power_dispensed: float = 0.0
        self._power_wanted_total: float = 0.0
```

Add/replace methods (keep every existing method not named here):

```python
    def SetProperty(self, prop) -> None:
        super().SetProperty(prop)
        if prop is not None:
            # BC FUN_005636D0: ships spawn with batteries full.
            self._main_battery_power = float(prop.GetMainBatteryLimit() or 0.0)
            self._backup_battery_power = float(prop.GetBackupBatteryLimit() or 0.0)

    def _prop_f(self, getter_name: str) -> float:
        prop = self.GetProperty()
        if prop is None:
            return 0.0
        return float(getattr(prop, getter_name)() or 0.0)

    def GetPowerOutput(self) -> float:
        return self._prop_f("GetPowerOutput") * self.GetConditionPercentage()

    def GetMainBatteryLimit(self) -> float:      return self._prop_f("GetMainBatteryLimit")
    def GetBackupBatteryLimit(self) -> float:    return self._prop_f("GetBackupBatteryLimit")
    def GetMaxMainConduitCapacity(self) -> float: return self._prop_f("GetMainConduitCapacity")

    def GetMainConduitCapacity(self) -> float:
        return self._prop_f("GetMainConduitCapacity") * self.GetConditionPercentage()

    def GetBackupConduitCapacity(self) -> float:  # deliberately NOT health-scaled
        return self._prop_f("GetBackupConduitCapacity")

    def GetPowerDispensed(self) -> float:         return self._power_dispensed
    def GetPowerWanted(self) -> float:            return self._power_wanted_total

    def StealPower(self, amount) -> float:
        take = min(float(amount), self._main_battery_power)
        self._main_battery_power -= take
        return take

    def StealPowerFromReserve(self, amount) -> float:
        take = min(float(amount), self._backup_battery_power)
        self._backup_battery_power -= take
        return take
```

If the existing `StealPower`/`StealPowerFromReserve` have different signatures/returns, replace them and update their tests in the same commit. Check `engine/appc/weapon_subsystems.py` tractor `UpdateCharge` (~line 1614) — it calls `ps.StealPower(cost)` in a boolean context; a float return of 0.0 is falsy, partial steals are truthy. Leave that call working for now (Task 4 replaces it).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_power_subsystem_conduits.py tests/unit -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A engine/appc/subsystems.py tests/
git commit -m "feat(power): battery/conduit surface with health-scaling asymmetry"
```

---

### Task 3: Interval tick — recharge, spill, conduit budgets

**Files:**
- Modify: `engine/appc/subsystems.py` (PowerSubsystem.Update, ~lines 1354–1393)
- Test: `tests/unit/test_power_interval_tick.py` (new)

**Interfaces:**
- Consumes: Task 2 fields/getters; existing `FloatRangeWatcher._update(fraction)`; `engine/core/loop.py` already calls `ps.Update(TICK_DELTA)` per sim tick.
- Produces: `Update(dt)` with BC interval semantics; `_add_power_to_batteries(amount)`; `GetAvailablePower()` = conduit budget sum after each interval. The per-frame consumer pump call (`_pump_consumers(dt)`) is a stub here; Task 4 fills it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_power_interval_tick.py
from engine.appc.subsystems import PowerSubsystem
from engine.appc.properties import PowerProperty


def _bind(ps, output=1000.0, main=250000.0, backup=80000.0,
          main_conduit=1200.0, backup_conduit=200.0):
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(output)
    prop.SetMainBatteryLimit(main)
    prop.SetBackupBatteryLimit(backup)
    prop.SetMainConduitCapacity(main_conduit)
    prop.SetBackupConduitCapacity(backup_conduit)
    ps.SetProperty(prop)
    return prop


def _run_seconds(ps, seconds, dt=1.0 / 60.0):
    for _ in range(int(seconds / dt)):
        ps.Update(dt)


def test_recharge_fills_main_then_spills_to_backup_then_discards():
    ps = PowerSubsystem("Warp Core")
    _bind(ps, output=1000.0, main=500.0, backup=300.0)
    ps.SetMainBatteryPower(0.0)
    ps.SetBackupBatteryPower(0.0)
    _run_seconds(ps, 1.05)            # one full interval fires
    assert ps.GetMainBatteryPower() == 500.0          # filled + capped
    assert abs(ps.GetBackupBatteryPower() - 500.0) < 100.0 or ps.GetBackupBatteryPower() <= 300.0
    _run_seconds(ps, 2.0)
    assert ps.GetMainBatteryPower() == 500.0
    assert ps.GetBackupBatteryPower() == 300.0        # capped; overflow discarded


def test_conduit_budgets_computed_per_interval():
    ps = PowerSubsystem("Warp Core")
    _bind(ps)
    _run_seconds(ps, 1.05)
    # Full batteries, full health: budgets = capacity * elapsed(≈1s)
    assert abs(ps.GetAvailablePower() - (1200.0 + 200.0)) < 30.0


def test_no_recharge_while_reactor_disabled():
    ps = PowerSubsystem("Warp Core")
    _bind(ps, main=1000.0)
    ps.SetMainBatteryPower(0.0)
    ps.SetBackupBatteryPower(0.0)
    # Drive to disabled via the existing damage/disabled API — see
    # test_power_repair_subsystems.py for the convention (SetDisabled or
    # condition below DisabledPercentage).
    ps.SetDisabled(1)
    _run_seconds(ps, 2.0)
    assert ps.GetMainBatteryPower() == 0.0
```

Tune the tolerance/exact numbers once you see the interval boundary behaviour (elapsed is a whole number of 1/60 ticks ≥ 1.0 s, so budgets use `elapsed ≈ 1.0167 s`; assert accordingly with the exact value, not a loose tolerance).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_power_interval_tick.py -v`
Expected: FAIL (current Update is a per-dt net-energy model with no interval, no spill-discard, no conduit budgets)

- [ ] **Step 3: Implement — replace `Update` and `_compute_idle_drain` consumers**

```python
    POWER_INTERVAL = 1.0   # seconds of game time; BC constant 0x892E20

    def _add_power_to_batteries(self, amount: float) -> None:
        """Main first (capped), spill to backup (capped), discard the rest."""
        main_cap = self.GetMainBatteryLimit()
        backup_cap = self.GetBackupBatteryLimit()
        room = main_cap - self._main_battery_power
        take = min(amount, max(room, 0.0))
        self._main_battery_power += take
        spill = amount - take
        room = backup_cap - self._backup_battery_power
        self._backup_battery_power += min(spill, max(room, 0.0))

    def Update(self, dt: float) -> None:
        prop = self.GetProperty()
        if prop is None:
            return
        dt = float(dt)
        self._interval_elapsed += dt
        if self._interval_elapsed >= self.POWER_INTERVAL:
            elapsed = self._interval_elapsed
            self._interval_elapsed = 0.0
            self._power_dispensed = 0.0
            if not self._is_offline():
                self._add_power_to_batteries(self.GetPowerOutput() * elapsed)
            main_max = self.GetMainConduitCapacity() * elapsed
            backup_max = self.GetBackupConduitCapacity() * elapsed
            self._main_conduit_current = min(self._main_battery_power, main_max)
            self._backup_conduit_current = min(self._backup_battery_power, backup_max)
            self._available_power = (self._main_conduit_current
                                     + self._backup_conduit_current)
        self._pump_consumers(dt)     # Task 4 fills this in
        main_cap = self.GetMainBatteryLimit()
        backup_cap = self.GetBackupBatteryLimit()
        self._main_battery_watcher._update(
            self._main_battery_power / main_cap if main_cap > 0.0 else 0.0)
        self._backup_battery_watcher._update(
            self._backup_battery_power / backup_cap if backup_cap > 0.0 else 0.0)

    def _pump_consumers(self, dt: float) -> None:
        pass   # Task 4
```

`_is_offline()`: reuse the module's existing offline predicate (`_is_offline(self)` helper or `IsDisabled()/IsDestroyed()` — match what `ShieldSubsystem.Update` uses). Delete `_compute_idle_drain` **only after** Task 4 replaces its callers; for now leave it unused-but-present so nothing breaks mid-plan.

**Ripple check:** `tests/unit/test_power_subsystem_update.py` tests the old net-energy model — rewrite its cases against interval semantics in this commit (they cover generation minus drain; drain now arrives in Task 4, so the rewritten file covers generation/caps only and Task 4 extends it).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_power_interval_tick.py tests/unit -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A engine/appc/subsystems.py tests/
git commit -m "feat(power): BC interval tick — recharge, spill-discard, conduit budgets"
```

---

### Task 4: Per-frame consumer draws — modes, efficiency, registration

**Files:**
- Modify: `engine/appc/subsystems.py` (PowerSubsystem._pump_consumers + _draw; PoweredSubsystem._update_power; CloakingSubsystem.POWER_MODE + _wants_power)
- Modify: `engine/appc/ships.py` (`_attach_subsystem`, ~line 660: register powered consumers in attach order)
- Modify: `engine/appc/weapon_subsystems.py` (TractorBeamSystem: `_wants_power` override; delete the `StealPower` block in `UpdateCharge` ~lines 1614–1640)
- Test: `tests/unit/test_power_consumer_draws.py` (new)

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `ShipClass._powered_consumers: list` (attach order = draw priority, mirroring BC's linked list)
  - `PowerSubsystem._draw(amount, mode) -> float` — depletes conduit budget AND battery
  - `PoweredSubsystem._update_power(dt, power)` — sets `_power_wanted/_power_received/_efficiency/_power_factor`
  - `CloakingSubsystem.POWER_MODE = PSM_BACKUP_ONLY`, `_wants_power() -> IsTryingToCloak()`
  - `TractorBeamSystem._wants_power()` — True only while a child weapon is firing (keep `POWER_MODE` inherited mode 0)

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_power_consumer_draws.py
from engine.appc.subsystems import (
    PowerSubsystem, PoweredSubsystem, PSM_BACKUP_ONLY, CloakingSubsystem,
)
from engine.appc.properties import PowerProperty


def _powered_ship():
    """Minimal ship: power plant + one 100 pw/s consumer. Use the loadout
    factory from test_ship_alert_powers_weapons.py (_galaxy_loadout) if it
    binds faster; otherwise construct via App.ShipClass_Create + setters."""
    import App
    ship = App.ShipClass_Create("TestShip")
    power = PowerSubsystem("Warp Core")
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(1000.0)
    prop.SetMainBatteryLimit(1000.0)
    prop.SetBackupBatteryLimit(500.0)
    prop.SetMainConduitCapacity(1200.0)
    prop.SetBackupConduitCapacity(200.0)
    power.SetProperty(prop)
    ship.SetPowerSubsystem(power)
    consumer = PoweredSubsystem("Sensor Array")
    consumer.SetNormalPowerPerSecond(100.0)
    consumer.TurnOn()
    ship.AddPoweredConsumer(consumer)   # or the real attach API — see ships.py
    return ship, power, consumer


def _tick(power, seconds, dt=1.0 / 60.0):
    for _ in range(int(seconds / dt)):
        power.Update(dt)


def test_full_power_consumer_gets_factor_one():
    ship, power, consumer = _powered_ship()
    _tick(power, 2.0)
    assert abs(consumer.GetPowerPercentage() - 1.0) < 1e-6
    assert abs(consumer.GetNormalPowerPercentage() - 1.0) < 1e-6


def test_boost_raises_factor_above_one():
    ship, power, consumer = _powered_ship()
    consumer.SetPowerPercentageWanted(1.25)
    _tick(power, 2.0)
    assert abs(consumer.GetNormalPowerPercentage() - 1.25) < 1e-3
    assert abs(consumer.GetPowerPercentage() - 1.0) < 1e-6   # fully fed


def test_starved_consumer_efficiency_drops():
    ship, power, consumer = _powered_ship()
    # Zero the reservoirs and the generator: nothing to draw.
    power.SetMainBatteryPower(0.0)
    power.SetBackupBatteryPower(0.0)
    power.GetProperty().SetPowerOutput(0.0)
    _tick(power, 2.0)
    assert consumer.GetPowerPercentage() == 0.0
    assert consumer.GetNormalPowerPercentage() == 0.0


def test_zero_normal_power_consumer_is_free_and_full():
    ship, power, consumer = _powered_ship()
    consumer.SetNormalPowerPerSecond(0.0)     # e.g. authored warp engines
    _tick(power, 2.0)
    assert consumer.GetNormalPowerPercentage() == 1.0


def test_backup_only_mode_never_touches_main():
    ship, power, consumer = _powered_ship()
    consumer.POWER_MODE = PSM_BACKUP_ONLY     # instance override fine for test
    main_before = None
    _tick(power, 1.05)                        # budgets seeded
    main_before = power.GetMainBatteryPower()
    _tick(power, 1.0)
    # Consumer drew only from backup; main moved only by recharge (capped: 0 delta)
    assert power.GetMainBatteryPower() >= main_before


def test_draws_deplete_battery_and_dispensed_counter():
    ship, power, consumer = _powered_ship()
    power.GetProperty().SetPowerOutput(0.0)   # no recharge: watch pure drain
    _tick(power, 3.0)
    assert power.GetMainBatteryPower() < 1000.0
    assert power.GetPowerDispensed() > 0.0
```

Adjust `SetPowerSubsystem`/`AddPoweredConsumer` to the real ship attach API found in `engine/appc/ships.py:660–753` (likely `_attach_subsystem` + slot setter); if consumer registration is new, name the public registration exactly `AddPoweredConsumer(subsystem)` so later tasks/tests match.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_power_consumer_draws.py -v`
Expected: FAIL — no registration API / factors never move

- [ ] **Step 3: Implement**

`engine/appc/ships.py` — in `_attach_subsystem` (after parent wiring):

```python
        if isinstance(subsystem, PoweredSubsystem) and subsystem not in self._powered_consumers:
            self._powered_consumers.append(subsystem)   # attach order = BC draw priority
```

(add `self._powered_consumers: list = []` to `ShipClass.__init__` and a public `AddPoweredConsumer` alias used by tests; import at module top, no local imports.)

`engine/appc/subsystems.py`:

```python
    # on PowerSubsystem
    def _pump_consumers(self, dt: float) -> None:
        ship = self.GetParentShip()
        consumers = getattr(ship, "_powered_consumers", None) if ship is not None else None
        if not consumers:
            return
        self._power_wanted_total = 0.0
        for consumer in consumers:
            consumer._update_power(dt, self)
            self._power_wanted_total += consumer.GetPowerWanted()

    def _draw(self, amount: float, mode: int) -> float:
        if amount <= 0.0:
            return 0.0
        got = 0.0
        if mode == PSM_MAIN_FIRST:
            got += self._draw_main(amount)
            got += self._draw_backup(amount - got)
        elif mode == PSM_BACKUP_FIRST:
            got += self._draw_backup(amount)
            got += self._draw_main(amount - got)
        else:  # PSM_BACKUP_ONLY — no fallback
            got += self._draw_backup(amount)
        self._power_dispensed += got
        return got

    def _draw_main(self, amount: float) -> float:
        take = min(amount, self._main_conduit_current, self._main_battery_power)
        if take <= 0.0:
            return 0.0
        self._main_conduit_current -= take
        self._main_battery_power -= take
        return take

    def _draw_backup(self, amount: float) -> float:
        take = min(amount, self._backup_conduit_current, self._backup_battery_power)
        if take <= 0.0:
            return 0.0
        self._backup_conduit_current -= take
        self._backup_battery_power -= take
        return take
```

```python
    # on PoweredSubsystem
    def _update_power(self, dt: float, power) -> None:
        dt = float(dt)
        if dt <= 0.0:
            return
        if not self._wants_power():
            self._power_wanted = 0.0
            self._power_received = 0.0
            self._efficiency = 0.0
            self._power_factor = 0.0
            return
        base = self._normal_power * dt
        if base <= 0.0:
            # Free consumer (authored 0 pw/s, e.g. warp engines): full function.
            self._power_wanted = 0.0
            self._power_received = 0.0
            self._efficiency = 1.0
            self._power_factor = 1.0
            return
        wanted = base * self._power_percentage_wanted
        self._power_wanted = wanted
        received = power._draw(wanted, self.POWER_MODE) if wanted > 0.0 else 0.0
        self._power_received = received
        self._efficiency = received / wanted if wanted > 0.0 else 1.0
        self._power_factor = received / base
```

`CloakingSubsystem` (class body):

```python
    POWER_MODE = PSM_BACKUP_ONLY   # RE ship-subsystems.md:185 — locked off the main grid

    def _wants_power(self) -> bool:
        return bool(self.IsTryingToCloak())
```

`engine/appc/weapon_subsystems.py` — `TractorBeamSystem`:

```python
    def _wants_power(self) -> bool:
        # Draws only while a beam is held (PowerDisplay's siphon semantics).
        return bool(self.IsOn()) and self._any_child_firing()
```

Implement `_any_child_firing()` from the existing child-weapon iteration (`GetNumChildSubsystems()/GetWeapon(i).IsFiring()` — same walk `PowerDisplay.HandleTractor` does). **Delete** the `StealPower(cost)` block in `UpdateCharge` (~1614–1640) and instead stop firing when starved:

```python
    def UpdateCharge(self, dt: float) -> None:
        if self._firing and self.GetPowerPercentage() <= 0.0 and self.GetNormalPowerWanted() > 0.0:
            self.StopFiring()
        super().UpdateCharge(dt)
```

Now delete `PowerSubsystem._compute_idle_drain` and its call site; the cloak special-case moves to `CloakingSubsystem._wants_power`. Weapon-system consumers (`PhaserSystem`, `TorpedoSystem`, `PulseWeaponSystem`) need no override — `IsOn()` (alert-driven) is the correct gate.

**Ripple check:** update `test_power_subsystem_update.py` drain cases, tractor power-gate tests (`test_weapon_system_powered.py`, `test_torpedo_tube_power_gate.py`) to the new draw model in this commit.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_power_consumer_draws.py tests/unit -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A engine/appc tests/
git commit -m "feat(power): per-frame consumer draws with three modes + efficiency"
```

---

### Task 5: Warp-core breach — reactor death destroys the ship

**Files:**
- Modify: `engine/appc/subsystems.py` (PowerSubsystem.Update)
- Test: `tests/unit/test_warp_core_breach.py` (new)

**Interfaces:**
- Consumes: whatever routine the combat path uses to kill a ship when hull reaches zero (find it: `grep -n "def.*[Dd]estroy" engine/appc/combat.py engine/appc/ships.py` — reuse that exact routine so death VFX/events match).
- Produces: destroying the power subsystem (`ship.DestroySystem(ship.GetPowerSubsystem())` or condition → 0) destroys the ship once, next power tick.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_warp_core_breach.py
def test_destroyed_reactor_breaches_ship():
    ship, power, _ = _powered_ship()      # reuse helper from task 4's test file
    power.SetCondition(0.0)               # or ship.DestroySystem(power) — match API
    for _ in range(120):
        power.Update(1.0 / 60.0)
    assert ship.IsDead() or ship.IsDying()   # match the real death predicate
```

Import the `_powered_ship` helper (move it to a shared `tests/unit/power_helpers.py` if pytest collection complains).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_warp_core_breach.py -v`
Expected: FAIL — ship survives reactor destruction

- [ ] **Step 3: Implement**

In `PowerSubsystem.Update`, before the interval block:

```python
        if self.IsDestroyed() and not self._breach_fired:
            self._breach_fired = True
            self._trigger_breach()
```

`_breach_fired = False` in `__init__`. `_trigger_breach()` calls the located ship-death routine on `self.GetParentShip()` (manual p.16: "Reaching 0% causes a warp-core breach and destroys the ship"). Guard `None` ship.

- [ ] **Step 4: Run tests** — `uv run pytest tests/unit/test_warp_core_breach.py tests/unit -x -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add -A engine/appc/subsystems.py tests/
git commit -m "feat(power): warp-core breach destroys the ship"
```

---

### Task 6: Effect — impulse power factor scales motion

**Files:**
- Modify: `engine/appc/ship_motion.py` (`_effective_motion`, lines ~62–79)
- Test: `tests/unit/test_motion_power_factor.py` (new)

**Interfaces:**
- Consumes: `ImpulseEngineSubsystem.GetNormalPowerPercentage()` (Task 1/4).
- Produces: effective max speed/accel/ang-vel/ang-accel scale by the power factor (0 → dead stop; 1.25 → +25% caps).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_motion_power_factor.py
from engine.appc.ship_motion import _effective_motion
from engine.appc.subsystems import ImpulseEngineSubsystem


class _Ship:
    def __init__(self, ies):
        self._ies = ies
    def GetImpulseEngineSubsystem(self):
        return self._ies


def _engines(max_speed=6.3, ang=0.4):
    ies = ImpulseEngineSubsystem("Impulse Engines")
    ies.SetMaxSpeed(max_speed)
    ies.SetMaxAngularVelocity(ang)
    ies.SetNormalPowerPerSecond(150.0)
    ies.TurnOn()
    return ies


def test_full_power_unchanged():
    ies = _engines()
    ies._power_factor = 1.0
    m = _effective_motion(_Ship(ies), 1.0)
    assert abs(m.max_speed - 6.3) < 1e-9


def test_half_power_halves_caps():
    ies = _engines()
    ies._power_factor = 0.5
    m = _effective_motion(_Ship(ies), 1.0)
    assert abs(m.max_speed - 3.15) < 1e-9
    assert abs(m.max_ang_vel - 0.2) < 1e-9


def test_boost_raises_caps():
    ies = _engines()
    ies._power_factor = 1.25
    m = _effective_motion(_Ship(ies), 1.0)
    assert abs(m.max_speed - 6.3 * 1.25) < 1e-9
```

- [ ] **Step 2: Run test** → FAIL (factor ignored)

- [ ] **Step 3: Implement** — in `_effective_motion`, after resolving `ies`:

```python
    power_factor = ies.GetNormalPowerPercentage() if ies is not None else 1.0
    f = f * power_factor
```

(one line before the existing `raw_speed` reads; everything downstream already multiplies by `f`).

- [ ] **Step 4: Run tests** — targeted file + `tests/unit -x -q` → PASS. Also run the AI smoke tests that drive ship motion (`uv run pytest tests -k "motion or speed" -q`) — at full power nothing may change.

- [ ] **Step 5: Commit**

```bash
git add -A engine/appc/ship_motion.py tests/
git commit -m "feat(power): impulse power factor scales speed/turn caps"
```

---

### Task 7: Effects — shield regen and sensor range scale by power factor

**Files:**
- Modify: `engine/appc/subsystems.py` (ShieldSubsystem.Update regen line ~1186)
- Modify: `engine/appc/sensor_detection.py` (range return, line ~86)
- Test: `tests/unit/test_shield_sensor_power_factor.py` (new)

**Interfaces:**
- Consumes: `GetNormalPowerPercentage()` on `ShieldSubsystem` / `SensorSubsystem`.
- Produces: per-face regen `charge_per_second * power_factor * dt`; sensor range `base * conditionPct * power_factor`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_shield_sensor_power_factor.py
from engine.appc.subsystems import ShieldSubsystem, SensorSubsystem


def test_shield_regen_scales_with_power_factor():
    ss = ShieldSubsystem("Shield Generator")
    ss.TurnOn()
    ss.SetMaxShields(ss.FRONT_SHIELDS, 100.0)
    ss.SetCurShields(ss.FRONT_SHIELDS, 0.0)
    ss.SetShieldChargePerSecond(ss.FRONT_SHIELDS, 10.0)
    ss._power_factor = 0.5
    ss.Update(1.0)
    assert abs(ss.GetCurShields(ss.FRONT_SHIELDS) - 5.0) < 1e-9
    ss._power_factor = 1.25
    ss.Update(1.0)
    assert abs(ss.GetCurShields(ss.FRONT_SHIELDS) - 17.5) < 1e-9


def test_sensor_range_scales_with_power_factor():
    from engine.appc import sensor_detection
    sen = SensorSubsystem("Sensor Array")
    sen.SetBaseSensorRange(100.0)
    sen._power_factor = 1.25

    class _Ship:
        def GetSensorSubsystem(self):
            return sen

    rng = sensor_detection.<the-range-function>(_Ship())
    assert abs(rng - 125.0) < 1e-6
```

Fill `<the-range-function>` with the real name at `sensor_detection.py:76–86`; match the face-constant and shield-setter names to the real `ShieldSubsystem` API.

- [ ] **Step 2: Run tests** → FAIL

- [ ] **Step 3: Implement**

Shield regen (line ~1186): `new = self._current_shields[f] + self._charge_per_second[f] * self.GetNormalPowerPercentage() * dt`

Sensor range (line ~86): `return base * sensors.GetConditionPercentage() * sensors.GetNormalPowerPercentage()`

- [ ] **Step 4: Run tests** — targeted + full unit suite → PASS (existing shield tests run at factor 1.0, unchanged)

- [ ] **Step 5: Commit**

```bash
git add -A engine/appc tests/
git commit -m "feat(power): shield regen and sensor range scale by power factor"
```

---

### Task 8: Effects — weapon charge and torpedo reload scale by power factor

**Files:**
- Modify: `engine/appc/weapon_subsystems.py` (phaser/pulse `UpdateCharge` ~lines 417–446; torpedo `UpdateReload` ~lines 1768–1775)
- Test: `tests/unit/test_weapon_power_factor.py` (new)

**Interfaces:**
- Consumes: parent weapon-system `GetNormalPowerPercentage()` (the *system* is the `PoweredSubsystem`; individual weapons are its children — read the factor via `self.GetParentSubsystem()`).
- Produces: idle recharge `self._recharge_rate * factor * dt`; torpedo effective reload delay `self._reload_delay / factor` (no reload at factor 0).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_weapon_power_factor.py
def test_phaser_recharge_scales_with_system_power_factor():
    # Build a phaser bank whose parent PhaserSystem has _power_factor = 0.5;
    # copy the fixture from tests/unit/test_weapon_system_powered.py.
    system, weapon = _phaser_fixture()
    system._power_factor = 0.5
    before = weapon.GetChargeLevel()
    weapon.UpdateCharge(1.0)
    gained_half = weapon.GetChargeLevel() - before
    system._power_factor = 1.0
    weapon2_gain = _fresh_gain(system)         # same fixture, factor 1.0
    assert abs(gained_half - 0.5 * weapon2_gain) < 1e-6


def test_torpedo_reload_stalls_at_zero_factor():
    system, tube = _torpedo_fixture()          # from test_torpedo_tube_power_gate.py
    system._power_factor = 0.0
    # fire, then advance past the normal reload delay: no new ready torpedo
    ...
```

Write these against the real fixtures in `test_weapon_system_powered.py` / `test_torpedo_tube_power_gate.py` — copy their construction verbatim rather than inventing new helpers.

- [ ] **Step 2: Run tests** → FAIL

- [ ] **Step 3: Implement**

Phaser/pulse idle recharge (line ~437):

```python
                factor = parent.GetNormalPowerPercentage() if parent is not None else 1.0
                want = min(self._recharge_rate * factor * dt, headroom)
```

Torpedo `UpdateReload` (~1768): compute `factor` from the parent system; if `factor <= 0.0` return early; else compare elapsed against `self._reload_delay / factor`. Note this method uses wall-clock `time.monotonic()` — scale the *threshold*, don't touch the clock.

- [ ] **Step 4: Run tests** — targeted + full unit suite → PASS

- [ ] **Step 5: Commit**

```bash
git add -A engine/appc/weapon_subsystems.py tests/
git commit -m "feat(power): weapon charge and torpedo reload scale by power factor"
```

---

### Task 9: Cloak starvation auto-decloak + reference-value drain test

**Files:**
- Modify: `engine/appc/subsystems.py` (CloakingSubsystem.Update)
- Test: `tests/unit/test_cloak_power_starvation.py` (new)
- Test: `tests/integration/test_power_reference_values.py` (new)

**Interfaces:**
- Consumes: cloak `GetPowerPercentage()` (efficiency), Tasks 1–4; Galaxy hardpoint values (output 1000, draw table `ship-subsystems.md:370–386`).
- Produces: cloaked ship with empty backup battery force-decloaks; end-to-end drain times match BC's reference table.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_cloak_power_starvation.py
def test_cloak_drops_when_backup_battery_empties():
    ship, power, _ = _powered_ship()
    cloak = CloakingSubsystem("Cloaking Device")
    cloak.SetNormalPowerPerSecond(1000.0)
    ship.AddPoweredConsumer(cloak)
    # attach cloak to ship slot per existing cloak tests' convention
    power.SetBackupBatteryPower(10.0)          # nearly dry
    power.GetProperty().SetPowerOutput(0.0)    # no recharge
    cloak.<start-cloak-per-existing-API>()
    for _ in range(600):                       # 10 s
        power.Update(1.0 / 60.0)
        cloak.Update(1.0 / 60.0)
    assert cloak.IsTryingToCloak() == 0        # forced decloak
```

```python
# tests/integration/test_power_reference_values.py
"""Pins the whole pipeline to BC's deficit table (ship-subsystems.md:370-386).
Galaxy: output 1000, full-combat draw 1651 -> deficit 651 -> main battery
(250k) drains in ~384 s (~6 m 24 s)."""


def test_galaxy_full_load_drain_time_matches_bc():
    ship = _galaxy_with_authored_power()   # power 1000/250k/80k/1200/200 +
                                           # consumers: impulse 150, sensors 100,
                                           # shields 400, phasers 300, torps 100,
                                           # warp 0, tractor 600 idle (not firing),
                                           # engineering(repair) 1 -> active draw 1051
    # Turn everything on except tractor (not firing) => idle-combat draw 1051.
    # deficit = 51; add 125% boosts or torpedo etc. to hit the documented
    # 1651 total: set every slider to 1.0 and turn ALL weapon systems on.
    power = ship.GetPowerSubsystem()
    seconds = 0
    dt = 1.0 / 60.0
    while power.GetMainBatteryPower() > 0.0 and seconds < 10000:
        power.Update(dt)
        seconds += dt
    expected = 250000.0 / <computed deficit>
    assert abs(seconds - expected) / expected < 0.05    # within 5%
```

Compute `<computed deficit>` from the consumers you actually enable — assert the *model* (drain time = capacity / deficit), then add a second assertion that the fully-loaded Galaxy deficit is 651 ± 1 when all seven table consumers draw (the table's 1651 total includes tractor firing at 600: enable it).

- [ ] **Step 2: Run tests** → FAIL

- [ ] **Step 3: Implement the cloak drop**

In `CloakingSubsystem.Update`, after the existing offline force-decloak block:

```python
        # Power starvation: backup battery dry => the device disengages
        # (ship-subsystems.md:187-189). Exact BC threshold unknown; 0.25 chosen —
        # tune from live play, keep as a named constant.
        AUTO_DECLOAK_EFFICIENCY = 0.25
        if (self.IsTryingToCloak() and self.GetNormalPowerWanted() > 0.0
                and self.GetPowerPercentage() < AUTO_DECLOAK_EFFICIENCY):
            self._force_decloak()
```

`_force_decloak()`: extract the existing offline-path body (state → DECLOAKED + `ET_DECLOAK_COMPLETED` when it was fully cloaked) into this helper and call it from both places.

- [ ] **Step 4: Run tests** — both new files + full unit suite → PASS

- [ ] **Step 5: Commit**

```bash
git add -A engine/appc/subsystems.py tests/
git commit -m "feat(power): cloak starvation auto-decloak + BC reference drain test"
```

---

### Task 10: Widget shims — TGFrame, STTiledIcon, STNumericBar, STFillGauge, App.globals

**Files:**
- Modify: `engine/appc/tg_ui/widgets.py` (add TGFrame, STTiledIcon)
- Create: `engine/appc/tg_ui/eng_power.py` (STNumericBar, STFillGauge — Eng* classes come in Task 11)
- Modify: `App.py` (exports, `globals` namespace, engineering colours, `TGFrame_Create/Cast`, `STTiledIcon_Create/Cast`)
- Test: `tests/unit/test_tg_ui_power_widgets.py` (new)

**Interfaces:**
- Consumes: existing `TGPane` base + factory/cast conventions in `widgets.py`.
- Produces (exact names PowerDisplay.py calls):
  - `TGFrame(TGPane)`: `GetInnerRect() -> rect` (rect has `GetLeft()/GetTop()` → 0.0), `SetNiColor(r,g,b,a)`, `SetEdgeStretch(mode)`, class constant `NO_STRETCH_LR`
  - `STTiledIcon(TGIcon)`: `SetTiling(direction, n)`, `SetTileSize(direction, size)`, class constants `DIRECTION_X = 0`, `DIRECTION_Y = 1`
  - `STNumericBar(TGPane)`: `SetValue(v)/GetValue()`, `SetRange(lo, hi)`, `SetColor(c)`
  - `STFillGauge(TGPane)`: `SetFillFraction(f)/GetFillFraction()`, `SetEmptyColor(c)`, `SetFillColor(c)`
  - `App.globals` — a namespace object with `DEFAULT_ST_INDENT_HORIZ = 5.0`, `DEFAULT_ST_INDENT_VERT = 5.0`, and all nine `g_kEngineering*Color` NiColorA values; the same colour names also exported at `App` top level (SDK App.py re-exports them, lines 13994–14003)

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_tg_ui_power_widgets.py
import App


def test_tgframe_surface():
    f = App.TGFrame_Create("lcars", 4300)
    rect = f.GetInnerRect()
    assert rect.GetLeft() == 0.0 and rect.GetTop() == 0.0
    f.SetNiColor(0.2, 0.4, 1.0, 1.0)
    f.SetEdgeStretch(App.TGFrame.NO_STRETCH_LR)
    assert App.TGFrame_Cast(f) is f
    assert App.TGFrame_Cast(object()) is None


def test_sttiled_icon_surface():
    icon = App.STTiledIcon_Create("lcars", 4101, App.NiColorA_BLACK)
    icon.SetTiling(App.STTiledIcon.DIRECTION_X, 10)
    icon.SetTileSize(App.STTiledIcon.DIRECTION_X, 4.0)
    assert App.STTiledIcon_Cast(icon) is icon


def test_numeric_bar_and_fill_gauge():
    from engine.appc.tg_ui.eng_power import STNumericBar, STFillGauge
    bar = STNumericBar()
    bar.SetRange(0.0, 1.25)
    bar.SetValue(0.75)
    assert bar.GetValue() == 0.75
    g = STFillGauge()
    g.SetFillFraction(0.5)
    assert g.GetFillFraction() == 0.5


def test_app_globals_engineering_colors():
    assert App.globals.DEFAULT_ST_INDENT_HORIZ > 0.0
    c = App.globals.g_kEngineeringMainPowerColor
    assert hasattr(c, "r") and hasattr(c, "a")
    assert App.g_kEngineeringMainPowerColor is c
    for name in ("WarpCore", "MainPower", "BackupPower", "Engines", "Shields",
                 "Weapons", "Sensors", "Cloak", "Tractor", "CtrlBkgndLine"):
        assert getattr(App.globals, "g_kEngineering%sColor" % name) is not None
```

- [ ] **Step 2: Run tests** → FAIL (`TGFrame_Create` missing, etc.)

- [ ] **Step 3: Implement**

`widgets.py` (follow the file's conventions — stored-not-rendered geometry, lenient casts):

```python
class _TGRect:
    def GetLeft(self) -> float:  return 0.0
    def GetTop(self) -> float:   return 0.0
    def GetRight(self) -> float: return 0.0
    def GetBottom(self) -> float: return 0.0


class TGFrame(TGPane):
    """Bordered frame — records colour/stretch; geometry inert like TGPane."""
    NO_STRETCH_LR = 1

    def __init__(self, group_name: str = "", icon_id: int = 0):
        super().__init__()
        self._group_name = str(group_name)
        self._icon_id = int(icon_id)
        self._ni_color = None
        self._edge_stretch = 0

    def GetInnerRect(self) -> _TGRect:        return _TGRect()
    def SetNiColor(self, *rgba) -> None:      self._ni_color = rgba
    def SetEdgeStretch(self, mode) -> None:   self._edge_stretch = int(mode)


class STTiledIcon(TGIcon):
    DIRECTION_X = 0
    DIRECTION_Y = 1

    def __init__(self, group_name: str = "", icon_id: int = 0, color=None):
        super().__init__(group_name, icon_id, color)
        self._tiling = {}
        self._tile_size = {}

    def SetTiling(self, direction, n) -> None:
        self._tiling[int(direction)] = n

    def SetTileSize(self, direction, size) -> None:
        self._tile_size[int(direction)] = float(size)
```

plus `TGFrame_Create/TGFrame_Cast/STTiledIcon_Create/STTiledIcon_Cast` factories in the file's factory section.

`eng_power.py`:

```python
"""EngPowerCtrl/EngPowerDisplay support widgets — state-holding, render-free.
The CEF Engineering panel snapshots live subsystem state directly; these
exist so Bridge/PowerDisplay.py runs unmodified."""
from engine.appc.tg_ui.widgets import TGPane


class STNumericBar(TGPane):
    def __init__(self):
        super().__init__()
        self._value = 0.0
        self._lo, self._hi = 0.0, 1.0
        self._color = None

    def SetValue(self, v) -> None:     self._value = float(v)
    def GetValue(self) -> float:       return self._value
    def SetRange(self, lo, hi) -> None: self._lo, self._hi = float(lo), float(hi)
    def SetColor(self, c) -> None:     self._color = c


class STFillGauge(TGPane):
    def __init__(self, kind: int = 0):
        super().__init__()
        self._kind = int(kind)
        self._fill = 0.0
        self._empty_color = None
        self._fill_color = None

    def SetFillFraction(self, f) -> None:  self._fill = float(f)
    def GetFillFraction(self) -> float:    return self._fill
    def SetEmptyColor(self, c) -> None:    self._empty_color = c
    def SetFillColor(self, c) -> None:     self._fill_color = c
```

`App.py` — after the NiColorA block (~line 1190):

```python
# ── App.globals — Appc.globals namespace (SDK App.py:13178). PowerDisplay and
# the engineering UI read indents + colours through it; colour values are
# LCARS approximations from the original UI (cosmetic — CEF restyles).
class _AppcGlobals:
    DEFAULT_ST_INDENT_HORIZ = 5.0
    DEFAULT_ST_INDENT_VERT = 5.0
    g_kEngineeringWarpCoreColor    = NiColorA(0.25, 0.47, 1.00, 1.0)  # blue
    g_kEngineeringMainPowerColor   = NiColorA(1.00, 0.80, 0.20, 1.0)  # yellow
    g_kEngineeringBackupPowerColor = NiColorA(1.00, 0.30, 0.15, 1.0)  # red
    g_kEngineeringEnginesColor     = NiColorA(0.85, 0.45, 0.95, 1.0)
    g_kEngineeringShieldsColor     = NiColorA(0.65, 0.55, 0.95, 1.0)
    g_kEngineeringWeaponsColor     = NiColorA(0.95, 0.60, 0.25, 1.0)
    g_kEngineeringSensorsColor     = NiColorA(0.95, 0.90, 0.30, 1.0)
    g_kEngineeringCloakColor       = NiColorA(0.95, 0.55, 0.20, 1.0)
    g_kEngineeringTractorColor     = NiColorA(0.95, 0.40, 0.55, 1.0)
    g_kEngineeringCtrlBkgndLineColor = NiColorA(0.30, 0.30, 0.30, 1.0)

globals = _AppcGlobals()
# SDK App.py re-exports the colours at module level (lines 13994-14003).
g_kEngineeringWarpCoreColor    = globals.g_kEngineeringWarpCoreColor
g_kEngineeringMainPowerColor   = globals.g_kEngineeringMainPowerColor
g_kEngineeringBackupPowerColor = globals.g_kEngineeringBackupPowerColor
g_kEngineeringEnginesColor     = globals.g_kEngineeringEnginesColor
g_kEngineeringShieldsColor     = globals.g_kEngineeringShieldsColor
g_kEngineeringWeaponsColor     = globals.g_kEngineeringWeaponsColor
g_kEngineeringSensorsColor     = globals.g_kEngineeringSensorsColor
g_kEngineeringCloakColor       = globals.g_kEngineeringCloakColor
g_kEngineeringTractorColor     = globals.g_kEngineeringTractorColor
```

**Caution:** `globals` shadows the builtin inside `App.py`'s module namespace — audit `App.py` for any internal use of the `globals()` builtin first (`grep -n "globals()" App.py`); if found, capture `_py_globals = globals` before the assignment and use that internally.

- [ ] **Step 4: Run tests** — targeted + full unit suite → PASS

- [ ] **Step 5: Commit**

```bash
git add -A engine/appc/tg_ui App.py tests/
git commit -m "feat(ui): TGFrame/STTiledIcon/STNumericBar/STFillGauge shims + App.globals colours"
```

---

### Task 11: EngPowerCtrl + EngPowerDisplay shims, singletons, Init hookup

**Files:**
- Modify: `engine/appc/tg_ui/eng_power.py`
- Modify: `App.py` (replace `_DisplayWidget` stubs at ~lines 1594–1599 with real exports)
- Test: `tests/unit/test_eng_power_ctrl.py` (new)

**Interfaces:**
- Consumes: Task 10 widgets; `PoweredSubsystem.GetPowerPercentageWanted`.
- Produces (exact SDK names):
  - `EngPowerCtrl(TGPane)`: `GetBarForSubsystem(subsystem) -> STNumericBar|None`, `Refresh()`
  - `EngPowerDisplay(TGPane)`: constants `MAIN=0, BACKUP=1, WARP_CORE=2`; `CreateBatteryGauge(which) -> STFillGauge`; `GetConceptualParent() -> None`
  - `App.EngPowerCtrl_Create(width)`, `App.EngPowerCtrl_GetPowerCtrl()`, `App.EngPowerCtrl_Cast`
  - `App.EngPowerDisplay_Create(w, h)` — creates the display, **stores the singleton, then calls `Bridge.PowerDisplay.Init(display)`** (BC's C++ ctor triggers Init; `Init` self-registers `ET_SET_PLAYER` for re-init and early-outs safely when no player exists yet)
  - `App.EngPowerDisplay_GetPowerDisplay()`, `App.EngPowerDisplay_Cast`
  - module-level reset hook for `tests/conftest.py` `_reset_leakable_engine_globals` (both singletons are leakable globals — register them there)

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_eng_power_ctrl.py
import App
from engine.appc.subsystems import PoweredSubsystem


def test_bar_per_subsystem_and_refresh():
    ctrl = App.EngPowerCtrl_Create(200.0)
    assert App.EngPowerCtrl_GetPowerCtrl() is ctrl
    sensors = PoweredSubsystem("Sensor Array")
    sensors.SetNormalPowerPerSecond(100.0)
    bar = ctrl.GetBarForSubsystem(sensors)
    assert bar is not None
    assert ctrl.GetBarForSubsystem(sensors) is bar      # stable per subsystem
    assert ctrl.GetBarForSubsystem(None) is None
    sensors.SetPowerPercentageWanted(0.75)
    ctrl.Refresh()
    assert abs(bar.GetValue() - 0.75) < 1e-9


def test_display_create_calls_powerdisplay_init_safely():
    # No player exists in this test: Init must early-out without raising and
    # still register its ET_SET_PLAYER re-init handler.
    disp = App.EngPowerDisplay_Create(100.0, 200.0)
    assert App.EngPowerDisplay_GetPowerDisplay() is disp
    assert App.EngPowerDisplay_Cast(disp) is disp
    gauge = disp.CreateBatteryGauge(App.EngPowerDisplay.MAIN)
    assert gauge is not None
```

- [ ] **Step 2: Run tests** → FAIL (stub `_DisplayWidget` returned)

- [ ] **Step 3: Implement**

`eng_power.py`:

```python
_power_ctrl_singleton = None
_power_display_singleton = None


def _reset_eng_power_singletons() -> None:
    global _power_ctrl_singleton, _power_display_singleton
    _power_ctrl_singleton = None
    _power_display_singleton = None


class EngPowerCtrl(TGPane):
    def __init__(self, width: float = 0.0):
        super().__init__(width, 0.0)
        self._bars: dict = {}      # id(subsystem) -> (subsystem, STNumericBar)

    def GetBarForSubsystem(self, subsystem):
        if subsystem is None:
            return None
        key = id(subsystem)
        entry = self._bars.get(key)
        if entry is None:
            bar = STNumericBar()
            bar.SetRange(0.0, 1.25)
            self._bars[key] = (subsystem, bar)
            return bar
        return entry[1]

    def Refresh(self) -> None:
        for subsystem, bar in self._bars.values():
            bar.SetValue(subsystem.GetPowerPercentageWanted())


class EngPowerDisplay(TGPane):
    MAIN = 0
    BACKUP = 1
    WARP_CORE = 2

    def CreateBatteryGauge(self, which):
        return STFillGauge(which)

    def GetConceptualParent(self):
        return None


def EngPowerCtrl_Create(width=0.0):
    global _power_ctrl_singleton
    _power_ctrl_singleton = EngPowerCtrl(width)
    return _power_ctrl_singleton


def EngPowerCtrl_GetPowerCtrl():
    return _power_ctrl_singleton


def EngPowerCtrl_Cast(obj):
    return obj if isinstance(obj, EngPowerCtrl) else None


def EngPowerDisplay_Create(width=0.0, height=0.0):
    global _power_display_singleton
    _power_display_singleton = EngPowerDisplay(width, height)
    try:
        import Bridge.PowerDisplay
        Bridge.PowerDisplay.Init(_power_display_singleton)
    except Exception:
        # SDK not importable in bare-unit contexts; the ET_SET_PLAYER re-init
        # path covers the live game. Never let UI construction kill a boot.
        pass
    return _power_display_singleton


def EngPowerDisplay_GetPowerDisplay():
    return _power_display_singleton


def EngPowerDisplay_Cast(obj):
    return obj if isinstance(obj, EngPowerDisplay) else None
```

Wire the names into `App.py` (delete the `_DisplayWidget` stub lines ~1594–1599), and add `_reset_eng_power_singletons` to `tests/conftest.py`'s `_reset_leakable_engine_globals`.

**Check the swallow:** the bare `except Exception` above hides real Init bugs. Emit a log line (`print` guarded by the module's existing debug convention or the engine logger) with the exception before continuing.

- [ ] **Step 4: Run tests** — targeted + full unit suite → PASS

- [ ] **Step 5: Commit**

```bash
git add -A engine/appc/tg_ui App.py tests/
git commit -m "feat(ui): EngPowerCtrl/EngPowerDisplay shims with PowerDisplay.Init hookup"
```

---

### Task 12: SDK integration — PowerDisplay.py + ManagePower run headless

**Files:**
- Test: `tests/host/test_power_display_sdk.py` (new)
- Modify: whatever the test flushes out (missing widget methods land in `engine/appc/tg_ui/`; missing App names in `App.py`; **never** edit the SDK file)

**Interfaces:**
- Consumes: everything above; the mission-harness conventions used by existing `tests/host/` SDK-boot tests (see how the QuickBattle click test boots the SDK — copy its bootstrap).
- Produces: `Bridge.PowerDisplay` imports, `Init` + `Update` + `AdjustPower` run to completion against a real player ship; `EngineerMenuHandlers.ManagePower` adjusts sliders end-to-end.

- [ ] **Step 1: Write the failing tests**

```python
# tests/host/test_power_display_sdk.py
"""Bridge/PowerDisplay.py must run UNMODIFIED against the widget shims.
Bootstrap: copy the SDK-boot fixture from the existing host-level QB test
(the one guarding the bridge-officer-speech path) — same conftest AST
transforms, same stub-list caveats (runtime stub list ≠ test stub list)."""
import App


def test_power_display_init_and_update_run(qb_booted_player):   # reuse/adapt fixture
    import Bridge.PowerDisplay as PD
    disp = App.EngPowerDisplay_Create(100.0, 200.0)   # triggers PD.Init
    PD.Update()                                        # the 0.5s refresh body
    # Bars exist and reflect the player's sliders after a Refresh:
    ctrl = App.EngPowerCtrl_GetPowerCtrl()
    player = App.Game_GetCurrentPlayer()
    sensors = player.GetSensorSubsystem()
    sensors.SetPowerPercentageWanted(0.5)
    ctrl.Refresh()
    assert abs(ctrl.GetBarForSubsystem(sensors).GetValue() - 0.5) < 1e-9


def test_adjust_power_throttles_proportionally_with_floor(qb_booted_player):
    import Bridge.PowerDisplay as PD
    player = App.Game_GetCurrentPlayer()
    systems = [player.GetImpulseEngineSubsystem(), player.GetWarpEngineSubsystem(),
               player.GetShields(), player.GetPhaserSystem(),
               player.GetTorpedoSystem(), player.GetPulseWeaponSystem(),
               player.GetSensorSubsystem()]
    for s in systems:
        if s:
            s.SetPowerPercentageWanted(1.25)
    # Shrink the conduits so demand > supply, then run the SDK auto-balance.
    App.EngPowerCtrl_Create(200.0)
    for s in systems:                       # bars must exist for AdjustPower
        if s:
            App.EngPowerCtrl_GetPowerCtrl().GetBarForSubsystem(s)
    PD.AdjustPower(systems)
    for s in systems:
        if s and s.GetNormalPowerWanted() > 0.0:
            assert s.GetPowerPercentageWanted() >= 0.2 - 1e-9   # 20% floor
    # weapons locked together, engines locked together:
    if player.GetPhaserSystem() and player.GetTorpedoSystem():
        assert (player.GetTorpedoSystem().GetPowerPercentageWanted()
                == player.GetPhaserSystem().GetPowerPercentageWanted())


def test_manage_power_event_flow(qb_booted_player):
    import Bridge.EngineerMenuHandlers as EMH
    player = App.Game_GetCurrentPlayer()
    before = player.GetSensorSubsystem().GetPowerPercentageWanted()
    ev = _manage_power_event(5)   # int 5 => group 2 (sensors), odd => +0.25
    EMH.ManagePower(_top_window_or_menu_object(), ev)
    after = player.GetSensorSubsystem().GetPowerPercentageWanted()
    assert abs(after - min(before + 0.25, 1.25)) < 1e-9
```

Build `_manage_power_event` with the project's event construction convention (`App.TGIntEvent` or equivalent — copy from the alert-keys test, which posts `ET_SET_ALERT_LEVEL` through the same chain).

- [ ] **Step 2: Run tests, iterate**

Run: `uv run pytest tests/host/test_power_display_sdk.py -v`
Expected first run: FAIL with a missing attribute somewhere inside `PowerDisplay.Init` (e.g. `UIHelpers.CreateCurve` internals, `GetLcarsModule`, `TGProfilingInfo`). **Fix each in the shim layer** (tg_ui widgets / App.py exports), never in the SDK file, re-running until green. Known likely gaps from the call inventory: `TGPane.GetConceptualParent` (add to `TGPane`, returns None), `STStylizedWindow` methods (`GetMaximumWidth`, `SetMaximumSize`, `GetBorderWidth`, `InteriorChangedSize` — extend `engine/appc/windows.py` shim), `g_kIconManager.GetIconGroup(...).GetIconScreenHeight` (exists, returns 0.0), `GraphicsModeInfo.GetPixelWidth/GetPixelHeight`.

- [ ] **Step 3: Verify no stub leakage on the critical path**

Add one more assertion: after `Init`, `disp.GetNthChild(PD.TRACTOR_TEXT)` returns a real `TGParagraph` (not `_Stub`) and `PD.HandleTractor`/`PD.HandleCloak` run against a synthetic event without raising — this is the siphon-line seam the CEF panel reads.

- [ ] **Step 4: Run** — file + `uv run pytest tests/host -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add -A engine App.py tests/
git commit -m "feat(power): Bridge/PowerDisplay.py + ManagePower run unmodified headless"
```

---

### Task 13: CEF Engineering power-grid panel

**Files:**
- Create: `engine/ui/engineering_power_panel.py`
- Create: `native/assets/ui-cef/js/engineering_power.js`
- Modify: `native/assets/ui-cef/hello.html` (script include), `native/assets/ui-cef/css/hello.css` (or a new `engineering_power.css` if other panels have their own — match the crew-menu precedent)
- Modify: `engine/host_loop.py` (construct + register the panel next to the other `registry.register(...)` calls, ~line 5090)
- Test: `tests/unit/test_engineering_power_panel.py` (new)

**Interfaces:**
- Consumes: player ship power state (`GetPowerSubsystem` + the seven slider systems), `App.EngPowerCtrl_GetPowerCtrl().Refresh()`, `Panel` base (`engine/ui/panel.py`), `PanelRegistry`.
- Produces: `EngineeringPowerPanel(Panel)` with `name = "engpower"`, JS entry `setEngineeringPower(payload)`, inbound actions `"engpower:set:<group>:<pct>"` for groups `weapons|engines|sensors|shields`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_engineering_power_panel.py
import json
from engine.ui.engineering_power_panel import EngineeringPowerPanel


def test_payload_shape_and_diffing(monkeypatch):
    panel = EngineeringPowerPanel(get_player=lambda: _fake_player())
    js = panel.render_payload()
    assert js.startswith("setEngineeringPower(")
    payload = json.loads(js[len("setEngineeringPower("):-2])
    assert set(payload["columns"]) == {"warp_core", "main", "backup"}
    assert [s["key"] for s in payload["sliders"]] == [
        "weapons", "engines", "sensors", "shields"]
    assert 0.0 <= payload["power_used"]["fraction"] <= 1.0
    assert set(payload["power_used"]["bands"]) == {"blue", "yellow", "red"}
    assert payload["tractor"]["active"] in (True, False)
    # unchanged state => no re-send
    assert panel.render_payload() is None


def test_slider_event_sets_group_and_refreshes():
    player = _fake_player()
    panel = EngineeringPowerPanel(get_player=lambda: player)
    assert panel.dispatch_event("engpower:set:weapons:0.75")
    for sys in (player.GetPhaserSystem(), player.GetTorpedoSystem(),
                player.GetPulseWeaponSystem()):
        if sys:
            assert abs(sys.GetPowerPercentageWanted() - 0.75) < 1e-9
    assert panel.dispatch_event("engpower:set:engines:1.25")
    assert abs(player.GetWarpEngineSubsystem().GetPowerPercentageWanted() - 1.25) < 1e-9
    assert not panel.dispatch_event("other:noise")
```

`_fake_player()`: build from the Task 4 `_powered_ship` helper extended with the seven systems (reuse `tests/unit/power_helpers.py`).

- [ ] **Step 2: Run tests** → FAIL (module missing)

- [ ] **Step 3: Implement the panel**

```python
# engine/ui/engineering_power_panel.py
"""Engineering power-transmission-grid panel (BC F5 top-right grid).

Renders LIVE engine state (not the PowerDisplay widget tree): sliders per
group, the banded Power Used bar, Warp Core / Main / Reserve columns, and
the tractor/cloak siphon lines. SDK PowerDisplay.py keeps owning the logic
(AdjustPower, refresh events); this panel is the display surface.
Payload semantics follow power-system.md §"The Power Used Bar":
  blue  = warp-core output / max bandwidth   (inside => batteries charging)
  yellow= main-conduit share                 (drawing Main)
  red   = backup-conduit share               (drawing Reserve)
"""
import json

from engine.ui.panel import Panel

_GROUPS = (
    ("weapons", "Weapons", ("GetPhaserSystem", "GetTorpedoSystem", "GetPulseWeaponSystem")),
    ("engines", "Engines", ("GetImpulseEngineSubsystem", "GetWarpEngineSubsystem")),
    ("sensors", "Sensor Array", ("GetSensorSubsystem",)),
    ("shields", "Shield Generator", ("GetShields",)),
)


class EngineeringPowerPanel(Panel):
    def __init__(self, get_player):
        super().__init__()
        self._get_player = get_player
        self._last_pushed = None

    @property
    def name(self) -> str:
        return "engpower"

    def _systems(self, player, getters):
        out = []
        for g in getters:
            getter = getattr(player, g, None)
            sys = getter() if getter else None
            if sys is not None:
                out.append(sys)
        return out

    def _snapshot(self):
        player = self._get_player()
        if player is None:
            return {"visible": False}
        power = player.GetPowerSubsystem()
        if power is None:
            return {"visible": False}
        sliders = []
        total_draw = 0.0
        for key, label, getters in _GROUPS:
            systems = self._systems(player, getters)
            pct = systems[0].GetPowerPercentageWanted() if systems else 0.0
            present = bool(systems)
            for s in systems:
                total_draw += s.GetNormalPowerWanted() * s.GetPowerPercentageWanted()
            sliders.append({"key": key, "label": label, "pct": round(pct, 4),
                            "present": present})
        bandwidth = power.GetMaxMainConduitCapacity() + power.GetBackupConduitCapacity()
        output = power.GetPowerOutput()
        main_cap = power.GetMainBatteryLimit()
        backup_cap = power.GetBackupBatteryLimit()
        tractor = player.GetTractorBeamSystem() if hasattr(player, "GetTractorBeamSystem") else None
        cloak = player.GetCloakingSubsystem() if hasattr(player, "GetCloakingSubsystem") else None
        tractor_active = bool(tractor is not None and tractor._wants_power())
        return {
            "visible": True,
            "power_used": {
                "fraction": round(min(total_draw / bandwidth, 1.0) if bandwidth > 0 else 0.0, 4),
                "bands": {
                    "blue": round(min(output / bandwidth, 1.0) if bandwidth > 0 else 0.0, 4),
                    "yellow": round(power.GetMainConduitCapacity() / bandwidth if bandwidth > 0 else 0.0, 4),
                    "red": round(power.GetBackupConduitCapacity() / bandwidth if bandwidth > 0 else 0.0, 4),
                },
            },
            "sliders": sliders,
            "columns": {
                "warp_core": round(power.GetConditionPercentage(), 4),
                "main": round(power.GetMainBatteryPower() / main_cap if main_cap > 0 else 0.0, 4),
                "backup": round(power.GetBackupBatteryPower() / backup_cap if backup_cap > 0 else 0.0, 4),
            },
            "tractor": {"present": tractor is not None, "active": tractor_active},
            "cloak": {"present": cloak is not None,
                      "active": bool(cloak is not None and cloak.IsTryingToCloak())},
        }

    def render_payload(self):
        snap = self._snapshot()
        if snap == self._last_pushed:
            return None
        self._last_pushed = snap
        return "setEngineeringPower(" + json.dumps(snap) + ");"

    def dispatch_event(self, action: str) -> bool:
        parts = action.split(":")
        if len(parts) != 4 or parts[0] != "engpower" or parts[1] != "set":
            return False
        group, raw = parts[2], parts[3]
        player = self._get_player()
        if player is None:
            return True
        try:
            pct = float(raw)
        except ValueError:
            return True
        for key, _label, getters in _GROUPS:
            if key == group:
                for sys in self._systems(player, getters):
                    sys.SetPowerPercentageWanted(pct)   # clamps internally
                break
        import App
        ctrl = App.EngPowerCtrl_GetPowerCtrl()
        if ctrl is not None:
            ctrl.Refresh()
        self._last_pushed = None
        return True
```

JS (`engineering_power.js`): render top-right fixed panel — title bar "Power Transmission Grid", horizontal Power Used bar with three background band segments sized by `bands` and a fill bar at `fraction`; four slider rows (label + range input `0..1.25` step `0.05` + % readout) firing `dauntlessEvent("engpower:set:<key>:<value>")` on input; three vertical columns (blue/yellow/red) with % labels `100% 97% 98%` style; "Tractor: Off/On" and "Cloak: Off/On" lines that light up (yellow to Main column for tractor, red to Reserve column for cloak) when active — greyed `#444` when idle. Follow `developer_options.js` for the payload-function + event-emit conventions; hide the whole root when `payload.visible === false`.

Register in `host_loop.py` beside the other panels; `get_player` uses the same accessor the target-list panel uses.

- [ ] **Step 4: Run tests** — targeted + full unit suite; then build + smoke: `cmake --build build -j && uv run pytest tests/host -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add -A engine/ui native/assets engine/host_loop.py tests/
git commit -m "feat(ui): CEF engineering power-grid panel with siphon lines"
```

---

### Task 14: Gate, live-verify checklist, memory

**Files:**
- Modify: `tests/known_failures.txt` only if the gate demands (expect: no changes)
- Modify: memory (`~/.claude` project memory) — update the power-system entry

- [ ] **Step 1: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exits 0; any non-ledger failure is a regression from this branch — fix it before proceeding (never eyeball "pre-existing").

- [ ] **Step 2: Reference-value sanity sweep**

Run: `uv run pytest tests/integration/test_power_reference_values.py -v`
Confirm Galaxy drain time within 5% of 384 s and print the Sovereign/Warbird numbers if those cases were added.

- [ ] **Step 3: Write the live-verify checklist into the plan/PR description**

```
LIVE VERIFY (needs Mark, in-game):
[ ] Power grid renders top-right in tactical + bridge views
[ ] Sliders drag 0-125%; impulse 0% = dead stop; 125% visibly faster turn
[ ] Red alert slowly drains Main battery %, green alert recharges
[ ] Tractor engage lights the siphon line + drains Main battery
[ ] Cloak (QB warbird) lights Reserve siphon; empty Reserve force-decloaks
[ ] Damage the warp core (dev Damage Preview): blue band shrinks,
    AdjustPower pulls sliders down, output column drops
[ ] Destroy warp core => ship destroyed (breach)
```

- [ ] **Step 4: Commit any final fixes and stop**

```bash
git add -A && git commit -m "chore(power): gate green + live-verify checklist"
```

Do NOT merge — finishing-a-development-branch skill decides integration with the user.

---

## Self-Review Notes (done at plan-writing time)

- **Spec coverage:** §1.1 properties → Tasks 2–4 (data-bag classes already exist; conduit/battery consumption is the real work); §1.2 sim → Tasks 2–5; §1.3 App surface → Tasks 1, 2, 11; §2 effects table → Tasks 6–9 (tractor row = Task 4's `_wants_power` + starvation stop); §3 UI → Tasks 10–13; §4 testing → per-task + Tasks 9, 12, 14. Out-of-scope items (MP, repair gameplay, power-scaled tractor strength) have no tasks — correct.
- **Known deviation:** consumer draw priority uses ship attach order (Task 4) ≈ BC's linked-list insertion order; both derive from hardpoint authoring order.
- **Deliberate simplification:** the CEF panel reads live engine state rather than the PowerDisplay widget tree (spec §3 "snapshots the shim tree" is satisfied for the *logic* path — AdjustPower/ManagePower/Refresh flow through the shims and are integration-tested in Task 12; the pixels come from the same underlying state).
