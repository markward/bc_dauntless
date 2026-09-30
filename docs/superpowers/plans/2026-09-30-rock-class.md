# Rock Class Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Asteroids become a lean `RockClass(ShipClass)` that drifts and spins without ship costs, takes rock-looking damage, and breaks up by size instead of dying like a ship, while every mission call on them keeps working.

**Architecture:** A genus-3 ship switches class to `RockClass` when its properties land (`SetupProperties`). The AI, motion and subsystem loops skip rocks via a new iterator, and a rock motion step integrates scripted velocity and spin. Hull death routes to `engine/rocks/death.py`, which fires the SDK events, spawns size-decided pieces (new rocks, tumbling chunks, dust) and emits no splash. The renderer gets a per-instance `surface_is_rock` flag for rock craters, no venting and grey debris, plus a "rock dust" spark kind. Collisions gain a spatial-hash broadphase.

**Tech Stack:** Python 3.11 engine (`engine/`), pytest; C++17 renderer and host bindings (`native/`), gtest with headless GL; the SDK is run through the mission harness.

**Spec:** `docs/superpowers/specs/2026-09-30-rock-class-design.md` (read it before any task).

## Global Constraints

- Branch `feat/rock-class` in worktree `.claude/worktrees/rock-class`, forked from `feat/rock-catalogue`. Never commit to `main`. Never push.
- **Banned git** (shared checkout rule): `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage **explicit paths only**. To mutate a file temporarily, back it up with `cp` and restore with `cp`, then `diff` to prove the restore is identical.
- Never launch the game (`./build/dauntless`). Headless tests only.
- Before claiming any SDK call is or isn't a no-op, check `docs/stub_heatmap.md`. Never decide whether SWIG surface exists by grepping `def <Name>(`.
- Units: GU (1 GU = 175 m). Never name a variable `*_m` / `*_mps` inside the engine. Rotation matrices are column-vector, right-handed. A body-frame delta **post**-multiplies (`R_new = R · Δ_body`), and a world-frame delta **pre**-multiplies (`R_new = Δ_world · R`).
- Never spell `game` or `sdk` as a path segment. Resolve through `engine/paths.py`. Never capture a path at import.
- Rock marker: `GetGenus() == App.GENUS_ASTEROID` (3). `GetGenus()` must keep answering 3 for every rock.
- Threshold dials (Python module constants in `engine/rocks/breakup.py`): `kMajorMinRadiusGU = 1.0`, `kChunkMinRadiusGU = 0.08`, `kVolumeBudget = 0.70`, `kPieceCountMin = 2`, `kPieceCountMax = 5`.
- Rock death: `ET_OBJECT_EXPLODING` fires at once; `ET_OBJECT_DESTROYED` fires `kRockDeathLife = 0.5` s later, or after `GetLifeTime()` if a death script set one below `LIFETIME_UNSET`.
- Size formula: `hull = 2500 × (r / 0.8)²`, `mass = 400 × (r / 0.8)³`, where r is in GU. For a piece: `hull = parent_max × (v_piece / v_parent)^(2/3)` and `mass = parent_mass × v_piece / v_parent`.
- Rocks deal no death splash and receive none.
- Python tests: `.venv/bin/python -m pytest <path> -q`. Full gate: `scripts/check_tests.sh` must exit 0 before the branch is called done. C++ build: `cmake --build build -j` from the worktree root, never from `native/`.
- Every C++ change that adds a host binding needs a rebuild before its pytest can pass. A stale `.so` shows as `AttributeError: module '_dauntless_host' has no attribute X`; rebuild rather than editing Python.
- A new per-instance renderer setter needs every test fake that implements `set_rim_eligible(self, iid, b)` to gain the new method too. Find them with `grep -rln "def set_rim_eligible" tests/`.

## Review Focus

1. **A genus-3 object reached before `SetupProperties`** (for example a precreated or preloaded ship, `MissionLib` `PreloadShip`) is still a plain `ShipClass` until properties land. Nothing may cache "is rock" earlier than that. Task 1 pins the class switch **and** a second `SetupProperties` call staying idempotent.
2. **A rock that dies while it is the player's target, or while a tractor holds it.** Target locks must clear and the tractor must release, exactly as for a ship. Task 4 pins `_clear_target_locks` being called for a dying rock.
3. **A rock removed by a mission (`DeleteObjectFromSet`) or a mission swap during its 0.5 s death window** must not fire `ET_OBJECT_DESTROYED` on a dead object, and must not leak pending pieces. Task 4 pins `death.reset()` clearing pending rocks, and `advance` skipping rocks no longer in a set.
4. **Catalogue rocks toggled off** (Developer Options → Catalogue Rocks) must still give script-less rocks (pieces, Multi1) a model and a family. Task 3 pins the silicate fallback, and that a model path exists with the toggle off.
5. **A static rock (`SetStatic(1)`, used by E2M1 and Multi1) hit by a collision or a tractor.** The motion step must never move it; collisions already treat it as immovable. Task 2 pins a static rock with a non-zero velocity staying put.

---

## File Structure

| File | Responsibility |
|---|---|
| `engine/rocks/rock.py` (new) | `RockClass`, `is_rock`, `maybe_become_rock`, `RockClass_Create`, `DamageableObject_Create`, `rock_model_override` |
| `engine/rocks/stats.py` (new) | size and piece hull/mass formulas |
| `engine/rocks/motion.py` (new) | drift and spin step for rocks |
| `engine/rocks/breakup.py` (new) | deterministic piece plan from a parent rock (pure) |
| `engine/rocks/death.py` (new) | rock death: events, pieces, chunk spec queue, reset |
| `engine/rocks/chunks.py` (new) | host side: turn chunk specs into rendered tumbling bodies |
| `engine/rocks/vfx.py` (new) | crack flash and dust burst at rock death |
| `engine/appc/ship_iter.py` | add `iter_non_rock_ships`, `iter_rocks` |
| `engine/appc/ships.py` | `SetupProperties` calls `maybe_become_rock` |
| `engine/appc/objects.py` | `DamageSystem` / `DestroySystem` route a rock to `rocks.death.begin` |
| `engine/core/loop.py`, `engine/appc/ai_driver.py`, `engine/appc/ship_motion.py` | skip rocks; loop calls rock motion and death advance |
| `engine/appc/splash_damage.py` | rocks excluded both ways |
| `engine/appc/collisions.py` | spatial-hash broadphase |
| `engine/appc/debris_chunk.py` | `spawn_body` factory for a free-standing chunk |
| `engine/appc/hull_hit_smoke.py`, `engine/appc/hit_feedback.py` | skip smoke on rocks; rock dust spark kind |
| `engine/host_loop.py` | rock model override at both realise sites; `surface_is_rock`; drain rock chunks; reset on swap |
| `engine/renderer.py` | `set_surface_rock` wrapper |
| `App.py` | export `DamageableObject_Create` |
| `native/src/scenegraph/...instance.h`, `world.{h,cc}` | `surface_is_rock` field and setter |
| `native/src/host/host_bindings.cc` | `set_surface_rock` binding; pass the flag to venting/debris; copy it on hull split |
| `native/src/renderer/breach_venting.{h,cc}`, `breach_debris.{h,cc}` | rock: no venting; grey-brown debris |
| `native/src/renderer/breach_pass.{h,cc}`, `shaders/breach.frag` | rock crater interior from the base texture |
| `native/src/renderer/hit_vfx_pass.cc` | spark kind 2 (rock dust); world-anchored when the instance is gone |
| `tests/conftest.py` | reset rock death and chunk state per test |

---

### Task 1: `RockClass` and loop exclusion

**Files:**
- Create: `engine/rocks/rock.py`
- Modify: `engine/appc/ships.py` (end of `SetupProperties`, ~line 1184-1300)
- Modify: `engine/appc/ship_iter.py` (add two iterators after `iter_ships`, ~line 83)
- Modify: `engine/core/loop.py:90-118` (`_update_ship_subsystems`)
- Modify: `engine/appc/ai_driver.py:1660-1693` (`tick_all_ai`)
- Modify: `engine/appc/ship_motion.py:135-138` (`tick_all_ship_motion`)
- Test: `tests/unit/test_rock_class.py`

**Interfaces:**
- Produces: `engine.rocks.rock.RockClass(ShipClass)`; `is_rock(obj) -> bool`; `maybe_become_rock(ship) -> bool`; `RockClass._become_rock() -> None`; the attributes `_model_override: tuple[str, float] | None` (default None), `_rock_family: str` (default `"silicate"`), `_angular_space: int` (default `PhysicsObjectClass.DIRECTION_WORLD_SPACE`) and `_rock_generation: int` (default 0); `engine.appc.ship_iter.iter_non_rock_ships()` and `iter_rocks()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_rock_class.py
import App
from engine.appc.ships import ShipClass_Create
from engine.appc.properties import ShipProperty, HullProperty


def _make(genus):
    ship = ShipClass_Create("Test")
    ps = ship.GetPropertySet()
    sp = ShipProperty("Mass")
    sp.SetGenus(genus)
    sp.SetMass(400.0)
    ps.AddToSet("Scene Root", sp)
    hp = HullProperty("Hull")
    hp.SetMaxCondition(2500.0)
    hp.SetCritical(1)
    hp.SetPrimary(1)
    hp.SetRadius(0.8)
    ps.AddToSet("Scene Root", hp)
    ship.SetupProperties()
    return ship


def test_genus_asteroid_becomes_rock():
    from engine.rocks.rock import RockClass, is_rock
    rock = _make(App.GENUS_ASTEROID)
    assert isinstance(rock, RockClass)
    assert is_rock(rock)
    assert rock.GetGenus() == App.GENUS_ASTEROID


def test_other_genus_stays_ship():
    from engine.rocks.rock import is_rock
    ship = _make(App.GENUS_SHIP)
    assert not is_rock(ship)


def test_setup_properties_twice_is_idempotent():
    from engine.rocks.rock import RockClass
    rock = _make(App.GENUS_ASTEROID)
    rock._rock_family = "icy"
    rock.SetupProperties()
    assert type(rock) is RockClass
    assert rock._rock_family == "icy"      # _become_rock must not reset state


def test_rock_passes_sdk_casts():
    rock = _make(App.GENUS_ASTEROID)
    assert App.ShipClass_Cast(rock) is rock
    assert App.DamageableObject_Cast(rock) is rock
    assert App.ObjectClass_Cast(rock) is rock


def test_rock_keeps_authored_hull_and_mass():
    rock = _make(App.GENUS_ASTEROID)
    assert rock.GetHull().GetMaxCondition() == 2500.0
    assert rock.GetMass() == 400.0


def test_rock_shields_do_not_block():
    from engine.appc.combat import shields_block
    rock = _make(App.GENUS_ASTEROID)
    assert shields_block(rock) is False


def test_set_ai_on_rock_is_inert():
    rock = _make(App.GENUS_ASTEROID)
    rock.SetAI(object())
    assert rock.GetAI() is None


def test_loops_skip_rocks(monkeypatch):
    from engine.appc import ship_iter
    rock = _make(App.GENUS_ASTEROID)
    ship = _make(App.GENUS_SHIP)
    monkeypatch.setattr(ship_iter, "iter_ships", lambda **kw: iter([rock, ship]))
    assert list(ship_iter.iter_non_rock_ships()) == [ship]
    assert list(ship_iter.iter_rocks()) == [rock]
```

`ShipProperty` / `HullProperty` constructor and `AddToSet` names: confirm them against `engine/appc/properties.py` and adjust the helper only. Also confirm that `App.GENUS_SHIP` exists in `engine/appc/constants_generated.py`; if it doesn't, use `App.GENUS_ASTEROID + 1`.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_rock_class.py -q`
Expected: FAIL, `ModuleNotFoundError: engine.rocks.rock`.

- [ ] **Step 3: Implement `engine/rocks/rock.py`**

```python
"""RockClass: a BC asteroid as a lean body, not a ship.

Spec: docs/superpowers/specs/2026-09-30-rock-class-design.md.

A RockClass IS a ShipClass (missions ShipClass_Cast rocks: E1M2.py:1257/1314,
E2M1.py:649/1079), but the AI, motion and subsystem loops skip it
(ship_iter.iter_non_rock_ships). A ship becomes a rock when its properties
land with genus GENUS_ASTEROID -- ShipClass_Create only ever sees a name.
"""
import engine.dev_mode as dev_mode
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ships import ShipClass


class RockClass(ShipClass):
    """No __slots__, no __init__: instances are made by reassigning the
    __class__ of a live ShipClass, so the layout must stay identical."""

    def _become_rock(self) -> None:
        d = self.__dict__
        d.setdefault("_model_override", None)
        d.setdefault("_rock_family", "silicate")
        d.setdefault("_angular_space", PhysicsObjectClass.DIRECTION_WORLD_SPACE)
        d.setdefault("_rock_generation", 0)
        self._ai = None

    def SetAI(self, ai, *_extra) -> None:
        if ai is not None:
            dev_mode.log_swallowed(
                "SetAI on a rock ignored",
                RuntimeError(str(self.GetName())))

    def ClearAI(self, *_extra) -> None:
        self._ai = None


def is_rock(obj) -> bool:
    return isinstance(obj, RockClass)


def maybe_become_rock(ship) -> bool:
    """Switch `ship` to RockClass if its genus says asteroid. Idempotent."""
    import App
    if isinstance(ship, RockClass):
        ship._become_rock()
        return True
    if type(ship) is not ShipClass:
        return False          # a ShipClass subclass we don't own: leave it
    try:
        genus = int(ship.GetGenus())
    except Exception:
        return False
    if genus != App.GENUS_ASTEROID:
        return False
    ship.__class__ = RockClass
    ship._become_rock()
    return True
```

Check how `ClearAI` is defined in `engine/appc/ships.py:162-175`. If it takes different arguments, mirror its signature.

- [ ] **Step 4: Hook `SetupProperties`**

At the very end of `ShipClass.SetupProperties` (after the property loop and anything that follows it), add:

```python
        from engine.rocks.rock import maybe_become_rock
        maybe_become_rock(self)
```

- [ ] **Step 5: Add the iterators to `engine/appc/ship_iter.py`**

```python
def iter_non_rock_ships(*, verbose: bool = False) -> Iterable:
    """iter_ships() minus rocks: the roster for the AI, motion and subsystem
    loops, which a rock never pays for (rock-class spec §1)."""
    from engine.rocks.rock import RockClass
    for ship in iter_ships(verbose=verbose):
        if not isinstance(ship, RockClass):
            yield ship


def iter_rocks() -> Iterable:
    from engine.rocks.rock import RockClass
    for ship in iter_ships():
        if isinstance(ship, RockClass):
            yield ship
```

- [ ] **Step 6: Switch the three loops**

- `engine/core/loop.py` `_update_ship_subsystems`: `for ship in iter_ships():` becomes `for ship in iter_non_rock_ships():`, and the import is updated.
- `engine/appc/ai_driver.py` `tick_all_ai`: `from engine.appc.ship_iter import iter_ships` becomes `iter_non_rock_ships`, and the loop uses it.
- `engine/appc/ship_motion.py` `tick_all_ship_motion`: the same swap.

Leave every other `iter_ships` caller alone (splash damage is handled in Task 4).

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/unit/test_rock_class.py -q`
Expected: PASS.
Run: `.venv/bin/python -m pytest tests/unit tests/integration/test_e1m2_asteroid_crash.py -q -x`
Expected: PASS. If an existing test asserts `type(asteroid) is ShipClass`, update it to `isinstance(..., ShipClass)`, and say so in the report.

- [ ] **Step 8: Commit**

```bash
git add engine/rocks/rock.py engine/appc/ships.py engine/appc/ship_iter.py engine/core/loop.py engine/appc/ai_driver.py engine/appc/ship_motion.py tests/unit/test_rock_class.py
git commit -m "feat(rocks): genus-3 ships become RockClass; AI, motion and subsystem loops skip rocks"
```

---

### Task 2: Rock motion step (scripted drift and spin)

`SetVelocity` / `SetAngularVelocity` only store values today, and nothing integrates them for an object with no setpoint. A headless probe on 2026-09-30 showed E1M2's five moving asteroids at 5-6.6 GU/s moving **0 GU** over 120 ticks.

**Files:**
- Create: `engine/rocks/motion.py`
- Modify: `engine/rocks/rock.py` (override `SetAngularVelocity`)
- Modify: `engine/core/loop.py` (call `rocks.motion.tick_all(TICK_DELTA)` right after `tick_all_ship_motion`, inside its own `_prof.scope("gl.rock_motion")`)
- Test: `tests/unit/test_rock_motion.py`, `tests/integration/test_e1m2_rocks.py`

**Interfaces:**
- Consumes: `RockClass`, `iter_rocks()` (Task 1).
- Produces: `engine.rocks.motion.tick_all(dt: float) -> None`; `engine.rocks.motion.step(rock, dt: float) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_rock_motion.py
import math
import App
from engine.appc.math import TGPoint3
from engine.appc.objects import PhysicsObjectClass
from tests.unit.test_rock_class import _make


def test_rock_drifts_by_velocity():
    from engine.rocks import motion
    rock = _make(App.GENUS_ASTEROID)
    rock.SetTranslateXYZ(0.0, 0.0, 0.0)
    rock.SetVelocity(TGPoint3(5.0, 0.0, 0.0))
    for _ in range(60):
        motion.step(rock, 1.0 / 60.0)
    assert abs(rock.GetTranslate().x - 5.0) < 1e-6


def test_static_rock_never_moves():
    from engine.rocks import motion
    rock = _make(App.GENUS_ASTEROID)
    rock.SetStatic(1)
    rock.SetVelocity(TGPoint3(5.0, 0.0, 0.0))
    motion.step(rock, 1.0)
    assert rock.GetTranslate().x == 0.0


def test_model_space_spin_is_about_body_axis():
    from engine.rocks import motion
    rock = _make(App.GENUS_ASTEROID)
    # Pitch the rock 90 deg about world X, so body-Z points along world -Y.
    R = App.TGMatrix3(); R.MakeRotation(math.pi / 2, TGPoint3(1, 0, 0))
    rock.SetMatrixRotation(R)
    rock.SetAngularVelocity(TGPoint3(0.0, 0.0, 1.0),
                            PhysicsObjectClass.DIRECTION_MODEL_SPACE)
    motion.step(rock, 0.5)
    # Spinning about BODY Z leaves body Z (the column) unchanged.
    z = rock.GetWorldRotation().GetCol(2)
    assert abs(z.y - R.GetCol(2).y) < 1e-6
    assert abs(z.z - R.GetCol(2).z) < 1e-6


def test_world_space_spin_is_about_world_axis():
    from engine.rocks import motion
    rock = _make(App.GENUS_ASTEROID)
    R = App.TGMatrix3(); R.MakeRotation(math.pi / 2, TGPoint3(1, 0, 0))
    rock.SetMatrixRotation(R)
    rock.SetAngularVelocity(TGPoint3(0.0, 0.0, 1.0))   # default world space
    motion.step(rock, 0.5)
    # Spinning about WORLD Z moves body-Y (which pointed along world +Z) nowhere.
    y = rock.GetWorldRotation().GetCol(1)
    assert abs(y.z - R.GetCol(1).z) < 1e-6
```

```python
# tests/integration/test_e1m2_rocks.py
import App
from engine import host_loop
from engine.core.loop import GameLoop
from tests.integration.test_sdk_bridge_load import _fresh_world

E1M2_MODULE = "Maelstrom.Episode1.E1M2.E1M2"


def _init_e1m2():
    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(E1M2_MODULE)
    return mod


def test_moving_asteroids_are_rocks_and_actually_move():
    from engine.rocks.rock import is_rock
    mod = _init_e1m2()
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    mod.CreateMovingAsteroids()
    names = sorted(mod.g_dAsteroidInfo.keys())
    rocks = [App.ShipClass_GetObject(pSet, n) for n in names]
    assert all(r is not None and is_rock(r) for r in rocks)
    start = [r.GetWorldLocation() for r in rocks]
    speeds = [r.GetVelocityTG().Length() for r in rocks]
    GameLoop().advance(120)            # 2 s of game time
    for r, p0, v in zip(rocks, start, speeds):
        p1 = r.GetWorldLocation()
        moved = ((p1.x - p0.x) ** 2 + (p1.y - p0.y) ** 2 + (p1.z - p0.z) ** 2) ** 0.5
        assert abs(moved - 2.0 * v) < 0.05 * v + 1e-3
```

`App.TGMatrix3`: confirm the name the shim exports (it may be `TGMatrix3` from `engine.appc.math`); use whichever `App` exposes.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_rock_motion.py tests/integration/test_e1m2_rocks.py -q`
Expected: FAIL (`engine.rocks.motion` missing; the E1M2 rocks don't move).

- [ ] **Step 3: Store the spin space on rocks** (`engine/rocks/rock.py`, inside `RockClass`)

```python
    def SetAngularVelocity(self, v, space=PhysicsObjectClass.DIRECTION_WORLD_SPACE) -> None:
        super().SetAngularVelocity(v, space)
        self._angular_space = int(space)
```

- [ ] **Step 4: Implement `engine/rocks/motion.py`**

```python
"""Drift and spin for rocks: the only motion a rock has.

Ships move through ship_motion's setpoint integrator, which a rock skips
(it has no AI and no engines). Missions give rocks motion with SetVelocity /
SetAngularVelocity (E1M2 CreateMovingAsteroids), which the shim only STORES,
so without this step a scripted rock never moves.

Spin honours the space it was set in: DIRECTION_MODEL_SPACE is a body-frame
axis (post-multiply, R.D), world space a world axis (pre-multiply, D.R).
"""
from engine.appc.math import TGMatrix3, TGPoint3
from engine.appc.objects import PhysicsObjectClass


def step(rock, dt: float) -> None:
    if rock.IsImmobile():
        return
    v = rock._velocity
    if v.x or v.y or v.z:
        p = rock.GetTranslate()
        rock.SetTranslateXYZ(p.x + v.x * dt, p.y + v.y * dt, p.z + v.z * dt)
    w = rock._angular_velocity
    if w.x or w.y or w.z:
        rate = (w.x * w.x + w.y * w.y + w.z * w.z) ** 0.5
        axis = TGPoint3(w.x / rate, w.y / rate, w.z / rate)
        D = TGMatrix3()
        D.MakeRotation(rate * dt, axis)
        R = rock.GetWorldRotation()
        if rock.__dict__.get("_angular_space") == PhysicsObjectClass.DIRECTION_MODEL_SPACE:
            R = R.MultMatrix(D)
        else:
            R = D.MultMatrix(R)
        rock.SetMatrixRotation(R)


def tick_all(dt: float) -> None:
    from engine.appc.ship_iter import iter_rocks
    for rock in iter_rocks():
        step(rock, dt)
```

- [ ] **Step 5: Call it from `GameLoop.tick`** (`engine/core/loop.py`, right after the `gl.motion` scope)

```python
        from engine.rocks import motion as rock_motion
        with _prof.scope("gl.rock_motion"):
            rock_motion.tick_all(TICK_DELTA)
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/unit/test_rock_motion.py tests/integration/test_e1m2_rocks.py tests/integration -q -k "e1m2 or rock"`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add engine/rocks/motion.py engine/rocks/rock.py engine/core/loop.py tests/unit/test_rock_motion.py tests/integration/test_e1m2_rocks.py
git commit -m "feat(rocks): rocks drift and spin from their scripted velocity (E1M2's moving asteroids now move)"
```

---

### Task 3: Script-less rocks (`RockClass_Create`, `DamageableObject_Create`) and their models

**Files:**
- Create: `engine/rocks/stats.py`
- Modify: `engine/rocks/rock.py` (add `RockClass_Create`, `DamageableObject_Create`, `rock_model_override`)
- Modify: `App.py` (export `DamageableObject_Create` from `engine.rocks.rock`; place it beside the `engine.appc.objects` import block at ~line 115)
- Modify: `engine/host_loop.py`, the two realise sites (~5995 in `realize_set_objects`, ~7076 in `_MissionLoader._realize_session`)
- Test: `tests/unit/test_rock_stats.py`, `tests/unit/test_rock_create.py`, `tests/integration/test_multi1_rocks.py`

**Interfaces:**
- Consumes: `RockClass`, `maybe_become_rock` (Task 1); `engine.rocks.catalogue.pick(key, kind, family) -> Rock | None`, `catalogue_root() -> Path`, `Rock.lod_paths`, `Rock.family`, `Rock.bound_radius_m` (sub-project 1).
- Produces:
  - `engine.rocks.stats.size_hull(r_gu) -> float`, `size_mass(r_gu) -> float`, `piece_hull(parent_max, v_ratio) -> float`, `piece_mass(parent_mass, v_ratio) -> float`
  - `engine.rocks.rock.RockClass_Create(radius_gu: float, *, family: str = "silicate", seed: str = "", name: str = "", kind: str = "fragment", hull: float | None = None, mass: float | None = None) -> RockClass`
  - `engine.rocks.rock.DamageableObject_Create(model_name: str)` returns a `RockClass`, or a plain `DamageableObject` when the model isn't a stock asteroid
  - `engine.rocks.rock.rock_model_override(ship) -> tuple[str, float] | None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_rock_stats.py
from engine.rocks import stats


def test_size_formula_calibrated_on_stock_asteroid():
    assert stats.size_hull(0.8) == 2500.0
    assert stats.size_mass(0.8) == 400.0
    assert abs(stats.size_hull(1.6) - 10000.0) < 1e-9
    assert abs(stats.size_mass(1.6) - 3200.0) < 1e-9


def test_piece_scaling():
    assert abs(stats.piece_hull(2500.0, 0.125) - 625.0) < 1e-9   # 0.125^(2/3) = 0.25
    assert stats.piece_mass(400.0, 0.125) == 50.0
```

```python
# tests/unit/test_rock_create.py
import App
from engine.appc.combat import shields_block


def test_rock_class_create_derives_stats_from_size():
    from engine.rocks.rock import RockClass_Create, is_rock
    r = RockClass_Create(1.6, family="icy", seed="x", name="Asteroid 9-1")
    assert is_rock(r)
    assert r.GetName() == "Asteroid 9-1"
    assert r.GetGenus() == App.GENUS_ASTEROID
    assert r.GetRadius() == 1.6
    assert abs(r.GetHull().GetMaxCondition() - 10000.0) < 1e-6
    assert r.GetHull().GetCondition() == r.GetHull().GetMaxCondition()
    assert r.GetHull().IsCritical()
    assert abs(r.GetMass() - 3200.0) < 1e-6
    assert shields_block(r) is False
    assert r._rock_family == "icy"


def test_rock_class_create_explicit_hull_and_mass_win():
    from engine.rocks.rock import RockClass_Create
    r = RockClass_Create(1.6, hull=123.0, mass=7.0, name="p")
    assert r.GetHull().GetMaxCondition() == 123.0
    assert r.GetMass() == 7.0


def test_rock_model_override_is_a_catalogue_fragment():
    from engine.rocks.rock import RockClass_Create, rock_model_override
    r = RockClass_Create(1.2, family="silicate", seed="abc", name="p")
    path, scale = rock_model_override(r)
    assert "/fragments/silicate_" in path.replace("\\", "/")
    assert path.endswith("lod0.gltf")
    assert scale == 1.0


def test_model_override_survives_catalogue_toggle_off():
    from engine.rocks import catalogue
    from engine.rocks.rock import RockClass_Create, rock_model_override
    catalogue.set_enabled(False)
    r = RockClass_Create(1.2, seed="abc", name="p")
    assert rock_model_override(r) is not None


def test_same_seed_same_model():
    from engine.rocks.rock import RockClass_Create, rock_model_override
    a = RockClass_Create(1.2, seed="Asteroid 5-1", name="a")
    b = RockClass_Create(1.2, seed="Asteroid 5-1", name="b")
    assert rock_model_override(a) == rock_model_override(b)


def test_damageable_object_create_asteroid_is_a_rock():
    import ships.Asteroid
    ships.Asteroid.LoadModel()
    obj = App.DamageableObject_Create("Asteroid")
    from engine.rocks.rock import is_rock, rock_model_override
    assert is_rock(obj)
    obj.SetMass(400.0)
    obj.SetScale(4.0)
    assert obj.GetMass() == 400.0
    assert rock_model_override(obj) is not None
```

```python
# tests/integration/test_multi1_rocks.py
import App
from tests.integration.test_sdk_bridge_load import _fresh_world


def test_multi1_places_54_distinct_rocks():
    from engine.rocks.rock import is_rock
    _fresh_world()
    import Systems.Multi1.Multi1 as m1
    m1.Initialize()
    pSet = m1.GetSet()
    rocks = [pSet.GetObject("Asteroid %d" % i) for i in range(1, 55)]
    assert all(r is not None and is_rock(r) for r in rocks)
    pts = {(round(r.GetWorldLocation().x, 3), round(r.GetWorldLocation().y, 3),
            round(r.GetWorldLocation().z, 3)) for r in rocks}
    assert len(pts) == 54
```

Multi1 also calls `App.g_kUtopiaModule.SetIgnoreClientIDForObjectCreation(1)` and `pAsteroid.RandomOrientation()`, and neither exists in the shim (both are absent from `docs/stub_heatmap.md` because they are App-module and instance stubs that return `_NamedStub`). Run the test first and see whether they already degrade harmlessly through the stub path. If `RandomOrientation` is a stub, implement it on `ObjectClass` in `engine/appc/objects.py` as a uniform random rotation drawn from `App.g_kSystemWrapper.GetRandomNumber`, so Multi1's seeded field stays deterministic, and add a unit test. Implement `SetIgnoreClientIDForObjectCreation` as a stored no-op on the utopia module. Report what you found.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_rock_stats.py tests/unit/test_rock_create.py tests/integration/test_multi1_rocks.py -q`
Expected: FAIL (modules and functions missing).

- [ ] **Step 3: Implement `engine/rocks/stats.py`**

```python
"""Hull and mass for rocks that have no hardpoint file (rock-class spec §1).

Calibrated on stock BC `Asteroid` (hardpoints/asteroid.py): radius 0.8 GU,
MaxCondition 2500, mass 400. Hull scales with surface (r^2), mass with volume
(r^3). A broken-off piece inherits from its parent instead, so a mission's
authored HP (E1M2 sets it per moving rock) carries down to the pieces.
"""
REF_RADIUS_GU = 0.8
REF_HULL = 2500.0
REF_MASS = 400.0


def size_hull(r_gu: float) -> float:
    return REF_HULL * (float(r_gu) / REF_RADIUS_GU) ** 2


def size_mass(r_gu: float) -> float:
    return REF_MASS * (float(r_gu) / REF_RADIUS_GU) ** 3


def piece_hull(parent_max: float, v_ratio: float) -> float:
    return float(parent_max) * float(v_ratio) ** (2.0 / 3.0)


def piece_mass(parent_mass: float, v_ratio: float) -> float:
    return float(parent_mass) * float(v_ratio)
```

- [ ] **Step 4: Implement the constructors in `engine/rocks/rock.py`**

```python
_STOCK_ASTEROID_NIFS = (
    "asteroid.nif", "asteroid1.nif", "asteroid2.nif", "asteroid3.nif")


def _catalogue_model(seed: str, kind: str, family: str):
    """(abs path to lod0, family actually used) for a catalogue rock. Works
    with the catalogue toggle off: that toggle only governs redirecting
    stock NIFs; a script-less rock has no stock mesh to fall back to."""
    from engine.rocks import catalogue
    rock = catalogue.pick(seed, kind=kind, family=family)
    if rock is None:
        rock = catalogue.pick(seed, kind=kind, family="silicate")
        family = "silicate"
    if rock is None:
        return None, family
    return str(catalogue.catalogue_root() / rock.lod_paths[0]), family


def _install_hull(ship, max_hp: float, radius_gu: float) -> None:
    from engine.appc.subsystems import HullSubsystem
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(float(max_hp))
    hull.SetCondition(float(max_hp))
    hull.SetCritical(1)
    hull.SetTargetable(1)
    hull.SetPrimary(1)
    hull.SetRadius(float(radius_gu))
    ship._hull = hull


def RockClass_Create(radius_gu, *, family="silicate", seed="", name="",
                     kind="fragment", hull=None, mass=None):
    import App
    from engine.appc.ships import ShipClass_Create
    from engine.rocks import stats
    ship = ShipClass_Create(name)
    ship.__class__ = RockClass
    ship._become_rock()
    ship.SetGenus(App.GENUS_ASTEROID)
    ship.SetSpecies(App.SPECIES_ASTEROID)
    ship.SetRadius(float(radius_gu))
    _install_hull(ship, stats.size_hull(radius_gu) if hull is None else hull,
                  radius_gu)
    ship.SetMass(stats.size_mass(radius_gu) if mass is None else float(mass))
    path, fam = _catalogue_model(seed or name, kind, family)
    ship._rock_family = fam
    ship._model_override = (path, 1.0) if path else None
    return ship


def DamageableObject_Create(model_name):
    """BC's lightweight rock constructor (Multi1.py:103, Multi6_S.py). A model
    name that resolves to a stock asteroid LOD becomes a RockClass sized from
    that NIF; anything else is a plain DamageableObject (out of scope beyond
    not crashing)."""
    import App
    from engine.appc.objects import DamageableObject
    lod = App.g_kLODModelManager.Get(str(model_name))
    filename = lod.lods[0].filename if (lod is not None and lod.lods) else ""
    base = filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if base not in _STOCK_ASTEROID_NIFS:
        return DamageableObject()
    radius = _stock_radius_gu(base)
    rock = RockClass_Create(radius, seed=str(model_name), name=str(model_name),
                            kind="major")
    rock._stock_nif_rel = filename
    return rock
```

`_stock_radius_gu(base)` returns the stock hardpoint radius for that mesh, read straight from the SDK hardpoint values in the spec's evidence: `asteroid.nif` → 0.8, `asteroid1.nif` → 0.24, `asteroid2.nif` → 0.744, `asteroid3.nif` → 5.0. Write it as a small dict. The rock's `GetRadius()` then scales with `SetScale` through the existing scale path. Check whether `ObjectClass.GetRadius` multiplies by `GetScale()` today (`engine/appc/objects.py:203`). If it doesn't, say so in the report and do **not** change it in this task: Multi1's `IsLocationEmptyTG(kPos, pAsteroid.GetRadius(), 1)` then uses the unscaled radius, which matches today's ship behaviour.

`rock_model_override(ship)`:

```python
def rock_model_override(ship):
    """(model path, load scale) for a rock with no ship script, else None.
    A DamageableObject_Create rock routes its stock NIF through the catalogue
    redirect like any stock asteroid; a RockClass_Create piece uses its own
    catalogue fragment."""
    if not is_rock(ship):
        return None
    rel = ship.__dict__.get("_stock_nif_rel")
    if rel:
        from engine import paths
        from engine.rocks import catalogue
        return catalogue.ship_model_source(ship.GetName(), str(paths.game_asset(rel)))
    return ship.__dict__.get("_model_override")
```

With the catalogue toggle off, `ship_model_source` returns the stock NIF, which is correct for `DamageableObject_Create` rocks. Pieces always use their fragment, and `test_model_override_survives_catalogue_toggle_off` pins that.

- [ ] **Step 5: Export `DamageableObject_Create` from `App.py`**

Add `from engine.rocks.rock import DamageableObject_Create` next to the `engine.appc.objects` import block. It must be a real attribute, so the module `__getattr__` stub path is no longer taken.

- [ ] **Step 6: Realise script-less rocks in `engine/host_loop.py`**

At both realise sites, the ship loop currently does:

```python
        nif_path = _ship_nif_path(ship, verbose=verbose)
        if nif_path is None:
            continue
        model_path, model_scale = _ship_model_source(ship, nif_path)
```

Change it to:

```python
        _override = _rock_model_override(ship)
        if _override is not None:
            model_path, model_scale = _override
            nif_path = model_path
        else:
            nif_path = _ship_nif_path(ship, verbose=verbose)
            if nif_path is None:
                continue
            model_path, model_scale = _ship_model_source(ship, nif_path)
```

`_rock_model_override` is a module-level helper next to `_ship_model_source`:

```python
def _rock_model_override(ship):
    from engine.rocks.rock import rock_model_override
    try:
        return rock_model_override(ship)
    except Exception as e:
        dev_mode.log_swallowed("rock model override", e)
        return None
```

Then read every later use of `nif_path` inside both loops (texture search dir, hull pieces, decals, `declared_model_dir`). For each one, confirm it tolerates a `.gltf` path or a ship with no script, and guard any that doesn't with `if _override is None`. List each use and your decision in the report. Check the load-time natural scale (`host_loop.py` ~5656-5676, `GetRadius()` / model extent) so that a fragment loaded at scale 1.0 renders at the rock's `GetRadius()`, and pin that with the existing fake-renderer realise test pattern (`tests/unit/test_realize_set.py`): a `RockClass_Create(1.5, …)` rock added to a set gets `create_instance` called with the fragment path.

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/unit/test_rock_stats.py tests/unit/test_rock_create.py tests/integration/test_multi1_rocks.py tests/unit/test_realize_set.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add engine/rocks/stats.py engine/rocks/rock.py App.py engine/host_loop.py tests/unit/test_rock_stats.py tests/unit/test_rock_create.py tests/integration/test_multi1_rocks.py tests/unit/test_realize_set.py
git commit -m "feat(rocks): script-less rocks (RockClass_Create, DamageableObject_Create) with catalogue models; Multi1's 54 rocks exist"
```

Add `engine/appc/objects.py` and its test to the commit if you implemented `RandomOrientation`.

---

### Task 4: Rock death and breakup (simulation side)

**Files:**
- Create: `engine/rocks/breakup.py`, `engine/rocks/death.py`
- Modify: `engine/appc/objects.py:1015-1053` (`DamageSystem`, `DestroySystem`)
- Modify: `engine/appc/splash_damage.py:34-80`
- Modify: `engine/core/loop.py` (call `rocks.death.advance(TICK_DELTA)` after rock motion)
- Modify: `tests/conftest.py` (`_reset_leakable_engine_globals`: call `engine.rocks.death.reset()`)
- Modify: `engine/host_loop.py` (mission teardown ~6776, beside `ship_death.reset()`: call `rocks.death.reset()`)
- Test: `tests/unit/test_rock_breakup.py`, `tests/unit/test_rock_death.py`

**Interfaces:**
- Consumes: `RockClass`, `is_rock`, `RockClass_Create`, `stats.piece_hull`, `stats.piece_mass` (Tasks 1 and 3).
- Produces:
  - `engine.rocks.breakup.PieceSpec`, a frozen dataclass: `radius_gu: float`, `offset: tuple[float, float, float]` (unit direction, parent body frame), `v_ratio: float`, `tier: str` (one of `"major"`, `"chunk"`, `"dust"`)
  - `engine.rocks.breakup.plan(parent_name: str, parent_radius_gu: float) -> list[PieceSpec]`
  - `engine.rocks.death.begin(rock, killer=None) -> None`, `advance(dt: float) -> None`, `reset() -> None`, `is_dying_rock(rock) -> bool`
  - `engine.rocks.death.drain_chunk_specs() -> list[ChunkSpec]`, where `ChunkSpec` is a frozen dataclass with fields `family: str`, `seed: str`, `radius_gu: float`, `mass: float`, `loc: tuple`, `vel: tuple`, `angular: tuple` and `pSet` (the set the parent was in)
  - `engine.rocks.death.drain_death_vfx() -> list[DeathVfxSpec]`, where `DeathVfxSpec` has fields `loc: tuple`, `radius_gu: float` and `pSet`
  - `engine.rocks.breakup` dials: `kMajorMinRadiusGU = 1.0`, `kChunkMinRadiusGU = 0.08`, `kVolumeBudget = 0.70`, `kPieceCountMin = 2`, `kPieceCountMax = 5`, `kSeparationSpeedGU = 0.4`, `kTumbleRate = 0.5`

- [ ] **Step 1: Write the failing breakup tests**

```python
# tests/unit/test_rock_breakup.py
from engine.rocks import breakup


def test_plan_is_deterministic_per_name():
    assert breakup.plan("Asteroid 5b", 4.0) == breakup.plan("Asteroid 5b", 4.0)
    assert breakup.plan("Asteroid 5b", 4.0) != breakup.plan("Asteroid 6b", 4.0)


def test_volume_budget_and_count():
    pieces = breakup.plan("Asteroid 5b", 4.0)
    assert breakup.kPieceCountMin <= len(pieces) <= breakup.kPieceCountMax
    assert abs(sum(p.v_ratio for p in pieces) - breakup.kVolumeBudget) < 1e-9
    for p in pieces:
        assert abs(p.radius_gu - 4.0 * p.v_ratio ** (1.0 / 3.0)) < 1e-9


def test_tiers_follow_thresholds():
    for name in ("a", "b", "c", "d", "e"):
        for p in breakup.plan(name, 4.0):
            if p.radius_gu >= breakup.kMajorMinRadiusGU:
                assert p.tier == "major"
            elif p.radius_gu >= breakup.kChunkMinRadiusGU:
                assert p.tier == "chunk"
            else:
                assert p.tier == "dust"


def test_small_rock_has_no_majors():
    assert all(p.tier != "major" for p in breakup.plan("x", 0.8))


def test_offsets_are_unit_vectors():
    for p in breakup.plan("Asteroid 5b", 4.0):
        assert abs(sum(c * c for c in p.offset) - 1.0) < 1e-9
```

- [ ] **Step 2: Implement `engine/rocks/breakup.py`**

```python
"""Deterministic breakup plan for a rock (rock-class spec §2).

Pure: name + radius in, pieces out. Seeded by the parent's name so the same
rock always breaks the same way. kVolumeBudget of the parent's volume goes
into pieces; the rest is dust. Tier by piece radius.
"""
import math
import random
import zlib
from dataclasses import dataclass

kMajorMinRadiusGU = 1.0
kChunkMinRadiusGU = 0.08
kVolumeBudget = 0.70
kPieceCountMin = 2
kPieceCountMax = 5
kSeparationSpeedGU = 0.4
kTumbleRate = 0.5


@dataclass(frozen=True)
class PieceSpec:
    radius_gu: float
    offset: tuple
    v_ratio: float
    tier: str


def _rng(name: str) -> random.Random:
    return random.Random(zlib.crc32(name.encode("utf-8")))


def _tier(r: float) -> str:
    if r >= kMajorMinRadiusGU:
        return "major"
    if r >= kChunkMinRadiusGU:
        return "chunk"
    return "dust"


def _unit(rng) -> tuple:
    z = rng.uniform(-1.0, 1.0)
    t = rng.uniform(0.0, 2.0 * math.pi)
    s = math.sqrt(max(0.0, 1.0 - z * z))
    return (s * math.cos(t), s * math.sin(t), z)


def plan(parent_name: str, parent_radius_gu: float) -> list:
    rng = _rng(str(parent_name))
    n = rng.randint(kPieceCountMin, kPieceCountMax)
    weights = [rng.uniform(0.3, 1.0) for _ in range(n)]
    total = sum(weights)
    ratios = [kVolumeBudget * w / total for w in weights]
    # Make the budget exact despite float summation.
    ratios[-1] = kVolumeBudget - sum(ratios[:-1])
    out = []
    for v in ratios:
        r = float(parent_radius_gu) * v ** (1.0 / 3.0)
        out.append(PieceSpec(radius_gu=r, offset=_unit(rng), v_ratio=v, tier=_tier(r)))
    return out
```

- [ ] **Step 3: Write the failing death tests**

```python
# tests/unit/test_rock_death.py
import App
from engine.appc.math import TGPoint3
from tests.unit.test_rock_class import _make


def _in_set(obj, name, set_name="RockTest"):
    pSet = App.g_kSetManager.GetSet(set_name) or App.SetClass_Create()
    if App.g_kSetManager.GetSet(set_name) is None:
        App.g_kSetManager.AddSet(pSet, set_name)
    pSet.AddObjectToSet(obj, name)
    return pSet


def _events(monkeypatch):
    seen = []
    real = App.g_kEventManager.AddEvent
    def spy(evt):
        seen.append(evt.GetEventType())
        return real(evt)
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", spy)
    return seen


def test_hull_zero_routes_to_rock_death_not_ship_death(monkeypatch):
    from engine.appc import ship_death
    from engine.rocks import death
    called = []
    monkeypatch.setattr(ship_death, "begin", lambda *a, **k: called.append(a))
    rock = _make(App.GENUS_ASTEROID)
    _in_set(rock, "Asteroid 5b")
    rock.DamageSystem(rock.GetHull(), 1e9)
    assert called == []
    assert death.is_dying_rock(rock)


def test_event_order_and_lifetime(monkeypatch):
    from engine.rocks import death
    seen = _events(monkeypatch)
    rock = _make(App.GENUS_ASTEROID)
    pSet = _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    assert seen.count(App.ET_OBJECT_EXPLODING) == 1
    assert App.ET_OBJECT_DESTROYED not in seen
    death.advance(0.49)
    assert App.ET_OBJECT_DESTROYED not in seen
    death.advance(0.02)
    assert seen.count(App.ET_OBJECT_DESTROYED) == 1
    assert pSet.GetObject("Asteroid 5b") is None


def test_death_script_lifetime_is_honoured(monkeypatch):
    from engine.rocks import death
    seen = _events(monkeypatch)
    rock = _make(App.GENUS_ASTEROID)
    _in_set(rock, "Asteroid 5b")
    rock.SetLifeTime(2.0)
    death.begin(rock)
    death.advance(1.0)
    assert App.ET_OBJECT_DESTROYED not in seen
    death.advance(1.01)
    assert App.ET_OBJECT_DESTROYED in seen


def test_death_script_runs_once():
    from engine.rocks import death
    rock = _make(App.GENUS_ASTEROID)
    _in_set(rock, "Asteroid 5b")
    runs = []
    rock.RunDeathScript = lambda: runs.append(1)
    death.begin(rock)
    death.begin(rock)        # idempotent
    assert runs == [1]


def test_big_rock_spawns_named_major_pieces_without_death_script():
    from engine.rocks import breakup, death
    from engine.rocks.rock import is_rock
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(4.0)
    rock.SetDeathScript("nowhere.Fn")
    rock.SetTargetable(1)
    pSet = _in_set(rock, "Asteroid 5b")
    rock.SetVelocity(TGPoint3(1.0, 0.0, 0.0))
    death.begin(rock)
    majors = [p for p in breakup.plan("Asteroid 5b", 4.0) if p.tier == "major"]
    for i in range(1, len(majors) + 1):
        piece = pSet.GetObject("Asteroid 5b-%d" % i)
        assert piece is not None and is_rock(piece)
        assert piece.GetDeathScript() is None
        assert piece._rock_generation == 1
        assert piece.GetVelocityTG().x > 0.9      # parent velocity carried


def test_piece_hull_scales_from_parent_max():
    from engine.rocks import breakup, death, stats
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(4.0)
    rock.GetHull().SetMaxCondition(8000.0)
    pSet = _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    majors = [p for p in breakup.plan("Asteroid 5b", 4.0) if p.tier == "major"]
    first = pSet.GetObject("Asteroid 5b-1")
    assert abs(first.GetHull().GetMaxCondition()
               - stats.piece_hull(8000.0, majors[0].v_ratio)) < 1e-6


def test_chunks_and_vfx_are_queued():
    from engine.rocks import breakup, death
    rock = _make(App.GENUS_ASTEROID)
    rock.SetRadius(4.0)
    _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    n_chunks = sum(1 for p in breakup.plan("Asteroid 5b", 4.0) if p.tier == "chunk")
    assert len(death.drain_chunk_specs()) == n_chunks
    assert death.drain_chunk_specs() == []
    assert len(death.drain_death_vfx()) == 1


def test_rock_death_clears_target_locks(monkeypatch):
    from engine.appc import ship_death
    from engine.rocks import death
    cleared = []
    monkeypatch.setattr(ship_death, "_clear_target_locks", lambda s: cleared.append(s))
    rock = _make(App.GENUS_ASTEROID)
    _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    death.advance(1.0)
    assert rock in cleared


def test_reset_drops_pending_and_removed_rock_is_skipped(monkeypatch):
    from engine.rocks import death
    seen = _events(monkeypatch)
    rock = _make(App.GENUS_ASTEROID)
    pSet = _in_set(rock, "Asteroid 5b")
    death.begin(rock)
    pSet.RemoveObjectFromSet("Asteroid 5b")
    death.advance(1.0)
    assert App.ET_OBJECT_DESTROYED not in seen
    death.begin(_make(App.GENUS_ASTEROID))
    death.reset()
    assert death.drain_chunk_specs() == []


def test_no_splash_from_or_to_rocks(monkeypatch):
    from engine.appc import combat, splash_damage
    hits = []
    monkeypatch.setattr(combat, "apply_hit", lambda target, *a, **k: hits.append(target))
    rock = _make(App.GENUS_ASTEROID)
    ship = _make(App.GENUS_SHIP)
    _in_set(rock, "Asteroid 5b")
    _in_set(ship, "Ship")
    rock.SetSplashDamage(1000.0, 50.0)
    splash_damage.apply(rock)
    assert hits == []                        # a rock splashes nothing
    ship.SetSplashDamage(1000.0, 50.0)
    splash_damage.apply(ship)
    assert rock not in hits                  # a ship's splash skips rocks
```

The set helpers (`App.SetClass_Create`, `g_kSetManager.AddSet`, `RemoveObjectFromSet`): confirm their names against `engine/appc/sets.py` and adjust `_in_set` only. `tests/conftest.py`'s autouse reset must clear the test set between tests; check how other unit tests build a scratch set (for example `tests/unit/test_realize_set.py`) and copy that pattern if it differs.

- [ ] **Step 4: Implement `engine/rocks/death.py`**

```python
"""Rock death (rock-class spec §2): replaces ship_death for rocks.

At 0 HP: death script, ET_OBJECT_EXPLODING at once, pieces out, no splash,
no fireball; the parent leaves its set and ET_OBJECT_DESTROYED fires after
kRockDeathLife (or the lifetime a death script set -- E1M2 sets 0.5 s).
Pieces that are majors are real RockClass objects added to the parent's set
here; chunks and the death VFX are queued for the host (render-side).
"""
from dataclasses import dataclass

import engine.dev_mode as dev_mode
from engine.appc.math import TGPoint3
from engine.rocks import breakup, stats

kRockDeathLife = 0.5

_dying: list = []           # [{"rock", "time_left", "pSet", "name"}]
_chunk_specs: list = []
_vfx_specs: list = []


@dataclass(frozen=True)
class ChunkSpec:
    family: str
    seed: str
    radius_gu: float
    mass: float
    loc: tuple
    vel: tuple
    angular: tuple
    pSet: object


@dataclass(frozen=True)
class DeathVfxSpec:
    loc: tuple
    radius_gu: float
    pSet: object


def is_dying_rock(rock) -> bool:
    return any(e["rock"] is rock for e in _dying)


def _life(rock) -> float:
    from engine.appc.objects import LIFETIME_UNSET
    try:
        life = float(rock.GetLifeTime())
    except Exception:
        return kRockDeathLife
    return life if life < LIFETIME_UNSET else kRockDeathLife


def begin(rock, killer=None) -> None:
    if rock is None or is_dying_rock(rock) or rock.IsDead():
        return
    rock.SetDying(True)
    pSet = rock.GetContainingSet()
    name = rock.GetName()
    try:
        rock.RunDeathScript()
    except Exception as e:
        dev_mode.log_swallowed("rock death script", e)
    from engine.appc import ship_death
    ship_death._broadcast_exploding(rock, killer)
    _dying.append({"rock": rock, "time_left": _life(rock), "pSet": pSet, "name": name})
    if pSet is not None:
        try:
            _break_up(rock, pSet, name)
        except Exception as e:
            dev_mode.log_swallowed("rock breakup", e)


def _break_up(rock, pSet, name) -> None:
    from engine.rocks.rock import RockClass_Create
    loc = rock.GetWorldLocation()
    R = rock.GetWorldRotation()
    v = rock.GetVelocityTG()
    radius = float(rock.GetRadius())
    hull = rock.GetHull()
    parent_max = float(hull.GetMaxCondition()) if hull is not None else stats.size_hull(radius)
    parent_mass = float(rock.GetMass())
    family = rock.__dict__.get("_rock_family", "silicate")
    gen = int(rock.__dict__.get("_rock_generation", 0)) + 1
    _vfx_specs.append(DeathVfxSpec((loc.x, loc.y, loc.z), radius, pSet))
    major_i = 0
    for i, p in enumerate(breakup.plan(name, radius)):
        d = TGPoint3(*p.offset)
        d.MultMatrixLeft(R)                  # body -> world
        at = (loc.x + d.x * radius * 0.5, loc.y + d.y * radius * 0.5,
              loc.z + d.z * radius * 0.5)
        sp = breakup.kSeparationSpeedGU
        vel = (v.x + d.x * sp, v.y + d.y * sp, v.z + d.z * sp)
        tr = breakup.kTumbleRate
        ang = (d.y * tr, d.z * tr, d.x * tr)
        if p.tier == "major":
            major_i += 1
            piece_name = "%s-%d" % (name, major_i)
            piece = RockClass_Create(
                p.radius_gu, family=family, seed=piece_name, name=piece_name,
                kind="fragment",
                hull=stats.piece_hull(parent_max, p.v_ratio),
                mass=stats.piece_mass(parent_mass, p.v_ratio))
            piece._rock_generation = gen
            for getter, setter in (("IsTargetable", "SetTargetable"),
                                   ("IsScannable", "SetScannable"),
                                   ("IsHailable", "SetHailable")):
                g = getattr(rock, getter, None)
                s = getattr(piece, setter, None)
                if callable(g) and callable(s):
                    s(g())
            piece.SetTranslateXYZ(*at)
            piece.SetMatrixRotation(R)
            piece.SetVelocity(TGPoint3(*vel))
            piece.SetAngularVelocity(TGPoint3(*ang))
            pSet.AddObjectToSet(piece, piece_name)
        elif p.tier == "chunk":
            _chunk_specs.append(ChunkSpec(
                family, "%s#%d" % (name, i), p.radius_gu,
                stats.piece_mass(parent_mass, p.v_ratio), at, vel, ang, pSet))


def advance(dt: float) -> None:
    from engine.appc import ship_death
    from engine.appc.objects import broadcast_object_deleted
    still = []
    for e in _dying:
        e["time_left"] -= dt
        if e["time_left"] > 0.0:
            still.append(e)
            continue
        rock = e["rock"]
        pSet = rock.GetContainingSet()
        if pSet is None:
            continue                         # a mission removed it first
        ship_death._clear_target_locks(rock)
        if hasattr(rock, "SetDead"):
            rock.SetDead(True)
        ship_death._broadcast_destroyed(rock)
        try:
            pSet.RemoveObjectFromSet(rock.GetName())
        except Exception as ex:
            dev_mode.log_swallowed("remove dead rock", ex)
        broadcast_object_deleted(rock)
    _dying[:] = still


def drain_chunk_specs() -> list:
    out = list(_chunk_specs)
    _chunk_specs.clear()
    return out


def drain_death_vfx() -> list:
    out = list(_vfx_specs)
    _vfx_specs.clear()
    return out


def reset() -> None:
    _dying.clear()
    _chunk_specs.clear()
    _vfx_specs.clear()
```

Before writing it, check that `LIFETIME_UNSET` is importable from `engine.appc.objects`, that `SetDying` / `SetDead` / `IsDead` exist on `DamageableObject`, and that `ship_death._remove` isn't the better reuse. `_remove` also fires `broadcast_object_deleted`; match its order, which is locks, then set removal, then `ET_DELETE_OBJECT_PUBLIC`. `ET_OBJECT_DESTROYED` must fire while the rock is still in its set, as `ship_death` does at retire; read `ship_death.retire` and mirror its exact ordering, then note it in the report.

- [ ] **Step 5: Route hull death and exclude splash**

In `engine/appc/objects.py`, `DamageSystem` and `DestroySystem` both call `ship_death.begin(...)`. Change each so that:

```python
            from engine.rocks.rock import is_rock
            if is_rock(self):
                from engine.rocks import death as rock_death
                rock_death.begin(self, killer=source)   # DestroySystem: no killer
            else:
                from engine.appc import ship_death
                ship_death.begin(self, killer=source)
```

In `engine/appc/splash_damage.apply`, return at once when `is_rock(ship)`, and `continue` for any `target` that `is_rock`.

- [ ] **Step 6: Advance and reset**

- `engine/core/loop.py` `GameLoop.tick`: after the rock motion scope, add `from engine.rocks import death as rock_death` and `rock_death.advance(TICK_DELTA)` inside `_prof.scope("gl.rock_death")`.
- `tests/conftest.py` `_reset_leakable_engine_globals`: add `from engine.rocks import death as _rock_death; _rock_death.reset()` beside the other resets.
- `engine/host_loop.py` mission teardown (~6776, where `ship_death.reset()` is called): add `rocks.death.reset()`.

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/unit/test_rock_breakup.py tests/unit/test_rock_death.py tests/unit/test_rock_class.py tests/integration/test_e1m2_asteroid_crash.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add engine/rocks/breakup.py engine/rocks/death.py engine/appc/objects.py engine/appc/splash_damage.py engine/core/loop.py engine/host_loop.py tests/conftest.py tests/unit/test_rock_breakup.py tests/unit/test_rock_death.py
git commit -m "feat(rocks): rocks break up by size at 0 HP instead of dying like ships; no death splash to or from rocks"
```

---

### Task 5: Collision broadphase

**Files:**
- Modify: `engine/appc/collisions.py:704-761` (`resolve_collisions`)
- Test: `tests/unit/test_collision_broadphase.py`

**Interfaces:**
- Produces: `engine.appc.collisions._candidate_pairs(positions: list[tuple], radii: list[float], sets: list) -> list[tuple[int, int]]` (index pairs with i < k, sorted in all-pairs order), plus the module dials `kBroadphaseMinCellGU = 4.0` and `_BROADPHASE = True`.

Design: bodies are bucketed **per containing set** (bodies in different sets are compared only when `frames.offset_between` is not None; keep that path exact by falling back to all-pairs across any two distinct sets). Within one set, a uniform hash uses cell size `max(kBroadphaseMinCellGU, 2 × max radius in that set)`. Each body checks its own cell and the 26 neighbouring cells. The pair list is **sorted** into the same `(i, k)` order the old nested loop produced, so `_respond_pair` runs in an identical sequence and the resolved state is bit-identical.

- [ ] **Step 1: Write the failing equivalence test**

```python
# tests/unit/test_collision_broadphase.py
import random
from engine.appc import collisions


class _B:
    def __init__(self, x, y, z, r):
        self.pos = (x, y, z)
        self.radius = r


def _all_pairs_overlapping(bodies):
    out = []
    for i in range(len(bodies)):
        for k in range(i + 1, len(bodies)):
            a, b = bodies[i], bodies[k]
            d2 = sum((a.pos[j] - b.pos[j]) ** 2 for j in range(3))
            if d2 <= (a.radius + b.radius) ** 2:
                out.append((i, k))
    return out


def test_candidates_cover_every_overlapping_pair():
    rng = random.Random(7)
    for trial in range(50):
        n = rng.randint(2, 120)
        bodies = [_B(rng.uniform(-60, 60), rng.uniform(-60, 60), rng.uniform(-60, 60),
                     rng.choice([0.2, 0.8, 3.0, 12.0])) for _ in range(n)]
        sets = ["S"] * n
        positions = [b.pos for b in bodies]
        radii = [b.radius for b in bodies]
        cands = collisions._candidate_pairs(positions, radii, sets)
        assert cands == sorted(cands)
        assert set(_all_pairs_overlapping(bodies)) <= set(cands)


def test_distinct_sets_fall_back_to_all_pairs():
    positions = [(0, 0, 0), (1000, 0, 0)]
    cands = collisions._candidate_pairs(positions, [1.0, 1.0], ["A", "B"])
    assert cands == [(0, 1)]
```

Also add a resolved-state equivalence test: build 30 real `_make(App.GENUS_ASTEROID)` rocks in one scratch set in a tight cluster (random positions within 10 GU, radius 0.8), run `resolve_collisions` once with the broadphase and once with it forced off (a module flag `_BROADPHASE = True` the test monkeypatches to False), and assert the returned hit lists and every object's `GetWorldLocation()` and collision overlay velocity are identical. Rebuild the rocks from the same seed for each run.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/test_collision_broadphase.py -q`
Expected: FAIL (`_candidate_pairs` missing).

- [ ] **Step 3: Implement**

```python
kBroadphaseMinCellGU = 4.0
_BROADPHASE = True


def _candidate_pairs(positions, radii, sets):
    """Index pairs (i<k) that could touch, in all-pairs order. Same set: a
    uniform hash (cell = max(floor, 2 x largest radius in the set); a pair
    that can overlap is at most 2*rmax apart, so it lies in adjacent cells).
    Different sets: always a candidate -- frames.offset_between decides
    later, exactly as before."""
    n = len(positions)
    if not _BROADPHASE:
        return [(i, k) for i in range(n) for k in range(i + 1, n)]
    by_set = {}
    for i, s in enumerate(sets):
        by_set.setdefault(s, []).append(i)
    pairs = set()
    for idxs in by_set.values():
        if len(idxs) < 2:
            continue
        cell = max(kBroadphaseMinCellGU, 2.0 * max(radii[i] for i in idxs))
        grid = {}
        for i in idxs:
            p = positions[i]
            key = (int(p[0] // cell), int(p[1] // cell), int(p[2] // cell))
            grid.setdefault(key, []).append(i)
        for (cx, cy, cz), members in grid.items():
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        other = grid.get((cx + dx, cy + dy, cz + dz))
                        if not other:
                            continue
                        for i in members:
                            for k in other:
                                if i < k:
                                    pairs.add((i, k))
    keys = list(by_set.keys())
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            for i in by_set[keys[a]]:
                for k in by_set[keys[b]]:
                    pairs.add((min(i, k), max(i, k)))
    return sorted(pairs)
```

In `resolve_collisions`, replace the nested `for i … for k …` with `for i, k in _candidate_pairs(pos_list, radii, sets):`, keeping the loop body unchanged. `pos_list` is each body's position (use the `_Body` snapshot's position field; read `_resolve_body` to find it) and `radii` is `[b.obj.GetRadius() for b in bodies]`. Use the radius `_respond_pair` actually tests, if it applies scale or a hull box; read `_respond_pair` and use its bounding radius so the broadphase stays conservative. State in the report which radius you used and why it bounds `_respond_pair`'s test.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/unit/test_collision_broadphase.py tests/unit -q -k collision`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/collisions.py tests/unit/test_collision_broadphase.py
git commit -m "perf(collisions): spatial-hash broadphase with identical pairs and resolved state"
```

---

### Task 6: `surface_is_rock` instance flag; no venting, no smoke, grey debris

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h` (after `rim_strength`, ~line 82)
- Modify: `native/src/scenegraph/include/scenegraph/world.h:46`, `native/src/scenegraph/src/world.cc:110-112`
- Modify: `native/src/host/host_bindings.cc` (new `set_surface_rock` beside `set_rim_eligible` ~2817; the venting and debris call ~1236-1243; hull split copy ~5135-5156)
- Modify: `native/src/renderer/include/renderer/breach_venting.h:18-21`, `native/src/renderer/breach_venting.cc:6-9`
- Modify: `native/src/renderer/include/renderer/breach_debris.h:18-21`, `native/src/renderer/breach_debris.cc` (colour keys ~69-70, ~105-106)
- Modify: `engine/renderer.py` (`_h` name list ~77; wrapper beside `set_rim_eligible` ~784)
- Modify: `engine/host_loop.py` realise sites (~6051, ~7159)
- Modify: `engine/appc/part_detach_render.py:_copy_render_state` (~168)
- Modify: `engine/appc/hull_hit_smoke.py:57-82`
- Modify: every test fake with `def set_rim_eligible` (`grep -rln "def set_rim_eligible" tests/`)
- Test: `native/tests/scenegraph/world_test.cc`, `native/tests/renderer/breach_venting_test.cc`, `native/tests/renderer/breach_debris_test.cc`, `tests/unit/test_renderer_rim.py`, `tests/unit/test_rock_render_flags.py`

**Interfaces:**
- Produces: `scenegraph::Instance::surface_is_rock` (bool, default false); `World::set_surface_rock(InstanceId, bool)`; the host binding `set_surface_rock(id, rock)`; `engine.renderer.set_surface_rock(instance_id, rock)`. `build_venting_descriptors(ring, id, now, bool surface_is_rock = false)` and `build_debris_descriptors(ring, id, now, bool surface_is_rock = false)`. The trailing default keeps other callers compiling.

- [ ] **Step 1: Write the failing native tests**

```cpp
// native/tests/scenegraph/world_test.cc  (append)
TEST(World, SurfaceRockDefaultsFalseAndSets) {
    scenegraph::World w;
    const auto id = w.create_instance(assets::ModelHandle{});
    ASSERT_NE(w.get(id), nullptr);
    EXPECT_FALSE(w.get(id)->surface_is_rock);
    w.set_surface_rock(id, true);
    EXPECT_TRUE(w.get(id)->surface_is_rock);
}
```

(Match `create_instance`'s argument to the other tests in that file.)

```cpp
// native/tests/renderer/breach_venting_test.cc  (append)
TEST(BuildVentingDescriptors, RockVentsNothing) {
    scenegraph::BreachEventRing ring;
    // Push one fresh event exactly as FreshEventYieldsOneDescriptor does.
    ring.push(/* copy that test's event construction */);
    scenegraph::InstanceId id{1, 1};
    EXPECT_FALSE(renderer::build_venting_descriptors(ring, id, 0.f, false).empty());
    EXPECT_TRUE(renderer::build_venting_descriptors(ring, id, 0.f, true).empty());
}
```

```cpp
// native/tests/renderer/breach_debris_test.cc  (append)
TEST(BuildDebrisDescriptors, RockDebrisIsGreyBrownNotHotOrange) {
    scenegraph::BreachEventRing ring;
    ring.push(/* same fresh event as the existing debris tests */);
    scenegraph::InstanceId id{1, 1};
    const auto rock = renderer::build_debris_descriptors(ring, id, 0.f, true);
    ASSERT_FALSE(rock.empty());
    for (const auto& d : rock) {
        const auto& k0 = d.color_keys[0];
        // No channel dominates: grey-brown, never a hot spark (r >> b).
        EXPECT_LT(k0.r - k0.b, 0.2f);
        EXPECT_LT(k0.r, 0.6f);
    }
}
```

Read how the existing tests in each file build a fresh `BreachEventRing` event and copy it verbatim into the `/* ... */` spots. Use the real `ParticleKey` field names (the existing code writes `ParticleKey{t, ?, r, g, b}`; check the struct).

- [ ] **Step 2: Write the failing Python tests**

```python
# tests/unit/test_renderer_rim.py  (append)
def test_set_surface_rock_forwards(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(renderer, "_h", fake)
    renderer.set_surface_rock(7, True)
    fake.set_surface_rock.assert_called_once_with(7, True)
```

```python
# tests/unit/test_rock_render_flags.py
import App
from tests.unit.test_rock_class import _make


def test_hull_smoke_skips_rocks(monkeypatch):
    from engine.appc import hull_hit_smoke, particles
    monkeypatch.setattr(particles, "EffectController_GetEffectLevel",
                        lambda: particles.EffectController.HIGH)
    spawned = []
    monkeypatch.setattr(hull_hit_smoke, "_spawn", lambda *a, **k: spawned.append(a),
                        raising=False)
    rock = _make(App.GENUS_ASTEROID)
    hull_hit_smoke.maybe_emit(rock, App.TGPoint3(0, 0, 0), App.TGPoint3(0, 0, 1),
                              "torpedo")
    assert spawned == []
```

Read `hull_hit_smoke.maybe_emit` for its real emission call and spy on that instead of `_spawn`. The test has to fail today by reaching the emission.

Add a realise test in the style of `tests/unit/test_realize_set.py`: a fake renderer records `set_surface_rock(iid, flag)`. A genus-3 ship realises with `True`; a normal ship gets `False` (or no call, if you choose to call it only for rocks; assert whichever you implement, and prefer calling it for rocks only).

- [ ] **Step 3: Run to verify failure**

Run: `cmake --build build -j 2>&1 | tail -3` (expect compile errors in the new tests), then `.venv/bin/python -m pytest tests/unit/test_renderer_rim.py tests/unit/test_rock_render_flags.py -q` (expect FAIL).

- [ ] **Step 4: Implement native**

`instance.h`, after `rim_strength`:

```cpp
    /// True for rocks (RockClass, rock-class spec §2): craters expose rock,
    /// no venting, grey-brown debris. Default false.
    bool surface_is_rock = false;
```

`world.h`: `void set_surface_rock(InstanceId id, bool rock);`. `world.cc`:

```cpp
void World::set_surface_rock(InstanceId id, bool rock) {
    if (auto* inst = get(id)) inst->surface_is_rock = rock;
}
```

`host_bindings.cc`, beside `set_rim_eligible`:

```cpp
    m.def("set_surface_rock",
          [](scenegraph::InstanceId id, bool rock) {
              g_world.set_surface_rock(id, rock);
          },
          py::arg("id"), py::arg("rock"),
          "Mark an instance as rock: rock craters, no venting, grey debris.");
```

At the venting/debris call (~1236-1243), pass `inst.surface_is_rock` as the new last argument to both builders. In the hull split copy block (~5135-5156), add `cinst->surface_is_rock = inst->surface_is_rock;`.

`breach_venting.{h,cc}`: add `bool surface_is_rock = false` as the last parameter (default in the header only), and make `if (surface_is_rock) return {};` the first line of the body.

`breach_debris.{h,cc}`: same parameter. At each colour-key site, choose rock colours when it is set:

```cpp
    // Rock: dust and grit, never glowing hull fragments.
    constexpr ParticleKey kRockChunk0{0.0f, 0.f, 0.42f, 0.38f, 0.33f};
    constexpr ParticleKey kRockChunk1{1.0f, 0.f, 0.26f, 0.24f, 0.22f};
    constexpr ParticleKey kRockGrit0 {0.0f, 0.f, 0.50f, 0.46f, 0.40f};
    constexpr ParticleKey kRockGrit1 {1.0f, 0.f, 0.30f, 0.28f, 0.25f};
```

Apply `kRockChunk*` to the hull-chunk emitter and `kRockGrit*` to the spark emitter when `surface_is_rock` is set, and leave the existing keys otherwise. Put the constants at namespace scope in `breach_debris.cc`, and match `ParticleKey`'s real constructor.

- [ ] **Step 5: Implement Python**

`engine/renderer.py`: add `"set_surface_rock"` to the `_h` name list next to `"set_rim_eligible"`, and add:

```python
def set_surface_rock(instance_id: InstanceId, rock: bool) -> None:
    """Mark an instance as rock (rock-class spec §2): craters expose rock,
    no venting, grey-brown debris."""
    _h.set_surface_rock(instance_id, rock)
```

`engine/host_loop.py`, at both realise sites right after `r_.set_rim_strength(...)`:

```python
        from engine.rocks.rock import is_rock
        if is_rock(ship):
            r_.set_surface_rock(iid, True)
```

`engine/appc/part_detach_render._copy_render_state`: after the rim lines, add `if is_rock(ship): renderer.set_surface_rock(chunk_iid, True)`.

`engine/appc/hull_hit_smoke.maybe_emit`: right after the `threshold is None` return, add:

```python
    from engine.rocks.rock import is_rock
    if is_rock(ship):
        # Hull smoke is a pressurised hull venting; a rock has none.
        return
```

Add `def set_surface_rock(self, iid, rock): pass` (or record it, where the fake records calls) to every test fake that defines `set_rim_eligible`.

- [ ] **Step 6: Build and run**

Run: `cmake --build build -j 2>&1 | tail -3`, then `build/native/tests/<scenegraph test binary> --gtest_filter='*SurfaceRock*'`, then the venting and debris test binaries filtered to `*Rock*`. Find the binary names with `ls build/native/tests`.
Run: `.venv/bin/python -m pytest tests/unit/test_renderer_rim.py tests/unit/test_rock_render_flags.py tests/unit/test_realize_set.py tests/unit/test_part_detach_render.py tests/host -q`
Expected: PASS.

- [ ] **Step 7: Commit**

Stage every file you touched by explicit path, including each updated fake, then:

```bash
git commit -m "feat(rocks): surface_is_rock instance flag; rocks never vent or smoke and shed grey-brown debris"
```

---

### Task 7: Rock crater interiors in the breach pass

**Files:**
- Modify: `native/src/renderer/include/renderer/breach_pass.h`, `native/src/renderer/breach_pass.cc` (`render`, `draw_instance`, `draw_hull_proxy` ~361-368)
- Modify: `native/src/renderer/shaders/breach.frag` (uniforms ~96; triplanar sample ~947-950)
- Test: `native/tests/renderer/breach_pass_test.cc`

**Interfaces:**
- Consumes: `Instance::surface_is_rock` (Task 6).
- Produces: `unsigned int renderer::find_base_texture_id(const assets::Model&)` (a free function in `breach_pass.cc`, declared in `breach_pass.h` for the test); the uniforms `u_interior_is_rock` (int) and `u_rock_tex` (sampler2D, texture unit 4); new trailing parameters `bool surface_is_rock = false, unsigned int rock_tex = 0` on `draw_instance` (defaulted, so existing tests compile).

Behaviour: for a rock instance, the crater interior samples the instance's own **base-stage texture**, triplanar, at the same `hit_point * u_tex_scale` coordinates, multiplied by `kRockInteriorDarken = 0.55` (a `constexpr` in the shader as a `const float`). It does not use `u_damage_tex`. The molten-rim emissive for fresh breaches is **suppressed** for rocks: rock doesn't glow molten. When `rock_tex` is 0 (no base texture), fall back to a flat `vec3(0.30, 0.28, 0.25)`. Everything else is unchanged, including the stencil, shell and field logic.

Reference for shape only (it cannot be applied): `git show 4b67f4ae` on `feat/procedural-asteroids`, which added this to the older sphere-per-carve pass.

- [ ] **Step 1: Write the failing tests** (in `breach_pass_test.cc`, reusing the `SolidFillDrawsInterior` fixture helpers)

```cpp
TEST(FindBaseTextureId, ReturnsFirstMeshBaseStageTexture) {
    assets::Model m = make_surface_patch_model(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 50.f);
    // make_surface_patch_model's material has no base texture:
    EXPECT_EQ(renderer::find_base_texture_id(m), 0u);
}

TEST_F(BreachPassGLTest, RockInteriorIgnoresDamageTexture) {
    // Draw the same scene twice as a rock with a solid mid-grey base texture;
    // the interior colour must not depend on the (animated) damage frame, and
    // must differ from the non-rock draw.
    const unsigned int grey = make_solid_texture(128, 128, 128);   // helper: 1x1 RGBA
    auto draw = [&](bool rock, float age) {
        clear_framebuffer();
        glEnable(GL_DEPTH_TEST); glDepthMask(GL_TRUE);
        renderer::BreachPass pass;
        voxel::VoxelVolume fill = solid_fill();
        const voxel::DistanceField field = make_single_cavity_field();
        const auto entry = make_field_entry(field);
        const assets::Model patch = make_surface_patch_model(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 50.f);
        scenegraph::Camera cam = cam_facing(kCavitySurfaceCenter, glm::vec3(0, 0, 1), 100.f);
        mark_hull_cut();
        pass.draw_instance(1, fill, entry, patch, glm::mat4(1.0f), cam, *pipeline,
                           age, glm::vec3(0.0f), 0.0f, test_lighting(),
                           rock, rock ? grey : 0u);
        glFinish();
        return read_inner_mean_rgb();                                  // helper
    };
    const auto rock_a = draw(true, scenegraph::kRimLife + 1.f);
    const auto rock_b = draw(true, scenegraph::kRimLife + 1.f + 0.125f); // next damage frame
    const auto hull   = draw(false, scenegraph::kRimLife + 1.f);
    EXPECT_NEAR(rock_a.r, rock_b.r, 2.0f);
    EXPECT_NEAR(rock_a.g, rock_b.g, 2.0f);
    EXPECT_GT(std::abs(rock_a.r - hull.r) + std::abs(rock_a.b - hull.b), 6.0f);
    // Grey in, grey out: no channel dominates.
    EXPECT_LT(std::abs(rock_a.r - rock_a.b), 8.0f);
}

TEST_F(BreachPassGLTest, RockHasNoMoltenRim) {
    // A fresh breach (age 0, inside kRimLife) is brighter than a cold one on a
    // hull (HotBreachBrighterThanCold). On a rock it must not be.
    // Build it exactly as HotBreachBrighterThanCold does, with rock=true and
    // the grey texture, and assert hot <= cold + 3 on the mean luminance.
}
```

Write `make_solid_texture` and `read_inner_mean_rgb` as file-local helpers next to the existing `read_inner_max`, and fill in `RockHasNoMoltenRim` by copying `HotBreachBrighterThanCold` (~983) with the rock arguments. `draw_instance`'s current parameter list may differ from the call shown; add the two new parameters at the end of its real signature.

- [ ] **Step 2: Build; verify failure**

Run: `cmake --build build -j 2>&1 | tail -3`
Expected: compile error (the new parameters don't exist yet).

- [ ] **Step 3: Implement**

- `find_base_texture_id(const assets::Model&)`: walk `model.meshes`, then `model.materials[mesh.material_index()]` and its `stages[Base].texture_index`, and return `model.textures[idx].id()` for the first valid one, or 0. Guard every index.
- `draw_instance(..., bool surface_is_rock = false, unsigned int rock_tex = 0)` passes both through to `draw_hull_proxy` and `draw_interior_shell`. There, bind `rock_tex` on `GL_TEXTURE4`, then set `u_rock_tex = 4` and `u_interior_is_rock = surface_is_rock && rock_tex != 0 ? 1 : (surface_is_rock ? 2 : 0)` (2 means rock with no texture, which uses the flat colour).
- `render()`: compute `inst.surface_is_rock ? find_base_texture_id(*model) : 0u` per instance and pass it and the flag to `draw_instance`.
- `breach.frag`: declare `uniform int u_interior_is_rock;` and `uniform sampler2D u_rock_tex;`. At the triplanar sample, pick `u_rock_tex` when `u_interior_is_rock == 1`, the flat colour when it is 2, and `u_damage_tex` otherwise, then multiply the rock result by `kRockInteriorDarken`. Wrap the molten-rim emissive term in `if (u_interior_is_rock == 0)`.
- GLSL is 4.10 (`project_shaders_glsl_410`). Shader edits need a CMake re-configure to be copied (`cmake -B build -S . -DPython3_EXECUTABLE=$PWD/.venv/bin/python3` then build). Shader errors show up only at runtime, and the GL tests catch them.

- [ ] **Step 4: Build and run**

Run: `cmake -B build -S . -DPython3_EXECUTABLE=$PWD/.venv/bin/python3 >/dev/null && cmake --build build -j 2>&1 | tail -3`
Run the breach-pass test binary with `--gtest_filter='*Breach*:*FindBaseTexture*'`, from the project root (the gate's in-process pass runs whole binaries from there).
Expected: PASS, including every existing `BreachPassGLTest`.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/breach_pass.h native/src/renderer/breach_pass.cc native/src/renderer/shaders/breach.frag native/tests/renderer/breach_pass_test.cc
git commit -m "feat(renderer): rock craters expose the rock's own texture, darkened, with no molten rim"
```

---

### Task 8: Rock dust sparks, death burst, tumbling rock chunks

**Files:**
- Modify: `native/src/renderer/hit_vfx_pass.cc` (tint and cone tables ~53-62; kind selection ~290; anchoring)
- Modify: `engine/appc/hit_feedback.py` (~91-99 `SPARK_KIND_*`, `_SPARK_BASE_COUNT`, and `_hull_impact_visual` ~488-534)
- Create: `engine/rocks/vfx.py`, `engine/rocks/chunks.py`
- Modify: `engine/appc/debris_chunk.py` (add `spawn_body`)
- Modify: `engine/host_loop.py` (per frame after `collisions.tick_collisions`: `rocks.vfx.pump()` and `rocks.chunks.pump(renderer, session)`; teardown: `rocks.chunks.clear(renderer)` is not needed, because chunks live in `debris_chunk._live` and are cleared by `debris_chunk.clear`)
- Test: `native/tests/renderer/hit_vfx_pass_test.cc`, `tests/unit/test_rock_vfx.py`, `tests/unit/test_rock_chunks.py`

**Interfaces:**
- Consumes: `death.drain_death_vfx()`, `death.drain_chunk_specs()`, `DeathVfxSpec`, `ChunkSpec` (Task 4); `rock._rock_family`, `rock_model_override` / `catalogue.pick` (Task 3); `is_rock` (Task 1).
- Produces:
  - `hit_feedback.SPARK_KIND_ROCK = 2`
  - `hit_vfx_pass` kind 2: grey-brown, near-spherical spread, world-anchored at `position` when `instance_id` has no live instance
  - `engine.rocks.vfx.pump() -> None`
  - `engine.rocks.chunks.pump(renderer, session) -> None`
  - `engine.appc.debris_chunk.spawn_body(iid, *, loc, rot, vel, angular, mass, radius, scale) -> DebrisChunk`

- [ ] **Step 1: Write the failing tests**

Native (`hit_vfx_pass_test.cc`): copy the file's existing spark-rendering test and parameterise it:
1. A kind-2 spark burst renders pixels whose mean colour has `|r − b| < 0.15 × max(r, b)`: grey, where the torpedo kind is orange (`r ≫ b`).
2. A kind-2 descriptor whose `instance_id` is not in the world still draws sparks (world-anchored), while a kind-1 descriptor with the same missing instance draws none (today's behaviour, kept).

Python:

```python
# tests/unit/test_rock_vfx.py
import App
from tests.unit.test_rock_class import _make


def test_rock_hit_uses_rock_dust_spark_kind(monkeypatch):
    from engine.appc import hit_feedback, hit_vfx
    got = []
    monkeypatch.setattr(hit_vfx, "spawn", lambda *a, **k: got.append(k))
    rock = _make(App.GENUS_ASTEROID)
    # Call _hull_impact_visual the way dispatch() does, for a hit big enough
    # to spark (absorbed_hull above SPARK_HULL_THRESHOLD).
    hit_feedback._hull_impact_visual(
        ship=rock, point=App.TGPoint3(0, 0, 0), normal=App.TGPoint3(0, 0, 1),
        severity=hit_feedback.Severity.HULL, weapon_type="torpedo",
        absorbed_hull=hit_feedback.SPARK_HULL_THRESHOLD * 2, ship_instances=None)
    assert got and all(k.get("weapon_kind") == hit_feedback.SPARK_KIND_ROCK
                       for k in got if k.get("spark_count", 0) > 0)


def test_death_vfx_spec_becomes_flash_dust_and_light(monkeypatch):
    from engine.appc import explosion_lights, hit_vfx
    from engine.rocks import death, vfx
    spawned, lights = [], []
    monkeypatch.setattr(hit_vfx, "spawn", lambda *a, **k: spawned.append((a, k)))
    monkeypatch.setattr(explosion_lights, "register_at",
                        lambda *a, **k: lights.append((a, k)), raising=False)
    death._vfx_specs.append(death.DeathVfxSpec((1.0, 2.0, 3.0), 4.0, object()))
    vfx.pump()
    assert len(spawned) == 1
    (pos,), kw = spawned[0]
    assert (pos.x, pos.y, pos.z) == (1.0, 2.0, 3.0)
    assert kw["weapon_kind"] == 2 and kw["spark_count"] > 0
    assert kw["instance_id"] is None
    assert kw["severity"] == hit_vfx.Severity.CRITICAL
    assert death.drain_death_vfx() == []
```

`explosion_lights.register(ship, …)` needs a ship, and the rock is gone by the time the flash lights. Read `explosion_lights.py`: if it can take a position, use that. Otherwise add `register_at(loc, pSet, *, size_gu, life_s)` beside `register`, sharing its internals, and have `vfx.pump` call it with `size_gu = 0.5 × radius` and `life_s = 0.4`. Adjust the light assertion to the function you use, and assert exactly one light.

```python
# tests/unit/test_rock_chunks.py
def test_chunk_spec_becomes_rendered_tumbling_body(monkeypatch):
    from engine.appc import debris_chunk
    from engine.rocks import chunks, death

    class FakeRenderer:
        def __init__(self): self.loaded, self.created, self.flags = [], [], []
        def load_model(self, path, search, reps=None, decals=None, scale=1.0):
            self.loaded.append((path, scale)); return 11
        def create_instance(self, handle): self.created.append(handle); return 22
        def set_surface_rock(self, iid, v): self.flags.append((iid, v))
        def set_world_transform(self, iid, m): pass
        def set_visible(self, iid, v): pass
        def destroy_instance(self, iid): pass

    r = FakeRenderer()
    death._chunk_specs.append(death.ChunkSpec(
        "silicate", "Asteroid 5b#3", 0.3, 5.0, (1.0, 0.0, 0.0),
        (0.1, 0.0, 0.0), (0.0, 0.2, 0.0), None))
    chunks.pump(r, session=None)
    assert r.loaded and "/fragments/silicate_" in r.loaded[0][0].replace("\\", "/")
    assert r.created == [11]
    assert (22, True) in r.flags
    live = debris_chunk.live()
    assert any(c.iid == 22 and abs(c.radius - 0.3) < 1e-9 for c in live)
```

`debris_chunk.live()` must include the new chunk, so it collides and is evicted through the existing `kMaxLiveChunks` cap. Read `debris_chunk.DebrisChunk.__init__` for its required fields: it needs an `origin_ship` weakref, so `spawn_body` passes a module-level sentinel object that the chunk can weakref (for example a tiny class instance kept alive in `chunks.py`). Check that nothing in `debris_chunk` or `collisions` dereferences the origin ship in a way that breaks with the sentinel, and state what you checked.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/test_rock_vfx.py tests/unit/test_rock_chunks.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement native kind 2**

In `hit_vfx_pass.cc`:
- Grow `kSparkTint` to 3 entries, with `{0.46f, 0.42f, 0.36f, 1.0f}` for rock dust.
- Grow `kSparkConeDegByKind` to 3 entries, with `170.0f`.
- Change the kind selection to `const int kind = std::clamp(v.weapon_kind, 0, 2);`.
- Where `inst == nullptr` currently skips the burst: when `kind == 2`, use `origin = v.position` and `base = v.normal` if it is non-zero, else `cam_right`, and draw the burst world-anchored. Keep the existing skip for kinds 0 and 1.
- Update the comment block above the tables.

Confirm that the descriptor struct carries `position` and `normal` in world space (see `host_loop.py:~1737`, where the descriptor dict is built).

- [ ] **Step 4: Implement Python**

`hit_feedback.py`: add `SPARK_KIND_ROCK = 2` and `_SPARK_BASE_COUNT[SPARK_KIND_ROCK] = 10`. In `_hull_impact_visual`, after `spark_count, weapon_kind = spark_params(...)`, add:

```python
    from engine.rocks.rock import is_rock
    if is_rock(ship):
        weapon_kind = SPARK_KIND_ROCK      # dust and grit, not hot metal
```

`engine/rocks/vfx.py`:

```python
"""Rock death burst (rock-class spec §2): a crack flash, a dust-and-grit
burst, a short light. No fireball. World-anchored: the rock leaves its set
0.5 s later, taking its renderer instance with it."""
from engine.appc.math import TGPoint3

kDustSparkCount = 40
kFlashLightLife = 0.4


def pump() -> None:
    from engine.appc import explosion_lights, hit_vfx
    from engine.rocks import death
    for spec in death.drain_death_vfx():
        pos = TGPoint3(*spec.loc)
        hit_vfx.spawn(pos, None, severity=hit_vfx.Severity.CRITICAL,
                      instance_id=None, weapon_kind=2,
                      spark_count=kDustSparkCount, pSet=spec.pSet)
        explosion_lights.register_at(pos, spec.pSet,
                                     size_gu=0.5 * spec.radius_gu,
                                     life_s=kFlashLightLife)
```

(Use the light function Step 1 settled on.)

`debris_chunk.spawn_body(iid, *, loc, rot, vel, angular, mass, radius, scale)` builds a `DebrisChunk` with `component_cells=0`, `centroid_body=TGPoint3(0,0,0)`, the next id from `_next_obj_id`, and the sentinel origin, appends it to `_live` and returns it.

`engine/rocks/chunks.py`:

```python
"""Host side of rock breakup: chunk specs -> rendered tumbling bodies.

A chunk is a debris_chunk body (collides, capped at kMaxLiveChunks, cleared
on mission swap) wearing a catalogue fragment. Sub-project 3 replaces these
with minors."""
from engine.appc.math import TGMatrix3, TGPoint3
import engine.dev_mode as dev_mode


class _RockOrigin:
    """Stand-in parent for debris_chunk's weakref; a rock chunk outlives its
    rock by design."""


_ORIGIN = _RockOrigin()


def pump(renderer, session) -> None:
    from engine.appc import debris_chunk
    from engine.rocks import catalogue, death
    for spec in death.drain_chunk_specs():
        try:
            rock = (catalogue.pick(spec.seed, kind="fragment", family=spec.family)
                    or catalogue.pick(spec.seed, kind="fragment", family="silicate"))
            if rock is None:
                continue
            path = str(catalogue.catalogue_root() / rock.lod_paths[-1])
            handle = renderer.load_model(path, [], None, decals=None, scale=1.0)
            iid = renderer.create_instance(handle)
            renderer.set_surface_rock(iid, True)
            R = TGMatrix3()
            R.MakeIdentity()
            debris_chunk.spawn_body(
                iid, loc=TGPoint3(*spec.loc), rot=R, vel=TGPoint3(*spec.vel),
                angular=TGPoint3(*spec.angular), mass=spec.mass,
                radius=spec.radius_gu,
                scale=spec.radius_gu / (rock.bound_radius_m / 175.0))
        except Exception as e:
            dev_mode.log_swallowed("spawn rock chunk", e)
```

`scale` must turn the fragment's model size into `radius_gu`. Read how `debris_chunk.tick` builds the world matrix from `scale`, and how `BC_MODEL_SCALE` / glTF metres map to GU (1 GU = 175 m; the fragment's `bound_radius_m` is 100 m at load scale 1). Then correct the expression so that a chunk with `radius_gu = 0.3` renders 0.3 GU in radius. Pin it in `test_rock_chunks.py` by capturing `set_world_transform`'s matrix and checking its column length. The texture search argument (`[]`) must match `renderer.load_model`'s real parameter; glTF textures are relative to the file.

`engine/host_loop.py`: right after the `sim.collisions` scope, add:

```python
        from engine.rocks import chunks as rock_chunks, vfx as rock_vfx
        with frame_profiler.scope("sim.rock_breakup"):
            rock_vfx.pump()
            rock_chunks.pump(r, session)
```

Use the renderer variable name in scope there. Headless tests don't run this block, which is correct: chunks and VFX are render-side.

- [ ] **Step 5: Build and run**

Run: `cmake --build build -j 2>&1 | tail -3`, then the hit_vfx test binary with `--gtest_filter='*Spark*:*Rock*'`, then `.venv/bin/python -m pytest tests/unit/test_rock_vfx.py tests/unit/test_rock_chunks.py tests/unit -q -k "hit_feedback or debris or rock"`.
Expected: PASS.

- [ ] **Step 6: Commit**

Stage the touched files by explicit path, then:

```bash
git commit -m "feat(rocks): rock dust sparks, crack-flash death burst, tumbling catalogue-fragment chunks"
```

---

### Task 9: Mission E2E, docs, and the gate

**Files:**
- Modify: `tests/integration/test_e1m2_rocks.py` (add cases)
- Create: `tests/integration/test_e2m1_rocks.py`
- Modify: `CLAUDE.md` (a "Rock class" row after the "Rock catalogue" row)
- Modify: `docs/superpowers/specs/2026-09-30-modern-asteroids-roadmap.md` (sub-project 2 status becomes "built, awaiting live check"; strike the `DamageableObject_Create` evidence note, now fixed)

- [ ] **Step 1: Write the E2E tests**

```python
# tests/integration/test_e1m2_rocks.py  (append)
def test_clearing_debris_spawns_the_moving_asteroids():
    """E1M2.ObjectDestroyed (E1M2.py:1257) ShipClass_Casts the destroyed
    object; when the last debris rock is destroyed it sets g_bDebrisCleared.
    Destroy every debris rock through the real damage path."""
    from engine.rocks import death
    mod = _init_e1m2()
    names = list(mod.g_lDebrisNames)
    assert names
    for n in names:
        obj = None
        for pSet in App.g_kSetManager._sets.values():
            obj = pSet.GetObject(n) or obj
        assert obj is not None
        obj.DamageSystem(obj.GetHull(), 1e9)
    GameLoop().advance(60)             # past kRockDeathLife; events dispatch
    assert mod.g_bDebrisCleared


def test_moving_asteroid_hitting_haven_counts():
    """E1M2.PlanetCollision (E1M2.py:1314) needs ShipClass_Cast(rock)."""
    from engine.appc import collisions
    mod = _init_e1m2()
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    mod.CreateMovingAsteroids()
    name = sorted(mod.g_dAsteroidInfo.keys())[0]
    rock = App.ShipClass_GetObject(pSet, name)
    haven = App.Planet_GetObject(pSet, "Haven")   # confirm the lookup name
    hp = haven.GetWorldLocation()
    r = haven.GetRadius() + rock.GetRadius()
    rock.SetTranslateXYZ(hp.x + r + 0.5, hp.y, hp.z)
    v = App.TGPoint3(-5.0, 0.0, 0.0)
    rock.SetVelocity(v)
    before = len(mod.g_dAsteroidInfo)
    loop = GameLoop()
    for _ in range(60):
        loop.tick()
        collisions.tick_collisions(1.0 / 60.0)
    assert len(mod.g_dAsteroidInfo) == before - 1
```

`g_lDebrisNames` debris may start in another set, or be created later by a mission step; read E1M2 (`CreateDebris` or similar near `E1M2.py:1100-1105`) and drive whatever creates it. Confirm that Haven lives in Vesuvi6 and how `Planet_GetObject` is spelled in the shim. If the collision event doesn't reach `PlanetCollision` headlessly because the handler is registered on something the harness doesn't build, find the cause and report it rather than weakening the assertion.

```python
# tests/integration/test_e2m1_rocks.py
import App
from engine import host_loop
from tests.integration.test_sdk_bridge_load import _fresh_world

E2M1_MODULE = "Maelstrom.Episode2.E2M1.E2M1"


def _init_e2m1():
    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(E2M1_MODULE)
    return mod


def test_asteroid_3_resolves_as_ship_and_is_static_rock():
    from engine.rocks.rock import is_rock
    mod = _init_e2m1()
    if App.g_kSetManager.GetSet("Beol4").GetObject("Asteroid 3") is None:
        mod.CreateAsteroids()
    a3 = App.ShipClass_GetObject(App.g_kSetManager.GetSet("Beol4"), "Asteroid 3")
    assert a3 is not None and is_rock(a3)
    assert a3.IsImmobile()


def test_karoon_collision_with_asteroid_counts():
    mod = _init_e2m1()
    beol = App.g_kSetManager.GetSet("Beol4")
    if beol.GetObject("Asteroid 3") is None:
        mod.CreateAsteroids()
    rock = App.ShipClass_GetObject(beol, "Asteroid 3")
    called = []
    mod.KaroonHitAsteroid = lambda: called.append(1)
    evt = App.TGEvent_Create()
    evt.SetEventType(App.ET_OBJECT_COLLISION)
    evt.SetSource(rock)
    evt.SetDestination(App.ShipClass_GetObject(beol, "Karoon") or rock)
    mod.g_bKaroonHitAsteroid = App.FALSE if hasattr(App, "FALSE") else 0

    class _Owner:
        def CallNextHandler(self, e): pass

    mod.KaroonCollision(_Owner(), evt)
    assert called == [1]
```

If E2M1 doesn't boot headlessly (no existing test boots it), find out why. If the cause is a missing piece of shim surface unrelated to rocks, add the smallest fix, with a test, and report it. If the fix is large, fall back to `_fresh_world()`, import the module through the SDK loader, and call `CreateAsteroids()` directly with the sets it needs. Say which path you took and why.

- [ ] **Step 2: Run the E2E tests**

Run: `.venv/bin/python -m pytest tests/integration/test_e1m2_rocks.py tests/integration/test_e2m1_rocks.py tests/integration/test_multi1_rocks.py -q`
Expected: PASS.

- [ ] **Step 3: Docs**

Add a `CLAUDE.md` row after "Rock catalogue":

`| Rock class — asteroids as rocks, not ships | engine/rocks/{rock,motion,death,breakup,chunks,vfx}.py, docs/superpowers/specs/2026-09-30-rock-class-design.md | A genus-3 (GENUS_ASTEROID) ship becomes RockClass(ShipClass) in SetupProperties, so ShipClass_Cast still passes (E1M2/E2M1 need it). AI, motion and subsystem loops skip rocks (ship_iter.iter_non_rock_ships); rocks.motion integrates scripted SetVelocity/SetAngularVelocity (honouring MODEL vs WORLD space) — before this, scripted rock velocity was never integrated. Hull death → rocks.death: death script, ET_OBJECT_EXPLODING, deterministic size-decided breakup (≥1.0 GU pieces become new rocks "<name>-N"; smaller → debris_chunk bodies wearing catalogue fragments; rest dust), ET_OBJECT_DESTROYED after 0.5 s or the death script's lifetime. ⚠️ Deliberate BC departures: no death splash to or from rocks; no fireball. Renderer: Instance::surface_is_rock → rock crater interiors, no venting/smoke, grey debris, spark kind 2 (rock dust). DamageableObject_Create("Asteroid") returns a rock (Multi1/Multi6). Dials: engine/rocks/breakup.py. |`

Update the roadmap sub-project 2 row to `built, awaiting live check — spec 2026-09-30-rock-class-design.md`, and change the `DamageableObject_Create` evidence bullet to say it is now implemented by sub-project 2.

- [ ] **Step 4: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. Any failure not in `tests/known_failures.txt` is a regression from this branch: fix it and do not baseline it. If a doc-consistency test (`tests/docs/test_doc_consistency.py`) flags the `CLAUDE.md` edit, fix the doc.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_e1m2_rocks.py tests/integration/test_e2m1_rocks.py CLAUDE.md docs/superpowers/specs/2026-09-30-modern-asteroids-roadmap.md
git commit -m "test(rocks): E1M2/E2M1 story beats pass on rocks; docs: rock class"
```

(Add any shim fix files from Step 1 by explicit path.)
