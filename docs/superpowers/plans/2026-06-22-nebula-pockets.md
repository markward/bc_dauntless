# Nebula Pockets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make BC `MetaNebula` pockets fully functional — faithful two-texture rendering (depth-aware inside fog + outside billboard shell) plus the gameplay effects (enter/exit events, environmental damage, sensor-range scaling).

**Architecture:** A native render pass (`NebulaPass`) owns the GL, fed once per frame by a host-loop scraper through a `set_nebulae` binding (mirrors `set_dust_planets`/`set_backdrops`). Gameplay logic (events, damage, sensor scaling) is pure Python in a per-sim-tick membership tracker. The existing geometry-only `MetaNebula` (`engine/appc/nebula.py`) is extended, not replaced.

**Tech Stack:** Python 3 (engine shim + host loop), pytest; C++17 + OpenGL (native renderer), pybind11 bindings, GLSL embedded via CMake `configure_file`; CTest `FrameTest` harness.

## Global Constraints

- **Game units (GU):** all nebula sphere coordinates/radii are world-space GU. Never convert to metres anywhere in the pipeline. Display conversion is irrelevant here (no UI surfaces). Variable names use `*_gu` where a unit is implied.
- **Stock-BC byte-identity:** when no nebula is present in the active set, both the render path and the gameplay path must early-out so behaviour is byte-identical to stock BC.
- **No desktop interaction on Mark's workstation** — live verification builds are handed off for him to drive; never synthetic-click or full-screen capture.
- **Shader rebuild:** editing any `.vert`/`.frag` requires re-running `cmake -B build -S .` before `cmake --build build` (CMake embeds shader text at configure time). A plain `--build` will NOT pick up shader edits.
- **Build tree:** single tree at `build/`. Binary `build/dauntless`; module `build/python/_open_stbc_host.cpython-*.so`. Edits to `native/src/host/host_bindings.cc` require a `dauntless` rebuild (compiled into both binary and module). Never run cmake from inside `native/`.
- **Python 1.5 constraint applies ONLY to `tools/appc_logger.py`** (the in-game instrumentation snippet), NOT to `engine/`. Engine code is modern Python 3.
- **Sim-tick discipline:** environmental damage uses sim `dt` (the fixed `TICK_DT`), never wall-clock; no damage when `frame_dt == 0` (paused). Tracker state resets on mission swap (`reset_sdk_globals`).

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `engine/appc/nebula.py` | Modify | Extend `MetaNebula` with getters; add `MetaNebula_Cast`. |
| `App.py` | Modify | Export `MetaNebula_Cast`; add `ET_ENTERED_NEBULA`/`ET_EXITED_NEBULA`/`ET_ENVIRONMENT_DAMAGE` constants. |
| `engine/appc/nebula_runtime.py` | Create | `NebulaTracker` — per-tick membership diff → events, damage, sensor scaling. No GL. |
| `engine/host_loop.py` | Modify | Drive the tracker per sim tick; reset on swap; add `_aggregate_nebulae`; call `r.set_nebulae`. |
| `engine/renderer.py` | Modify | `set_nebulae(list)` wrapper over `_h.set_nebulae`. |
| `native/src/host/host_bindings.cc` | Modify | `g_nebula_pass`, `g_nebulae`; `set_nebulae` binding; render call in `render_space`; lifecycle in init/shutdown. |
| `native/src/renderer/include/renderer/nebula_pass.h` | Create | `NebulaPass` class + `NebulaVolume` struct. |
| `native/src/renderer/nebula_pass.cc` | Create | Pass implementation (inside fog + outside shell). |
| `native/src/renderer/shaders/nebula.vert` / `nebula.frag` | Create | GLSL for both render modes. |
| `native/src/renderer/CMakeLists.txt` | Modify | `embed_shader` entries + add `nebula_pass.cc` to the renderer lib sources. |
| `native/src/renderer/pipeline.cc` | Modify | Construct the nebula `Shader` (if pass uses pipeline shader plumbing) — see Task 4. |
| `tests/unit/test_nebula.py` | Create | Model + tracker pytest. |
| `native/tests/...` (FrameTest) | Modify | C++ frame test for the pass. |

---

## Task 1: MetaNebula model completion — getters + `MetaNebula_Cast`

**Files:**
- Modify: `engine/appc/nebula.py`
- Modify: `App.py:345` (export line)
- Test: `tests/unit/test_nebula.py` (create)

**Interfaces:**
- Consumes: existing `MetaNebula(r,g,b,visibility,sensor_density,internal_tex,external_tex)` constructor; `Nebula` base (has `GetName`/`SetName`/`GetWorldLocation` via `ObjectClass`).
- Produces:
  - `MetaNebula.GetTintRGB() -> tuple[float,float,float]`
  - `MetaNebula.GetVisibility() -> float`
  - `MetaNebula.GetSensorDensity() -> float`
  - `MetaNebula.GetInternalTexture() -> str`
  - `MetaNebula.GetExternalTexture() -> str`
  - `MetaNebula.GetDamage() -> tuple[float,float]`  (hull/sec, shields/sec)
  - `MetaNebula_Cast(obj) -> MetaNebula | None`  (returns obj iff it is a `MetaNebula`)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_nebula.py`:

```python
import App


def _make_nebula():
    n = App.MetaNebula_Create(
        155.0 / 255.0, 90.0 / 255.0, 185.0 / 255.0,
        145.0, 10.5,
        "data/Backgrounds/nebulaoverlay.tga",
        "data/Backgrounds/nebulaexternal.tga",
    )
    n.SetupDamage(150.0, 20.0)
    n.AddNebulaSphere(0.0, 1500.0, 0.0, 1500.0)
    return n


def test_metanebula_getters_return_constructor_values():
    n = _make_nebula()
    r, g, b = n.GetTintRGB()
    assert abs(r - 155.0 / 255.0) < 1e-6
    assert abs(g - 90.0 / 255.0) < 1e-6
    assert abs(b - 185.0 / 255.0) < 1e-6
    assert n.GetVisibility() == 145.0
    assert n.GetSensorDensity() == 10.5
    assert n.GetInternalTexture() == "data/Backgrounds/nebulaoverlay.tga"
    assert n.GetExternalTexture() == "data/Backgrounds/nebulaexternal.tga"
    assert n.GetDamage() == (150.0, 20.0)


