# Cloak Survival Resource (B + C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make cloak a managed survival resource — sustained cloak drains the reserve so a damaged ship gets flushed out (B), and a crippled cloak-capable NPC hides to repair then re-engages or is forced out (C).

**Architecture:** B changes `CloakingSubsystem._update_power` to draw a tunable rate straight from the backup battery via the existing `StealPowerFromReserve` (bypassing the conduit throttle), so reactor-condition scaling decides sustainability and Step 0's reserve guard flushes an empty ship. C adds an engine-side `defensive_cloak.py` controller (`tick_defensive_cloak`, layered like `tick_collision_avoidance`) that cloaks a hurt ship, suppresses its SDK AI while hiding, and exits on healed-or-forced.

**Tech Stack:** Python 3 (engine/appc, engine/core), pytest. Pure-Python — no C++ rebuild.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-07-cloak-survival-resource-design.md`.
- Builds on merged **Step 0** (`CloakingSubsystem._backup_reserve` snapshot + `MIN_RESERVE_TO_HOLD_CLOAK` guard) and **Part A** (focus-loss lifecycle). No C++ rebuild.
- All tunables are module-level constants — **no hardpoint edits**: `CLOAK_RESERVE_DRAIN_PER_SECOND` (default 1000.0), `CLOAK_HULL_THRESHOLD` (0.35), `FIT_TO_FIGHT_THRESHOLD` (0.70).
- Dev diagnostics use `print()` gated by `dev_mode.is_enabled()` — **never `logging`**; `[cloak]` prefix; off in production.
- C applies only to ships with `GetAI() is not None` (never the player) and a functional (`not IsDisabled()`/`not IsDestroyed()`) cloaking subsystem.
- No two mechanisms drive the cloak at once: while a ship is DEFENSIVE, `tick_all_ai` skips its SDK AI (so Part A's `CloakShip`/focus lifecycle does not run for it).
- Per-ship controller state must reset across missions/tests (mirror `collision_avoidance.reset_avoidance_state` + `tests/conftest.py:_reset_leakable_engine_globals`).
- Test gate: `scripts/check_tests.sh` (pytest + ctest); baseline failures only those in `tests/known_failures.txt`.

---

### Task 1: B — reserve drains at the cloak's full rate

**Files:**
- Modify: `engine/appc/subsystems.py` (`CloakingSubsystem`: add `CLOAK_RESERVE_DRAIN_PER_SECOND`; rewrite `_update_power` ~line 2119 to draw direct-from-reserve)
- Test: `tests/unit/test_cloak_reserve_depletion.py` (new)

**Interfaces:**
- Consumes: `PowerSubsystem.StealPowerFromReserve(amount)->float` (`subsystems.py:1639`, deducts from `_backup_battery_power`); Step 0's `_backup_reserve` snapshot + `MIN_RESERVE_TO_HOLD_CLOAK` guard; `CloakingSubsystem._wants_power()`.
- Produces: `CloakingSubsystem.CLOAK_RESERVE_DRAIN_PER_SECOND` (float class const); `_update_power` now drains the reserve at that rate while trying to cloak.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cloak_reserve_depletion.py`:

