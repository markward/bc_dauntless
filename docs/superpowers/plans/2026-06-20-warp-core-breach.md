# Warp-Core Breach Explosion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a ship's Warp Core subsystem condition crosses from >0 to 0, detonate a massive weapon-style area explosion (≈10× a photon torpedo) from the core's location that damages every ship in range, with a 1.5 s hull-death subsystem cascade feeding it and same-tick chain reactions.

**Architecture:** Two new pure-Python modules in `engine/appc/` — `subsystem_cascade.py` (the 1.5 s hull-death cascade) and `warp_core_breach.py` (arm/advance/detonate). A small routing hook in `objects.py` arms the breach / schedules the cascade on zero-crossings. `combat.apply_hit` gains a `splash_radius` override so the breach reuses the entire existing weapon-damage path. `host_loop._advance_combat` pumps both new modules each tick.

**Tech Stack:** Python 3 (engine layer), pytest. No native/C++ or shader changes.

## Global Constraints

Copied verbatim from CLAUDE.md and the spec — every task's requirements implicitly include these:

- **Engine layer is modern Python 3.** The Python-1.5 / no-f-strings / no-`True` constraints apply **only** to `tools/appc_logger.py`, never to `engine/`. Write idiomatic Python 3.
- **Game units (GU).** All distances/radii are GU (1 GU = 175 m). Name variables `*_gu`, never `*_m`. The breach radius constant is `BREACH_RADIUS_GU`.
- **Column-vector rotation convention.** World position of a subsystem mount = `subsystem_world_position(sub, ship)` from `engine/appc/subsystems.py` (`ship_loc + R · local`, no scale). Never hand-roll the matrix math.
- **Death / VFX is raise-safe.** Damage logic must never depend on VFX or optional renderer calls succeeding. Wrap optional/VFX side effects in `try/except` and call `dev_mode.log_swallowed("<label>", e)` (pattern: `engine/appc/ship_death.py:_spawn_explosion`).
- **Run tests:** `uv run pytest tests/unit/<file>.py -v` for a single file; `scripts/run_tests.sh` for the full watchdog-capped suite. Do NOT invoke the full suite per-step — only at the noted points.
- **Photon torpedo damage-radius-factor is 0.13 GU**, so 10× = **1.3 GU**. Photon damage is 500; a 5000-condition core × `BREACH_DAMAGE_FACTOR 1.0` = 5000 center damage = 10× photon.

**Spec:** `docs/superpowers/specs/2026-06-20-warp-core-breach-design.md`

---

### Task 1: `apply_hit` gains a `splash_radius` override

**Files:**
- Modify: `engine/appc/combat.py:318-352`
- Test: `tests/unit/test_apply_hit_splash_radius_override.py` (create)

**Interfaces:**
- Produces: `combat.apply_hit(ship, damage, hit_point, source, *, normal=None, host=None, ship_instances=None, weapon_type=None, hardpoint_weapon=None, payload_template=None, splash_radius: float | None = None)`. When `splash_radius` is not None it overrides the resolved `r_hit`; when None, behaviour is byte-identical to today.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_apply_hit_splash_radius_override.py`:

```python
"""apply_hit(splash_radius=...) overrides the resolved R_hit.

A subsystem placed beyond the default phaser radius (0.15 GU) but inside an
explicit 1.3 GU override must be damaged only when the override is supplied.
"""
from engine.appc.combat import apply_hit
from engine.appc.math import TGMatrix3, TGPoint3
import App


class _FakeSub:
    def __init__(self, name, pos, radius, max_condition=1000.0):
        self.name = name
        self._pos = pos
        self._radius = radius
        self._max = max_condition
        self._condition = max_condition

    def GetPosition(self):     return self._pos
    def GetRadius(self):       return self._radius
    def GetCondition(self):    return self._condition
    def GetMaxCondition(self): return self._max
    def IsDamaged(self):       return self._condition < self._max
    def IsDisabled(self):      return False
    def IsDestroyed(self):     return False


class _FakeHull(_FakeSub):
    pass


class _FakeShip(App.TGEventHandlerObject):
    def __init__(self, hull, subsystems):
        super().__init__()
        self._hull = hull
        self._subs = list(subsystems)
        self._loc = TGPoint3(0.0, 0.0, 0.0)
        self._rot = TGMatrix3()
        self.damage_log = []

    def GetHull(self):          return self._hull
    def GetSubsystems(self):    return list(self._subs)
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetShields(self):       return None

    def DamageSystem(self, sub, amount):
        self.damage_log.append((sub.name, amount))
        sub._condition = max(0.0, sub._condition - amount)


def _names(ship):
    return [n for n, _ in ship.damage_log]


def test_default_radius_does_not_reach_distant_subsystem():
    hull = _FakeHull("Hull", TGPoint3(0, 0, 0), radius=1.0)
    far = _FakeSub("Far", TGPoint3(0.5, 0, 0), radius=0.1)
    ship = _FakeShip(hull=hull, subsystems=[hull, far])
    apply_hit(ship, 100.0, TGPoint3(0, 0, 0), source=None, normal=None)
    assert "Far" not in _names(ship)


def test_override_radius_reaches_distant_subsystem():
    hull = _FakeHull("Hull", TGPoint3(0, 0, 0), radius=1.0)
    far = _FakeSub("Far", TGPoint3(0.5, 0, 0), radius=0.1)
    ship = _FakeShip(hull=hull, subsystems=[hull, far])
    apply_hit(ship, 100.0, TGPoint3(0, 0, 0), source=None, normal=None,
              splash_radius=1.3)
    assert "Far" in _names(ship)
    # weight = (0.1 + 1.3 - 0.5) / 1.3 = 0.9/1.3 ≈ 0.6923
    far_amount = next(a for n, a in ship.damage_log if n == "Far")
    assert abs(far_amount - 100.0 * (0.9 / 1.3)) < 1e-6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_apply_hit_splash_radius_override.py -v`
Expected: `test_override_radius_reaches_distant_subsystem` FAILS with `TypeError: apply_hit() got an unexpected keyword argument 'splash_radius'`. (`test_default_radius_...` passes.)

- [ ] **Step 3: Add the kwarg and override**

In `engine/appc/combat.py`, change the signature (currently lines 318-321):

```python
def apply_hit(ship, damage: float, hit_point, source, *,
              normal=None, host=None, ship_instances=None,
              weapon_type: str | None = None,
              hardpoint_weapon=None, payload_template=None,
              splash_radius: float | None = None) -> None:
```

Then change the `r_hit` resolution (currently line 352, `r_hit = weapon_splash_radius(hardpoint_weapon, payload_template)`) to:

```python
    r_hit = weapon_splash_radius(hardpoint_weapon, payload_template)
    if splash_radius is not None:
        r_hit = float(splash_radius)
```

Add to the existing kwargs docstring block (after the `payload_template` line, ~line 345):

```python
        splash_radius       — explicit R_hit override in game units. When set,
                              supersedes the (hardpoint_weapon, payload_template)
                              resolution. Used by the warp-core breach to force a
                              1.3 GU blast. None for all weapon callers.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_apply_hit_splash_radius_override.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Verify no existing combat caller regressed**

Run: `uv run pytest tests/unit/test_apply_hit_splash.py tests/unit/test_combat_hit_resolution.py tests/unit/test_combat_splash_radius.py -v`
Expected: all PASS (default `splash_radius=None` keeps every caller unchanged).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/combat.py tests/unit/test_apply_hit_splash_radius_override.py
git commit -m "feat(combat): apply_hit splash_radius override

Optional kwarg overrides the resolved R_hit; default None preserves every
existing weapon caller. Used by the warp-core breach for a 1.3 GU blast.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `subsystem_cascade` — 1.5 s hull-death subsystem zeroing

**Files:**
- Create: `engine/appc/subsystem_cascade.py`
- Test: `tests/unit/test_subsystem_cascade.py` (create)

**Interfaces:**
- Produces: `subsystem_cascade.schedule(ship)`, `subsystem_cascade.advance(dt: float)`, `subsystem_cascade.reset()`, and `subsystem_cascade.CASCADE_DELAY = 1.5`.
- Consumes: `combat._iter_subsystems(ship)` (yields leaf subsystems excluding hull); `ship.GetHull()`, `ship.GetPowerSubsystem()`, `ship.DestroySystem(sub)`, `ship.IsDestroyBrokenSystems()`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_subsystem_cascade.py`:

```python
"""Tests for the hull-death subsystem cascade (engine/appc/subsystem_cascade.py)."""
import pytest

from engine.appc import subsystem_cascade


class _Sub:
    def __init__(self, name, cond=100.0):
        self.name = name
        self._c = cond
        self._destroyed = False

    def GetCondition(self):   return self._c
    def SetCondition(self, v): self._c = v
    def SetDestroyed(self, v): self._destroyed = bool(v)
    def IsDestroyed(self):     return self._destroyed


class _Ship:
    """Fake ship exposing the surface the cascade walks."""
    def __init__(self, hull, power, others, destroy_broken=True):
        self._hull = hull
        self._power = power
        self._others = list(others)
        self._destroy_broken = destroy_broken
        self.destroyed = []  # subsystems passed to DestroySystem, in order

    def GetHull(self):            return self._hull
    def GetPowerSubsystem(self):  return self._power
    def GetSubsystems(self):      return [self._hull, self._power, *self._others]
    def IsDestroyBrokenSystems(self): return 1 if self._destroy_broken else 0

    def DestroySystem(self, sub):
        self.destroyed.append(sub)
        sub.SetCondition(0.0)
        sub.SetDestroyed(True)


@pytest.fixture(autouse=True)
def _clean():
    subsystem_cascade.reset()
    yield
    subsystem_cascade.reset()


def _make_ship(**kw):
    hull = _Sub("Hull", cond=0.0)   # hull already dead when cascade is scheduled
    power = _Sub("WarpCore", cond=100.0)
    sensors = _Sub("Sensors", cond=100.0)
    return _Ship(hull, power, [sensors], **kw), hull, power, sensors


def test_schedule_then_advance_past_delay_zeroes_all_subsystems():
    ship, hull, power, sensors = _make_ship()
    subsystem_cascade.schedule(ship)
    subsystem_cascade.advance(subsystem_cascade.CASCADE_DELAY)
    destroyed = set(ship.destroyed)
    assert power in destroyed and sensors in destroyed and hull in destroyed
    assert power.GetCondition() == 0.0


def test_does_not_fire_before_delay():
    ship, _, power, _ = _make_ship()
    subsystem_cascade.schedule(ship)
    subsystem_cascade.advance(subsystem_cascade.CASCADE_DELAY / 2.0)
    assert ship.destroyed == []
    assert power.GetCondition() == 100.0


def test_destroy_broken_systems_flag_off_suppresses_cascade():
    ship, _, power, _ = _make_ship(destroy_broken=False)
    subsystem_cascade.schedule(ship)
    subsystem_cascade.advance(subsystem_cascade.CASCADE_DELAY * 2)
    assert ship.destroyed == []
    assert power.GetCondition() == 100.0


def test_schedule_is_idempotent():
    ship, _, power, _ = _make_ship()
    subsystem_cascade.schedule(ship)
    subsystem_cascade.schedule(ship)
    subsystem_cascade.advance(subsystem_cascade.CASCADE_DELAY)
    # Warp core destroyed exactly once despite the double schedule.
    assert ship.destroyed.count(power) == 1


def test_reset_clears_pending():
    ship, _, power, _ = _make_ship()
    subsystem_cascade.schedule(ship)
    subsystem_cascade.reset()
    subsystem_cascade.advance(subsystem_cascade.CASCADE_DELAY)
    assert ship.destroyed == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_subsystem_cascade.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.appc.subsystem_cascade'`.