def test_metanebula_cast_accepts_nebula_rejects_other():
    n = _make_nebula()
    assert App.MetaNebula_Cast(n) is n
    assert App.MetaNebula_Cast(object()) is None
    assert App.MetaNebula_Cast(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_nebula.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'GetTintRGB'` (and `MetaNebula_Cast` import works but getters missing).

- [ ] **Step 3: Add getters to `engine/appc/nebula.py`**

Insert these methods into class `MetaNebula` (after `IsObjectInNebula`):

```python
    def GetTintRGB(self):
        return self._rgb

    def GetVisibility(self):
        return self._visibility

    def GetSensorDensity(self):
        return self._sensor_density

    def GetInternalTexture(self):
        return self._internal_tex

    def GetExternalTexture(self):
        return self._external_tex

    def GetDamage(self):
        return self._damage
```

Replace the existing module-level `MetaNebula_Cast`/`Nebula_Cast` block at the bottom of the file. The current file only has `Nebula_Cast`; add `MetaNebula_Cast`:

```python
def MetaNebula_Cast(obj):
    return obj if isinstance(obj, MetaNebula) else None
```

- [ ] **Step 4: Export `MetaNebula_Cast` from `App.py`**

In `App.py`, change line 345 from:

```python
from engine.appc.nebula import MetaNebula, MetaNebula_Create, Nebula_Cast
```

to:

```python
from engine.appc.nebula import MetaNebula, MetaNebula_Create, Nebula_Cast, MetaNebula_Cast
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_nebula.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/nebula.py App.py tests/unit/test_nebula.py
git commit -m "feat(nebula): MetaNebula getters + MetaNebula_Cast export"
```

---

## Task 2: Membership tracker — enter/exit events

**Files:**
- Create: `engine/appc/nebula_runtime.py`
- Modify: `App.py` (event constants)
- Test: `tests/unit/test_nebula.py` (append)

**Interfaces:**
- Consumes: `App.g_kEventManager` (`AddEvent`, `AddBroadcastPythonMethodHandler`); `App.TGEvent_Create`; `MetaNebula.IsObjectInNebula`, `GetName`; `pSet.GetClassObjectList(App.CT_NEBULA)`; ship `GetName`.
- Produces:
  - Constants in `App.py`: `ET_ENTERED_NEBULA = 0x1300`, `ET_EXITED_NEBULA = 0x1301`, `ET_ENVIRONMENT_DAMAGE = 0x1302`.
  - `class NebulaTracker` with:
    - `update(self, pSet, ships, dt) -> None` — diff membership, broadcast enter/exit events.
    - `reset(self) -> None` — clear all membership state (call on mission swap).
  - Event semantics: enter/exit events have `SetSource(nebula)`, `SetDestination(ship)`, `SetEventType(ET_ENTERED_NEBULA|ET_EXITED_NEBULA)`.

Event-type values chosen to extend the existing `engine/appc/events.py` private range (`0x1000` keyboard … `0x1200` warp button); `0x1300+` is free and won't collide with the SDK's Appc-side ids.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_nebula.py`:

```python
from engine.appc.nebula_runtime import NebulaTracker


class _FakeShip:
    def __init__(self, name, x, y, z):
        self._name = name
        self._x, self._y, self._z = x, y, z

    def GetName(self):
        return self._name

    def move_to(self, x, y, z):
        self._x, self._y, self._z = x, y, z

    def GetWorldLocation(self):
        import App
        return App.TGPoint3(self._x, self._y, self._z)


class _EventSink:
    """Broadcast listener that records (event_type, source_name, dest_name)."""
    def __init__(self):
        self.events = []

    def record_enter(self, evt):
        self.events.append(("enter", evt.GetSource().GetName(),
                            evt.GetDestination().GetName()))

    def record_exit(self, evt):
        self.events.append(("exit", evt.GetSource().GetName(),
                            evt.GetDestination().GetName()))


def _set_with_nebula():
    import App
    s = App.SetClass_Create()
    n = _make_nebula()                       # sphere at (0,1500,0) r=1500
    s.AddObjectToSet(n, "neb")
    return s, n


def test_tracker_fires_enter_then_exit_once_per_transition():
    import App
    s, n = _set_with_nebula()
    sink = _EventSink()
    w = App.TGPythonInstanceWrapper()
    w.SetPyWrapper(sink)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_ENTERED_NEBULA, w, "record_enter")
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_EXITED_NEBULA, w, "record_exit")

    ship = _FakeShip("Player", 0.0, 5000.0, 0.0)   # far outside
    tracker = NebulaTracker()

    tracker.update(s, [ship], 1.0)                 # outside → no event
    assert sink.events == []

    ship.move_to(0.0, 1500.0, 0.0)                 # centre → enter
    tracker.update(s, [ship], 1.0)
    assert sink.events == [("enter", "neb", "Player")]

    tracker.update(s, [ship], 1.0)                 # still inside → no repeat
    assert sink.events == [("enter", "neb", "Player")]

    ship.move_to(0.0, 5000.0, 0.0)                 # leave → exit
    tracker.update(s, [ship], 1.0)
    assert sink.events == [("enter", "neb", "Player"),
                           ("exit", "neb", "Player")]


def test_tracker_reset_clears_membership():
    import App
    s, n = _set_with_nebula()
    ship = _FakeShip("Player", 0.0, 1500.0, 0.0)
    tracker = NebulaTracker()
    tracker.update(s, [ship], 1.0)                 # now inside
    tracker.reset()
    sink = _EventSink()
    w = App.TGPythonInstanceWrapper()
    w.SetPyWrapper(sink)
    App.g_kEventManager.AddBroadcastPythonMethodHandler(
        App.ET_EXITED_NEBULA, w, "record_exit")
    # After reset, an inside ship is treated as "newly seen": staying inside
    # fires a fresh ENTER, never a spurious EXIT.
    tracker.update(s, [ship], 1.0)
    assert all(e[0] != "exit" for e in sink.events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_nebula.py -v`
Expected: FAIL — `ModuleNotFoundError: engine.appc.nebula_runtime` / `AttributeError: module 'App' has no attribute 'ET_ENTERED_NEBULA'`.

- [ ] **Step 3: Add event constants to `App.py`**

In `App.py`, near the other `ET_*` constants (the block around `ET_ENTERED_SET = 105` / `ET_DELETE_OBJECT_PUBLIC = 200`), add:

```python
# Nebula + environmental event types. Private to the Phase-2 engine; values
# extend the engine/appc/events.py private range (0x1000..0x1200) and do not
# collide with SDK Appc-side ids.
ET_ENTERED_NEBULA = 0x1300
ET_EXITED_NEBULA = 0x1301
ET_ENVIRONMENT_DAMAGE = 0x1302
```

- [ ] **Step 4: Create `engine/appc/nebula_runtime.py`**

```python
"""Per-sim-tick nebula membership tracking.

Diffs which ships are inside which MetaNebula each tick and broadcasts
ET_ENTERED_NEBULA / ET_EXITED_NEBULA. Environmental damage and sensor
scaling are layered on in nebula_runtime (Task 3). No GL — pure gameplay.

Mirrors the SDK's Conditions/ConditionInNebula.py event contract: the
source of each event is the nebula, the destination is the ship.
"""
import App


def _nebulae_in_set(pSet):
    """MetaNebula objects in pSet (empty list when none — cheap early-out)."""
    out = []
    for obj in pSet.GetClassObjectList(App.CT_NEBULA):
        neb = App.MetaNebula_Cast(obj)
        if neb is not None:
            out.append(neb)
    return out


def _fire(event_type, nebula, ship):
    evt = App.TGEvent_Create()
    evt.SetEventType(event_type)
    evt.SetSource(nebula)
    evt.SetDestination(ship)
    App.g_kEventManager.AddEvent(evt)


class NebulaTracker:
    def __init__(self):
        # {id(nebula): set(id(ship))} — who is currently inside each nebula.
        self._inside = {}

    def reset(self):
        self._inside.clear()

    def update(self, pSet, ships, dt):
        nebulae = _nebulae_in_set(pSet)
        if not nebulae:
            # No nebula in this set: nothing to track. Drop any stale state
            # (e.g. after a set change) so re-entry fires a fresh ENTER.
            if self._inside:
                self._inside.clear()
            return

        for nebula in nebulae:
            key = id(nebula)
            prev = self._inside.get(key, set())
            now = set()
            for ship in ships:
                if nebula.IsObjectInNebula(ship):
                    sid = id(ship)
                    now.add(sid)
                    if sid not in prev:
                        _fire(App.ET_ENTERED_NEBULA, nebula, ship)
            # Exits: ships that were inside last tick but are not now.
            exited_ids = prev - now
            if exited_ids:
                by_id = {id(s): s for s in ships}
                for sid in exited_ids:
                    ship = by_id.get(sid)
                    if ship is not None:
                        _fire(App.ET_EXITED_NEBULA, nebula, ship)
            self._inside[key] = now
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_nebula.py -v`
Expected: PASS (all four tests).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/nebula_runtime.py App.py tests/unit/test_nebula.py
git commit -m "feat(nebula): membership tracker + enter/exit events"
```

---

## Task 3: Environmental damage + sensor scaling

**Files:**
- Modify: `engine/appc/nebula_runtime.py`
- Test: `tests/unit/test_nebula.py` (append)

**Interfaces:**
- Consumes: ship `GetHull()` → hull subsystem with `GetCondition()/SetCondition(v)`; ship `GetShieldSubsystem()` → `GetCurrentShields(face)/SetCurrentShields(face,v)`, `NUM_SHIELDS`; ship `GetSensorSubsystem()` → `GetBaseSensorRange()/SetBaseSensorRange(v)`; ship `_handlers` instance-handler dict (to honour `MissionLib.IgnoreEvent` opt-out).
- Produces: `NebulaTracker.update` now applies, while a ship is inside:
  - **hull** `cond -= hull_dmg * dt` (floored at 0), unless the ship opted out of `ET_ENVIRONMENT_DAMAGE`;
  - **shields** drained evenly across faces by `shield_dmg * dt` (floored at 0), same opt-out;
  - **sensor range** scaled by `clamp(sensor_density, 0, 1)` on enter, restored to the saved base on exit.

**Design notes (carried from spec §4):**
- `SetupDamage(150.0, 20.0)` is dmg/**sec**; multiply by `dt`.
- Vesuvi's `sensor_density = 10.5` is out-of-range data → `clamp(.,0,1)` yields `1.0` (no penalty). Multi5/Multi6 use documented `[0,1]`.
- Opt-out is honoured by inspecting whether the object registered `MissionLib.IgnoreEvent` for `ET_ENVIRONMENT_DAMAGE` via `AddPythonFuncHandlerForInstance` (the asteroids in `Vesuvi4_S`). This is the localised faithful path; we still fire no event for ignorers (they take no damage and nothing else listens).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_nebula.py`:

```python
class _FakeHull:
    def __init__(self, cond):
        self._c = cond

    def GetCondition(self):
        return self._c

    def SetCondition(self, v):
        self._c = v


class _FakeShields:
    NUM_SHIELDS = 6

    def __init__(self, per_face):
        self._f = [per_face] * self.NUM_SHIELDS

    def GetCurrentShields(self, face):
        return self._f[int(face)]

    def SetCurrentShields(self, face, v):
        self._f[int(face)] = v


class _FakeSensor:
    def __init__(self, base):
        self._b = base

    def GetBaseSensorRange(self):
        return self._b

    def SetBaseSensorRange(self, v):
        self._b = v


class _DamageableShip(_FakeShip):
    def __init__(self, name, x, y, z, hull=1000.0, shield=500.0, sensor=2000.0):
        super().__init__(name, x, y, z)
        self._hull = _FakeHull(hull)
        self._shield = _FakeShields(shield)
        self._sensor = _FakeSensor(sensor)
        self._handlers = {}        # event_type -> [qualified_name]

    def GetHull(self):
        return self._hull

    def GetShieldSubsystem(self):
        return self._shield

    def GetSensorSubsystem(self):
        return self._sensor

    def AddPythonFuncHandlerForInstance(self, event_type, qualified_name):
        self._handlers.setdefault(event_type, []).append(qualified_name)


def test_environmental_damage_drains_hull_and_shields():
    import App
    s, n = _set_with_nebula()      # SetupDamage(150, 20)
    ship = _DamageableShip("P", 0.0, 1500.0, 0.0, hull=1000.0, shield=500.0)
    tracker = NebulaTracker()
    tracker.update(s, [ship], 2.0)             # 2 s tick
    assert ship.GetHull().GetCondition() == 1000.0 - 150.0 * 2.0
    # 20/s * 2 s = 40 total, spread across 6 faces.
    assert abs(ship.GetShieldSubsystem().GetCurrentShields(0)
               - (500.0 - 40.0 / 6.0)) < 1e-6


def test_environmental_damage_floors_at_zero():
    import App
    s, n = _set_with_nebula()
    ship = _DamageableShip("P", 0.0, 1500.0, 0.0, hull=100.0, shield=1.0)
    tracker = NebulaTracker()
    tracker.update(s, [ship], 10.0)            # huge tick
    assert ship.GetHull().GetCondition() == 0.0
    assert ship.GetShieldSubsystem().GetCurrentShields(0) == 0.0


def test_ignore_event_opt_out_takes_no_damage():
    import App
    s, n = _set_with_nebula()
    ship = _DamageableShip("Rock", 0.0, 1500.0, 0.0, hull=1000.0)
    ship.AddPythonFuncHandlerForInstance(
        App.ET_ENVIRONMENT_DAMAGE, "MissionLib.IgnoreEvent")
    tracker = NebulaTracker()
    tracker.update(s, [ship], 2.0)
    assert ship.GetHull().GetCondition() == 1000.0


def test_sensor_range_scaled_on_enter_restored_on_exit():
    import App
    # Build a nebula with sensor_density 0.25 (in range).
    s = App.SetClass_Create()
    n = App.MetaNebula_Create(0.1, 0.1, 0.1, 100.0, 0.25,
                              "i.tga", "e.tga")
    n.SetupDamage(0.0, 0.0)
    n.AddNebulaSphere(0.0, 0.0, 0.0, 100.0)
    s.AddObjectToSet(n, "neb")
    ship = _DamageableShip("P", 0.0, 0.0, 0.0, sensor=2000.0)
    tracker = NebulaTracker()
    tracker.update(s, [ship], 1.0)             # enter
    assert ship.GetSensorSubsystem().GetBaseSensorRange() == 2000.0 * 0.25
    ship.move_to(0.0, 5000.0, 0.0)
    tracker.update(s, [ship], 1.0)             # exit
    assert ship.GetSensorSubsystem().GetBaseSensorRange() == 2000.0


def test_sensor_density_out_of_range_clamps_to_one():
    import App
    s, n = _set_with_nebula()                  # sensor_density 10.5
    ship = _DamageableShip("P", 0.0, 1500.0, 0.0, sensor=2000.0)
    tracker = NebulaTracker()
    tracker.update(s, [ship], 1.0)
    assert ship.GetSensorSubsystem().GetBaseSensorRange() == 2000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_nebula.py -v`
Expected: FAIL — hull/shield/sensor unchanged (damage + scaling not yet implemented).

- [ ] **Step 3: Extend `NebulaTracker` in `engine/appc/nebula_runtime.py`**

Add a module-level helper and rewrite `update` to apply effects. Replace the `update` method body and add helpers:

```python
def _ignores_env_damage(ship):
    handlers = getattr(ship, "_handlers", None)
    if not handlers:
        return False
    return "MissionLib.IgnoreEvent" in handlers.get(App.ET_ENVIRONMENT_DAMAGE, [])


def _apply_env_damage(ship, hull_per_s, shield_per_s, dt):
    if hull_per_s <= 0.0 and shield_per_s <= 0.0:
        return
    if _ignores_env_damage(ship):
        return
    if hull_per_s > 0.0:
        hull = ship.GetHull()
        if hull is not None:
            new = hull.GetCondition() - hull_per_s * dt
            hull.SetCondition(new if new > 0.0 else 0.0)
    if shield_per_s > 0.0:
        shields = ship.GetShieldSubsystem()
        if shields is not None:
            per_face = (shield_per_s * dt) / shields.NUM_SHIELDS
            for face in range(shields.NUM_SHIELDS):
                cur = shields.GetCurrentShields(face) - per_face
                shields.SetCurrentShields(face, cur if cur > 0.0 else 0.0)


def _clamp01(v):
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v
```

Update the class to track saved sensor ranges and apply scaling on transitions. The `update` method becomes:

```python
    def __init__(self):
        self._inside = {}            # {id(nebula): set(id(ship))}
        self._sensor_saved = {}      # {id(ship): base_range} while scaled

    def reset(self):
        self._inside.clear()
        self._sensor_saved.clear()

    def _scale_sensor(self, ship, density):
        sensor = ship.GetSensorSubsystem() if hasattr(ship, "GetSensorSubsystem") else None
        if sensor is None:
            return
        sid = id(ship)
        if sid in self._sensor_saved:
            return                   # already scaled
        base = sensor.GetBaseSensorRange()
        self._sensor_saved[sid] = base
        sensor.SetBaseSensorRange(base * _clamp01(density))

    def _restore_sensor(self, ship):
        sid = id(ship)
        if sid not in self._sensor_saved:
            return
        sensor = ship.GetSensorSubsystem() if hasattr(ship, "GetSensorSubsystem") else None
        if sensor is not None:
            sensor.SetBaseSensorRange(self._sensor_saved[sid])
        del self._sensor_saved[sid]

    def update(self, pSet, ships, dt):
        nebulae = _nebulae_in_set(pSet)
        if not nebulae:
            if self._inside:
                self._inside.clear()
            for ship in ships:
                self._restore_sensor(ship)
            return

        for nebula in nebulae:
            key = id(nebula)
            prev = self._inside.get(key, set())
            now = set()
            hull_dmg, shield_dmg = nebula.GetDamage()
            density = nebula.GetSensorDensity()
            for ship in ships:
                if nebula.IsObjectInNebula(ship):
                    sid = id(ship)
                    now.add(sid)
                    if sid not in prev:
                        _fire(App.ET_ENTERED_NEBULA, nebula, ship)
                        self._scale_sensor(ship, density)
                    _apply_env_damage(ship, hull_dmg, shield_dmg, dt)
            exited_ids = prev - now
            if exited_ids:
                by_id = {id(s): s for s in ships}
                for sid in exited_ids:
                    ship = by_id.get(sid)
                    if ship is not None:
                        _fire(App.ET_EXITED_NEBULA, nebula, ship)
                        self._restore_sensor(ship)
            self._inside[key] = now
```

Note: keep the existing `_nebulae_in_set` and `_fire` helpers; only `update`, `__init__`, `reset` are replaced and the four module helpers are added.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_nebula.py -v`
Expected: PASS (all nine tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/nebula_runtime.py tests/unit/test_nebula.py
git commit -m "feat(nebula): environmental damage + sensor-range scaling"
```

---

## Task 4: Host-loop integration of the tracker

**Files:**
- Modify: `engine/host_loop.py` (instantiate tracker; drive per sim tick; reset on swap)
- Test: manual + existing suite (no new unit test — integration is exercised live in Task 8)

**Interfaces:**
- Consumes: `NebulaTracker` (Task 3); the host loop's active set + ship list + fixed sim `dt`.
- Produces: a module-level `_nebula_tracker = NebulaTracker()` driven each sim tick over the active set's ships, reset inside `reset_sdk_globals`.

**Integration points (verified):**
- `reset_sdk_globals` is `engine/host_loop.py:1700`; add the tracker reset there.
- The fixed-step sim advances per tick near the combat/motion advance (`_advance_combat` at `:327`, called from the main loop). The tracker must run with the sim `dt` (the per-tick `TICK_DT`, NOT the render `frame_dt`), and must NOT run when the sim is frozen (`pause.is_open` → `_player_dt == 0`).

- [ ] **Step 1: Add the tracker singleton + reset**

Near the other host-loop module globals (top of `engine/host_loop.py`, alongside warp/diag globals), add:

```python
from engine.appc.nebula_runtime import NebulaTracker
_nebula_tracker = NebulaTracker()
```

In `reset_sdk_globals` (`engine/host_loop.py:1700`), add a line in the body:

```python
    _nebula_tracker.reset()
```

(Place it with the other singleton resets; `_nebula_tracker` is module-global so no `global` declaration needed for a method call.)

- [ ] **Step 2: Drive the tracker each sim tick**

Find the per-tick sim-advance site (where `_advance_combat(ships, dt, ...)` is called within the fixed-step loop). Immediately after the combat advance, add:

```python
            # Nebula membership → enter/exit events, environmental damage,
            # sensor scaling. Uses sim dt (not frame_dt); skipped while paused
            # (dt == 0) and a no-op for sets without a nebula.
            if dt > 0.0 and active_set is not None:
                _nebula_tracker.update(
                    active_set,
                    active_set.GetClassObjectList(App.CT_SHIP),
                    dt,
                )
```

Use the same `dt` variable the surrounding sim-advance code uses for this tick (the fixed `TICK_DT`), and the same `active_set` reference used by the render block. If `active_set`/`dt` are named differently at that site, match the local names — do not introduce new lookups.

- [ ] **Step 3: Verify the suite still passes**

Run: `uv run pytest tests/unit/test_nebula.py -v`
Run: `bash scripts/run_tests.sh` (watchdog-capped full suite; confirm no regressions)
Expected: PASS / no new failures.

- [ ] **Step 4: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(nebula): drive membership tracker from host-loop sim tick"
```

---

## Task 5: Render data plumbing + empty NebulaPass

**Goal:** Scrape nebula descriptors each frame, push them across a `set_nebulae` binding into a `NebulaPass` that is constructed/destroyed and called in `render_space` but draws NOTHING yet. Proves data reaches C++ before any shader work.

**Files:**
- Modify: `engine/host_loop.py` (`_aggregate_nebulae` + `r.set_nebulae`)
- Modify: `engine/renderer.py` (`set_nebulae` wrapper)
- Create: `native/src/renderer/include/renderer/nebula_pass.h`
- Create: `native/src/renderer/nebula_pass.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `nebula_pass.cc` to sources)
- Modify: `native/src/host/host_bindings.cc` (globals, binding, lifecycle, render call)
- Test: `tests/unit/test_nebula.py` (aggregator unit test)

