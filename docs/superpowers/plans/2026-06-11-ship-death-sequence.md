# Ship Death Sequence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ships actually die — a critical subsystem reaching zero condition triggers a fixed-window death sequence (inert coast → explosion → `ET_OBJECT_DESTROYED` → removal from set).

**Architecture:** A dedicated `engine/appc/ship_death.py` module owns a throes registry with a three-function interface (`begin`/`advance`/`reset`), ticked once per frame from `_advance_combat`. Death triggers off the engine's existing-but-unused critical flag (`ShipSubsystem.IsCritical()`), folding in the warp-core breach. AI and weapons gate on an "out of action" predicate during the dying window; physics is untouched (the ship coasts). The explosion reuses the SDK's `Effects.CreateExplosionPuffHigh` with the real `ExplosionA/B.tga` sprites via the existing particle backend.

**Tech Stack:** Python 3, pytest. Engine shim modules under `engine/appc/`. SDK modules (`Effects`) resolved via `tests/conftest.py`'s `_SDKFinder`.

**Spec:** `docs/superpowers/specs/2026-06-11-ship-death-sequence-design.md`

> **IMPORTANT — test runs:** Never run the full pytest suite (`uv run pytest` with no path) — it consumes >100 GB RAM and freezes macOS. Always run focused targets, e.g. `uv run pytest tests/unit/test_ship_death.py -v`.

---

## File Structure

- **Create:** `engine/appc/ship_death.py` — throes registry + death-sequence state machine (`begin`/`advance`/`reset`/`_out_of_action`/`_spawn_explosion`).
- **Create:** `tests/unit/test_ship_death.py` — all death-sequence unit tests.
- **Modify:** `engine/appc/objects.py` — rewrite `DamageSystem` trigger to use the critical flag; add `DestroySystem`; add `_is_critical` helper.
- **Modify:** `engine/host_loop.py` — call `ship_death.advance(dt)` in `_advance_combat`; call `ship_death.reset()` in `swap_mission`.
- **Modify:** `engine/appc/ai_driver.py` — gate `tick_ai` on `_out_of_action`.
- **Modify:** `engine/appc/subsystems.py` — extend `_is_offline` to treat an out-of-action parent ship as offline.
- **Modify:** `App.py` — add the `ET_OBJECT_DESTROYED` event-type constant.

---

## Task 1: `ship_death` core state machine (logic only, no VFX, no event yet)

Build the registry and the dying→dead→removed transition. The explosion and the `ET_OBJECT_DESTROYED` broadcast are deliberately stubbed/deferred to later tasks so this task is pure logic.