- [ ] **Step 3: Write the module**

Create `engine/appc/subsystem_cascade.py`:

```python
# engine/appc/subsystem_cascade.py
"""Hull-death subsystem cascade: zero every subsystem CASCADE_DELAY seconds
after the hull reaches 0.

This is BC's "destroy broken systems" behaviour. Zeroing the warp core during
the cascade drives its condition across 0, which the objects.py zero-crossing
hook turns into a warp_core_breach.arm(ship). Gated by the SDK-faithful
ship.IsDestroyBrokenSystems() flag (default ON) so a mission's
SetDestroyBrokenSystems(0) derelict keeps its subsystems.

See docs/superpowers/specs/2026-06-20-warp-core-breach-design.md.
"""
import engine.dev_mode as dev_mode

CASCADE_DELAY = 1.5  # seconds from hull-0 to all-subsystems-0

# Registry of pending cascades: each entry is {"ship": ship, "time_left": float}.
_active: list[dict] = []


def _destroy_broken_systems(ship) -> bool:
    """Honour ship.IsDestroyBrokenSystems(); default ON when absent (fakes)."""
    if not hasattr(ship, "IsDestroyBrokenSystems"):
        return True
    return bool(ship.IsDestroyBrokenSystems())


def schedule(ship) -> None:
    """Register a CASCADE_DELAY-second cascade for `ship`. Idempotent and
    gated by the SDK flag: a ship that opts out (SetDestroyBrokenSystems(0))
    or is already scheduled is ignored."""
    if ship is None or not _destroy_broken_systems(ship):
        return
    for entry in _active:
        if entry["ship"] is ship:
            return
    _active.append({"ship": ship, "time_left": CASCADE_DELAY})


def advance(dt: float) -> None:
    """Tick every pending cascade; on expiry, zero all subsystems. Prunes."""
    if not _active:
        return
    survivors = []
    for entry in _active:
        entry["time_left"] -= dt
        if entry["time_left"] > 0.0:
            survivors.append(entry)
            continue
        _fire(entry["ship"])
    _active[:] = survivors


def _fire(ship) -> None:
    """DestroySystem every subsystem on `ship` (hull + warp core + leaves),
    each at most once. Raise-safe — a cascade failure must not kill the tick."""
    try:
        seen = set()
        targets = []
        for getter in ("GetHull", "GetPowerSubsystem"):
            if hasattr(ship, getter):
                s = getattr(ship, getter)()
                if s is not None and id(s) not in seen:
                    seen.add(id(s))
                    targets.append(s)
        from engine.appc.combat import _iter_subsystems
        for s in _iter_subsystems(ship):
            if s is not None and id(s) not in seen:
                seen.add(id(s))
                targets.append(s)
        for s in targets:
            if hasattr(ship, "DestroySystem"):
                ship.DestroySystem(s)
    except Exception as _e:
        dev_mode.log_swallowed("subsystem cascade fire", _e)


def reset() -> None:
    """Clear the registry (mission swap / test teardown)."""
    _active.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_subsystem_cascade.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystem_cascade.py tests/unit/test_subsystem_cascade.py
git commit -m "feat(combat): 1.5s hull-death subsystem cascade

Zeroes every subsystem CASCADE_DELAY seconds after hull death, gated by
IsDestroyBrokenSystems. Drives the warp core to 0 to feed the breach.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `warp_core_breach` — arm / advance / detonate

**Files:**
- Create: `engine/appc/warp_core_breach.py`
- Test: `tests/unit/test_warp_core_breach.py` (create)

**Interfaces:**
- Produces: `warp_core_breach.arm(ship)`, `warp_core_breach.advance(dt, host=None, ship_instances=None)`, `warp_core_breach.detonate(ship, host=None, ship_instances=None)`, `warp_core_breach.reset()`, and constants `BREACH_DAMAGE_FACTOR = 1.0`, `BREACH_RADIUS_GU = 1.3`, `BREACH_FIREBALL_FACTOR = 2.0`.
- Consumes: `combat.apply_hit(..., splash_radius=)` (Task 1), `combat._splash_weight` and `combat._resolve_hit_point` (existing), `subsystems.subsystem_world_position(sub, ship)`, `ship_iter.iter_ships()`. Target ships expose `GetWorldLocation()`, `GetRadius()`. The detonating ship exposes `GetPowerSubsystem()` returning a core with `GetMaxCondition()` and `GetPosition()`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_warp_core_breach.py`:

```python
"""Tests for the warp-core breach (engine/appc/warp_core_breach.py)."""
import pytest

from engine.appc import warp_core_breach
from engine.appc.math import TGMatrix3, TGPoint3


class _Core:
    def __init__(self, max_condition=5000.0, pos=None):
        self._max = max_condition
        self._pos = pos or TGPoint3(0.0, 0.0, 0.0)

    def GetMaxCondition(self): return self._max
    def GetPosition(self):     return self._pos


class _Ship:
    def __init__(self, name, loc, radius=1.0, core=None):
        self._name = name
        self._loc = loc
        self._radius = radius
        self._core = core
        self._rot = TGMatrix3()

    def GetName(self):          return self._name
    def GetWorldLocation(self): return self._loc
    def GetWorldRotation(self): return self._rot
    def GetRadius(self):        return self._radius
    def GetPowerSubsystem(self): return self._core


@pytest.fixture(autouse=True)
def _clean():
    warp_core_breach.reset()
    yield
    warp_core_breach.reset()


def _patch_ships(monkeypatch, ships):
    """Make detonate's iter_ships() yield exactly `ships`."""
    import engine.appc.ship_iter as ship_iter
    monkeypatch.setattr(ship_iter, "iter_ships", lambda *a, **k: list(ships))


def _capture_apply_hit(monkeypatch):
    """Record combat.apply_hit calls as (target, damage, splash_radius)."""
    import engine.appc.combat as combat
    calls = []

    def fake(ship, damage, hit_point, source, **kw):
        calls.append((ship, damage, kw.get("splash_radius")))
    monkeypatch.setattr(combat, "apply_hit", fake)
    return calls


def test_arm_then_advance_detonates_once(monkeypatch):
    calls = _capture_apply_hit(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), core=_Core(5000.0))
    near = _Ship("Near", TGPoint3(0.5, 0, 0), radius=0.5)
    _patch_ships(monkeypatch, [src, near])

    warp_core_breach.arm(src)
    warp_core_breach.advance(0.0)

    # Source skipped; near ship hit once.
    targets = [c[0] for c in calls]
    assert near in targets and src not in targets
    # splash_radius forced to the breach radius.
    assert calls[0][2] == warp_core_breach.BREACH_RADIUS_GU


def test_arm_is_single_fire(monkeypatch):
    calls = _capture_apply_hit(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), core=_Core(5000.0))
    near = _Ship("Near", TGPoint3(0.5, 0, 0), radius=0.5)
    _patch_ships(monkeypatch, [src, near])

    warp_core_breach.arm(src)
    warp_core_breach.arm(src)        # duplicate arm ignored
    warp_core_breach.advance(0.0)
    warp_core_breach.advance(0.0)    # already breached, no re-detonate
    assert len(calls) == 1


def test_no_core_ship_never_detonates(monkeypatch):
    calls = _capture_apply_hit(monkeypatch)
    src = _Ship("Shuttle", TGPoint3(0, 0, 0), core=None)
    near = _Ship("Near", TGPoint3(0.5, 0, 0), radius=0.5)
    _patch_ships(monkeypatch, [src, near])

    warp_core_breach.arm(src)
    warp_core_breach.advance(0.0)
    assert calls == []


def test_damage_scales_with_core_and_falls_off_with_distance(monkeypatch):
    calls = _capture_apply_hit(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), core=_Core(5000.0))
    # near at d=0.5, R=0.5: weight = (0.5 + 1.3 - 0.5)/1.3 = 1.0 (clamped)
    near = _Ship("Near", TGPoint3(0.5, 0, 0), radius=0.5)
    _patch_ships(monkeypatch, [src, near])

    warp_core_breach.arm(src)
    warp_core_breach.advance(0.0)

    near_dmg = next(d for t, d, _ in calls if t is near)
    # magnitude = 1.0 * 5000 = 5000; weight clamped to 1.0
    assert abs(near_dmg - 5000.0) < 1e-6


def test_ship_outside_radius_untouched(monkeypatch):
    calls = _capture_apply_hit(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), core=_Core(5000.0))
    # far at d=10, R=0.1: weight = (0.1 + 1.3 - 10)/1.3 < 0 -> 0
    far = _Ship("Far", TGPoint3(10.0, 0, 0), radius=0.1)
    _patch_ships(monkeypatch, [src, far])

    warp_core_breach.arm(src)
    warp_core_breach.advance(0.0)
    assert far not in [c[0] for c in calls]


def test_chain_resolves_same_tick_and_terminates(monkeypatch):
    """An apply_hit that arms a neighbour (mimicking the objects.py hook when a
    neighbour's core hits 0) must detonate that neighbour in the SAME advance,
    and the drain loop must terminate."""
    import engine.appc.combat as combat
    src = _Ship("A", TGPoint3(0, 0, 0), core=_Core(5000.0))
    nbr = _Ship("B", TGPoint3(0.5, 0, 0), radius=0.5, core=_Core(5000.0))
    _patch_ships(monkeypatch, [src, nbr])

    detonated = []
    orig_detonate = warp_core_breach.detonate

    calls = []

    def fake_apply_hit(ship, damage, hit_point, source, **kw):
        calls.append(ship)
        # First time B is hit, simulate its core reaching 0 -> arm.
        if ship is nbr:
            warp_core_breach.arm(nbr)
    monkeypatch.setattr(combat, "apply_hit", fake_apply_hit)

    def tracking_detonate(ship, **kw):
        detonated.append(ship)
        return orig_detonate(ship, **kw)
    monkeypatch.setattr(warp_core_breach, "detonate", tracking_detonate)

    warp_core_breach.arm(src)
    warp_core_breach.advance(0.0)

    # Both A and B detonated within the single advance.
    assert src in detonated and nbr in detonated
    # B detonated once (single-fire guard), loop terminated.
    assert detonated.count(nbr) == 1


def test_reset_clears_state(monkeypatch):
    calls = _capture_apply_hit(monkeypatch)
    src = _Ship("Doomed", TGPoint3(0, 0, 0), core=_Core(5000.0))
    _patch_ships(monkeypatch, [src])
    warp_core_breach.arm(src)
    warp_core_breach.reset()
    warp_core_breach.advance(0.0)
    assert calls == []
```

Note on `test_chain_...`: `advance` looks up `warp_core_breach.detonate` as a module attribute at call time, so `monkeypatch.setattr(warp_core_breach, "detonate", ...)` is observed by the drain loop. Implement `advance` to call `detonate` via the module global (a bare `detonate(...)` call inside the module resolves the patched global), which it does below.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_warp_core_breach.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.appc.warp_core_breach'`.

- [ ] **Step 3: Write the module**

Create `engine/appc/warp_core_breach.py`:

```python
# engine/appc/warp_core_breach.py
"""Warp-core breach: a catastrophic explosion when a ship's Warp Core
(PowerSubsystem) condition crosses from >0 to 0.

Armed once per ship by the objects.py zero-crossing hook (direct core kill,
hull-death cascade, or a neighbour's breach). detonate() — driven from
advance() — deals weapon-style area damage to every ship within
BREACH_RADIUS_GU of the core's world position, with NO allegiance filter, by
reusing combat.apply_hit (shields/hull/subsystem-splash/decals/sparks/audio
all fire). Chains resolve in the same tick via a non-recursive drain loop;
each ship detonates at most once.

See docs/superpowers/specs/2026-06-20-warp-core-breach-design.md.
"""
import engine.dev_mode as dev_mode

BREACH_DAMAGE_FACTOR   = 1.0   # centre damage = factor * core max condition
BREACH_RADIUS_GU       = 1.3   # 10x photon torpedo DRF (0.13 GU)
BREACH_FIREBALL_FACTOR = 2.0   # fireball size vs ship radius (tuned by feel)

_armed: list = []      # ships queued to detonate (FIFO)
_breached: set = set() # id(ship) that have already detonated


def arm(ship) -> None:
    """Queue `ship` to detonate. Idempotent: a ship already queued or already
    breached is ignored. This is the single-fire guarantee."""
    if ship is None or id(ship) in _breached:
        return
    if any(s is ship for s in _armed):
        return
    _armed.append(ship)


def advance(dt: float, host=None, ship_instances=None) -> None:
    """Drain the armed queue, detonating each ship. Non-recursive: a detonation
    may arm further ships (chains), which this while-loop picks up in the same
    tick. The _breached guard guarantees termination."""
    while _armed:
        ship = _armed.pop(0)
        if id(ship) in _breached:
            continue
        _breached.add(id(ship))
        # Module-global lookup so tests can monkeypatch `detonate`.
        detonate(ship, host=host, ship_instances=ship_instances)


def detonate(ship, host=None, ship_instances=None) -> None:
    """Massive explosion at the warp core's world position: weapon-style AoE
    damage to every ship in BREACH_RADIUS_GU + a fireball. Raise-safe."""
    from engine.appc import combat
    from engine.appc.subsystems import subsystem_world_position
    from engine.appc.ship_iter import iter_ships

    core = ship.GetPowerSubsystem() if hasattr(ship, "GetPowerSubsystem") else None
    if core is None:
        return
    centre = subsystem_world_position(core, ship)
    magnitude = BREACH_DAMAGE_FACTOR * float(core.GetMaxCondition())

    _spawn_fireball(ship, core)

    for target in list(iter_ships()):
        if target is ship:
            continue
        loc = target.GetWorldLocation()
        dx = centre.x - loc.x
        dy = centre.y - loc.y
        dz = centre.z - loc.z
        d = (dx * dx + dy * dy + dz * dz) ** 0.5
        r_tgt = target.GetRadius() if hasattr(target, "GetRadius") else 0.0
        w = combat._splash_weight(r_tgt, BREACH_RADIUS_GU, d)
        if w <= 0.0:
            continue
        point, normal = _impact_point(target, centre, host, ship_instances)
        try:
            combat.apply_hit(
                target, magnitude * w, point, source=ship,
                normal=normal, host=host, ship_instances=ship_instances,
                weapon_type="torpedo", splash_radius=BREACH_RADIUS_GU,
            )
        except Exception as _e:
            dev_mode.log_swallowed("warp core breach apply_hit", _e)


def _impact_point(target, centre, host, ship_instances):
    """Return (point, normal) on `target`'s hull, traced from `centre` toward
    the target centre. Falls back to the sphere-facing point (normal None)
    when no host/renderer instance is available (headless / tests)."""
    from engine.appc.math import TGPoint3
    from engine.appc.combat import _resolve_hit_point
    loc = target.GetWorldLocation()
    dx = loc.x - centre.x
    dy = loc.y - centre.y
    dz = loc.z - centre.z
    dist = (dx * dx + dy * dy + dz * dz) ** 0.5
    r_tgt = target.GetRadius() if hasattr(target, "GetRadius") else 0.0
    if dist <= 1e-6:
        # Blast centre coincides with the target centre — hit its centre.
        return TGPoint3(loc.x, loc.y, loc.z), None
    inv = 1.0 / dist
    direction = TGPoint3(dx * inv, dy * inv, dz * inv)
    origin = TGPoint3(centre.x, centre.y, centre.z)
    fallback = TGPoint3(loc.x - direction.x * r_tgt,
                        loc.y - direction.y * r_tgt,
                        loc.z - direction.z * r_tgt)
    return _resolve_hit_point(host, ship_instances, target,
                              origin, direction, dist + r_tgt, fallback)


def _spawn_fireball(ship, core) -> None:
    """One large ExplosionA fireball at the core's body offset. Raise-safe —
    VFX must never block the damage path (mirrors ship_death._spawn_explosion)."""
    try:
        import Effects
        from engine.appc.math import TGPoint3
        radius = ship.GetRadius() if hasattr(ship, "GetRadius") else 1.0
        size = max(radius * BREACH_FIREBALL_FACTOR, 4.0)
        pos = core.GetPosition() if hasattr(core, "GetPosition") else TGPoint3(0, 0, 0)
        action = Effects.CreateExplosionPuffHigh(
            2.0,                                # fLife
            size,                               # fSize
            ship,                               # pEmitFrom — tracks the hull
            TGPoint3(pos.x, pos.y, pos.z),      # kEmitPos — warp core body offset
            TGPoint3(0.0, 0.0, 1.0),            # kEmitDir
            None,                               # pAttachTo
        )
        ctrl = action.GetController() if hasattr(action, "GetController") else None
        if ctrl is not None:
            ctrl.CreateTarget("data/Textures/Effects/ExplosionA.tga")
        if action is not None and hasattr(action, "Play"):
            action.Play()
    except Exception as _e:
        dev_mode.log_swallowed("spawn warp core fireball", _e)


def reset() -> None:
    """Clear the armed queue and breached set (mission swap / test teardown)."""
    _armed.clear()
    _breached.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_warp_core_breach.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/warp_core_breach.py tests/unit/test_warp_core_breach.py
git commit -m "feat(combat): warp-core breach detonation

arm/advance/detonate: weapon-style 1.3 GU AoE from the warp core position,
no allegiance filter, same-tick non-recursive chain drain, single-fire guard.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Zero-crossing hook in `objects.py`

**Files:**
- Modify: `engine/appc/objects.py:368-399` (`DamageSystem`, `DestroySystem`)
- Test: `tests/unit/test_objects_zero_crossing_hook.py` (create)

**Interfaces:**
- Consumes: `warp_core_breach.arm(ship)` (Task 3), `subsystem_cascade.schedule(ship)` (Task 2).
- Produces: a module-level `objects._route_zero_crossing(ship, subsystem, crossed_zero: bool)` that arms the breach when `subsystem is ship.GetPowerSubsystem()`, schedules the cascade when `subsystem is ship.GetHull()`, and no-ops otherwise or when `crossed_zero` is False. Called from both `DamageSystem` and `DestroySystem` on a >0→0 transition.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_objects_zero_crossing_hook.py`:

```python
"""DamageSystem/DestroySystem route warp-core / hull zero-crossings to the
breach + cascade (engine/appc/objects.py)."""
import pytest

from engine.appc.objects import DamageableObject
from engine.appc import warp_core_breach, subsystem_cascade


class _Sub:
    def __init__(self, name, cond=100.0, critical=False):
        self.name = name
        self._c = cond
        self._max = cond
        self._crit = critical
        self._destroyed = False

    def GetCondition(self):    return self._c
    def SetCondition(self, v): self._c = v
    def GetMaxCondition(self): return self._max
    def IsCritical(self):      return 1 if self._crit else 0
    def SetDestroyed(self, v): self._destroyed = bool(v)
    def IsDestroyed(self):     return self._destroyed


class _Ship(DamageableObject):
    def __init__(self, hull, power):
        super().__init__()
        self._hull = hull
        self._power = power

    def GetHull(self):           return self._hull
    def GetPowerSubsystem(self): return self._power
    def IsDying(self):           return 0
    def IsDead(self):            return 0
    def SetDying(self, v):       pass


@pytest.fixture(autouse=True)
def _clean():
    warp_core_breach.reset()
    subsystem_cascade.reset()
    yield
    warp_core_breach.reset()
    subsystem_cascade.reset()


def _spy(monkeypatch):
    armed, scheduled = [], []
    monkeypatch.setattr(warp_core_breach, "arm", lambda s: armed.append(s))
    monkeypatch.setattr(subsystem_cascade, "schedule", lambda s: scheduled.append(s))
    return armed, scheduled


def test_warp_core_to_zero_arms_breach(monkeypatch):
    armed, scheduled = _spy(monkeypatch)
    hull = _Sub("Hull", cond=100.0)
    power = _Sub("WarpCore", cond=50.0, critical=False)
    ship = _Ship(hull, power)
    ship.DamageSystem(power, 50.0)   # 50 -> 0, crosses
    assert ship is armed[0]
    assert scheduled == []


def test_warp_core_already_zero_does_not_rearm(monkeypatch):
    armed, _ = _spy(monkeypatch)
    hull = _Sub("Hull", cond=100.0)
    power = _Sub("WarpCore", cond=0.0)
    ship = _Ship(hull, power)
    ship.DamageSystem(power, 10.0)   # 0 -> 0, no crossing
    assert armed == []


def test_hull_to_zero_schedules_cascade(monkeypatch):
    armed, scheduled = _spy(monkeypatch)
    hull = _Sub("Hull", cond=30.0)
    power = _Sub("WarpCore", cond=100.0)
    ship = _Ship(hull, power)
    ship.DamageSystem(hull, 30.0)    # 30 -> 0, crosses
    assert ship is scheduled[0]
    assert armed == []


def test_non_core_non_hull_subsystem_routes_nothing(monkeypatch):
    armed, scheduled = _spy(monkeypatch)
    hull = _Sub("Hull", cond=100.0)
    power = _Sub("WarpCore", cond=100.0)
    sensors = _Sub("Sensors", cond=40.0)
    ship = _Ship(hull, power)
    ship.DamageSystem(sensors, 40.0)  # sensors -> 0, but neither core nor hull
    assert armed == [] and scheduled == []


def test_destroy_system_on_warp_core_arms_breach(monkeypatch):
    armed, _ = _spy(monkeypatch)
    hull = _Sub("Hull", cond=100.0)
    power = _Sub("WarpCore", cond=100.0)
    ship = _Ship(hull, power)
    ship.DestroySystem(power)         # forced 100 -> 0, crosses
    assert ship is armed[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_objects_zero_crossing_hook.py -v`
Expected: FAIL — `test_warp_core_to_zero_arms_breach` fails (breach not armed) because the hook does not exist yet.

- [ ] **Step 3: Add the routing helper and wire both methods**

In `engine/appc/objects.py`, add this module-level function immediately after `_is_critical` (after line 348):

```python
def _route_zero_crossing(ship, subsystem, crossed_zero: bool) -> None:
    """On a subsystem crossing >0 -> 0, arm the warp-core breach (when the
    subsystem is the ship's PowerSubsystem) or schedule the hull-death cascade
    (when it is the hull). No-op otherwise. Kept separate from the critical ->
    ship_death.begin path, which is unchanged.

    See docs/superpowers/specs/2026-06-20-warp-core-breach-design.md.
    """
    if not crossed_zero:
        return
    power = ship.GetPowerSubsystem() if hasattr(ship, "GetPowerSubsystem") else None
    if power is not None and subsystem is power:
        from engine.appc import warp_core_breach
        warp_core_breach.arm(ship)
        return
    hull = ship.GetHull() if hasattr(ship, "GetHull") else None
    if hull is not None and subsystem is hull:
        from engine.appc import subsystem_cascade
        subsystem_cascade.schedule(ship)
```

Then change `DamageSystem` (lines 368-384) so the body reads:

```python
    def DamageSystem(self, subsystem, amount: float) -> None:
        """Apply damage to a subsystem, flooring condition at zero. If the
        subsystem is critical and reaches zero, start the ship death
        sequence (covers hull AND warp core via SetCritical(1)). A >0 -> 0
        crossing also arms the warp-core breach / schedules the hull cascade."""
        if subsystem is None:
            return
        amt = float(amount)
        if amt <= 0.0:
            return
        cur = subsystem.GetCondition()
        new_cond = max(0.0, cur - amt)
        subsystem.SetCondition(new_cond)
        _route_zero_crossing(self, subsystem, cur > 0.0 and new_cond <= 0.0)
        if new_cond <= 0.0 and _is_critical(subsystem) \
                and hasattr(self, "IsDying") and hasattr(self, "IsDead") \
                and not self.IsDying() and not self.IsDead():
            from engine.appc import ship_death
            ship_death.begin(self)
```

Then change `DestroySystem` (lines 386-399) so the body reads:

```python
    def DestroySystem(self, subsystem) -> None:
        """Force a subsystem to zero condition (mirrors SDK
        pShip.DestroySystem). Ship death is a side effect only when the
        subsystem is critical; DestroySystem(pSensors) just zeroes sensors. A
        >0 -> 0 crossing arms the warp-core breach / schedules the cascade."""
        if subsystem is None:
            return
        cur = subsystem.GetCondition()
        subsystem.SetCondition(0.0)
        if hasattr(subsystem, "SetDestroyed"):
            subsystem.SetDestroyed(True)
        _route_zero_crossing(self, subsystem, cur > 0.0)
        if _is_critical(subsystem) \
                and hasattr(self, "IsDying") and hasattr(self, "IsDead") \
                and not self.IsDying() and not self.IsDead():
            from engine.appc import ship_death
            ship_death.begin(self)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_objects_zero_crossing_hook.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Verify combat + death paths still pass**

Run: `uv run pytest tests/unit/test_apply_hit_splash.py tests/unit/test_ship_death.py tests/unit/test_combat_hit_resolution.py -v`
Expected: all PASS (the new routing is additive; the existing critical→`ship_death.begin` path is untouched).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/objects.py tests/unit/test_objects_zero_crossing_hook.py
git commit -m "feat(combat): route warp-core/hull zero-crossings to breach+cascade

DamageSystem/DestroySystem arm the warp-core breach on a PowerSubsystem >0->0
crossing and schedule the hull-death cascade on a hull crossing. Existing
critical->ship_death path unchanged.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Pump both modules from `host_loop` + end-to-end integration test

**Files:**
- Modify: `engine/host_loop.py:363` (`_advance_combat`) and `engine/host_loop.py:2076` (reset block)
- Test: `tests/unit/test_warp_core_breach_integration.py` (create)

**Interfaces:**
- Consumes: `subsystem_cascade.advance(dt)` / `.reset()` (Task 2), `warp_core_breach.advance(dt, host, ship_instances)` / `.reset()` (Task 3), and the `objects.py` routing (Task 4).
- Produces: nothing new — this is the wiring that makes the feature run in the live loop, plus a capstone test proving Case B (hull death → cascade → breach → neighbour damage) end-to-end through the real modules.

- [ ] **Step 1: Write the failing integration test**

Create `tests/unit/test_warp_core_breach_integration.py`:

```python
"""End-to-end: hull death -> 1.5s cascade -> warp core crosses 0 -> breach
damages a neighbour. Exercises objects.py routing + subsystem_cascade +
warp_core_breach together (Case B), with combat.apply_hit captured."""
import pytest

from engine.appc.objects import DamageableObject
from engine.appc import warp_core_breach, subsystem_cascade
from engine.appc.math import TGMatrix3, TGPoint3


class _Sub:
    def __init__(self, name, cond=100.0, critical=False, pos=None,
                 max_condition=None):
        self.name = name
        self._c = cond
        self._max = max_condition if max_condition is not None else cond
        self._crit = critical
        self._pos = pos or TGPoint3(0.0, 0.0, 0.0)
        self._destroyed = False

    def GetCondition(self):    return self._c
    def SetCondition(self, v): self._c = v
    def GetMaxCondition(self): return self._max
    def IsCritical(self):      return 1 if self._crit else 0
    def GetPosition(self):     return self._pos
    def SetDestroyed(self, v): self._destroyed = bool(v)
    def IsDestroyed(self):     return self._destroyed


class _Ship(DamageableObject):
    def __init__(self, name, loc, hull, power, others, radius=1.0):
        super().__init__()
        self._name = name
        self._loc = loc
        self._radius = radius
        self._hull = hull
        self._power = power
        self._others = list(others)

    def GetName(self):           return self._name
    def GetWorldLocation(self):  return self._loc
    def GetWorldRotation(self):  return TGMatrix3()
    def GetRadius(self):         return self._radius
    def GetHull(self):           return self._hull
    def GetPowerSubsystem(self): return self._power
    def GetSubsystems(self):     return [self._hull, self._power, *self._others]
    def IsDestroyBrokenSystems(self): return 1
    def IsDying(self):           return 0
    def IsDead(self):            return 0
    def SetDying(self, v):       pass


@pytest.fixture(autouse=True)
def _clean():
    warp_core_breach.reset()
    subsystem_cascade.reset()
    yield
    warp_core_breach.reset()
    subsystem_cascade.reset()