```python
"""B: a cloaked ship draws its full CLOAK_RESERVE_DRAIN_PER_SECOND straight from
the backup reserve (bypassing the conduit throttle), so sustained cloak depletes
the reserve unless the reactor keeps up. Healthy reactor sustains; damaged one is
flushed out by Step 0's reserve guard. See
docs/superpowers/specs/2026-07-07-cloak-survival-resource-design.md."""
import App
from engine.appc.subsystems import CloakingSubsystem, PowerSubsystem
from engine.appc.properties import PowerProperty


def _powered_ship(output=1500.0):
    ship = App.ShipClass_Create("TestShip")
    power = PowerSubsystem("Warp Core")
    prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(output)
    prop.SetMainBatteryLimit(100000.0)
    prop.SetBackupBatteryLimit(200000.0)
    prop.SetMainConduitCapacity(1700.0)
    prop.SetBackupConduitCapacity(300.0)
    power.SetProperty(prop)
    ship.SetPowerSubsystem(power)
    return ship, power


def _cloak_on(ship, drain=1000.0):
    cloak = CloakingSubsystem("Cloaking Device")
    cloak.CLOAK_RESERVE_DRAIN_PER_SECOND = drain
    ship.AddPoweredConsumer(cloak)
    return cloak


def test_cloak_drains_reserve_at_full_rate_not_conduit_throttled():
    # Backup conduit is 300/s; the direct-from-reserve draw must ignore it and
    # pull the full 1000/s. Reactor off so we measure pure draw.
    ship, power = _powered_ship(output=0.0)
    cloak = _cloak_on(ship, drain=1000.0)
    power.SetBackupBatteryPower(50000.0)
    cloak.InstantCloak()
    for _ in range(60):                       # 1 s at 60 Hz
        power.Update(1.0 / 60.0)
    drained = 50000.0 - power.GetBackupBatteryPower()
    assert 950.0 <= drained <= 1050.0         # ~1000/s, not ~300/s


def test_healthy_reactor_sustains_cloak():
    # Reactor 1500/s > drain 1000/s: reserve holds, ship stays cloaked.
    ship, power = _powered_ship(output=1500.0)
    cloak = _cloak_on(ship, drain=1000.0)
    power.SetBackupBatteryPower(200000.0)
    cloak.StartCloaking()
    for _ in range(600):                      # 10 s
        power.Update(1.0 / 60.0)
        cloak.Update(1.0 / 60.0)
    assert cloak.IsTryingToCloak() == 1


def test_damaged_reactor_depletes_reserve_and_forces_decloak():
    # Reactor 1500 * 30% condition = 450/s < drain 1000/s: reserve empties ->
    # Step 0 guard force-decloaks. Start with a small reserve so it empties fast.
    ship, power = _powered_ship(output=1500.0)
    power.SetCondition(power.GetMaxCondition() * 0.30)   # damaged reactor
    cloak = _cloak_on(ship, drain=1000.0)
    power.SetBackupBatteryPower(2000.0)                  # small reserve
    cloak.StartCloaking()
    for _ in range(600):                                # up to 10 s
        power.Update(1.0 / 60.0)
        cloak.Update(1.0 / 60.0)
    assert cloak.IsTryingToCloak() == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_cloak_reserve_depletion.py -v`
Expected: FAIL — `test_cloak_drains_reserve_at_full_rate...` drains ~300 (conduit-throttled) not ~1000; `AttributeError` is also acceptable if `CLOAK_RESERVE_DRAIN_PER_SECOND` isn't defined yet.

- [ ] **Step 3: Implement in `engine/appc/subsystems.py`**

Add the constant to `CloakingSubsystem` (next to `MIN_RESERVE_TO_HOLD_CLOAK`, ~line 2042):

```python
    # Reserve drain while cloaked (pw/s), drawn DIRECTLY from the backup battery
    # via StealPowerFromReserve — bypassing the backup-conduit throttle so a
    # sustained cloak genuinely depletes the reserve. Tunable here (no hardpoint
    # edit). Biased to the crossover: a healthy reactor out-refills this and
    # sustains cloak; a damaged one falls behind and the reserve empties, tripping
    # the MIN_RESERVE_TO_HOLD_CLOAK guard. Mark tunes by eye.
    CLOAK_RESERVE_DRAIN_PER_SECOND: float = 1000.0
```

Replace the existing `CloakingSubsystem._update_power` (~line 2119, the `super()._update_power(...)` + snapshot version) with the direct-from-reserve draw:

```python
    def _update_power(self, dt: float, power) -> None:
        """Direct-from-reserve draw. While trying to cloak, drain
        CLOAK_RESERVE_DRAIN_PER_SECOND straight from the backup battery
        (StealPowerFromReserve), bypassing the conduit throttle so the reserve
        genuinely depletes. Snapshots the post-draw reserve for the Step 0
        starvation guard in Update() (the loop ticks power before cloak, so the
        snapshot is fresh when Update reads it). Not trying to cloak -> no draw."""
        dt = float(dt)
        if dt <= 0.0:
            return
        if not self._wants_power():
            self._power_wanted = 0.0
            self._power_received = 0.0
            self._efficiency = 0.0
            self._power_factor = 0.0
            self._backup_reserve = power.GetBackupBatteryPower()
            return
        base = self.CLOAK_RESERVE_DRAIN_PER_SECOND * dt
        received = power.StealPowerFromReserve(base) if base > 0.0 else 0.0
        self._power_wanted = base
        self._power_received = received
        self._efficiency = received / base if base > 0.0 else 1.0
        self._power_factor = self._efficiency
        self._backup_reserve = power.GetBackupBatteryPower()
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_cloak_reserve_depletion.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run cloak regression (Step 0 starvation + consumers must still hold)**

Run: `uv run pytest tests/unit/test_cloak_power_starvation.py tests/unit/test_power_consumer_draws.py tests/unit/test_cloaking_subsystem.py -q`
Expected: PASS. (Step 0's `test_full_backup_battery_does_not_decloak` uses draw 100 and now drains reserve directly; the full 80000 reserve still never empties in 10 s, so it stays cloaked. If a starvation test now behaves differently, report it — do not weaken the test.)

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_cloak_reserve_depletion.py
git commit -m "feat(cloak): reserve drains at full rate (direct-from-reserve draw)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: C core — the defensive-cloak controller module

**Files:**
- Create: `engine/appc/defensive_cloak.py`
- Test: `tests/unit/test_defensive_cloak.py` (new)

**Interfaces:**
- Consumes: `iter_ships()` from `engine.appc.ship_iter`; `ship.GetAI()`, `ship.GetCloakingSubsystem()`, `ship.GetHull()`, `ship.GetTarget()`; `cloak.IsDisabled()`, `cloak.IsDestroyed()`, `cloak.IsTryingToCloak()`, `cloak.StartCloaking()`, `cloak.StopCloaking()`; `hull.GetConditionPercentage()`; `dev_mode.is_enabled()`.
- Produces: `tick_defensive_cloak(dt: float) -> None`; `is_defensive(ship) -> bool`; `reset_defensive_cloak_state() -> None`; constants `CLOAK_HULL_THRESHOLD`, `FIT_TO_FIGHT_THRESHOLD`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_defensive_cloak.py`:

```python
"""C: engine-side defensive-cloak controller. A crippled cloak-capable AI ship
hides (cloaks) to repair, and exits when healed (>= FIT_TO_FIGHT_THRESHOLD) or
forced out by reserve exhaustion (cloak no longer trying). Player/no-cloak ships
are never entered. See docs/superpowers/specs/2026-07-07-cloak-survival-resource-design.md."""
import App
from engine.appc.ships import ShipClass
from engine.appc.subsystems import CloakingSubsystem, HullSubsystem
from engine.appc import defensive_cloak
from engine.appc.defensive_cloak import (
    tick_defensive_cloak, is_defensive, reset_defensive_cloak_state,
    CLOAK_HULL_THRESHOLD, FIT_TO_FIGHT_THRESHOLD,
)


def _reset():
    reset_defensive_cloak_state()
    App.g_kSetManager._sets.clear()


def _combat_cloak_ship(hull_pct=1.0, with_target=True, with_cloak=True, with_ai=True):
    pSet = App.g_kSetManager._sets.get("S")
    if pSet is None:
        pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass()
    pSet.AddObjectToSet(ship, "Ship%d" % id(ship))
    hull = HullSubsystem("Hull"); hull.SetMaxCondition(1000.0)
    hull.SetCondition(1000.0 * hull_pct)
    ship.SetHull(hull)
    if with_cloak:
        ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    if with_ai:
        ship.SetAI(object())            # any non-None AI marker
    if with_target:
        tgt = ShipClass(); pSet.AddObjectToSet(tgt, "Tgt%d" % id(tgt))
        ship.SetTarget(tgt)
    return ship


def test_enters_defensive_when_crippled_in_combat():
    _reset()
    ship = _combat_cloak_ship(hull_pct=CLOAK_HULL_THRESHOLD - 0.05)
    tick_defensive_cloak(1.0 / 60.0)
    assert is_defensive(ship)
    assert ship.GetCloakingSubsystem().IsTryingToCloak() == 1
    _reset()


def test_does_not_enter_when_healthy():
    _reset()
    ship = _combat_cloak_ship(hull_pct=0.9)
    tick_defensive_cloak(1.0 / 60.0)
    assert not is_defensive(ship)
    _reset()


def test_does_not_enter_without_target():
    _reset()
    ship = _combat_cloak_ship(hull_pct=0.1, with_target=False)
    tick_defensive_cloak(1.0 / 60.0)
    assert not is_defensive(ship)
    _reset()


def test_player_and_no_cloak_ships_never_enter():
    _reset()
    player = _combat_cloak_ship(hull_pct=0.1, with_ai=False)   # no AI == player-like
    nocloak = _combat_cloak_ship(hull_pct=0.1, with_cloak=False)
    tick_defensive_cloak(1.0 / 60.0)
    assert not is_defensive(player)
    assert not is_defensive(nocloak)
    _reset()


def test_exits_when_healed_above_fit_threshold():
    _reset()
    ship = _combat_cloak_ship(hull_pct=CLOAK_HULL_THRESHOLD - 0.05)
    tick_defensive_cloak(1.0 / 60.0)
    assert is_defensive(ship)
    ship.GetHull().SetCondition(ship.GetHull().GetMaxCondition() * (FIT_TO_FIGHT_THRESHOLD + 0.05))
    tick_defensive_cloak(1.0 / 60.0)
    assert not is_defensive(ship)
    assert ship.GetCloakingSubsystem().IsDecloaking() or ship.GetCloakingSubsystem().IsTryingToCloak() == 0
    _reset()


def test_hysteresis_holds_between_thresholds():
    _reset()
    ship = _combat_cloak_ship(hull_pct=CLOAK_HULL_THRESHOLD - 0.05)
    tick_defensive_cloak(1.0 / 60.0)                     # enter
    ship.GetHull().SetCondition(ship.GetHull().GetMaxCondition() * 0.50)   # between 0.35 and 0.70
    tick_defensive_cloak(1.0 / 60.0)
    assert is_defensive(ship)                            # still hiding, not re-engaged
    _reset()


def test_exits_when_forced_out_by_exhaustion():
    _reset()
    ship = _combat_cloak_ship(hull_pct=CLOAK_HULL_THRESHOLD - 0.05)
    tick_defensive_cloak(1.0 / 60.0)                     # enter, cloaking
    # Simulate Step 0 forced decloak (reserve dry): cloak no longer trying.
    ship.GetCloakingSubsystem().InstantDecloak()
    tick_defensive_cloak(1.0 / 60.0)
    assert not is_defensive(ship)                        # controller released it
    _reset()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_defensive_cloak.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.defensive_cloak'`.

- [ ] **Step 3: Implement `engine/appc/defensive_cloak.py`**