**Interfaces:**
- Produces (Python):
  - `engine.host_loop._aggregate_nebulae(pSet) -> list[dict]`, each dict:
    ```
    {"spheres": [(x,y,z,r), ...],          # GU
     "rgb": (r,g,b),                       # 0..1
     "visibility": float,                  # GU
     "external_tex": str, "internal_tex": str}
    ```
  - `engine.renderer.set_nebulae(nebulae: list) -> None`
- Produces (C++):
  - `renderer::NebulaVolume { std::vector<glm::vec4> spheres; glm::vec3 rgb; float visibility; std::string external_tex, internal_tex; }`
  - `renderer::NebulaPass` with `render(const scenegraph::Camera&, Pipeline&, const std::vector<NebulaVolume>&)`, `set_enabled(bool)`.
  - binding `set_nebulae(list[dict])` populating `g_nebulae`.

- [ ] **Step 1: Write the aggregator failing test**

Append to `tests/unit/test_nebula.py`:

```python
def test_aggregate_nebulae_from_set():
    import App
    from engine.host_loop import _aggregate_nebulae
    s, n = _set_with_nebula()
    out = _aggregate_nebulae(s)
    assert len(out) == 1
    d = out[0]
    assert d["spheres"] == [(0.0, 1500.0, 0.0, 1500.0)]
    assert abs(d["rgb"][0] - 155.0 / 255.0) < 1e-6
    assert d["visibility"] == 145.0
    assert d["external_tex"] == "data/Backgrounds/nebulaexternal.tga"
    assert d["internal_tex"] == "data/Backgrounds/nebulaoverlay.tga"


def test_aggregate_nebulae_empty_when_none():
    import App
    from engine.host_loop import _aggregate_nebulae
    s = App.SetClass_Create()
    assert _aggregate_nebulae(s) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_nebula.py -k aggregate -v`