**Files:**
- Create: `engine/appc/ship_death.py`
- Test: `tests/unit/test_ship_death.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_ship_death.py
"""Unit tests for the ship death sequence (engine/appc/ship_death.py)."""
import pytest

from engine.appc import ship_death


class FakeSet:
    """Minimal SetClass stand-in recording removals by name."""
    def __init__(self):
        self.removed = []
    def RemoveObjectFromSet(self, name):
        self.removed.append(name)


class FakeShip:
    """Minimal ship: lifecycle flags + name + containing set + radius."""
    def __init__(self, name="Enemy1", containing_set=None, radius=1.0):
        self._name = name
        self._set = containing_set if containing_set is not None else FakeSet()
        self._radius = radius
        self._dying = False
        self._dead = False
    def GetName(self):           return self._name
    def GetContainingSet(self):  return self._set
    def GetRadius(self):         return self._radius
    def IsDying(self):           return 1 if self._dying else 0
    def IsDead(self):            return 1 if self._dead else 0
    def SetDying(self, v):       self._dying = bool(v)
    def SetDead(self, v=True):   self._dead = bool(v) if v is not True else True


@pytest.fixture(autouse=True)
def _clean_registry():
    ship_death.reset()
    yield
    ship_death.reset()


def test_begin_marks_ship_dying():
    ship = FakeShip()
    ship_death.begin(ship)
    assert ship.IsDying() == 1
    assert ship.IsDead() == 0


def test_begin_is_idempotent():
    ship = FakeShip()
    ship_death.begin(ship)
    ship_death.begin(ship)  # second call must not double-register
    # Advance just short of the throes window: still exactly one entry, alive.
    ship_death.advance(ship_death.THROES_DURATION - 0.01)
    assert ship.IsDead() == 0


def test_advance_transitions_to_dead_and_removes_after_throes():
    s = FakeSet()
    ship = FakeShip(name="Doomed", containing_set=s)
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION)  # timer expires
    assert ship.IsDead() == 1
    assert s.removed == ["Doomed"]


def test_advance_does_not_kill_before_throes_elapse():
    ship = FakeShip()
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION / 2.0)
    assert ship.IsDead() == 0
    assert ship.IsDying() == 1


def test_entry_pruned_after_death():
    ship = FakeShip()
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION)
    # A second advance after death must be a no-op (entry pruned, no re-removal).
    ship._set.removed.clear()
    ship_death.advance(1.0)
    assert ship._set.removed == []


def test_reset_clears_registry():
    ship = FakeShip()
    ship_death.begin(ship)
    ship_death.reset()
    ship_death.advance(ship_death.THROES_DURATION)
    assert ship.IsDead() == 0  # nothing ticked


def test_out_of_action_predicate():
    ship = FakeShip()
    assert ship_death._out_of_action(ship) is False
    ship.SetDying(True)
    assert ship_death._out_of_action(ship) is True
    ship.SetDying(False)
    ship.SetDead(True)
    assert ship_death._out_of_action(ship) is True


def test_advance_prunes_ship_with_no_set():
    ship = FakeShip()
    ship._set = None  # GetContainingSet() -> None
    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION)  # must not raise
    assert ship.IsDead() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_death.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.appc.ship_death'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# engine/appc/ship_death.py
"""Ship death sequence — fixed-window throes, then removal.

Single owner of the dying -> dead transition. `begin(ship)` starts the
throes timer (and spawns the death explosion); `advance(dt)` ticks every
dying ship and, when its timer expires, marks it dead (which fires
ship_lifecycle.publish_destroyed), broadcasts ET_OBJECT_DESTROYED, and
removes it from its set. Plugs into the per-frame _advance_combat hub the
same way hit_vfx / particles do.

See docs/superpowers/specs/2026-06-11-ship-death-sequence-design.md.
"""

THROES_DURATION       = 2.5   # seconds the ship coasts, dying, before removal
EXPLOSION_SIZE_FACTOR = 1.0   # ship-radius multiplier (starting value, tune by feel)
MIN_EXPLOSION_SIZE    = 2.0   # GU floor for tiny craft (starting value, tune by feel)

# Registry of in-progress death sequences: list of {"ship", "time_left"}.
_active: list[dict] = []


def _out_of_action(ship) -> bool:
    """True when `ship` is dying or dead. Single definition of 'inert',
    imported by the AI and weapon gate sites. hasattr-guarded so non-ship
    objects never read as out of action."""
    if ship is None:
        return False
    dying = bool(ship.IsDying()) if hasattr(ship, "IsDying") else False
    dead = bool(ship.IsDead()) if hasattr(ship, "IsDead") else False
    return dying or dead


def begin(ship) -> None:
    """Start the death sequence for `ship`. Idempotent: a ship already
    dying or dead is ignored (covers a second critical subsystem dropping
    mid-throes)."""
    if ship is None or _out_of_action(ship):
        return
    if hasattr(ship, "SetDying"):
        ship.SetDying(True)
    _active.append({"ship": ship, "time_left": THROES_DURATION})
    _spawn_explosion(ship)


def advance(dt: float) -> None:
    """Tick every in-progress death sequence. When a timer expires, mark
    the ship dead and remove it from its set. Prunes completed entries."""
    if not _active:
        return
    survivors = []
    for entry in _active:
        entry["time_left"] -= dt
        if entry["time_left"] > 0.0:
            survivors.append(entry)
            continue
        _finish(entry["ship"])
    _active[:] = survivors


def _finish(ship) -> None:
    """Death instant: mark dead, then remove from set. Order matters —
    SetDead fires publish_destroyed while the handle is still valid."""
    if hasattr(ship, "SetDead"):
        ship.SetDead()
    try:
        pSet = ship.GetContainingSet() if hasattr(ship, "GetContainingSet") else None
        if pSet is not None and hasattr(ship, "GetName"):
            pSet.RemoveObjectFromSet(ship.GetName())
    except Exception:
        pass


def _spawn_explosion(ship) -> None:
    """Death explosion VFX. Filled in a later task; no-op for now."""
    pass


def reset() -> None:
    """Clear the registry (mission swap / test teardown)."""
    _active.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_death.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ship_death.py tests/unit/test_ship_death.py
git commit -m "feat(death): ship_death throes state machine (begin/advance/reset)"
```

