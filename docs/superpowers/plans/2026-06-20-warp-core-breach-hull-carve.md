# Warp-Core Breach Hull Carve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a ship's warp core breaches, carve one big voxel hole through its hull at the warp core that grows over ~1.5 s, so the exploding ship visibly tears open (the breach AoE currently skips the source ship).

**Architecture:** A new pure-Python `core_breach_carve` registry, scheduled from `warp_core_breach.detonate` and advanced each tick from `host_loop`, emits a growing carve at the warp core's world position via the existing `host.hull_carve_add(...)` binding. The existing breach render pass draws it. No native/C++/shader changes.

**Tech Stack:** Python 3 (engine), pytest. The carve binding and render pass already exist.

## Global Constraints

Copied verbatim from the spec — every task's requirements implicitly include these:

- **Engine layer is modern Python 3.** Run tests with `uv run pytest <path> -v`.
- **No native changes / no rebuild** — reuse `host.hull_carve_add(iid, world_point, world_normal, radius_gu, time)` and the existing breach render pass.
- Constants exactly: `GROW_DURATION = 1.5`, `MAX_RADIUS_SHIP_FRACTION = 0.7`, `MIN_RADIUS_GU = 0.1`.
- Carve **center = warp core world position** (`subsystem_world_position(core, ship)`), recomputed each tick from the current transform (constant in body frame → a single growing carve).
- Radius grows ease-out: `radius = max(MIN_RADIUS_GU, 0.7 * ship.GetRadius() * (1 - (1-t)^2))`, `t = min(1, age/GROW_DURATION)`.
- **Bypasses** the weapon-hit gate (no eligibility / throttle / ≥60-damage). Raise-safe (`dev_mode.log_swallowed`).
- Carve normal: `normalize(core_world - ship.GetWorldLocation())`, fallback to ship up `GetWorldRotation().GetCol(2)` when the core is at the centre.

**Spec:** `docs/superpowers/specs/2026-06-20-warp-core-breach-hull-carve-design.md`

---

### Task 1: `core_breach_carve` registry

**Files:**
- Create: `engine/appc/core_breach_carve.py`
- Test: `tests/unit/test_core_breach_carve.py` (create)