Expected: FAIL — `ImportError: cannot import name '_aggregate_nebulae'`.

- [ ] **Step 3: Implement `_aggregate_nebulae` in `engine/host_loop.py`**

Add near `_aggregate_planets` (`engine/host_loop.py:1959`):

```python
def _aggregate_nebulae(pSet):
    """Render descriptors for MetaNebula volumes in pSet (world-space GU).

    Returns [] for sets without a nebula (renderer early-outs → stock BC).
    """
    import App
    if pSet is None:
        return []
    out = []
    for obj in pSet.GetClassObjectList(App.CT_NEBULA):
        neb = App.MetaNebula_Cast(obj)
        if neb is None:
            continue
        spheres = [tuple(s) for s in neb.GetNebulaSpheres()]
        if not spheres:
            continue
        out.append({
            "spheres": spheres,
            "rgb": neb.GetTintRGB(),
            "visibility": neb.GetVisibility(),
            "external_tex": neb.GetExternalTexture(),
            "internal_tex": neb.GetInternalTexture(),
        })
    return out
```

- [ ] **Step 4: Run aggregator test (passes), then add the renderer wrapper**

Run: `uv run pytest tests/unit/test_nebula.py -k aggregate -v` → PASS.

In `engine/renderer.py`, add after `set_backdrops`:

```python
def set_nebulae(nebulae: list) -> None:
    """Configure the active set's MetaNebula volumes for the nebula pass.
    Each entry: {"spheres": [(x,y,z,r)...], "rgb": (r,g,b),
    "visibility": float, "external_tex": str, "internal_tex": str}.
    Empty list = no nebula (pass early-outs)."""
    _h.set_nebulae(nebulae)
```

- [ ] **Step 5: Call the aggregator from the per-frame render block**

In `engine/host_loop.py`, in the render-aggregation block (after the `r.set_dust_planets(planets)` line near `:4634`), add:

```python
            nebulae = [] if _warp_streaking else _aggregate_nebulae(active_set)
            r.set_nebulae(nebulae)
```

(`_warp_streaking` already exists in this block; nebulae are local-system objects torn down during warp, so suppress them while streaking, matching suns.)

- [ ] **Step 6: Create the C++ header `native/src/renderer/include/renderer/nebula_pass.h`**

```cpp
// native/src/renderer/include/renderer/nebula_pass.h
#pragma once

#include <glm/glm.hpp>

#include <memory>
#include <string>
#include <vector>

namespace assets { class Texture; }
namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

/// One MetaNebula volume: a union of fuzzy spheres with a tint and an
/// inside-visibility falloff distance (GU). Textures are faithful BC assets.
struct NebulaVolume {
    std::vector<glm::vec4> spheres;   // xyz = centre (GU), w = radius (GU)
    glm::vec3   rgb        = glm::vec3(0.5f);
    float       visibility = 145.0f;  // GU; inside-fog falloff distance
    std::string external_tex;         // from-outside billboard (opaque)
    std::string internal_tex;         // inside-fog overlay (alpha)
};

class NebulaPass {
public:
    // Render style. FAITHFUL is the only path this project ships; the seam
    // is here so a future Modern-VFX VOLUMETRIC path drops in behind the
    // same data contract (NebulaVolume) with no host/model changes.
    enum class Style { FAITHFUL, VOLUMETRIC };

    NebulaPass();
    ~NebulaPass();
    NebulaPass(const NebulaPass&) = delete;
    NebulaPass& operator=(const NebulaPass&) = delete;

    /// Draw all volumes. Caller guarantees the scene depth buffer is
    /// populated (inside fog reads depth so hulls occlude correctly).
    /// Early-outs when `volumes` is empty or the pass is disabled.
    void render(const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const std::vector<NebulaVolume>& volumes);

    void  set_enabled(bool enabled) { enabled_ = enabled; }
    bool  enabled() const { return enabled_; }
    void  set_style(Style s) { style_ = s; }
    Style style() const { return style_; }

private:
    bool  enabled_     = true;
    bool  initialized_ = false;
    Style style_       = Style::FAITHFUL;

    void initialize_gl();
};

}  // namespace renderer
```

- [ ] **Step 7: Create the C++ stub `native/src/renderer/nebula_pass.cc` (no draw yet)**

```cpp
// native/src/renderer/nebula_pass.cc
#include "renderer/nebula_pass.h"

#include "renderer/pipeline.h"

#include <scenegraph/camera.h>

#include <glad/glad.h>

namespace renderer {

NebulaPass::NebulaPass() = default;
NebulaPass::~NebulaPass() = default;

void NebulaPass::initialize_gl() {
    // GL objects created here in Task 6 (VAO/quad/instance buffers).
    initialized_ = true;
}

void NebulaPass::render(const scenegraph::Camera& camera,
                        Pipeline& pipeline,
                        const std::vector<NebulaVolume>& volumes) {
    (void)camera;
    (void)pipeline;
    if (!enabled_ || volumes.empty()) return;
    if (!initialized_) initialize_gl();
    // Task 6 (inside fog) and Task 7 (outside shell) draw here.
}

}  // namespace renderer
```

