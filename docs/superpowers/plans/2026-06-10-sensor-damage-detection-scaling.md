# Sensor-Damage Detection Scaling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce a ship's target-detection range in proportion to its sensor subsystem's condition, and detect nothing once the sensor is offline — for both the player's target list and AI candidate selection.

**Architecture:** A new pure-formula module `engine/appc/sensor_detection.py` computes `effective_sensor_range(ship)` and `can_detect(observer, target)`. The player target list (`update_target_list_visibility` in `subsystems.py`) sources its range from that formula. AI selection is gated by a two-part monkeypatch: `SelectTarget.FindGoodTarget` (the candidate-enumeration method) publishes the querying ship into a module global, and a wrapped `ObjectGroup.GetActiveObjectTupleInSet` filters candidates through `can_detect` while that global is set. Single-threaded Python makes the global safe.

**Tech Stack:** Python 3, pytest. No renderer/native build involved — all headless.

**Spec:** `docs/superpowers/specs/2026-06-10-sensor-damage-detection-scaling-design.md`

---

## Background facts (read before starting)

- `SensorSubsystem` lives in `engine/appc/subsystems.py:1792`. It has `GetBaseSensorRange()` (populated from `SensorProperty` during ship setup), `GetConditionPercentage()` (inherited from `ShipSubsystem`), and a default `_disabled_percentage` of `0.25`.
- `_is_offline(sub)` (`engine/appc/subsystems.py:368`) returns True when a subsystem is disabled (`IsDisabled()`, condition ≤ 25% by default) OR destroyed. Reuse it; do not reinvent the offline check.
- `_get_xyz(obj)` (`engine/appc/subsystems.py:2224`) reads a world position as `(x, y, z)` floats, tolerating whichever accessor the object exposes; falls back to `(0, 0, 0)`.
- `ShipClass.GetSensorSubsystem()` (`engine/appc/ships.py:526`) returns the attached sensor subsystem or `None`.
- `update_target_list_visibility(target_menu, ships, player, range_units=30000.0)` (`engine/appc/subsystems.py:2176`) currently hides all rows when the player sensor is offline, else does a distance check against `range_units`. It is called from `engine/host_loop.py:2328` with **no** `range_units` argument.
- The SDK's `SelectTarget.FindGoodTarget` (`sdk/Build/scripts/AI/Preprocessors.py:1423`, called from `SelectTarget.Update` at `:1251`) calls `self.pTargetGroup.GetActiveObjectTupleInSet(pSet)` at `:1432` to enumerate candidates, then has shortcuts `len==0 → None` and `len==1 → that one`. `self.pCodeAI.GetShip()` is the querying ship. `UpdateTargetInfo` (`:1331`) runs *after* selection and does not enumerate — do not wrap it.
- `ObjectGroup.GetActiveObjectTupleInSet(self, pSet)` is defined once at `engine/appc/objects.py:415`; `ObjectGroupWithInfo` (the type `ObjectGroup_ForceToGroup` returns) inherits it without override, so patching the base class covers both.
- `_bootstrap_firing_pipeline()` (`engine/host_loop.py:82`, called at `:2190`) is the established "bring up the SDK-faithful pipeline at startup" hook.