---

## Task 2: Critical-flag trigger in `DamageSystem`

Replace the hull-identity check with a critical-flag check so the warp core (and any `SetCritical(1)` subsystem) triggers death.

**Files:**
- Modify: `engine/appc/objects.py` (`DamageableObject.DamageSystem`, new `_is_critical` helper)
- Test: `tests/unit/test_ship_death.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_ship_death.py`:

```python
# --- Task 2: critical-flag trigger via DamageSystem -------------------------
from engine.appc.objects import DamageableObject


class FakeSub:
    """Subsystem with condition + critical flag (mirrors ShipSubsystem)."""
    def __init__(self, max_condition=100.0, critical=0):
        self._cond = float(max_condition)
        self._max = float(max_condition)
        self._critical = int(critical)
        self._destroyed = False
    def GetCondition(self):      return self._cond
    def SetCondition(self, v):   self._cond = max(0.0, float(v))
    def GetMaxCondition(self):   return self._max
    def IsCritical(self):        return self._critical
    def SetDestroyed(self, v):   self._destroyed = bool(v)
    def IsDestroyed(self):       return 1 if self._destroyed else 0


class FakeDamageable(DamageableObject):
    """DamageableObject with a hull + lifecycle flags, for trigger tests."""
    def __init__(self):
        super().__init__()
        self._hull = FakeSub(critical=1)
        self._dying = False
        self._dead = False
        self._name = "Subject"
        self._set = FakeSet()
    def GetHull(self):           return self._hull
    def GetName(self):           return self._name
    def GetContainingSet(self):  return self._set
    def GetRadius(self):         return 1.0
    def IsDying(self):           return 1 if self._dying else 0
    def IsDead(self):            return 1 if self._dead else 0
    def SetDying(self, v):       self._dying = bool(v)
    def SetDead(self, v=True):   self._dead = bool(v) if v is not True else True


def test_damaging_critical_subsystem_to_zero_triggers_death():
    obj = FakeDamageable()
    obj.DamageSystem(obj.GetHull(), 100.0)  # hull is critical
    assert obj.IsDying() == 1


def test_damaging_noncritical_subsystem_to_zero_does_not_trigger_death():
    obj = FakeDamageable()
    sensors = FakeSub(critical=0)
    obj.DamageSystem(sensors, 100.0)
    assert sensors.GetCondition() == 0.0
    assert obj.IsDying() == 0


def test_warp_core_critical_triggers_death():
    obj = FakeDamageable()
    warp_core = FakeSub(critical=1)
    obj.DamageSystem(warp_core, 100.0)
    assert obj.IsDying() == 1


def test_partial_damage_does_not_trigger_death():
    obj = FakeDamageable()
    obj.DamageSystem(obj.GetHull(), 40.0)  # hull still at 60
    assert obj.IsDying() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_death.py -k "critical or warp_core or partial_damage" -v`
Expected: FAIL — `test_damaging_noncritical_subsystem...` fails because today's code triggers on hull identity, not critical flag (and `test_warp_core...` fails because a non-hull critical sub doesn't trigger).

- [ ] **Step 3: Rewrite `DamageSystem` and add `_is_critical`**

In `engine/appc/objects.py`, replace the existing `DamageSystem` method body (currently at `objects.py:357`) and add the helper just above the `DamageableObject` class:

```python
def _is_critical(subsystem) -> bool:
    """True when a subsystem carries the engine's critical flag. Guarded so
    objects/subsystems without IsCritical (Phase 1 stubs) read as False."""
    if subsystem is None or not hasattr(subsystem, "IsCritical"):
        return False
    return bool(subsystem.IsCritical())
```