```python
"""Engine-side defensive cloak-to-repair controller.

A crippled cloak-capable AI ship breaks off, cloaks, and repairs in hiding, then
re-engages once healed or is flushed out by reserve exhaustion (Part B). This is
an engine behavior overlaid on the SDK AI (same pattern as collision_avoidance):
while a ship is DEFENSIVE its SDK AI is suppressed (tick_all_ai skips it), so the
SDK CloakShip/focus lifecycle never fights this controller for the cloak.

Spec: docs/superpowers/specs/2026-07-07-cloak-survival-resource-design.md.
"""
from engine.appc.ship_iter import iter_ships
import engine.dev_mode as dev_mode

# Hull-condition thresholds (fraction 0..1). Hysteresis gap prevents thrash.
CLOAK_HULL_THRESHOLD: float = 0.35     # hide below this
FIT_TO_FIGHT_THRESHOLD: float = 0.70   # re-engage at/above this

# Per-ship mode: ships present in this set are DEFENSIVE (hiding). Absent == NORMAL.
_defensive: set = set()


def reset_defensive_cloak_state() -> None:
    """Clear all per-ship mode. Called on mission swap / test isolation (mirrors
    collision_avoidance.reset_avoidance_state)."""
    _defensive.clear()


def is_defensive(ship) -> bool:
    """True while this ship is hiding-to-repair. tick_all_ai skips the SDK AI of
    such ships so the two cloak drivers never conflict."""
    return id(ship) in _defensive


def _functional_cloak(ship):
    """The ship's cloaking subsystem if present and usable, else None."""
    get = getattr(ship, "GetCloakingSubsystem", None)
    cloak = get() if callable(get) else None
    if cloak is None:
        return None
    if cloak.IsDisabled() or cloak.IsDestroyed():
        return None
    return cloak


def _hull_pct(ship):
    hull = ship.GetHull() if hasattr(ship, "GetHull") else None
    if hull is None:
        return None
    return hull.GetConditionPercentage()


def _dev_log(ship, verb: str) -> None:
    if not dev_mode.is_enabled():
        return
    name = ship.GetName() if hasattr(ship, "GetName") else "<ship>"
    print("[cloak] %s -> %s" % (name, verb))


def tick_defensive_cloak(dt: float) -> None:
    """Per-frame controller. Runs BEFORE tick_all_ai each frame; ships it marks
    DEFENSIVE have their SDK AI suppressed by tick_all_ai this frame."""
    for ship in iter_ships():
        _update_ship(ship)


def _update_ship(ship) -> None:
    ai = ship.GetAI() if hasattr(ship, "GetAI") else None
    if ai is None:                       # never the player
        _defensive.discard(id(ship))
        return
    cloak = _functional_cloak(ship)
    if cloak is None:                    # cloak lost / no cloak -> leave DEFENSIVE
        if id(ship) in _defensive:
            _defensive.discard(id(ship))
        return
    hull_pct = _hull_pct(ship)
    if hull_pct is None:
        return

    if id(ship) in _defensive:
        # Exit conditions (healed-or-forced).
        if not cloak.IsTryingToCloak():             # forced out (reserve dry) or lost
            _defensive.discard(id(ship))
            _dev_log(ship, "re-engaging (forced out)")
            return
        if hull_pct >= FIT_TO_FIGHT_THRESHOLD:      # healed
            cloak.StopCloaking()
            _defensive.discard(id(ship))
            _dev_log(ship, "re-engaging (repaired %d%%)" % int(hull_pct * 100))
        return

    # Enter: crippled + in combat (has a target).
    target = ship.GetTarget() if hasattr(ship, "GetTarget") else None
    if hull_pct < CLOAK_HULL_THRESHOLD and target is not None:
        cloak.StartCloaking()
        _defensive.add(id(ship))
        _dev_log(ship, "defensive hide (hull %d%%)" % int(hull_pct * 100))
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_defensive_cloak.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/defensive_cloak.py tests/unit/test_defensive_cloak.py
git commit -m "feat(cloak): defensive cloak-to-repair controller (state machine)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: C integration — loop wiring + SDK-AI suppression + state reset

**Files:**
- Modify: `engine/core/loop.py` (call `tick_defensive_cloak(TICK_DELTA)` before `tick_all_ai`)
- Modify: `engine/appc/ai_driver.py` (`tick_all_ai`: skip a ship whose `defensive_cloak.is_defensive(ship)` is true)
- Modify: `tests/conftest.py` (`_reset_leakable_engine_globals`: call `reset_defensive_cloak_state()`)
- Test: `tests/unit/test_defensive_cloak_suppression.py` (new)

**Interfaces:**
- Consumes: `defensive_cloak.tick_defensive_cloak`, `defensive_cloak.is_defensive`, `defensive_cloak.reset_defensive_cloak_state` (Task 2).
- Produces: `tick_all_ai` no longer ticks the SDK AI of a DEFENSIVE ship; the controller runs each frame; state resets between tests.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_defensive_cloak_suppression.py`:

```python
"""tick_all_ai must skip the SDK AI of a ship the defensive-cloak controller has
marked DEFENSIVE (so the SDK CloakShip/focus lifecycle doesn't fight the engine
controller). Normal ships still tick."""
import App
from engine.appc.ships import ShipClass
from engine.appc.subsystems import CloakingSubsystem, HullSubsystem
from engine.appc import defensive_cloak
from engine.appc.ai_driver import tick_all_ai


class _CountingAI:
    """Minimal AI marker whose GetShip()/tick is observable."""
    def __init__(self, ship):
        self._ship = ship
        self.ticks = 0
    def GetShip(self):
        return self._ship


def _reset():
    defensive_cloak.reset_defensive_cloak_state()
    App.g_kSetManager._sets.clear()


def test_defensive_ship_sdk_ai_is_suppressed(monkeypatch):
    _reset()
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = ShipClass(); pSet.AddObjectToSet(ship, "S1")
    ai = _CountingAI(ship); ship.SetAI(ai)

    # Count tick_ai dispatches per ship via monkeypatch on the driver's tick_ai.
    import engine.appc.ai_driver as drv
    seen = []
    monkeypatch.setattr(drv, "tick_ai", lambda a, game_time: seen.append(a) or 0)

    # NORMAL: ship's AI is ticked.
    tick_all_ai(game_time=0.0)
    assert ai in seen

    # DEFENSIVE: ship's AI is skipped.
    defensive_cloak._defensive.add(id(ship))
    seen.clear()
    tick_all_ai(game_time=1.0)
    assert ai not in seen
    _reset()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_defensive_cloak_suppression.py -v`