**Interfaces:**
- Produces: `core_breach_carve.schedule(ship)`; `core_breach_carve.advance(dt, host=None, ship_instances=None)`; `core_breach_carve.reset()`; constants `GROW_DURATION = 1.5`, `MAX_RADIUS_SHIP_FRACTION = 0.7`, `MIN_RADIUS_GU = 0.1`.
- Consumes: `subsystems.subsystem_world_position(sub, ship)`; `damage_decals.current_game_time()`; `host.hull_carve_add(iid, (x,y,z), (nx,ny,nz), radius, time)`; the target ship exposes `GetWorldLocation`, `GetWorldRotation`, `GetRadius`, `GetPowerSubsystem` (→ a core with `GetPosition`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_core_breach_carve.py`:

```python
"""Tests for the warp-core breach hull carve (engine/appc/core_breach_carve.py)."""
import pytest

from engine.appc import core_breach_carve
from engine.appc.math import TGMatrix3, TGPoint3


class _Core:
    def __init__(self, pos=None):
        self._pos = pos or TGPoint3(0.5, 0.0, 0.0)  # body offset from ship centre

    def GetPosition(self):
        return self._pos


class _Ship:
    def __init__(self, loc=None, radius=2.0, core="default"):
        self._loc = loc or TGPoint3(0.0, 0.0, 0.0)
        self._radius = radius
        self._core = _Core() if core == "default" else core
        self._rot = TGMatrix3()  # identity

    def GetWorldLocation(self):  return self._loc
    def GetWorldRotation(self):  return self._rot
    def GetRadius(self):         return self._radius
    def GetPowerSubsystem(self): return self._core


class _Host:
    def __init__(self):
        self.carves = []  # (iid, point, normal, radius, time)

    def hull_carve_add(self, iid, point, normal, radius, time):
        self.carves.append((iid, point, normal, radius, time))


@pytest.fixture(autouse=True)
def _clean():
    core_breach_carve.reset()
    yield
    core_breach_carve.reset()


def test_advance_emits_carve_at_core_with_growing_radius():
    ship = _Ship(radius=2.0)
    host = _Host()
    si = {ship: 7}
    core_breach_carve.schedule(ship)

    core_breach_carve.advance(0.15, host, si)
    core_breach_carve.advance(0.45, host, si)   # age now 0.6

    assert len(host.carves) == 2
    # Same instance id, centered at the core world position (ship at origin,
    # identity rotation, core body offset (0.5,0,0) -> world (0.5,0,0)).
    assert host.carves[0][0] == 7
    assert host.carves[0][1] == pytest.approx((0.5, 0.0, 0.0))
    # Radius strictly grows as it ages.
    assert host.carves[1][3] > host.carves[0][3]


def test_carve_normal_points_from_centre_through_core():
    ship = _Ship(radius=2.0)
    host = _Host()
    core_breach_carve.schedule(ship)
    core_breach_carve.advance(0.1, host, {ship: 1})
    nx, ny, nz = host.carves[0][2]
    assert (round(nx, 5), round(ny, 5), round(nz, 5)) == (1.0, 0.0, 0.0)


def test_reaches_full_radius_then_drops():
    ship = _Ship(radius=2.0)
    host = _Host()
    si = {ship: 1}
    core_breach_carve.schedule(ship)

    core_breach_carve.advance(core_breach_carve.GROW_DURATION, host, si)  # t=1
    # Full radius = 0.7 * 2.0 * easeOut(1.0) = 1.4
    assert host.carves[-1][3] == pytest.approx(1.4)

    n = len(host.carves)
    core_breach_carve.advance(1.0, host, si)   # entry dropped -> no new carve
    assert len(host.carves) == n


def test_no_instance_emits_nothing_and_drops():
    ship = _Ship()
    host = _Host()
    core_breach_carve.schedule(ship)
    core_breach_carve.advance(0.1, host, {})   # ship not in ship_instances
    assert host.carves == []
    core_breach_carve.advance(0.1, host, {ship: 1})  # already dropped
    assert host.carves == []


def test_ship_without_core_is_not_scheduled():
    ship = _Ship(core=None)
    host = _Host()
    core_breach_carve.schedule(ship)
    core_breach_carve.advance(0.1, host, {ship: 1})
    assert host.carves == []


def test_schedule_is_idempotent():
    ship = _Ship()
    host = _Host()
    core_breach_carve.schedule(ship)
    core_breach_carve.schedule(ship)
    core_breach_carve.advance(0.1, host, {ship: 1})
    assert len(host.carves) == 1   # one entry, one carve this tick


def test_reset_clears_registry():
    ship = _Ship()
    host = _Host()
    core_breach_carve.schedule(ship)
    core_breach_carve.reset()
    core_breach_carve.advance(0.1, host, {ship: 1})
    assert host.carves == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_core_breach_carve.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.appc.core_breach_carve'`.

- [ ] **Step 3: Write the module**

Create `engine/appc/core_breach_carve.py`:

```python
# engine/appc/core_breach_carve.py
"""Warp-core breach hull carve: one big growing voxel hole at the warp core.

warp_core_breach.detonate schedules a carve on the exploding ship; advance()
grows it over GROW_DURATION and emits it each tick via host.hull_carve_add at
the warp core's world position. The core sits inside the hull, so a carve there
punches a hole through and exposes the interior — the self-destruction the
breach AoE skips (it skips the source ship). Reuses the existing carve binding
and render pass; no native changes.

See docs/superpowers/specs/2026-06-20-warp-core-breach-hull-carve-design.md.
"""
import engine.dev_mode as dev_mode

GROW_DURATION            = 1.5   # seconds the hole grows to full size
MAX_RADIUS_SHIP_FRACTION = 0.7   # full carve radius as a fraction of ship radius
MIN_RADIUS_GU            = 0.1   # floor so the first growing frame is visible

# Registry of in-progress core breaches: each entry is {"ship": ship, "age": float}.
_active: list[dict] = []


def schedule(ship) -> None:
    """Register a growing core-breach carve for `ship`. Idempotent per ship;
    no-op when the ship has no warp core (PowerSubsystem)."""
    if ship is None:
        return
    core = ship.GetPowerSubsystem() if hasattr(ship, "GetPowerSubsystem") else None
    if core is None:
        return
    for entry in _active:
        if entry["ship"] is ship:
            return
    _active.append({"ship": ship, "age": 0.0})


def _ease_out(t: float) -> float:
    """Fast-then-settle growth curve, 0..1."""
    return 1.0 - (1.0 - t) * (1.0 - t)


def _carve_normal(ship, core_world):
    """World normal for rim orientation: from the ship centre through the core,
    falling back to the ship up axis when the core is at the centre."""
    from engine.appc.math import TGPoint3
    loc = ship.GetWorldLocation()
    dx = core_world.x - loc.x
    dy = core_world.y - loc.y
    dz = core_world.z - loc.z
    mag = (dx * dx + dy * dy + dz * dz) ** 0.5
    if mag > 1e-6:
        return TGPoint3(dx / mag, dy / mag, dz / mag)
    if hasattr(ship, "GetWorldRotation"):
        up = ship.GetWorldRotation().GetCol(2)
        return TGPoint3(up.x, up.y, up.z)
    return TGPoint3(0.0, 0.0, 1.0)


def advance(dt: float, host=None, ship_instances=None) -> None:
    """Grow + emit each active core-breach carve. Drops an entry when it reaches
    full size or its ship is no longer rendered. Raise-safe per entry."""
    if not _active:
        return
    survivors = []
    for entry in _active:
        try:
            keep = _advance_one(entry, dt, host, ship_instances)
        except Exception as _e:
            dev_mode.log_swallowed("core breach carve advance", _e)
            keep = False
        if keep:
            survivors.append(entry)
    _active[:] = survivors


def _advance_one(entry, dt, host, ship_instances) -> bool:
    """Advance one entry; emit its carve. Returns True to keep it active, False
    to drop it (full size reached, or the ship is no longer rendered)."""
    ship = entry["ship"]
    entry["age"] += float(dt)
    t = min(1.0, entry["age"] / GROW_DURATION)

    iid = ship_instances.get(ship) if ship_instances is not None else None
    if iid is None or host is None or not hasattr(host, "hull_carve_add"):
        return False

    core = ship.GetPowerSubsystem() if hasattr(ship, "GetPowerSubsystem") else None
    if core is None:
        return False

    from engine.appc.subsystems import subsystem_world_position
    from engine.appc import damage_decals
    core_world = subsystem_world_position(core, ship)
    radius_full = MAX_RADIUS_SHIP_FRACTION * (
        ship.GetRadius() if hasattr(ship, "GetRadius") else 1.0)
    radius = max(MIN_RADIUS_GU, radius_full * _ease_out(t))
    normal = _carve_normal(ship, core_world)
    now = damage_decals.current_game_time()

    host.hull_carve_add(
        iid,
        (core_world.x, core_world.y, core_world.z),
        (normal.x, normal.y, normal.z),
        radius,
        now,
    )
    return t < 1.0   # drop once the full-size carve has been emitted


def reset() -> None:
    """Clear the registry (mission swap / test teardown)."""
    _active.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_core_breach_carve.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/core_breach_carve.py tests/unit/test_core_breach_carve.py
git commit -m "feat(vfx): warp-core breach hull-carve registry

One big voxel carve at the warp core on the exploding ship, growing over
GROW_DURATION via the existing hull_carve_add binding. Bypasses the weapon-hit
gate; raise-safe; drops at full size or when the ship is no longer rendered.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `detonate` schedules the core-breach carve

**Files:**
- Modify: `engine/appc/warp_core_breach.py` (`detonate`, after the shockwave-spawn block at line 67-69)
- Test: `tests/unit/test_warp_core_breach.py` (add one test)

**Interfaces:**
- Consumes: `core_breach_carve.schedule(ship)` (Task 1).
- Produces: `warp_core_breach.detonate` schedules a core-breach carve on the exploding ship.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_warp_core_breach.py` (reuse its existing `_Core`/`_Ship`/`TGPoint3`/`_patch_ships` fakes and `_clean` fixture):

```python
def test_detonate_schedules_core_breach_carve(monkeypatch):
    from engine.appc import core_breach_carve
    scheduled = []
    monkeypatch.setattr(core_breach_carve, "schedule",
                        lambda ship: scheduled.append(ship))
    import engine.appc.ship_iter as ship_iter
    src = _Ship("Doomed", TGPoint3(0.0, 0.0, 0.0), core=_Core(5000.0))
    monkeypatch.setattr(ship_iter, "iter_ships", lambda *a, **k: [src])

    warp_core_breach.detonate(src)

    assert scheduled == [src]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_warp_core_breach.py::test_detonate_schedules_core_breach_carve -v`
Expected: FAIL — `detonate` does not call `core_breach_carve.schedule` yet (`scheduled == []`).

- [ ] **Step 3: Schedule the carve in `detonate`**

In `engine/appc/warp_core_breach.py`, find the shockwave-spawn block in `detonate` (around lines 65-69):

```python
    try:
        from engine.appc import shockwaves
        shockwaves.spawn(centre, BREACH_RADIUS_GU, shockwaves.SHOCKWAVE_LIFETIME)
    except Exception as _e:
        dev_mode.log_swallowed("spawn warp core shockwave", _e)
```

Add immediately after it:

```python
    try:
        from engine.appc import core_breach_carve
        core_breach_carve.schedule(ship)
    except Exception as _e:
        dev_mode.log_swallowed("schedule core breach carve", _e)
```

- [ ] **Step 4: Run the new test AND the full breach suite**

Run: `uv run pytest tests/unit/test_warp_core_breach.py tests/unit/test_warp_core_breach_integration.py -v`
Expected: all PASS (the new test plus every existing breach test — `schedule` is additive and the AoE loop is unchanged).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/warp_core_breach.py tests/unit/test_warp_core_breach.py
git commit -m "feat(vfx): breach schedules a core hull-carve on the exploding ship

detonate now schedules core_breach_carve on the source ship (the AoE still
skips it), so the breaching ship visibly tears open.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Host-loop wiring (advance + reset)

**Files:**
- Modify: `engine/host_loop.py` (after `warp_core_breach.advance(...)` at line 368; after `warp_core_breach.reset()` at line 2088)
- Verify: grep + `py_compile`

**Interfaces:**
- Consumes: `core_breach_carve.advance(dt, host, ship_instances)`, `core_breach_carve.reset()` (Task 1).
- Produces: nothing new — wiring that grows/emits the carve each tick and clears it on mission swap.

- [ ] **Step 1: Find the wiring sites**

Run:
```bash
grep -n "warp_core_breach.advance\|warp_core_breach.reset\|core_breach_carve" engine/host_loop.py
```
Expected: a `warp_core_breach.advance(dt, host=host, ship_instances=ship_instances)` in `_advance_combat` and a `warp_core_breach.reset()` in the mission-swap reset block. (No existing `core_breach_carve` references.)

- [ ] **Step 2: Advance the carve registry each tick**

In `engine/host_loop.py`, immediately after the `warp_core_breach.advance(dt, host=host, ship_instances=ship_instances)` line, add:

```python
    from engine.appc import core_breach_carve
    core_breach_carve.advance(dt, host=host, ship_instances=ship_instances)
```

- [ ] **Step 3: Reset on mission swap**

In `engine/host_loop.py`, immediately after the `warp_core_breach.reset()` line, add:

```python
        from engine.appc import core_breach_carve
        core_breach_carve.reset()
```

- [ ] **Step 4: Verify wiring present and the module compiles**

Run:
```bash
grep -n "core_breach_carve.advance\|core_breach_carve.reset" engine/host_loop.py
uv run python -m py_compile engine/host_loop.py && echo "SYNTAX OK"
```
Expected: two grep hits (advance, reset) and `SYNTAX OK`. (`import engine.host_loop` fails headless on the native `_dauntless_host` module — pre-existing and unrelated; `py_compile` is the correct check.)

- [ ] **Step 5: Confirm the carve tests still pass**

Run: `uv run pytest tests/unit/test_core_breach_carve.py tests/unit/test_warp_core_breach.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(vfx): pump core-breach hull carve each tick

Advance core_breach_carve beside warp_core_breach in _advance_combat; reset it
beside warp_core_breach.reset on mission swap.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- Growing core-breach carve registry (schedule/advance/reset, constants) → Task 1. ✓
- Center at warp core, recomputed each tick; single growing carve → Task 1 (`subsystem_world_position` each `_advance_one`). ✓
- Radius ease-out, `0.7 * GetRadius()`, MIN floor → Task 1. ✓
- Normal from centre through core, up-axis fallback → Task 1 `_carve_normal`. ✓
- Bypasses weapon gate (direct `hull_carve_add`, no eligibility/throttle) → Task 1 (no gate code). ✓
- Raise-safe per entry; headless/no-renderer no-ops → Task 1 (`try/except`, iid/host guards). ✓
- `detonate` schedules it → Task 2. ✓
- host_loop advance + reset → Task 3. ✓
- Drops at full size / when ship unrendered → Task 1 (`return t < 1.0`, iid None → False) + tests. ✓
- Pure Python, no native changes → confirmed (only `hull_carve_add` reuse). ✓

**2. Placeholder scan:** No TBD/TODO/"handle edge cases". All steps carry complete code; the headless-import caveat is stated. ✓

**3. Type consistency:** `schedule(ship)`, `advance(dt, host, ship_instances)`, `reset()`, and constants `GROW_DURATION`/`MAX_RADIUS_SHIP_FRACTION`/`MIN_RADIUS_GU` are named identically across Task 1 (definition + tests), Task 2 (spy on `schedule`), and Task 3 (advance/reset wiring). `hull_carve_add(iid, point, normal, radius, time)` arg order matches the real binding (`InstanceId, world_point, world_normal, radius, time`) confirmed during planning. `subsystem_world_position(core, ship)` matches the real `subsystem_world_position(sub, ship=None)`. ✓