```python
    def DamageSystem(self, subsystem, amount: float) -> None:
        """Apply damage to a subsystem, flooring condition at zero. If the
        subsystem is critical and reaches zero, start the ship death
        sequence (covers hull AND warp core via SetCritical(1))."""
        if subsystem is None:
            return
        amt = float(amount)
        if amt <= 0.0:
            return
        cur = subsystem.GetCondition()
        new_cond = max(0.0, cur - amt)
        subsystem.SetCondition(new_cond)
        if new_cond <= 0.0 and _is_critical(subsystem) \
                and hasattr(self, "IsDying") and not self.IsDying() \
                and not self.IsDead():
            from engine.appc import ship_death
            ship_death.begin(self)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_death.py -v`
Expected: PASS (all, including Task 1 tests).

- [ ] **Step 5: Guard against regressions in existing combat/subsystem tests**

Run: `uv run pytest tests/unit/test_subsystems.py tests/unit/test_player.py -v`
Expected: PASS (no regressions from the trigger change).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/objects.py tests/unit/test_ship_death.py
git commit -m "feat(death): trigger death off critical flag in DamageSystem"
```

---

## Task 3: Implement `DestroySystem`

The SDK calls `pShip.DestroySystem(sub)` for scripted instant-kills; today it hits the `_Stub` no-op. Implement it: zero the subsystem, then apply the same critical-flag death rule.

**Files:**
- Modify: `engine/appc/objects.py` (`DamageableObject`)
- Test: `tests/unit/test_ship_death.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_ship_death.py`:

```python
# --- Task 3: DestroySystem --------------------------------------------------
def test_destroy_system_on_critical_kills():
    obj = FakeDamageable()
    obj.DestroySystem(obj.GetHull())
    assert obj.GetHull().GetCondition() == 0.0
    assert obj.IsDying() == 1


def test_destroy_system_on_noncritical_zeroes_but_no_death():
    obj = FakeDamageable()
    sensors = FakeSub(critical=0)
    obj.DestroySystem(sensors)
    assert sensors.GetCondition() == 0.0
    assert sensors.IsDestroyed() == 1
    assert obj.IsDying() == 0


def test_destroy_system_none_is_noop():
    obj = FakeDamageable()
    obj.DestroySystem(None)  # must not raise
    assert obj.IsDying() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_death.py -k destroy_system -v`
Expected: FAIL — `DestroySystem` currently returns a `_Stub` (truthy no-op), so condition stays at max and no death occurs.

- [ ] **Step 3: Add `DestroySystem` to `DamageableObject`**

In `engine/appc/objects.py`, add directly below `DamageSystem`:

```python
    def DestroySystem(self, subsystem) -> None:
        """Force a subsystem to zero condition (mirrors SDK
        pShip.DestroySystem). Ship death is a side effect only when the
        subsystem is critical; DestroySystem(pSensors) just zeroes sensors."""
        if subsystem is None:
            return
        subsystem.SetCondition(0.0)
        if hasattr(subsystem, "SetDestroyed"):
            subsystem.SetDestroyed(True)
        if _is_critical(subsystem) and hasattr(self, "IsDying") \
                and not self.IsDying() and not self.IsDead():
            from engine.appc import ship_death
            ship_death.begin(self)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_death.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/objects.py tests/unit/test_ship_death.py
git commit -m "feat(death): implement DestroySystem with critical-flag death rule"
```

---

## Task 4: Wire `advance` and `reset` into the host loop

Tick the death registry every frame and clear it on mission swap.

**Files:**
- Modify: `engine/host_loop.py` (`_advance_combat` ~line 269; `swap_mission` ~line 1703)
- Test: `tests/unit/test_ship_death.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_ship_death.py`:

```python
# --- Task 4: host-loop wiring ------------------------------------------------
def test_host_loop_advance_combat_ticks_death():
    """_advance_combat must call ship_death.advance so dying ships progress."""
    import engine.host_loop as host_loop
    ship = FakeShip(name="Tick")
    ship_death.begin(ship)
    # Drive the per-frame combat hub with no ships and a full-throes dt.
    host_loop._advance_combat([], ship_death.THROES_DURATION)
    assert ship.IsDead() == 1