- [ ] **Step 8: Add `nebula_pass.cc` to the renderer CMake sources**

In `native/src/renderer/CMakeLists.txt`, add `nebula_pass.cc` to the renderer library's source list (find the existing `add_library(... dust_pass.cc ...)` or target_sources block listing `dust_pass.cc` and add `nebula_pass.cc` alongside it).

- [ ] **Step 9: Wire globals, lifecycle, binding, and render call in `host_bindings.cc`**

In `native/src/host/host_bindings.cc`:

(a) Add include near `#include <renderer/dust_pass.h>` (line ~28):
```cpp
#include <renderer/nebula_pass.h>
```

(b) Add globals near `g_dust_pass`/`g_dust_planets` (line ~149):
```cpp
std::vector<renderer::NebulaVolume> g_nebulae;
std::unique_ptr<renderer::NebulaPass> g_nebula_pass;
```

(c) In `init` (near `g_dust_pass = std::make_unique<...>()`, line ~342):
```cpp
    g_nebula_pass = std::make_unique<renderer::NebulaPass>();
    g_nebulae.clear();
```

(d) In `shutdown` (near `g_dust_pass.reset()`, line ~396):
```cpp
    g_nebula_pass.reset();
    g_nebulae.clear();
```

(e) Render call inside `render_space`, right AFTER the dust pass block (line ~571, after the `g_dust_pass->render(...)` call) and before lens flares. Inside fog needs depth (populated by the opaque submit above), and the from-outside shell depth-tests against hulls:
```cpp
        if (!for_viewscreen && g_nebula_pass)
            g_nebula_pass->render(cam, *g_pipeline, g_nebulae);
```

(f) The binding, near `set_dust_planets` (line ~1621):
```cpp
    m.def("set_nebulae",
          [](const std::vector<py::dict>& descs) {
              g_nebulae.clear();
              g_nebulae.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::NebulaVolume v;
                  for (const auto& s :
                       d["spheres"].cast<std::vector<std::tuple<float,float,float,float>>>()) {
                      v.spheres.emplace_back(std::get<0>(s), std::get<1>(s),
                                             std::get<2>(s), std::get<3>(s));
                  }
                  auto rgb = d["rgb"].cast<std::tuple<float,float,float>>();
                  v.rgb = glm::vec3(std::get<0>(rgb), std::get<1>(rgb),
                                    std::get<2>(rgb));
                  v.visibility   = d["visibility"].cast<float>();
                  v.external_tex = d["external_tex"].cast<std::string>();
                  v.internal_tex = d["internal_tex"].cast<std::string>();
                  g_nebulae.push_back(std::move(v));
              }
          },
          py::arg("nebulae"),
          "Set the active set's MetaNebula volumes, applied each frame().");
```

- [ ] **Step 10: Reconfigure + build**

Run:
```bash
cmake -B build -S . && cmake --build build -j
```
Expected: clean build of `build/dauntless` and the `_open_stbc_host` module (the new source compiles; binding registers).

- [ ] **Step 11: Smoke-test the binding from Python**