Expected: FAIL — the DEFENSIVE ship's AI is still ticked (`ai in seen`), because `tick_all_ai` has no suppression check yet.

- [ ] **Step 3: Add the suppression check in `engine/appc/ai_driver.py`**

In `tick_all_ai`, skip DEFENSIVE ships. Replace the loop body so it reads:

```python
    from engine.appc.ship_iter import iter_ships
    from engine.appc import defensive_cloak
    for ship in iter_ships():
        # A ship hiding-to-repair is owned by the defensive-cloak controller;
        # suppress its SDK AI so the two cloak drivers never conflict.
        if defensive_cloak.is_defensive(ship):
            continue
        ai = ship.GetAI() if hasattr(ship, "GetAI") else None
        if ai is not None:
            status = tick_ai(ai, game_time)
            if status == US_DONE and not getattr(ai, "_done_event_fired", False):
                ai._done_event_fired = True
                fire_ai_done(ship, ai)
```

- [ ] **Step 4: Wire the controller into the game loop — `engine/core/loop.py`**

In `GameLoop.tick`, import and call the controller before `tick_all_ai` (so modes are set before the AI walk). Add to the imports block (alongside `tick_collision_avoidance`):

```python
        from engine.appc.defensive_cloak import tick_defensive_cloak
```

and call it immediately before the `tick_all_ai(game_time=game_time)` line:

```python
        tick_defensive_cloak(TICK_DELTA)
        tick_all_ai(game_time=game_time)
```

- [ ] **Step 5: Register the state reset in `tests/conftest.py`**

In `_reset_leakable_engine_globals`, add a defensive-cloak reset alongside the other module resets:

```python
    try:
        from engine.appc.defensive_cloak import reset_defensive_cloak_state
        reset_defensive_cloak_state()
    except Exception:
        pass
```

- [ ] **Step 6: Run to verify the suppression test passes + no regression**

Run: `uv run pytest tests/unit/test_defensive_cloak_suppression.py tests/unit/test_ai_driver.py tests/unit/test_loop.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add engine/core/loop.py engine/appc/ai_driver.py tests/conftest.py tests/unit/test_defensive_cloak_suppression.py
git commit -m "feat(cloak): wire defensive-cloak controller + suppress SDK AI while hiding

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Integration — hide, repair, re-engage (and flushed out)

**Files:**
- Test: `tests/integration/test_defensive_cloak_cadence.py` (new)

**Interfaces:**
- Consumes: `GameLoop` from `engine.core.loop` (its `tick()` runs `tick_defensive_cloak` then `tick_all_ai`, and ticks `PowerSubsystem`/`CloakingSubsystem`); `defensive_cloak` (Tasks 2-3); B's reserve depletion (Task 1).

**Note on repair:** this test does NOT wire a real `RepairSubsystem` (its `MaxRepairPoints` comes from a property and the enqueue/heal path is exercised by `test_gameloop_repair_tick.py`, not here). Healing is simulated by bumping the hull condition each tick — a faithful *repair proxy* that keeps this test focused on the controller + B-depletion + loop wiring end-to-end.

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_defensive_cloak_cadence.py`:

```python
"""End-to-end (headless GameLoop): a crippled cloak-capable AI ship enters
DEFENSIVE (cloaks); with a healthy reactor + repair progress it heals and
re-engages; with a weak reactor it is flushed out by reserve exhaustion before
healing. Repair is simulated by an external per-tick hull bump (repair proxy);
the real RepairSubsystem heal path is covered by test_gameloop_repair_tick.py."""
import App
import pytest
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.core.loop import GameLoop
from engine.appc import defensive_cloak
from engine.appc.ships import ShipClass
from engine.appc.ai import ArtificialIntelligence
from engine.appc.subsystems import CloakingSubsystem, HullSubsystem, PowerSubsystem
from engine.appc.properties import PowerProperty


class _InertAI:
    """Minimal AI whose SDK tick is a harmless no-op: tick_ai's type-dispatch
    matches none of the AI classes and falls through to `return ai._status`, so
    this must carry `_status` (and GetShip for the inert-coast gate). Used so a
    ship that EXITS defensive mode and resumes its SDK AI doesn't crash the loop."""
    def __init__(self, ship):
        self._ship = ship
        self._status = ArtificialIntelligence.US_ACTIVE
    def GetShip(self):
        return self._ship


@pytest.fixture(autouse=True)
def _iso():
    defensive_cloak.reset_defensive_cloak_state()
    App.g_kSetManager._sets.clear()
    App.g_kTimerManager._time = 0.0; App.g_kRealtimeTimerManager._time = 0.0
    yield
    defensive_cloak.reset_defensive_cloak_state()
    App.g_kSetManager._sets.clear()


def _game():
    m = Mission(); m.SetScript("tests.integration.test_defensive_cloak_cadence")
    e = Episode(); e.SetCurrentMission(m); g = Game(); g.SetCurrentEpisode(e)
    _set_current_game(g)


def _build(pSet, name, reactor_output, hull_pct):
    ship = ShipClass(); pSet.AddObjectToSet(ship, name)
    hull = HullSubsystem("Hull"); hull.SetMaxCondition(1000.0)
    hull.SetCondition(1000.0 * hull_pct); ship.SetHull(hull)
    power = PowerSubsystem("Warp Core"); prop = PowerProperty("Warp Core")
    prop.SetPowerOutput(reactor_output); prop.SetMainBatteryLimit(100000.0)
    prop.SetBackupBatteryLimit(8000.0)          # small reserve so exhaustion is reachable
    prop.SetMainConduitCapacity(1700.0); prop.SetBackupConduitCapacity(300.0)
    power.SetProperty(prop); ship.SetPowerSubsystem(power)
    power.SetMainBatteryPower(100000.0)         # main full -> reactor output spills to reserve
    power.SetBackupBatteryPower(8000.0)
    ship.SetCloakingSubsystem(CloakingSubsystem("Cloaking Device"))
    ship.SetAI(_InertAI(ship))
    tgt = ShipClass(); pSet.AddObjectToSet(tgt, name + "_tgt"); ship.SetTarget(tgt)
    return ship


def _bump_hull(ship, per_tick):
    hull = ship.GetHull()
    hull.SetCondition(min(hull.GetMaxCondition(), hull.GetCondition() + per_tick))


def test_healthy_ship_hides_repairs_and_re_engages():
    # Healthy reactor (1500 > 1000 drain) sustains cloak; repair proxy heals it
    # past the fit threshold -> re-engages.
    _game()
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = _build(pSet, "Fixer", reactor_output=1500.0, hull_pct=0.30)
    loop = GameLoop()
    entered = False
    for _ in range(60 * 30):                    # up to 30 s
        loop.advance(1)
        if defensive_cloak.is_defensive(ship):
            entered = True
            _bump_hull(ship, per_tick=1.0)       # ~60 hull/s repair proxy
        elif entered:
            break
    assert entered, "crippled ship should have hidden"
    assert not defensive_cloak.is_defensive(ship), "should re-engage once healed"
    assert ship.GetHull().GetConditionPercentage() >= defensive_cloak.FIT_TO_FIGHT_THRESHOLD


def test_weak_reactor_ship_is_flushed_out_before_healing():
    # Weak reactor (200 << 1000 drain): reserve empties -> Step 0 forces decloak
    # -> controller releases it, still hurt. No repair proxy (never heals).
    _game()
    pSet = App.SetClass_Create(); pSet.SetName("S"); App.g_kSetManager._sets["S"] = pSet
    ship = _build(pSet, "Doomed", reactor_output=200.0, hull_pct=0.30)
    loop = GameLoop()
    entered = False
    for _ in range(60 * 30):
        loop.advance(1)
        if defensive_cloak.is_defensive(ship):
            entered = True
        elif entered:
            break
    assert entered
    assert not defensive_cloak.is_defensive(ship)
    assert ship.GetHull().GetConditionPercentage() < defensive_cloak.FIT_TO_FIGHT_THRESHOLD
```