**Circular-import rule:** `sensor_detection.py` may import from `subsystems.py` at module top (subsystems does NOT import sensor_detection at top). `subsystems.update_target_list_visibility` must import from `sensor_detection` **lazily inside the function** (matching the file's existing lazy-import idiom).

**Memory warning:** Never run the full pytest suite — it OOMs the host (>100 GB RAM). Always run the specific test files/nodes named in each task.

---

## File Structure

- **Create** `engine/appc/sensor_detection.py` — the formula (`effective_sensor_range`, `can_detect`), the AI-gate primitives (`observing`, `current_observing_ship`, `_wrap_active_tuple`, `_wrap_find_good_target`, `install_ai_sensor_gate`).
- **Create** `tests/unit/test_sensor_detection.py` — all new tests.
- **Modify** `engine/appc/subsystems.py:2176` — `update_target_list_visibility` sources range from the formula when `range_units` is omitted.
- **Modify** `engine/host_loop.py:82` — install the AI gate during bootstrap.

---

## Task 1: Core formula module

**Files:**
- Create: `engine/appc/sensor_detection.py`
- Test: `tests/unit/test_sensor_detection.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_sensor_detection.py`:

```python
"""Sensor-damage detection scaling: range formula, detection predicate,
and the AI candidate-selection gate."""
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import SensorSubsystem
from engine.appc.sensor_detection import (
    FALLBACK_RANGE_GU, effective_sensor_range, can_detect,
)


def _ship_with_sensor(base_range, condition=100.0, max_condition=100.0,
                      at=(0.0, 0.0, 0.0)):
    ship = ShipClass_Create("Galaxy")
    ship.SetTranslateXYZ(*at)
    sensors = SensorSubsystem("Sensors")
    sensors._max_condition = max_condition
    sensors._condition = condition
    sensors.SetBaseSensorRange(base_range)
    ship.SetSensorSubsystem(sensors)
    return ship, sensors


def test_undamaged_sensor_returns_full_base_range():
    ship, _ = _ship_with_sensor(2000.0)
    assert effective_sensor_range(ship) == 2000.0


def test_range_scales_linearly_with_condition():
    ship, _ = _ship_with_sensor(2000.0, condition=60.0)
    assert effective_sensor_range(ship) == 1200.0


def test_disabled_sensor_returns_zero():
    # 20% condition is below the default 25% disabled threshold -> offline.
    ship, _ = _ship_with_sensor(2000.0, condition=20.0)
    assert effective_sensor_range(ship) == 0.0


def test_destroyed_sensor_returns_zero():
    ship, sensors = _ship_with_sensor(2000.0)
    sensors.SetCondition(0.0)
    assert effective_sensor_range(ship) == 0.0


def test_no_sensor_subsystem_returns_fallback():
    ship = ShipClass_Create("Galaxy")  # no sensor attached
    assert effective_sensor_range(ship) == FALLBACK_RANGE_GU


def test_zero_base_range_returns_fallback():
    ship, _ = _ship_with_sensor(0.0)
    assert effective_sensor_range(ship) == FALLBACK_RANGE_GU


def test_can_detect_true_inside_range():
    observer, _ = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    target = ShipClass_Create("BirdOfPrey")
    target.SetTranslateXYZ(1000.0, 0.0, 0.0)
    assert can_detect(observer, target) is True


def test_can_detect_false_outside_range():
    observer, _ = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    target = ShipClass_Create("BirdOfPrey")
    target.SetTranslateXYZ(2500.0, 0.0, 0.0)
    assert can_detect(observer, target) is False


def test_can_detect_false_when_observer_blind():
    observer, sensors = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    sensors.SetCondition(0.0)  # offline -> range 0
    target = ShipClass_Create("BirdOfPrey")
    target.SetTranslateXYZ(10.0, 0.0, 0.0)
    assert can_detect(observer, target) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sensor_detection.py -v`
Expected: collection/import error — `ModuleNotFoundError: No module named 'engine.appc.sensor_detection'`.

- [ ] **Step 3: Create the module with the formula**

Create `engine/appc/sensor_detection.py`:

```python
"""Sensor-damage detection scaling.

A ship detects targets out to a range that scales linearly with its
sensor subsystem's condition, and detects nothing once the sensor is
offline (disabled at <= DisabledPercentage, or destroyed). Used by both
the player target list and the AI candidate-selection gate.

See docs/superpowers/specs/2026-06-10-sensor-damage-detection-scaling-design.md
"""

from engine.appc.subsystems import _is_offline, _get_xyz

# Range used when a ship models no sensor subsystem or carries no
# BaseSensorRange hardpoint data. Preserves the player target list's
# historical 30000 GU reach and keeps sensor-less fixtures fully sighted.
FALLBACK_RANGE_GU = 30000.0


def effective_sensor_range(ship) -> float:
    """Detection range (game units) for *ship* given its sensor condition.

    Full BaseSensorRange when undamaged, scaled linearly by condition
    percentage, and 0.0 once the sensor subsystem is offline (disabled or
    destroyed). Returns FALLBACK_RANGE_GU for ships that don't model a
    sensor subsystem or carry no BaseSensorRange.
    """
    sensors = (ship.GetSensorSubsystem()
               if (ship is not None and hasattr(ship, "GetSensorSubsystem"))
               else None)
    if sensors is None:
        return FALLBACK_RANGE_GU
    if _is_offline(sensors):
        return 0.0
    base = sensors.GetBaseSensorRange()
    if base <= 0.0:
        return FALLBACK_RANGE_GU
    return base * sensors.GetConditionPercentage()


def can_detect(observer, target) -> bool:
    """True iff *observer* can detect *target* within its effective sensor
    range. False when the observer is blind (range 0)."""
    r = effective_sensor_range(observer)
    if r <= 0.0:
        return False
    ox, oy, oz = _get_xyz(observer)
    tx, ty, tz = _get_xyz(target)
    dx, dy, dz = tx - ox, ty - oy, tz - oz
    return (dx * dx + dy * dy + dz * dz) <= (r * r)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sensor_detection.py -v`
Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sensor_detection.py tests/unit/test_sensor_detection.py
git commit -m "feat(sensors): effective_sensor_range + can_detect formula

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: AI-gate primitives (observing + wrappers + installer)

**Files:**
- Modify: `engine/appc/sensor_detection.py` (append)
- Test: `tests/unit/test_sensor_detection.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_sensor_detection.py`:

```python
from engine.appc.sensor_detection import (
    observing, current_observing_ship,
    _wrap_active_tuple, _wrap_find_good_target,
)


def test_observing_sets_and_restores_global():
    assert current_observing_ship() is None
    with observing("SHIP_A"):
        assert current_observing_ship() == "SHIP_A"
        with observing("SHIP_B"):
            assert current_observing_ship() == "SHIP_B"
        assert current_observing_ship() == "SHIP_A"
    assert current_observing_ship() is None


def test_observing_restores_even_on_exception():
    try:
        with observing("SHIP_A"):
            raise ValueError("boom")
    except ValueError:
        pass
    assert current_observing_ship() is None


def test_wrap_find_good_target_publishes_ship_during_call():
    captured = []

    def fake_orig(self, dEndTime):
        captured.append(current_observing_ship())
        return "result"

    wrapped = _wrap_find_good_target(fake_orig)

    class _FakeCodeAI:
        def GetShip(self):
            return "SHIP_X"

    class _FakeSelectTarget:
        pCodeAI = _FakeCodeAI()

    assert wrapped(_FakeSelectTarget(), 1.0) == "result"
    assert captured == ["SHIP_X"]
    assert current_observing_ship() is None  # cleared after the call
    assert getattr(wrapped, "_sensor_gated", False) is True


def test_wrap_find_good_target_handles_missing_codeai():
    captured = []

    def fake_orig(self, dEndTime):
        captured.append(current_observing_ship())
        return "ok"

    wrapped = _wrap_find_good_target(fake_orig)

    class _NoCodeAI:
        pCodeAI = None

    assert wrapped(_NoCodeAI(), 0.0) == "ok"
    assert captured == [None]


def test_wrap_active_tuple_filters_only_when_observer_set():
    near = ShipClass_Create("BirdOfPrey"); near.SetTranslateXYZ(500.0, 0.0, 0.0)
    far = ShipClass_Create("BirdOfPrey"); far.SetTranslateXYZ(5000.0, 0.0, 0.0)

    def fake_orig(self, pSet):
        return (near, far)

    wrapped = _wrap_active_tuple(fake_orig)

    # No observer set -> unfiltered passthrough.
    assert wrapped(object(), None) == (near, far)

    # Observer with 2000 GU range -> only the near ship survives.
    observer, _ = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    with observing(observer):
        assert wrapped(object(), None) == (near,)
    assert getattr(wrapped, "_sensor_gated", False) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sensor_detection.py -k "observing or wrap" -v`
Expected: ImportError on `observing` / `_wrap_active_tuple` (not yet defined).

- [ ] **Step 3: Append the primitives to the module**

Append to `engine/appc/sensor_detection.py`:

```python
# ── AI candidate-selection gate ───────────────────────────────────────────────
# The SDK's SelectTarget.UpdateTargetInfo enumerates candidates via
# ObjectGroup.GetActiveObjectTupleInSet, which has no ship context. We stash the
# querying ship in a module global for the duration of an UpdateTargetInfo call
# (single-threaded Python -- safe) and have a wrapped GetActiveObjectTupleInSet
# consult it. Every other caller of that method runs with the global None and is
# unaffected.

_observing_ship = None


def current_observing_ship():
    """The ship whose sensors gate the in-flight candidate enumeration, or
    None when no AI target selection is active."""
    return _observing_ship


class observing:
    """Context manager that marks *ship* as the current sensor observer for
    the duration of a candidate enumeration. Nestable; restores the prior
    observer (or None) on exit, including on exception."""

    def __init__(self, ship):
        self._ship = ship
        self._prev = None

    def __enter__(self):
        global _observing_ship
        self._prev = _observing_ship
        _observing_ship = self._ship
        return self

    def __exit__(self, *exc):
        global _observing_ship
        _observing_ship = self._prev
        return False


def _wrap_active_tuple(orig):
    """Wrap ObjectGroup.GetActiveObjectTupleInSet so that, while an observer
    ship is published, its result is filtered to objects that observer can
    detect. No-op (identity passthrough) when no observer is set."""

    def _gated_active(self, pSet):
        result = orig(self, pSet)
        observer = current_observing_ship()
        if observer is None:
            return result
        return tuple(obj for obj in result if can_detect(observer, obj))

    _gated_active._sensor_gated = True
    return _gated_active


def _wrap_find_good_target(orig):
    """Wrap SelectTarget.UpdateTargetInfo so the querying ship is published as
    the current observer for the duration of the original call."""

    def _gated_update(self, dEndTime):
        code_ai = getattr(self, "pCodeAI", None)
        ship = code_ai.GetShip() if code_ai is not None else None
        with observing(ship):
            return orig(self, dEndTime)

    _gated_update._sensor_gated = True
    return _gated_update


def install_ai_sensor_gate() -> None:
    """Idempotently install the two-part AI sensor gate: wrap
    ObjectGroup.GetActiveObjectTupleInSet (candidate filter) and
    SelectTarget.UpdateTargetInfo (observer publisher). Safe to call repeatedly
    and safe when the SDK AI package is unavailable."""
    from engine.appc.objects import ObjectGroup
    if not getattr(ObjectGroup.GetActiveObjectTupleInSet, "_sensor_gated", False):
        ObjectGroup.GetActiveObjectTupleInSet = _wrap_active_tuple(
            ObjectGroup.GetActiveObjectTupleInSet
        )

    try:
        import AI.Preprocessors as _pp
    except ImportError:
        # Pure-unit context without the SDK AI tree. The ObjectGroup patch is
        # still live and exercised directly via observing(); the SelectTarget
        # wrap installs on a later call once the SDK is importable.
        return
    if not getattr(_pp.SelectTarget.UpdateTargetInfo, "_sensor_gated", False):
        _pp.SelectTarget.UpdateTargetInfo = _wrap_find_good_target(
            _pp.SelectTarget.UpdateTargetInfo
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sensor_detection.py -v`
Expected: all tests (Task 1 + Task 2) PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sensor_detection.py tests/unit/test_sensor_detection.py
git commit -m "feat(sensors): AI sensor-gate primitives (observing + wrappers + installer)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Installed-gate integration over a real ObjectGroup + set

**Files:**
- Test: `tests/unit/test_sensor_detection.py` (append)

This verifies the real path: `install_ai_sensor_gate()` patches the live `ObjectGroup` class, and `GetActiveObjectTupleInSet` over a real `SetClass` filters by the observer's sensor range while `observing()` is active. It also asserts idempotency and the unfiltered default.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_sensor_detection.py`:

```python
from engine.appc.objects import ObjectGroup
from engine.appc.sensor_detection import install_ai_sensor_gate


def _set_with(*named_ships):
    pSet = App.SetClass_Create()
    pSet.SetName("S")
    for name, ship in named_ships:
        ship.SetName(name)
        pSet.AddObjectToSet(ship, name)
    return pSet


def test_installed_gate_filters_active_tuple_by_sensor_range():
    install_ai_sensor_gate()

    near = ShipClass_Create("BirdOfPrey"); near.SetTranslateXYZ(500.0, 0.0, 0.0)
    far = ShipClass_Create("BirdOfPrey"); far.SetTranslateXYZ(5000.0, 0.0, 0.0)
    pSet = _set_with(("Near", near), ("Far", far))

    group = ObjectGroup()
    group.AddName("Near"); group.AddName("Far")

    # No observer -> both contacts returned (non-AI callers unaffected).
    assert set(group.GetActiveObjectTupleInSet(pSet)) == {near, far}

    # Observer with 2000 GU range -> only the near contact survives.
    observer, sensors = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    with observing(observer):
        assert group.GetActiveObjectTupleInSet(pSet) == (near,)


def test_installed_gate_blinds_observer_with_offline_sensors():
    install_ai_sensor_gate()

    enemy = ShipClass_Create("BirdOfPrey"); enemy.SetTranslateXYZ(100.0, 0.0, 0.0)
    pSet = _set_with(("Enemy", enemy))
    group = ObjectGroup(); group.AddName("Enemy")

    observer, sensors = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    sensors.SetCondition(0.0)  # offline -> range 0
    with observing(observer):
        assert group.GetActiveObjectTupleInSet(pSet) == ()


def test_install_is_idempotent():
    install_ai_sensor_gate()
    first = ObjectGroup.GetActiveObjectTupleInSet
    install_ai_sensor_gate()
    second = ObjectGroup.GetActiveObjectTupleInSet
    # Second install must not re-wrap (same function object, no double filter).
    assert first is second
    assert getattr(second, "_sensor_gated", False) is True
```

- [ ] **Step 2: Run tests to verify they fail (then pass)**

Run: `uv run pytest tests/unit/test_sensor_detection.py -k installed_gate -v`
Expected: these PASS immediately (the implementation already exists from Task 2). If `test_install_is_idempotent` fails with `first is not second`, the attribute-marker guard in `install_ai_sensor_gate` is wrong — fix it before continuing.

Run the whole file: `uv run pytest tests/unit/test_sensor_detection.py -v`
Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_sensor_detection.py
git commit -m "test(sensors): installed AI gate filters real ObjectGroup over a set

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Player target list sources range from the formula

**Files:**
- Modify: `engine/appc/subsystems.py:2176` (`update_target_list_visibility`)
- Test: `tests/unit/test_sensor_detection.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_sensor_detection.py`:

```python
from engine.appc.subsystems import update_target_list_visibility


def test_player_list_uses_scaled_range_when_range_units_omitted():
    App._reset_target_menu_singleton()
    player, sensors = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    player.SetName("Player")
    enemy = ShipClass_Create("BirdOfPrey"); enemy.SetName("Enemy")
    enemy.SetTranslateXYZ(1000.0, 0.0, 0.0)

    menu = App.STTargetMenu_CreateW("Targets")
    menu.RebuildShipMenu(enemy)

    # Undamaged: 2000 GU range, enemy at 1000 GU -> visible.
    update_target_list_visibility(menu, [enemy], player)
    assert menu.GetObjectEntry(enemy).IsVisible() == 1

    # Damaged to 40% -> 800 GU range, enemy at 1000 GU now out of range.
    sensors.SetCondition(40.0)
    update_target_list_visibility(menu, [enemy], player)
    assert menu.GetObjectEntry(enemy).IsVisible() == 0

    # Repaired: visible again.
    sensors.SetCondition(100.0)
    update_target_list_visibility(menu, [enemy], player)
    assert menu.GetObjectEntry(enemy).IsVisible() == 1


def test_player_list_explicit_range_units_still_honored():
    App._reset_target_menu_singleton()
    player, sensors = _ship_with_sensor(2000.0, at=(0.0, 0.0, 0.0))
    player.SetName("Player")
    enemy = ShipClass_Create("BirdOfPrey"); enemy.SetName("Enemy")
    enemy.SetTranslateXYZ(2500.0, 0.0, 0.0)  # beyond 2000 base, inside 30000

    menu = App.STTargetMenu_CreateW("Targets")
    menu.RebuildShipMenu(enemy)

    # Explicit override ignores the scaled range and uses 30000.
    update_target_list_visibility(menu, [enemy], player, range_units=30000.0)
    assert menu.GetObjectEntry(enemy).IsVisible() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_sensor_detection.py -k "player_list" -v`
Expected: `test_player_list_uses_scaled_range_when_range_units_omitted` FAILS — with the current `range_units=30000.0` default, the enemy at 1000 GU stays visible at 40% condition (expected 0, got 1).

- [ ] **Step 3: Change the signature default and compute the range**

In `engine/appc/subsystems.py`, change the `update_target_list_visibility` signature default from `range_units: float = 30000.0` to `range_units: float = None`, and compute it from the player when omitted. The current body is:

```python
    from engine.appc.target_menu import STSubsystemMenu
    if player is None:
        return
    sensors = (player.GetSensorSubsystem()
               if hasattr(player, "GetSensorSubsystem") else None)
    if _is_offline(sensors):
        for ship in ships:
            row = target_menu.GetObjectEntry(ship)
            if row is None or not isinstance(row, STSubsystemMenu):
                continue
            row.SetNotVisible()
        return
    px, py, pz = _get_xyz(player)
    range_sq = range_units * range_units
```

Replace it with:

```python
    from engine.appc.target_menu import STSubsystemMenu
    if player is None:
        return
    sensors = (player.GetSensorSubsystem()
               if hasattr(player, "GetSensorSubsystem") else None)
    if _is_offline(sensors):
        for ship in ships:
            row = target_menu.GetObjectEntry(ship)
            if row is None or not isinstance(row, STSubsystemMenu):
                continue
            row.SetNotVisible()
        return
    # Range source: an explicit range_units overrides; otherwise scale by the
    # player's sensor condition (engine/appc/sensor_detection). Lazy import
    # avoids an import cycle (sensor_detection imports this module).
    if range_units is None:
        from engine.appc.sensor_detection import effective_sensor_range
        range_units = effective_sensor_range(player)
    px, py, pz = _get_xyz(player)
    range_sq = range_units * range_units
```

Also update the signature line and its docstring `range_units` paragraph so the default reads `None` (compute from sensor condition) instead of `30000`. The signature becomes:

```python
def update_target_list_visibility(target_menu, ships, player, range_units: float = None) -> None:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sensor_detection.py -k "player_list" -v`
Expected: both PASS.

Regression-check the existing sensor-UI tests (they pass `range_units=30000.0` explicitly and must stay green):

Run: `uv run pytest tests/unit/test_sensors_disabled_blanks_target_ui.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_sensor_detection.py
git commit -m "feat(sensors): player target list range scales with sensor condition

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Install the AI gate at host bootstrap

**Files:**
- Modify: `engine/host_loop.py:82` (`_bootstrap_firing_pipeline`)
- Test: `tests/unit/test_sensor_detection.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_sensor_detection.py`:

```python
def test_bootstrap_installs_sensor_gate():
    """The startup bootstrap installs the AI sensor gate as its first action,
    so ObjectGroup.GetActiveObjectTupleInSet is wrapped after host init."""
    from engine import host_loop
    try:
        host_loop._bootstrap_firing_pipeline()
    except Exception:
        # Later pipeline setup may need fuller host state in some contexts;
        # the gate install is the first line of the function, so it has
        # already run by the time any later step could raise.
        pass
    assert getattr(ObjectGroup.GetActiveObjectTupleInSet, "_sensor_gated", False) is True
```

- [ ] **Step 2: Run the test to verify it fails**

Running the single node spawns a fresh process where no other test has installed the gate, so this proves the bootstrap wiring itself.

Run: `uv run pytest "tests/unit/test_sensor_detection.py::test_bootstrap_installs_sensor_gate" -v`
Expected: FAIL — `_bootstrap_firing_pipeline` does not yet call the installer, so `GetActiveObjectTupleInSet` has no `_sensor_gated` marker.

- [ ] **Step 3: Add the install call as the first line of the bootstrap**

In `engine/host_loop.py`, inside `_bootstrap_firing_pipeline()`, add the install immediately after the docstring and before `import App`:

```python
def _bootstrap_firing_pipeline() -> None:
    """... existing docstring unchanged ..."""
    # Install the sensor-damage AI gate first so it is live regardless of
    # whether any later pipeline step short-circuits. Idempotent.
    from engine.appc.sensor_detection import install_ai_sensor_gate
    install_ai_sensor_gate()

    import App
    ...
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_sensor_detection.py::test_bootstrap_installs_sensor_gate -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/unit/test_sensor_detection.py
git commit -m "feat(sensors): install AI sensor gate at host bootstrap

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Run the feature's full test file:

Run: `uv run pytest tests/unit/test_sensor_detection.py -v`
Expected: all tests PASS.

- [ ] Run the adjacent suites this change touches:

Run: `uv run pytest tests/unit/test_sensors_disabled_blanks_target_ui.py tests/unit/test_object_group_active.py tests/unit/test_object_groups.py -v`
Expected: all PASS (no regressions in the player-list offline behavior or ObjectGroup enumeration).

- [ ] Confirm there are no other direct callers of `update_target_list_visibility` relying on the old `30000.0` default:

Run: `grep -rn "update_target_list_visibility(" engine/ tests/`
Expected: only `host_loop.py:2328` (no `range_units`, now computes) and the test call sites. If any production caller passes no `range_units` and expected 30000, note it — the new behavior scales by sensor condition there too (intended).

---

## Spec coverage check

- Proportional range reduction with damage → Task 1 (`effective_sensor_range` linear × condition) + Task 4 (player) + Tasks 2/3/5 (AI).
- All sensors offline → no player targets → Task 4 (offline early-return retained; range 0 hides all).
- All sensors offline → no AI targets → Tasks 2/3/5 (empty candidate tuple → `SelectTarget` returns None).
- Real BaseSensorRange as baseline → Task 1.
- Blind at disabled threshold → Task 1 (reuses `_is_offline`).
- AI symmetric, overrides `bIgnoreSensors` → Tasks 2/3/5 (filter applies regardless of the flag).
- Non-goals (jamming, `_known_objects` sweep, rebalancing) → not implemented, by design.