Run:
```bash
uv run python -c "import build.python._open_stbc_host as h; print(hasattr(h,'set_nebulae'))"
```
(If the import path differs, use the project's standard module-import smoke check.) Expected: `True`.

- [ ] **Step 12: Commit**

```bash
git add engine/host_loop.py engine/renderer.py native/src/renderer/include/renderer/nebula_pass.h native/src/renderer/nebula_pass.cc native/src/renderer/CMakeLists.txt native/src/host/host_bindings.cc tests/unit/test_nebula.py
git commit -m "feat(nebula): render data plumbing + empty NebulaPass wired into frame"
```

---

## Task 6: Inside depth-aware fog

**Goal:** When the camera is inside any sphere, composite world-space distance fog tinted by `rgb`, falloff from `visibility`, modulated by the `nebulaoverlay` texture, reading the scene depth buffer so hulls/objects recede into the murk.

**Files:**
- Create: `native/src/renderer/shaders/nebula.vert`, `nebula.frag`
- Modify: `native/src/renderer/CMakeLists.txt` (`embed_shader` entries)
- Modify: `native/src/renderer/pipeline.cc` (construct the nebula `Shader`, expose to the pass) — follow the `dust_` Shader pattern at `pipeline.cc:57`.
- Modify: `native/src/renderer/nebula_pass.cc` (`initialize_gl` + inside-fog draw)
- Test: C++ `FrameTest`

**Interfaces:**
- Consumes: `NebulaVolume` list, camera (for eye position + view/proj), the pipeline's depth texture, `Pipeline`'s nebula `Shader`.
- Produces: inside-fog composite over the framebuffer.

**Approach:** a fullscreen pass. The fragment shader reconstructs world position from the depth buffer, computes whether the camera is inside the sphere union, and for inside fragments accumulates fog `= 1 - exp(-min(sceneDist, maxDist)/visibility)` tinted by `rgb`, with a low-frequency `nebulaoverlay` sample (projected by view direction) breaking up uniformity. Constants are tunable; correctness = "tinted fog appears with depth, absent when no nebula / camera outside all spheres."

> **Live-tuning note (calibrate up then down):** start the fog strength and noise contribution a touch strong, verify in the Vesuvi4 set, then dial to taste. The constants below are the dials.

- [ ] **Step 1: Write/extend the C++ FrameTest (failing)**

In the existing renderer `FrameTest` suite, add a test that constructs a `NebulaPass`, feeds one `NebulaVolume` (sphere at origin, radius 100, rgb (0.6,0.35,0.72), visibility 50), positions the camera at the centre, renders into the test FBO, and asserts the centre pixel is tinted toward `rgb` versus a no-nebula control render. Follow the existing `dust_pass`/`hologram_pass` FrameTest pattern for FBO setup and pixel readback.

(Use the suite's existing helpers; assert `abs(pixel.b - pixel.r) > threshold` consistent with a purple tint, and that an empty-volume render leaves the control pixel unchanged.)

- [ ] **Step 2: Run it to verify it fails**

Run: `ctest --test-dir build -R FrameTest -V` (or the suite's nebula test name)
Expected: FAIL (pass draws nothing yet).

- [ ] **Step 3: Create `native/src/renderer/shaders/nebula.vert`**

```glsl
#version 330 core
// Fullscreen triangle; no vertex buffer needed (gl_VertexID trick).
out vec2 v_uv;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    v_uv = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
```

- [ ] **Step 4: Create `native/src/renderer/shaders/nebula.frag`**

```glsl
#version 330 core
in  vec2 v_uv;
out vec4 frag;

uniform sampler2D u_scene;      // scene colour
uniform sampler2D u_depth;      // scene depth (non-linear)
uniform sampler2D u_overlay;    // nebulaoverlay.tga (alpha noise)

uniform mat4  u_inv_view_proj;  // clip -> world
uniform vec3  u_eye;            // camera world pos (GU)
uniform float u_near;
uniform float u_far;

// Up to 8 spheres in the union (xyz centre GU, w radius GU).
uniform int   u_sphere_count;
uniform vec4  u_spheres[8];
uniform vec3  u_rgb;
uniform float u_visibility;     // GU falloff
// Tunable dials.
uniform float u_max_fog;        // ceiling on fog alpha (default 0.92)
uniform float u_noise_amount;   // overlay modulation (default 0.35)

vec3 world_from_depth(vec2 uv, float d) {
    vec4 clip = vec4(uv * 2.0 - 1.0, d * 2.0 - 1.0, 1.0);
    vec4 w = u_inv_view_proj * clip;
    return w.xyz / w.w;
}

void main() {
    vec3  scene = texture(u_scene, v_uv).rgb;
    float d     = texture(u_depth, v_uv).r;
    vec3  wp    = world_from_depth(v_uv, d);

    // Inside test: camera inside the sphere union?
    bool inside = false;
    for (int i = 0; i < u_sphere_count; ++i) {
        vec3 c = u_spheres[i].xyz;
        float r = u_spheres[i].w;
        if (dot(u_eye - c, u_eye - c) <= r * r) { inside = true; break; }
    }
    if (!inside) { frag = vec4(scene, 1.0); return; }

    // Distance from eye to the scene fragment (GU). Background (d==1) uses
    // the visibility horizon so the sky also fogs out fully.
    float dist = (d >= 1.0) ? (u_visibility * 4.0) : length(wp - u_eye);
    float fog  = 1.0 - exp(-dist / max(u_visibility, 1.0));

    // Low-frequency overlay breakup, projected on screen for cheapness.
    float n = texture(u_overlay, v_uv * 1.5).a;
    fog *= (1.0 - u_noise_amount) + u_noise_amount * n;
    fog  = clamp(fog, 0.0, u_max_fog);

    frag = vec4(mix(scene, u_rgb, fog), 1.0);
}
```

- [ ] **Step 5: Register the shaders in `native/src/renderer/CMakeLists.txt`**

Add alongside the other `embed_shader(...)` lines:

```cmake
embed_shader(SHADER_NEBULA_VS shaders/nebula.vert nebula_vs)
embed_shader(SHADER_NEBULA_FS shaders/nebula.frag nebula_fs)
```

Ensure the generated `${SHADER_NEBULA_VS}`/`${SHADER_NEBULA_FS}` are added to the renderer target's sources exactly as the dust/backdrop generated headers are (match the existing pattern in that file).

- [ ] **Step 6: Construct the nebula Shader in `pipeline.cc`**

Following `dust_` at `native/src/renderer/pipeline.cc:57`:
- add includes near line 15:
  ```cpp
  #include "embedded_nebula_vs.h"
  #include "embedded_nebula_fs.h"
  ```
- add a member `std::unique_ptr<Shader> nebula_;` to the pipeline (mirror `dust_`) and construct it near line 57:
  ```cpp
  nebula_ = std::make_unique<Shader>(shader_src::nebula_vs, shader_src::nebula_fs);
  ```
- expose it the same way `dust_`/`backdrop_` are reached by their passes (accessor or friend access — match the established convention in this file).

- [ ] **Step 7: Implement `initialize_gl` + inside-fog draw in `nebula_pass.cc`**

Replace the stub body. `initialize_gl` creates an empty VAO (fullscreen triangle needs no VBO) and loads the overlay texture from `volumes[0].internal_tex` lazily. `render`:
- bind the pipeline's nebula shader;
- bind scene-colour + depth textures (obtain from `pipeline` the same way other screen-space passes do — match the dust/lens-flare convention for reaching the scene/depth targets);
- upload `u_inv_view_proj` (`inverse(proj*view)` from `camera`), `u_eye`, `u_near`/`u_far`, the sphere array (clamped to 8), `u_rgb`, `u_visibility`, and the tunable defaults `u_max_fog = 0.92f`, `u_noise_amount = 0.35f`;
- disable depth write/test (it's a composite), draw `glDrawArrays(GL_TRIANGLES, 0, 3)`.

Process volumes in a loop (one fullscreen composite per volume; for the single-nebula Vesuvi/Multi cases this is ≤ a handful). Keep the GLSL the source of truth; the constants above are the only dials.

- [ ] **Step 8: Reconfigure + build (shaders changed!)**

Run:
```bash
cmake -B build -S . && cmake --build build -j
```
Expected: clean build (the `cmake -B` is REQUIRED — shader text is embedded at configure time).

- [ ] **Step 9: Run the FrameTest to verify it passes**

Run: `ctest --test-dir build -R FrameTest -V`
Expected: PASS — centre pixel tinted toward `rgb`; empty-volume control unchanged.

- [ ] **Step 10: Commit**

```bash
git add native/src/renderer/shaders/nebula.vert native/src/renderer/shaders/nebula.frag native/src/renderer/CMakeLists.txt native/src/renderer/pipeline.cc native/src/renderer/nebula_pass.cc native/tests/
git commit -m "feat(nebula): inside depth-aware fog composite"
```

---

## Task 7: Outside billboard shell

**Goal:** When the camera is outside a sphere, draw a soft additive camera-facing billboard (`nebulaexternal.tga`) sized to the sphere so the nebula is visible from a distance; cross-fade into the inside fog as the camera crosses the rim. Depth-test against hulls so ships in front occlude the cloud.

**Files:**
- Modify: `native/src/renderer/shaders/nebula.vert`, `nebula.frag` (add a billboard mode, or a second shader pair `nebula_shell.*`)
- Modify: `native/src/renderer/CMakeLists.txt` (if a second shader pair is added)
- Modify: `native/src/renderer/nebula_pass.cc` (shell draw)
- Modify: `native/src/renderer/pipeline.cc` (construct the shell Shader if separate)
- Test: C++ `FrameTest` (camera-outside case)

**Interfaces:**
- Consumes: same `NebulaVolume` list + camera; the from-outside texture `external_tex`.
- Produces: additive billboard shell rendered when the camera is outside a given sphere, fading near the rim.

**Approach:** for each sphere, when `dist(eye, centre) > radius`, draw a camera-facing quad centred on the sphere, scaled to `~radius`, sampling `nebulaexternal.tga`, additive-blended, with edge falloff (`smoothstep` on radial UV) and a rim cross-fade factor `clamp((dist - radius) / (rimBand), 0, 1)` so it dissolves as you approach/enter (the inside fog takes over). Depth-test enabled (`GL_LEQUAL`), depth-write disabled, additive blend.

> **Live-tuning note:** bias the shell brightness and `rimBand` strong first in Vesuvi4 (so the cloud reads clearly from a distance), then dial back.

- [ ] **Step 1: Add the camera-outside FrameTest (failing)**

Extend the FrameTest from Task 6: place the camera OUTSIDE the sphere (e.g. at distance `2*radius` looking at the centre), render, and assert the centre region is brighter than the no-nebula control (additive cloud present). Assert that with the camera INSIDE, the shell does not double-bright the centre (shell suppressed inside).

- [ ] **Step 2: Run it to verify it fails**

Run: `ctest --test-dir build -R FrameTest -V`
Expected: FAIL (no shell drawn yet).

- [ ] **Step 3: Add the shell shader**

Create `native/src/renderer/shaders/nebula_shell.vert` (camera-facing billboard):

```glsl
#version 330 core
layout(location = 0) in vec2 a_corner;   // [-1,1] quad corner
uniform mat4  u_view;
uniform mat4  u_proj;
uniform vec3  u_center;   // sphere centre (GU)
uniform float u_size;     // ~sphere radius (GU)
out vec2 v_uv;
void main() {
    // Build a camera-facing basis from the view matrix rows.
    vec3 right = vec3(u_view[0][0], u_view[1][0], u_view[2][0]);
    vec3 up    = vec3(u_view[0][1], u_view[1][1], u_view[2][1]);
    vec3 wp = u_center + (right * a_corner.x + up * a_corner.y) * u_size;
    v_uv = a_corner * 0.5 + 0.5;
    gl_Position = u_proj * u_view * vec4(wp, 1.0);
}
```

Create `native/src/renderer/shaders/nebula_shell.frag`:

```glsl
#version 330 core
in  vec2 v_uv;
out vec4 frag;
uniform sampler2D u_external;   // nebulaexternal.tga
uniform vec3  u_rgb;
uniform float u_rim_fade;       // [0,1] 0 = at rim (suppressed), 1 = far
uniform float u_brightness;     // tunable (default 1.0)
void main() {
    vec2 d = v_uv * 2.0 - 1.0;
    float r = length(d);
    float edge = 1.0 - smoothstep(0.6, 1.0, r);     // soft circular falloff
    vec3 tex = texture(u_external, v_uv).rgb;
    float a = edge * u_rim_fade * u_brightness;
    frag = vec4(tex * u_rgb * a, a);                // additive (see blend setup)
}
```

- [ ] **Step 4: Register shell shaders in CMake**

```cmake
embed_shader(SHADER_NEBULA_SHELL_VS shaders/nebula_shell.vert nebula_shell_vs)
embed_shader(SHADER_NEBULA_SHELL_FS shaders/nebula_shell.frag nebula_shell_fs)
```

Add the generated headers to the renderer sources as before; construct a `nebula_shell_` `Shader` in `pipeline.cc` next to `nebula_`.

- [ ] **Step 5: Implement the shell draw in `nebula_pass.cc`**

In `render`, before (or after) the inside-fog composite, loop spheres; for each where `length(eye - centre) > radius`:
- compute `rim_fade = clamp((dist - radius) / (radius * 0.5), 0, 1)` (the `0.5` band is tunable);
- bind the shell shader + `external_tex` texture (load lazily, cached);
- set blend `glBlendFunc(GL_ONE, GL_ONE)` (additive), `glDepthMask(GL_FALSE)`, `glEnable(GL_DEPTH_TEST)`, `glDepthFunc(GL_LEQUAL)`;
- upload `u_view`,`u_proj`,`u_center`,`u_size = radius`,`u_rgb`,`u_rim_fade`,`u_brightness = 1.0f`;
- draw the unit quad (a small static VBO of 4 corners created in `initialize_gl`).

Restore GL state (blend func, depth mask) afterward.

- [ ] **Step 6: Reconfigure + build**

Run:
```bash
cmake -B build -S . && cmake --build build -j
```

- [ ] **Step 7: Run FrameTest to verify it passes**

Run: `ctest --test-dir build -R FrameTest -V`
Expected: PASS — outside-camera centre brighter than control; inside-camera shell suppressed.

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/shaders/nebula_shell.vert native/src/renderer/shaders/nebula_shell.frag native/src/renderer/CMakeLists.txt native/src/renderer/pipeline.cc native/src/renderer/nebula_pass.cc native/tests/
git commit -m "feat(nebula): outside billboard shell + rim cross-fade"
```

---

## Task 8: Live verification in the Vesuvi4 set

**Goal:** Confirm the full feature end-to-end in a real set. No automated test — hand the build to Mark to drive (no desktop interaction on his workstation).

**Files:** none (verification only).

- [ ] **Step 1: Build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: clean.

- [ ] **Step 2: Prepare the verification checklist for handoff**

Document for Mark to drive (load the **Vesuvi4** set via `--developer` → Load Mission / set loader):
1. From outside: the nebula reads as a soft purple cloud (shell) at the sphere.
2. Flying in: shell cross-fades to inside depth-fog; distant asteroids/ships recede into the murk; the sky fogs out.
3. Hull damage ticks while inside (~150/s); shields drain (~20/s); both stop on exit.
4. Sensors shorten while inside (Vesuvi `10.5` clamps → no penalty there; verify the penalty in **Multi5**/**Multi6**, density `0.5`).
5. Warp is blocked inside (existing `_in_nebula` gate — regression check).
6. Asteroids ("Unknown Debris") take NO damage (IgnoreEvent opt-out).
7. Toggle/scene with no nebula renders byte-identical to before (stock BC).

- [ ] **Step 3: Record results + tune**

After Mark drives it, capture which dials need adjustment (fog strength `u_max_fog`/`u_noise_amount`, shell `u_brightness`/rim band) and apply, rebuilding with `cmake -B build -S .` after any shader edit. Commit any tuning:

```bash
git add native/src/renderer/
git commit -m "tune(nebula): fog/shell dials per live verification"
```

---

## Self-Review

**Spec coverage:**
- §3 model getters + `MetaNebula_Cast` → Task 1 ✓
- §4 enter/exit events → Task 2 ✓
- §4 environmental damage (dt-scaled, IgnoreEvent opt-out) → Task 3 ✓
- §4 sensor-density scaling ([0,1] clamp) → Task 3 ✓
- §4 host-loop integration, mission-swap reset, no-damage-at-pause → Task 4 ✓
- §3/§4 render data scraper + binding → Task 5 ✓
- §2 forward-compat `nebula_style` enum seam → Task 5 (`NebulaPass::Style`) ✓
- §2 inside depth-aware fog → Task 6 ✓
- §2 outside billboard shell + rim cross-fade → Task 7 ✓
- §5 testing (pytest units, FrameTest, live Vesuvi4) → Tasks 1-3,5,6,7,8 ✓
- Global: byte-identical stock BC when no nebula → empty-list early-outs in `_aggregate_nebulae`, tracker, and pass ✓

**Placeholder scan:** No TBD/TODO. Native steps that reach pipeline scene/depth targets say "match the established convention" because the exact accessor must follow the in-file pattern (dust/lens-flare) rather than an invented signature — the reviewer between tasks confirms it. All Python steps carry complete code.

**Type consistency:** `MetaNebula_Cast`, `GetTintRGB/GetVisibility/GetSensorDensity/GetInternal/ExternalTexture/GetDamage`, `NebulaTracker.update(pSet, ships, dt)/reset()`, `_aggregate_nebulae(pSet)`, `set_nebulae(list)`, `NebulaVolume{spheres,rgb,visibility,external_tex,internal_tex}`, `NebulaPass::render(camera,pipeline,volumes)` — names match across all tasks.