def test_hull_death_cascade_breach_damages_neighbour(monkeypatch):
    # Source ship at origin with a 5000-condition warp core; neighbour 0.5 away.
    src = _Ship("A", TGPoint3(0, 0, 0),
                hull=_Sub("Hull", cond=20.0, critical=True),
                power=_Sub("WarpCore", cond=100.0, critical=True,
                           max_condition=5000.0),
                others=[_Sub("Sensors", cond=100.0)])
    nbr = _Ship("B", TGPoint3(0.5, 0, 0),
                hull=_Sub("Hull", cond=9999.0, critical=True),
                power=_Sub("WarpCore", cond=9999.0, critical=True,
                           max_condition=5000.0),
                others=[], radius=0.5)

    import engine.appc.ship_iter as ship_iter
    monkeypatch.setattr(ship_iter, "iter_ships", lambda *a, **k: [src, nbr])

    import engine.appc.combat as combat
    hits = []
    monkeypatch.setattr(combat, "apply_hit",
                        lambda ship, damage, hp, source, **kw: hits.append((ship, damage)))

    # Hull dies -> schedules the cascade (no breach yet).
    src.DamageSystem(src.GetHull(), 20.0)
    subsystem_cascade.advance(subsystem_cascade.CASCADE_DELAY / 2.0)
    warp_core_breach.advance(0.0)
    assert hits == []   # cascade not yet fired

    # Past the 1.5s delay: cascade zeroes the warp core -> arms breach.
    subsystem_cascade.advance(subsystem_cascade.CASCADE_DELAY)
    warp_core_breach.advance(0.0)

    targets = [h[0] for h in hits]
    assert nbr in targets and src not in targets
```

- [ ] **Step 2: Run test to verify it fails or passes for the right reason**

Run: `uv run pytest tests/unit/test_warp_core_breach_integration.py -v`
Expected: PASS. (This test calls the new modules directly, so it validates the cross-module behaviour even before the host_loop wiring. It is the regression guard for Steps 3-4. If it FAILS, fix the modules from Tasks 2-4 before wiring.)

- [ ] **Step 3: Wire the per-tick pump into `_advance_combat`**

In `engine/host_loop.py`, find the `ship_death.advance(dt)` call (line 363) inside `_advance_combat(ships, dt, host=None, ship_instances=None)`. Insert the two new advance calls immediately after it:

```python
    ship_death.advance(dt)
    from engine.appc import subsystem_cascade, warp_core_breach
    subsystem_cascade.advance(dt)
    warp_core_breach.advance(dt, host=host, ship_instances=ship_instances)
```

(Local import mirrors the safe pattern already used in the reset block; `host` and `ship_instances` are the `_advance_combat` parameters, already in scope here.)

- [ ] **Step 4: Wire the reset alongside `ship_death.reset()`**

In `engine/host_loop.py`, find the reset block (lines 2075-2076):

```python
        from engine.appc import ship_death
        ship_death.reset()
```

Insert immediately after it:

```python
        from engine.appc import subsystem_cascade
        subsystem_cascade.reset()
        from engine.appc import warp_core_breach
        warp_core_breach.reset()
```

- [ ] **Step 5: Verify the wiring is present**

Run: `grep -n "subsystem_cascade.advance\|warp_core_breach.advance\|subsystem_cascade.reset\|warp_core_breach.reset" engine/host_loop.py`
Expected: four lines printed — two `.advance(...)` in `_advance_combat`, two `.reset()` in the reset block.

- [ ] **Step 6: Run the integration test + import-sanity for host_loop**

Run: `uv run pytest tests/unit/test_warp_core_breach_integration.py -v && uv run python -c "import engine.host_loop"`
Expected: test PASSES and the import prints nothing (no syntax/import error).

- [ ] **Step 7: Run the full unit suite via the watchdog wrapper**

Run: `scripts/run_tests.sh tests/unit -q`
Expected: PASS with no new failures. (Pre-existing note: the C++ `FrameTest.PhaserHeatGlow` ctest is not part of this pytest run and is a known-unrelated failure — see CLAUDE memory.)

- [ ] **Step 8: Commit**

```bash
git add engine/host_loop.py tests/unit/test_warp_core_breach_integration.py
git commit -m "feat(host): pump warp-core breach + subsystem cascade each tick

_advance_combat advances both after ship_death; reset wired beside
ship_death.reset. Capstone integration test proves hull-death cascade ->
breach -> neighbour damage (Case B).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- Trigger = warp core >0→0, once per ship → Task 4 (`_route_zero_crossing` + `arm` guard), Task 3 (`_breached` set). ✓
- Case A (direct core kill) → Task 4 `DamageSystem`/`DestroySystem` routing. ✓
- Case B (hull → 1.5 s cascade → all subsystems → 0) → Task 2 + Task 4 hull routing; integration in Task 5. ✓
- Chain only when a neighbour's core actually reaches 0 → Task 3 (apply_hit splashes the core; objects hook re-arms) + `test_chain_resolves_same_tick_and_terminates`. ✓
- Immediate detonation at the crossing (same tick) → Task 3 drain loop + Task 5 pump ordering. ✓
- Magnitude scales with `core.GetMaxCondition()` (factor 1.0) → Task 3 `detonate`. ✓
- Radius 1.3 GU, linear falloff via `_splash_weight`, no allegiance filter → Task 3. ✓
- Reuse full weapon path (decals/sparks/audio) via `apply_hit(splash_radius=)` → Task 1 + Task 3. ✓
- `IsDestroyBrokenSystems()` gate → Task 2 `_destroy_broken_systems`. ✓
- `ship_death.py` untouched → confirmed; only `objects.py`, `combat.py`, `host_loop.py` modified. ✓
- Reset wiring on mission swap → Task 5 Step 4. ✓
- Reentrancy/termination → Task 3 non-recursive drain + `_breached` guard; `test_chain_...terminates`. ✓

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". The one feel-tuned constant (`BREACH_FIREBALL_FACTOR`) has a concrete value (2.0) and a comment, matching `ship_death`'s tunable style. ✓

**3. Type consistency:** `arm`/`advance(dt, host, ship_instances)`/`detonate(ship, host, ship_instances)`/`reset` names match across Tasks 3-5. `schedule`/`advance(dt)`/`reset`/`CASCADE_DELAY` match across Tasks 2,4,5. `_route_zero_crossing(ship, subsystem, crossed_zero)` matches its callers in Task 4. `splash_radius` kwarg name matches across Tasks 1 and 3. `_splash_weight(r_sub, r_hit, d)` and `_resolve_hit_point(host, ship_instances, ship, origin, direction, max_dist, fallback)` match the existing `combat.py` signatures read during planning. ✓