def test_swap_mission_calls_ship_death_reset(monkeypatch):
    """swap_mission must clear the death registry (no dangling throes)."""
    import engine.host_loop as host_loop
    called = {"reset": False}
    monkeypatch.setattr(ship_death, "reset",
                        lambda: called.__setitem__("reset", True))
    # The wiring is a single line; assert the source references it so this
    # test fails until the call is added.
    import inspect
    src = inspect.getsource(host_loop.HostController.swap_mission)
    assert "ship_death.reset()" in src
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_death.py -k "host_loop or swap_mission" -v`
Expected: FAIL — `_advance_combat` does not yet tick `ship_death`, and `swap_mission` has no `ship_death.reset()` call.

- [ ] **Step 3: Add the `advance` call to `_advance_combat`**

In `engine/host_loop.py`, in `_advance_combat`, immediately after the existing `particles.advance(dt)` line (~line 271):

```python
    from engine.appc import ship_death
    ship_death.advance(dt)
```

- [ ] **Step 4: Add the `reset` call to `swap_mission`**

In `engine/host_loop.py`, in `HostController.swap_mission`, immediately after the existing `ship_lifecycle.reset()` line (~line 1703):

```python
            from engine.appc import ship_death
            ship_death.reset()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_death.py -k "host_loop or swap_mission" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/unit/test_ship_death.py
git commit -m "feat(death): tick ship_death.advance per frame, reset on mission swap"
```

---

## Task 5: Gate AI during the dying window

A dying ship issues no new AI orders (inert coast).

**Files:**
- Modify: `engine/appc/ai_driver.py` (`tick_ai`, ~line 34)
- Test: `tests/unit/test_ship_death.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_ship_death.py`:

```python
# --- Task 5: AI gate --------------------------------------------------------
def test_dying_ship_ai_tick_returns_done_without_running():
    from engine.appc import ai_driver
    from engine.appc.ai import PlainAI, ArtificialIntelligence

    ran = {"value": False}

    class SpyAI(PlainAI):
        def __init__(self, ship):
            super().__init__()
            self._ship = ship
        # If tick reaches the body, this flips. The gate must prevent it.

    ship = FakeShip(name="AIShip")
    ship.SetDying(True)
    ai = SpyAI(ship)

    status = ai_driver.tick_ai(ai, 0.0)
    assert status == ArtificialIntelligence.US_DONE