- [ ] **Step 2: Run to verify it passes**

Run: `uv run pytest tests/integration/test_defensive_cloak_cadence.py -v`
Expected: PASS (2 passed). If `test_weak_reactor...` stays DEFENSIVE forever, the reserve isn't depleting — verify Task 1's direct-from-reserve draw and that main battery is full so reactor output spills to the reserve. If `test_healthy...` never heals, raise the `_bump_hull` per-tick or the tick budget — do not weaken the threshold assertion. Report either as a finding.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_defensive_cloak_cadence.py
git commit -m "test(cloak): defensive hide->repair->re-engage + weak-reactor flush-out

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Full gate + live verification handoff

**Files:** none (verification only)

- [ ] **Step 1: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exits 0. B changed the cloak's power-draw path — confirm the Step 0 starvation tests and power-consumer tests are green. Any failure not in `tests/known_failures.txt` blocks completion.

- [ ] **Step 2: Present the in-game live-test checklist to the user**

Python-only — **no `cmake` rebuild**. Give the user these steps:

1. Launch **from a terminal** (stdout visible): `./build/dauntless --developer`
2. Fight a cloak-capable enemy (Warbird / Bird-of-Prey). Damage it below ~35% hull.
3. Watch stdout: `[cloak] <ship> -> defensive hide (hull NN%)`, then either
   `[cloak] <ship> -> re-engaging (repaired NN%)` after it heals, or
   `[cloak] <ship> -> forced decloak` / `-> re-engaging (forced out)` if its reactor
   can't sustain the cloak.
4. **Expected:** a lightly-damaged ship hides, heals, and comes back; a badly-damaged
   one gets flushed out still hurt. Watch for cloak/decloak **thrash** (rapid alternating
   lines) — if seen, tune `CLOAK_HULL_THRESHOLD`/`FIT_TO_FIGHT_THRESHOLD` (wider gap) or
   `CLOAK_RESERVE_DRAIN_PER_SECOND`.

- [ ] **Step 3: Update memory after live-verify**

Once confirmed in game, update `project_cloaking_system.md`: Parts B + C DONE + live-verified, note branch/commits and the tuned constant values.

---

## Self-Review

**Spec coverage:**
- B direct-from-reserve draw + `CLOAK_RESERVE_DRAIN_PER_SECOND` + condition-scaled crossover + Step 0 flush → Task 1. ✓
- C controller (enter/while/exit, healed-or-forced, hysteresis, guards, dev prints) → Task 2. ✓
- C SDK-AI suppression + loop wiring + state reset → Task 3. ✓
- Interaction (no two cloak drivers) → Task 3 suppression + Task 2 exit-on-not-trying. ✓
- Edge cases: player/no-AI, no-cloak, disabled cloak, no target, forced-out, hysteresis → Task 2 tests; ship death/mission-swap via `reset_defensive_cloak_state` (Task 3 conftest). ✓
- Observability `[cloak]` prints (print, not logging) → Task 2 `_dev_log`. ✓
- Integration hide→repair→re-engage + flush-out → Task 4. ✓
- Live verification → Task 5. ✓
- Out-of-scope (active flee, non-cloak retreat, warp/dock repair, player UI) → untouched. ✓

**Placeholder scan:** No TBD/TODO. Every code step shows complete code. Task 1 Step 3 and Task 3 Steps 3-5 describe exact edit sites with the full replacement text.

**Type consistency:** `tick_defensive_cloak(dt)`, `is_defensive(ship)->bool`, `reset_defensive_cloak_state()`, `_defensive` set, and constants `CLOAK_HULL_THRESHOLD`/`FIT_TO_FIGHT_THRESHOLD`/`CLOAK_RESERVE_DRAIN_PER_SECOND` are named identically across Tasks 1-4 and their tests. `StealPowerFromReserve` matches `subsystems.py:1639`. `is_defensive` is consumed in `tick_all_ai` (Task 3) exactly as produced in Task 2.