def test_alive_ship_ai_tick_not_gated():
    from engine.appc import ai_driver
    from engine.appc.ai import PlainAI
    ship = FakeShip(name="LiveShip")  # not dying
    ai = PlainAI()
    ai._ship = ship
    # Should not raise and should not be force-returned by the death gate.
    # (We only assert the gate is transparent for a live ship.)
    ai_driver.tick_ai(ai, 0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_death.py -k "ai_tick" -v`
Expected: FAIL — `test_dying_ship_ai_tick_returns_done_without_running` fails because there is no death gate (a fresh `PlainAI` with `US_ACTIVE` does not return `US_DONE`).

- [ ] **Step 3: Add the gate to `tick_ai`**

In `engine/appc/ai_driver.py`, at the very top of `tick_ai`, after the existing `if ai is None:` guard:

```python
def tick_ai(ai, game_time: float) -> int:
    """Tick one AI subtree at the given game time. Returns the resulting status."""
    if ai is None:
        return US_DONE
    # Inert-coast gate: a dying/dead ship issues no new orders.
    from engine.appc import ship_death
    ship = ai.GetShip() if hasattr(ai, "GetShip") else None
    if ship is not None and ship_death._out_of_action(ship):
        return US_DONE
    if isinstance(ai, BuilderAI):
        return _tick_builder(ai, game_time)
    # ... (rest unchanged)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_death.py -k "ai_tick" -v`
Expected: PASS.

- [ ] **Step 5: Guard AI regressions**

Run: `uv run pytest tests/unit/test_plain_ai_script_loading.py tests/unit/test_priority_list_refreshes_conditional.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ai_driver.py tests/unit/test_ship_death.py
git commit -m "feat(death): gate AI ticks for dying/dead ships (inert coast)"
```

---

## Task 6: Gate weapons during the dying window

A dying ship cannot fire. Extend the shared `_is_offline` funnel so a weapon whose parent ship is out of action reads offline.

**Files:**
- Modify: `engine/appc/subsystems.py` (`_is_offline`, ~line 368)
- Test: `tests/unit/test_ship_death.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_ship_death.py`:

```python
# --- Task 6: weapon gate ----------------------------------------------------
def test_weapon_offline_when_parent_ship_dying():
    from engine.appc.subsystems import _is_offline

    class FakeWeapon:
        def __init__(self, ship):
            self._ship = ship
        def IsDisabled(self):   return 0
        def IsDestroyed(self):  return 0
        def GetParentShip(self): return self._ship

    ship = FakeShip(name="Gunner")
    weapon = FakeWeapon(ship)
    assert _is_offline(weapon) is False  # alive: weapon online
    ship.SetDying(True)
    assert _is_offline(weapon) is True   # dying: weapon gated offline


def test_weapon_offline_unaffected_when_no_parent_ship():
    from engine.appc.subsystems import _is_offline

    class FakeWeaponNoShip:
        def IsDisabled(self):   return 0
        def IsDestroyed(self):  return 0
        def GetParentShip(self): return None

    assert _is_offline(FakeWeaponNoShip()) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_death.py -k "weapon_offline" -v`
Expected: FAIL — `_is_offline` does not yet consider parent-ship death, so a dying ship's weapon still reads online.

- [ ] **Step 3: Extend `_is_offline`**

In `engine/appc/subsystems.py`, replace the body of `_is_offline` (currently at `subsystems.py:368`):

```python
def _is_offline(sub) -> bool:
    """True when a subsystem is disabled OR destroyed, OR its parent ship is
    out of action (dying/dead — inert coast). Single source of truth for the
    capability gates (weapons, engines, sensors, shield generator, repair).
    Reads predicates at use-time so repair lifting condition releases the gate
    automatically on the next call."""
    if sub is None:
        return False
    if bool(sub.IsDisabled()) or bool(sub.IsDestroyed()):
        return True
    if hasattr(sub, "GetParentShip"):
        from engine.appc import ship_death
        if ship_death._out_of_action(sub.GetParentShip()):
            return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_death.py -k "weapon_offline" -v`
Expected: PASS.

- [ ] **Step 5: Guard subsystem/weapon regressions**

Run: `uv run pytest tests/unit/test_subsystems.py tests/unit/test_energy_weapon_power_gate.py tests/unit/test_torpedo_tube_power_gate.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_ship_death.py
git commit -m "feat(death): gate weapons offline when parent ship is dying/dead"
```

---

## Task 7: Death explosion VFX

Fill in `_spawn_explosion` to fire the SDK's `Effects.CreateExplosionPuffHigh` with the real `ExplosionA/B` sprites, sized to the ship's radius. Raise-safe.

**Files:**
- Modify: `engine/appc/ship_death.py` (`_spawn_explosion`)
- Test: `tests/unit/test_ship_death.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_ship_death.py`:

```python
# --- Task 7: explosion VFX --------------------------------------------------
def test_begin_spawns_explosion_controller():
    """begin must register at least one particle controller targeting an
    Explosion sprite."""
    from engine.appc import particles
    particles.reset()
    ship = FakeShip(name="Boom", radius=3.0)
    ship_death.begin(ship)
    descriptors = particles.snapshot_descriptors()
    assert len(descriptors) >= 1
    paths = [d.get("texture_path", "") for d in descriptors]
    assert any("Explosion" in p for p in paths)
    particles.reset()


def test_spawn_explosion_raise_safe(monkeypatch):
    """If the SDK Effects call raises, begin must still mark the ship dying."""
    import Effects
    def boom(*a, **k):
        raise RuntimeError("no backend")
    monkeypatch.setattr(Effects, "CreateExplosionPuffHigh", boom)
    ship = FakeShip(name="Safe")
    ship_death.begin(ship)  # must not raise
    assert ship.IsDying() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_death.py -k "explosion or raise_safe" -v`
Expected: FAIL — `test_begin_spawns_explosion_controller` fails because `_spawn_explosion` is still a `pass` no-op (no descriptor registered).

- [ ] **Step 3: Implement `_spawn_explosion`**

In `engine/appc/ship_death.py`, replace the `_spawn_explosion` stub:

```python
def _spawn_explosion(ship) -> None:
    """Death explosion: an ExplosionA/B fireball sized to the ship radius,
    emitted from the (still-present, coasting) hull. Reuses the SDK Effects
    helper via our AnimTSParticleController shim + particle backend.

    Raise-safe: death logic must never depend on VFX succeeding (missing
    asset / headless test without a backend just yields no explosion)."""
    try:
        import Effects
        from engine.appc.math import TGPoint3
        radius = ship.GetRadius() if hasattr(ship, "GetRadius") else 1.0
        size = max(radius * EXPLOSION_SIZE_FACTOR, MIN_EXPLOSION_SIZE)
        action = Effects.CreateExplosionPuffHigh(
            THROES_DURATION,            # fLife
            size,                       # fSize
            ship,                       # pEmitFrom — tracks the tumbling hull
            TGPoint3(0.0, 0.0, 0.0),    # kEmitPos (body origin)
            TGPoint3(0.0, 0.0, 1.0),    # kEmitDir
            None,                       # pAttachTo — unattached at emit pos
        )
        if action is not None and hasattr(action, "Play"):
            action.Play()
    except Exception:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_death.py -k "explosion or raise_safe" -v`
Expected: PASS.

- [ ] **Step 5: Run the full death test file**

Run: `uv run pytest tests/unit/test_ship_death.py -v`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ship_death.py tests/unit/test_ship_death.py
git commit -m "feat(death): ExplosionA/B fireball via SDK Effects on death"
```

---

## Task 8: Broadcast `ET_OBJECT_DESTROYED` on death

Mission scripts (`ConditionDestroyed`, per-episode `ObjectDestroyed` handlers) react to `ET_OBJECT_DESTROYED`. The constant is not defined in our `App` shim and nothing broadcasts it. Add the constant and broadcast the event in `_finish`, before removal, with both source and destination set to the dying ship (func-broadcast handlers read source; method-broadcast handlers filter on destination).

**Files:**
- Modify: `App.py` (add `ET_OBJECT_DESTROYED` constant)
- Modify: `engine/appc/ship_death.py` (`_finish`)
- Test: `tests/unit/test_ship_death.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_ship_death.py`:

```python
# --- Task 8: ET_OBJECT_DESTROYED broadcast ----------------------------------
def test_app_defines_object_destroyed_constant():
    import App
    assert isinstance(App.ET_OBJECT_DESTROYED, int)


def test_death_broadcasts_object_destroyed_once():
    import App
    from engine.appc.events import TGPythonInstanceWrapper

    fired = {"count": 0, "source_name": None}

    class Listener:
        def Destroyed(self, pEvent):
            fired["count"] += 1
            src = pEvent.GetSource()
            fired["source_name"] = src.GetName() if src is not None else None

    listener = Listener()
    wrapper = TGPythonInstanceWrapper()
    wrapper.SetPyWrapper(listener)

    ship = FakeShip(name="Marked")
    # Register a per-source method handler keyed on this ship (the SDK
    # ConditionDestroyed pattern: target == the watched object).
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_OBJECT_DESTROYED, wrapper, "Destroyed", ship)

    ship_death.begin(ship)
    ship_death.advance(ship_death.THROES_DURATION)

    assert fired["count"] == 1
    assert fired["source_name"] == "Marked"

    App.g_kEventManager.RemoveAllInstanceHandlers()
```

> Note: the test relies on `TGPythonInstanceWrapper`, `AddBroadcastPythonMethodHandler(event_type, wrapper, method, target)`, and the manager dispatching method handlers whose `target` matches the event destination — all present in `engine/appc/events.py`. `FakeShip` must be accepted as a destination; the event manager's method-handler dispatch filters on `event.GetDestination() is target` and does not require `TGEventHandlerObject`, so `FakeShip` works.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_ship_death.py -k "object_destroyed" -v`
Expected: FAIL — `App.ET_OBJECT_DESTROYED` raises `AttributeError` (constant undefined), and no broadcast occurs.

- [ ] **Step 3: Add the `ET_OBJECT_DESTROYED` constant**

In `App.py`, in the event-type block (after `ET_OBJECT_EXPLODING = 106` at line 579):

```python
ET_OBJECT_DESTROYED = 107
```

- [ ] **Step 4: Broadcast the event in `_finish`**

In `engine/appc/ship_death.py`, update `_finish` to broadcast before removal:

```python
def _finish(ship) -> None:
    """Death instant: mark dead, broadcast ET_OBJECT_DESTROYED, then remove
    from set. Order matters — the event fires while the handle is still in
    the set so handlers can read the ship's name/position."""
    if hasattr(ship, "SetDead"):
        ship.SetDead()
    _broadcast_destroyed(ship)
    try:
        pSet = ship.GetContainingSet() if hasattr(ship, "GetContainingSet") else None
        if pSet is not None and hasattr(ship, "GetName"):
            pSet.RemoveObjectFromSet(ship.GetName())
    except Exception:
        pass


def _broadcast_destroyed(ship) -> None:
    """Fire ET_OBJECT_DESTROYED with source == destination == ship, so both
    func-broadcast handlers (read GetSource) and per-source method handlers
    (filter on GetDestination) receive it. Raise-safe."""
    try:
        import App
        evt = App.TGEvent_Create()
        evt.SetEventType(App.ET_OBJECT_DESTROYED)
        evt.SetSource(ship)
        evt.SetDestination(ship)
        App.g_kEventManager.AddEvent(evt)
    except Exception:
        pass
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_ship_death.py -k "object_destroyed" -v`
Expected: PASS.

- [ ] **Step 6: Run the full death test file once more**

Run: `uv run pytest tests/unit/test_ship_death.py -v`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add App.py engine/appc/ship_death.py tests/unit/test_ship_death.py
git commit -m "feat(death): define + broadcast ET_OBJECT_DESTROYED on ship death"
```

---

## Task 9: Final integration sweep

Confirm the whole sequence holds together and no neighbouring tests regressed.

**Files:** none (verification only)

- [ ] **Step 1: Run the death suite plus the most coupled neighbours**

Run:
```bash
uv run pytest tests/unit/test_ship_death.py tests/unit/test_subsystems.py \
  tests/unit/test_player.py tests/integration/test_warp_smoke.py -v
```
Expected: PASS. (Do NOT run the bare full suite — it OOMs the host.)

- [ ] **Step 2: Manual smoke note**

The end-to-end visual check (kill an NPC in a running mission, observe inert coast → `ExplosionA/B` fireball → ship despawn) is a `./build/dauntless` runtime check, recorded here as a follow-up for the verify skill — not automated in this plan.

---

## Self-Review notes

- **Spec coverage:** state machine (T1), critical-flag trigger + warp core + matankeldon-by-flag (T2), `DestroySystem` (T3), per-frame wiring + mission-swap reset (T4), inert-coast AI gate (T5), weapon gate (T6), `ExplosionA/B` VFX raise-safe (T7), `ET_OBJECT_DESTROYED` broadcast + removal ordering (T8), save/load (no new code — relies on existing `_dying`/`_dead` persistence, noted in spec), non-goals untouched.
- **Spec correction folded in:** the spec assumed `SetDead()` already fired `ET_OBJECT_DESTROYED`; it does not (constant undefined, no broadcast). T8 implements it — fulfilling the spec's removal-ordering requirement.
- **matankeldon exception:** handled for free by the flag (its `WarpCore.SetCritical(0)` means `_is_critical` returns False); no special-case test needed beyond `test_damaging_noncritical_subsystem...`.
- **Type consistency:** `_out_of_action`, `begin`, `advance`, `reset`, `_finish`, `_spawn_explosion`, `_broadcast_destroyed`, `_is_critical` names are used identically across tasks.
