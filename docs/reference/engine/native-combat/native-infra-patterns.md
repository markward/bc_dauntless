> Snapshot map written 2026-10-31 at commit 7c6ece598: the native patterns (TransformStore, torpedo_scan, bindings, CMake flags, passive descriptors, step_memo, differential tests) the native combat step follows. Line numbers drift.

# Native combat mirror: infrastructure map

Worktree root: /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/anim-visibility (paths below are relative to it).

## 1. TransformStore

Files:
- `native/src/transforms/include/dauntless/transform_store.h` (162 lines): class `dauntless::TransformStore`.
- `native/src/transforms/src/transform_store.cc` (alloc/free/check/getters).
- `native/src/transforms/src/proximity_query.cc` (unfused kernels).
- Process-wide singleton: `TransformStore& transform_store();` (declared at the end of the header, defined in transform_store.cc).

Storage and handles (`transform_store.h`, private section):
```cpp
std::vector<Transform> slots_;            // struct Transform { double pos[3]; double rot[9]; }  (row-major rot)
std::vector<std::uint32_t> generations_;
std::vector<std::uint32_t> free_;
std::uint32_t live_ = 0;
```
- A handle is the pair `(index, generation)` of uint32. `alloc()` returns `std::pair<uint32_t,uint32_t>`.
- `free(index, gen)` bumps the generation immediately on free and again on reuse, so a stale handle fails at once. A stale handle throws `StaleHandle` (a `std::runtime_error`), which pybind surfaces as `RuntimeError`.
- Callers hold indices, never pointers, because the backing vector reallocates. `at(index)` is the unchecked accessor; do not retain a reference across `alloc()`.
- The header says it is NOT internally synchronised. The threaded integrator was meant to work on disjoint slots with the GIL released.
- Storage is double, because a Python float is a C double.

Python side:
- `engine/appc/transform_store.py`: two backends, one contract. `PythonTransformStore` (flat list, `_STRIDE = 12`) and `NativeTransformStore(_h)`, which is `__slots__ = ("_h",)` and forwards to `_h.transform_*`.
- `get_store()` at transform_store.py:313-329 picks Native when `_dauntless_host` imports and `hasattr(_h, "transform_alloc")`, resolved at USE.
- `_reset_store_for_tests()` at :332 only drops the Python wrapper. The C++ singleton and its slots survive.

Registration:
- `engine/appc/objects.py:100` in `ObjectClass.__init__`: `self._xform = _store.alloc()`.
- Free path, objects.py:104-110: `weakref.finalize(self, _release_transform_slot, _store, self._xform)`, with `.atexit = False`. `_release_transform_slot` (objects.py:68-77) swallows every exception.
- Not `__del__`, because ObjectClass instances sit in reference cycles (event handlers).
- Writes: `get_store().set_position(*self._xform, x, y, z)` (objects.py:321 etc.) and `set_rotation(*self._xform, m.as_tuple())` (:402). Reads are `get_position`, `get_rotation`, `get_rotation_col`.
- Renderer binding: `host_io.set_instance_transform_slot(iid, idx, gen, scale)` (host_loop.py:6514).

Lifecycle on mission swap:
- There is NO store reset. The tests/conftest.py:1957-1969 comment says the store is deliberately not reset, and the rule is that every test that allocates a handle frees it.
- Slots die when the Python object is collected (finalizer).
- Mission swap and fresh-world tests rely on GC. A mirror registered per object therefore needs its own explicit clear, with the same shape as `torpedo_scan_clear`, plus a finalizer path.

Native binding functions (`native/src/host/host_bindings.cc`, section "Transform store" at ~9014):
- `transform_alloc`, `transform_free`, `transform_get_position`, `transform_set_position`, `transform_get_rotation`, `transform_set_rotation`, `transform_get_rotation_col`, `transform_get_positions`, `transform_within_radius`, `transform_proximity_report`, `transform_sweep_candidates`, `transform_live_count`, `transform_capacity`.

## 2. Existing native queries: proximity_query.cc and torpedo_scan.cc

**Files**
- `native/src/transforms/src/proximity_query.cc` (84 lines) holds `TransformStore::within_radius`, `TransformStore::proximity_report` and the free function `sweep_candidates`. It has its own translation unit "so they can be compiled with -ffp-contract=off".
- `native/src/transforms/src/torpedo_scan.cc` (135 lines) and `native/src/transforms/include/dauntless/torpedo_scan.h` (90 lines).
- Static library `dauntless_transforms`.

**Exactness flags** (`native/src/transforms/CMakeLists.txt`, verbatim):
```cmake
add_library(dauntless_transforms STATIC
    src/transform_store.cc
    src/torpedo_scan.cc
    src/proximity_query.cc
)
target_include_directories(dauntless_transforms PUBLIC include)
target_compile_features(dauntless_transforms PUBLIC cxx_std_20)
target_link_libraries(dauntless_transforms PUBLIC glm)
if(NOT MSVC)
    set_source_files_properties(src/torpedo_scan.cc src/proximity_query.cc
        PROPERTIES COMPILE_OPTIONS "-ffp-contract=off")
endif()
```
- The flag is PER SOURCE FILE, not per target, and non-MSVC only.
- Each file also has the belt-and-braces pragma:
```cpp
#if defined(__clang__)
#pragma clang fp contract(off)
#endif
```
- `rockgen` sets it per target: `native/src/rockgen/CMakeLists.txt:20` has `target_compile_options(rockgen PRIVATE -ffp-contract=off)`.
- For MSVC, `/fp:precise` is the default and contraction is off. No MSVC arm exists in transforms.

**Per-file Debug optimisation precedent** (`native/src/lottie/CMakeLists.txt:11-26`):
```cmake
if(MSVC)
    string(REGEX REPLACE "/RTC[1csu]+|/Od|/Ob0" "" CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG}")
    set_source_files_properties(src/lottie_clip.cc src/panel_worker.cc PROPERTIES
        COMPILE_OPTIONS "$<$<CONFIG:Debug>:/Od>;$<$<CONFIG:Debug>:/Ob0>;$<$<CONFIG:Debug>:/RTC1>")
    set_source_files_properties(src/panel_math.cc PROPERTIES
        COMPILE_OPTIONS "$<$<CONFIG:Debug>:/O2>")
else()
    set_source_files_properties(src/panel_math.cc PROPERTIES
        COMPILE_OPTIONS "$<$<CONFIG:Debug>:-O2>")
endif()
```
- This is the only existing "optimised inside Debug" pattern, and it is exactly what spec §7.6.5 needs. Combine it with `-ffp-contract=off` in the same `COMPILE_OPTIONS` list.
- Caveat: `set_source_files_properties(... COMPILE_OPTIONS ...)` REPLACES the value if called twice for one file, so build one combined list.
- Caveat: the MSVC arm rewrites the directory-scope `CMAKE_CXX_FLAGS_DEBUG`.
- No global -O flags elsewhere. `native/CMakeLists.txt:223-235` only sets MSVC `/O2 /Ob2` for Release.

**Binding** (pybind11, one file):
- `native/src/host/host_bindings.cc` is compiled into BOTH targets (`build/dauntless`, via `HOST_BINDINGS_SOURCES` in `native/src/host/CMakeLists.txt`, and the `_dauntless_host` module).
- `PYBIND11_MODULE(_dauntless_host, m)` at host_bindings.cc:3427.
- `#include "dauntless/torpedo_scan.h"` at :19. The transform store header is reached via it.
- Targets link `dauntless_transforms` (host/CMakeLists.txt: `_dauntless_host` PRIVATE list and the `dauntless` list).
- A new kernel library must be added to BOTH link lists. A new header should be included near :19 and new `m.def`s appended after the torpedo_scan block, which ends at the end of the module body (~:9210).

Binding styles to copy:
- Buffer-protocol args (no copies): `transform_within_radius`, `transform_proximity_report` (:9072-9124), `transform_sweep_candidates` (:9126-9158).
  - Take `py::buffer`, call `.request()`, validate `itemsize` and `size` (throw `py::value_error`), cast `info.ptr`, and return `py::list` or `py::bytes`.
  - Python passes `array('d')`, `array('I')`, `array('i')`, `bytearray`.
- Scalar setters (:9172-9194): the `torpedo_scan_add/remove/set_velocity/set_source/set_group/clear/size` lambdas, each one line forwarding to `dauntless::torpedo_scan()`.
- `torpedo_scan_incoming` (:9195-9212) takes `std::array<double,3>` and `std::vector<std::tuple<...>>` via `pybind11/stl.h`.

**State reading:**
- `TorpedoScan` holds `const TransformStore&` and rows with the transform handle `(xi, xg)`, then reads the store LIVE: `store_.valid(r.xi, r.xg)` then `store_.at(r.xi).pos`. No position copies. Velocity, source and group are mirrored by setters.
- `TorpedoScan` is a row table: `std::vector<Row>` plus `unordered_map<int64,size_t> index_`. `remove` tombstones (`alive=false`) and compacts when dead > 64 and dead*2 > size. Results come back in insertion order.
- Singleton: `TorpedoScan& torpedo_scan() { static TorpedoScan scan(transform_store()); return scan; }`.
- `proximity_report`/`sweep_candidates` take arrays from Python each call.

**GIL:**
- NO GIL release in any of the transform/proximity/torpedo bindings. They are plain synchronous lambdas.
- The only `py::gil_scoped_release` in host_bindings.cc is `pick_folder` (:3474). `gil_scoped_acquire` appears at :8950 and :8969 (callbacks).
- If the new kernels want to release the GIL, they will be the first. They must then touch only native memory.

**C++ unit tests:** `native/tests/transforms/torpedo_scan_test.cc` uses a local `TransformStore store; TorpedoScan scan{store};` in a `Fixture` struct, and does not use the singleton.

## 3. Python facade and headless pytest

- `engine/host_io.py` (guarded import at :31-34):
  ```python
  try:
      import _dauntless_host as _h
  except ImportError:
      _h = None  # bindings module not built; headless — wrappers no-op.
  ```
- Manifest: `_REQUIRED_BINDINGS` (:~44) is called hard. `_OPTIONAL_BINDINGS` is soft-guarded with `getattr(_h, "NAME", None)`.
- `validate_bindings()` checks them at real-host boot only, never at import. `tests/unit/test_host_io_binding_manifest.py` derives ground truth from `_h.NAME` references in host_io.py, so any `_h.NAME` added to host_io.py must be added to a manifest.
- The transform and torpedo_scan bindings are NOT called through host_io. They go through `engine/appc/transform_store.py` (`NativeTransformStore(_h)`) and `engine/appc/torpedo_scan.py` (`NativeTorpedoScan(_h)`), each of which does its own `import _dauntless_host`. `torpedo_scan_*` is not in the host_io manifest. A new mirror module should follow the torpedo_scan.py shape.
- Two-backend selection in `engine/appc/torpedo_scan.py`:
  - `get_scan()` (bottom of the file) is resolved at USE and re-resolved if the store singleton changed. It picks `NativeTorpedoScan(store._h)` when the store is a `NativeTransformStore`, otherwise `PythonTorpedoScan(store)`.
  - The Python backend is a bit-exact twin. A mirror's Python twin is therefore the existing pure-Python combat step, selected by `DAUNTLESS_NATIVE_COMBAT=0` or by the module being absent.
- Headless pytest gets the `.so` from `tests/conftest.py:60-65`:
  ```python
  _BUILD_PYTHON = PROJECT_ROOT / "build" / "python"
  if _BUILD_PYTHON.is_dir() and str(_BUILD_PYTHON) not in sys.path:
      sys.path.insert(0, str(_BUILD_PYTHON))
  ```
- The `.so` is NOT required. Tests degrade to the Python backend if the import fails.
- Native-specific tests skip. Pattern from `tests/unit/test_torpedo_scan_conformance.py:20-52`:
  ```python
  try:
      import _dauntless_host as _h
  except ImportError:
      _h = None
  _HAS_NATIVE = _h is not None and hasattr(_h, "torpedo_scan_add")
  pytest.param(_native_scan, id="native", marks=pytest.mark.skipif(
      not _HAS_NATIVE, reason="native torpedo_scan bindings not built"))
  ```
  Keying on `hasattr(_h, "<new fn>")` also skips on a stale `.so`.
- Conformance tests run BOTH backends against one contract (`test_transform_store_conformance.py`, `test_torpedo_scan_conformance.py`). The latter also compares against the reference Python walk over randomised fights with borderline thresholds.
- `tests/conftest.py:1253,1265` call `_host.<fn>` for process-lifetime C++ globals in `_reset_leakable_engine_globals`. A new C++ mirror singleton needs a clear call there, wrapped in `try/except`.

## 4. C++ test layout

- `native/tests/CMakeLists.txt` fetches googletest v1.14.0 and `include(GoogleTest)`. Subdirs are added at :68-78: assets, lottie, platform, renderer, scenegraph, audio, voxel, rockgen, **transforms**, host, ui_cef.
- `native/tests/transforms/CMakeLists.txt` (verbatim, entire file):
  ```cmake
  add_executable(transform_store_tests
      transform_store_test.cc
      torpedo_scan_test.cc
  )
  target_link_libraries(transform_store_tests
      PRIVATE
          dauntless_transforms
          GTest::gtest_main
  )
  gtest_discover_tests(transform_store_tests)
  ```
  Adding a test file means appending it to the `add_executable` list. A new kernel library goes in `target_link_libraries`.
- `native/tests/host/CMakeLists.txt` defines the `host_tests` target. It links `dauntless_host_core` and GTest. It has no transforms link.
- The test binaries build with `-O0` (Debug), without `-ffp-contract=off`. Kernel sources compiled into a library get their own per-source flags, so tests of the kernel through the library are fine. A test that includes kernel code inline would not get them.
- The gate (`scripts/check_tests.sh`) runs ctest plus an in-process pass of each gtest binary. Do not run it during development.

## 5. WakeField, switch and audit

> **Power is native only now** (phase 6 A1 Task 8, 2026-11-05). The
> passive-power half this section used to describe -- `FrozenField`,
> `engine/appc/passive_power.py`, the per-plant draw program, its thaw and its
> `audit_compare` reference run -- is deleted, with the Python subsystem
> stage it optimised (subsystem_step.h THE POWER PIECE is the one
> implementation). What remains is the weapons half: `WakeField` and the
> sleep audit, K0's Python reference path. Quotes below of deleted code are
> marked as history.

WakeField, verbatim from `engine/appc/passive_state.py:51-63`:
```python
class WakeField:
    """Data descriptor with no __get__: reads stay plain instance-dict reads,
    every write (even of an equal value) wakes a sleeping owner."""

    def __set_name__(self, owner, name) -> None:
        self._name = name

    def __set__(self, obj, value) -> None:
        obj.__dict__[self._name] = value
        if obj.__dict__.get("_passive_asleep", False):
            wake(obj)
```

FrozenField (HISTORY: deleted in phase 6 Task 8), as it was in
`engine/appc/passive_power.py:38-48`:
```python
class FrozenField:
    def __set_name__(self, owner, name) -> None:
        self._name = name

    def __set__(self, obj, value) -> None:
        obj.__dict__[self._name] = value
        if obj.__dict__.get("_power_frozen"):
            obj._passive_power_thaw()
```
- Usage: `_charge_level = WakeField()` (weapon_subsystems.py:685). The seven PoweredSubsystem fields that were FrozenFields (`_is_on` and six more) are plain `NativeField`s since Task 8.
- Key design point: no `__get__`, so the value lives in `obj.__dict__[name]` and reads are plain dict reads. It is a data descriptor (`__set__` defined), so it intercepts writes. `__init__`'s first assignment also goes through `__set__`.
- Instances need no registration. State is a flag in `obj.__dict__` (`_passive_asleep`; `_power_frozen` was the deleted power half's). Hooks are the optional `_passive_on_sleep/_passive_on_wake` methods.
- For a `NativeField` the per-instance mirror slot index could be kept in `obj.__dict__` the same way.
- Bypass trap (spec §7.1): in-place mutation such as `_current_shields[f] = v` does not trigger `__set__`.

Registry reset:
- Module-level state in passive_state.py: `_enabled`, `_audit`, `_failures`, `_counts`. `reset()` at :28-35 restores the defaults (enabled True, audit False) and clears failures.
- Test reset: `tests/conftest.py` (in `_reset_leakable_engine_globals`):
  ```python
  from engine.appc import passive_state as _passive_state
  _passive_state.reset()
  ```
  (It also reset `passive_power` until Task 8 deleted it.)

How the env switch is read once per GameLoop start:
- `engine/core/loop.py:25-26`:
  ```python
  def __init__(self) -> None:
      passive_state.configure()
  ```
- `passive_state.py:14-18`:
  ```python
  def configure(environ=os.environ):
      global _enabled, _audit
      _enabled = environ.get("DAUNTLESS_PASSIVE_STATE") != "0"
      _audit = environ.get("DAUNTLESS_PASSIVE_AUDIT") == "1"
  ```
- Constructing a `GameLoop` re-reads the environment, so tests call `passive_state.configure({...})` AFTER `headless_mission.load(...)`, which builds a GameLoop.
- `DAUNTLESS_NATIVE_COMBAT` / `DAUNTLESS_NATIVE_AUDIT` should copy this: `configure(environ)` called from `GameLoop.__init__`, `enabled()`/`audit_enabled()` getters, `reset()` wired into conftest.

Audit pattern:
- `audit_step(obj, step)` (passive_state.py:~112) snapshots `vars(obj)` (and `_passive_audit_children`), runs the step, diffs, appends `(TypeName, field)` to `_failures`, then RESTORES the state.
- `audit_compare(objs, reference, step)` (~:131) snapshots, runs `reference()`, snapshots `after`, restores, runs `step()`, diffs against `after`. It skips fields in the object's `_passive_audit_ignore` and leaves the state `step` produced.
- Scalar comparison `_unchanged` (:~96-104) compares floats by `.hex()`, so -0.0 is distinct from 0.0. Containers compare by identity.
- Call sites: `passive_weapons.py:147` (`audit = passive_state.audit_enabled()`, then `audit_step(weapon, lambda: update(dt))` at :175). The power draw program's `audit_compare` call site went with `passive_power.py` (Task 8); `audit_compare` itself remains in passive_state.py.
- Surfaced via `passive_state.audit_failures()`, asserted `== []` in tests (`tests/host/test_passive_state_scene_audit.py`, `tests/unit/test_passive_state.py`). `counts()` proves the mechanism actually ran (slept/woke > 0).
- Audit failures are only recorded; nothing is logged to stderr or raised at runtime.

## 6. engine/core/step_memo.py (verbatim) and forget() call sites

```python
"""Answers that hold for a stretch of the combat step. [docstring trimmed here; see file]"""
import contextlib

_depth = 0
_tables: list = []


def table() -> dict:
    """A dict this module empties on forget() and when the outermost block
    closes. Callers keep it and read it only while active()."""
    t = {}
    _tables.append(t)
    return t


def active() -> bool:
    return _depth > 0


def forget() -> None:
    """Something an answer may depend on changed: drop them all."""
    for t in _tables:
        t.clear()


@contextlib.contextmanager
def combat_step():
    """Open (or join) a block. The outermost block's exit drops every
    answer, so the objects keyed by id() never outlive it."""
    global _depth
    _depth += 1
    try:
        yield
    finally:
        _depth -= 1
        if _depth == 0:
            forget()
```
(The file is 50 lines. The module docstring says the tables are `engine.appc.sensor_detection` can_detect per observer/target pair and `engine.appc.subsystems` mount world position.)

All `forget()` call sites (7):
- `engine/host_loop.py:1119`: after `cb.vfx`, before `cb.death`.
- `engine/host_loop.py:1130`: after `cb.death`, before `cb.damage_sys`.
- `engine/host_loop.py:1146`: after `cb.damage_sys`, before `cb.held_weapons`.
- `engine/host_loop.py:1308`: before `cb.tractors`.
- `engine/host_loop.py:1312`: after `cb.tractors`.
- `engine/appc/combat.py:617` and `:621`: `apply_hit` wrapper, in `try/finally` around `_apply_hit(*args, **kwargs)`.
- The `combat_step()` context exit also calls it implicitly when depth returns to 0.
- Note: there is no forget between `cb.projectiles`' `apply_hit` loop and `cb.vfx`, but `apply_hit` forgets itself.
- The memo is not forgotten on a write-through to a mirrored field. The spec's epoch counter would be a new thing alongside it. `table()` registers a per-module dict in the module-global `_tables` list, which is never cleared.

## 7. Test infrastructure for differentials and audit

### `tests/host/test_passive_state_scene_audit.py` (whole file is ~50 lines)
- Autouse fixture `monkeypatch.setenv("DAUNTLESS_MODS_DIR", str(tmp_path / "empty_mods"))` for hermetic mods scan.
- Skips unless BC assets exist: `galaxy = (bc_assets.GAME_ROOT / "data"/"Models"/"Ships"/"Galaxy"/"Galaxy.nif")`, `pytest.skip("BC assets not available")`. Helper: `tests/helpers/bc_assets.py`.
- Env: `OPEN_STBC_HOST_HEADLESS=1`, `DAUNTLESS_COMBAT_SHIPS=16`, `DAUNTLESS_PASSIVE_AUDIT=1`, and delenv of `DAUNTLESS_PASSIVE_STATE`.
- Fake clock: `monkeypatch.setattr(hl, "_frame_clock", clock)` with `now[0] += 0.1`, so 6 ticks per frame.
- Run: `assert hl.run("engine.dev_missions.combat_stress", max_ticks=120) == 0`.
- Assertions: `passive_state.enabled()`, `audit_failures() == []`, and `counts()["slept"] > 0 and ["woke"] > 0`, so the audit provably exercised the mechanism. Since Task 8 it also runs the native subsystem stage and asserts `native_subsystems.skip_counts() == {}` (the `passive_power.counts()` asserts went with the module).

### `test_passive_weapons_differential.py` (and, until Task 8 deleted it, `tests/integration/test_passive_power_differential.py`)
- Constants: `SHIPS="6"`, `TICKS=600`, `SEED=20261030`, `OP_CHANCE=0.08`, `KINDS=(...)`.
- Helper `_hex(v) = float(v).hex()`: bitwise float compare.
- `_Scene(monkeypatch, passive, audit=True)` per run:
  1. `monkeypatch.delenv` for the switch and audit vars.
  2. `monkeypatch.setenv("DAUNTLESS_COMBAT_SHIPS", SHIPS)`.
  3. `App.g_kTimerManager._time = 0.0`; `random.seed(0)`.
  4. `headless_mission.load("engine.dev_missions.combat_stress")` (`tests/helpers/headless_mission.py`: `_fresh_world()` plus `host_loop._init_mission(name)`).
  5. AFTER the load, `passive_state.configure({...})`, because constructing a GameLoop re-reads the environment. Reference run: `{"DAUNTLESS_PASSIVE_STATE": "0"}`. Optimised run: `{"DAUNTLESS_PASSIVE_AUDIT": "1"}` or `{}`.
  6. `self.ships = list(iter_ships())` (from `engine.appc.ship_iter`).
- Two runs, same seed, each inside `with monkeypatch.context() as mp:` so env and patches unwind. `_both(...)` returns `(reference, passive)` logs.
- Op stream: its own `random.Random(SEED)`, separate from module `random` (AI uses unseeded module `random`, hence the explicit `random.seed(0)`).
  - `op(rng)` picks a kind and applies it through the public SDK API: `SetPowerPercentageWanted`, `TurnOff`, `StealPower`, `StartCloaking`, `Fire`, `StopFiring`, `SetChargeLevel`, and so on.
  - Ops are applied only between frames, at a rate scaled by `ticks_per_frame`, plus mid-burst ops in the weapons version (`if rng.random() < 0.3: self.op(...)` after `_advance_weapons`).
- Driving the sim (NO GameLoop.tick, because AI draws on unseeded random):
  - Power: `App.g_kTimerManager._time += TICK_DELTA; game_loop._update_ship_subsystems()`.
  - Weapons: `host_loop._advance_weapons(self.ships, TICK_DELTA)`.
  - For combat: `host_loop._advance_combat(...)` (signature near host_loop.py:1060-1075, with `ships`, `dt`, `ship_instances`, `push_render_data`). A combat differential should call it directly, probably within `step_memo.combat_step()`.
  - `TICK_DELTA` is imported from `engine.core.loop`.
- `record()` captures a row per tick:
  - Power: `_hex(...)` of every SDK getter on every plant and consumer.
  - Weapons: tuples `(GetChargeLevel(), IsFiring(), _depleted, _cooldown_remaining)` and `(GetNumReady(), tuple(_reload_timers))`.
  - Rows are compared with `==` per tick, with the message "state differs at tick %d".
- Event log capture (weapons file): wrap `App.g_kEventManager.AddEvent` via `monkeypatch.setattr`, record `(kind, dest.GetName(), self.tick)` for chosen event types (`ET_TORPEDO_RELOAD`, `ET_WEAPON_FIRED`, the pulse charge-toggle type). Compare the event lists too. The pulse charge-toggle type is obtained from `Conditions.ConditionPulseReady.ET_CHARGE_TOGGLE`.
- Weapon walking helper `_walk(ships)` at test_passive_weapons_differential.py:43. Enemy selection by name prefix `"Enemy"`.
- Parametrised over `seed` and `ticks_per_frame` (1 and 6), plus a no-audit "production shape" case.
- `_assert_identical` also asserts the mechanism ran (`counts["program_ticks"] > 0`, `["thawed"] > 0`) and `audit_failures() == []`. A "reference never used the optimised path" assert is present: `passive_power.counts()["program_ticks"] == 0` after the reference run.
- A new combat differential can copy `_Scene`/`_both`/`_hex`/`record`, swapping the switch for `DAUNTLESS_NATIVE_COMBAT`. The reference arm is `{"DAUNTLESS_NATIVE_COMBAT": "0"}`.
- Other helpers worth reusing: `tests/helpers/fresh_world.py`, `tests/helpers/torpedo_fixtures.py`, `tests/helpers/shielded_ship.py`, `tests/helpers/beams.py`, `tests/helpers/one_set.py`, `tests/helpers/cloak_geometry.py`, `tests/helpers/sensor_time.py`.
- Torpedo differentials: `tests/unit/test_torpedo_scan_conformance.py` is the template (randomised fights, borderline thresholds).

## 8. frame_profiler scopes

- `engine/core/frame_profiler.py` has a top-of-file docstring (the model: flat `mark()` phases with nested `scope()` tree) and `@contextmanager def scope(name)` at :269.
  - It is a no-op when disabled, but costs ~0.36 us for the generator even then, so only use it at seams, never per ship.
  - The parent is whatever scope or mark is open at entry, re-recorded each entry.
  - A name entered twice in one frame sums.
- No registration or declaration is needed: just `with frame_profiler.scope("cb.something"):` and the name appears.
- `PER_TICK_ROOTS = frozenset({"sim.gameloop"})` (:~116) is the only declared set. It marks rows summed per catch-up tick. `sim.combat` and `cb.*` are once per frame, outside that loop.
- Usage in host_loop.py: `with frame_profiler.scope("cb.eligibility")` (:1092), `cb.projectiles` (:1095), `cb.vfx` (:1111), `cb.death` (:1120, children `death.ship`, `death.lights`, `death.lifetime`), `cb.damage_sys` (:1131, children `dmg.cascade`, `dmg.core_breach`, `dmg.visible`, `dmg.internal_blast`), `cb.held_weapons` (:1147, wraps `_pump_held_weapons(ships_list, dt)`), `cb.phasers` (:1155), `cb.tractors` (:1309), `cb.render_data` (:1330). `sim.combat` is opened at host_loop.py:12526.
- GameLoop tick scopes use the `gl.*` prefix (`engine/core/loop.py`: `gl.timers.game`, `gl.ai`, ...), imported as `from engine.core import frame_profiler as _prof`.
- Convention for new scopes: `cb.native_*` children nested under the existing `cb.*` scope, plus a mirror-sync scope if write-through cost is to be measured. The spec's bar is that total `sim` per tick is not higher.

## 9. Write-back and push paths (added 2026-11-02, weapon-state phase)

Added with `docs/superpowers/specs/2026-11-02-native-weapon-state-design.md` (§4.1, §4.2, outcome §10). Current as of `1d714e767`.

**C-applied write logs** (`native/src/host/combat_write_apply.{h,cc}`; Python side `_applier_context`, `_ApplyKinds` in `engine/appc/native_combat.py`):
- A driver installs an applier context per session with `combat_set_applier(ctx)`, which returns the previous context; the driver restores it in `finally`, so a nested session (a K1 `StartFiring` inside a K0 or K2 record) swaps in its own. With a context installed, `combat_k0_next`, `combat_k1_next` and `combat_k2_next` apply a record's writes in C before returning it and return the record without them. With none, the bindings return the log as before.
- Apply kinds, keyed by (class, field), computed once from `_quiet_setter` (the same field can be WAKE on a phaser bank, PYTHON on a tractor beam, PLAIN on a tube): `APPLY_PLAIN` (dict store), `APPLY_REF` (handle → object: pins, else registry with the `_nslot` check; −1 → None), `APPLY_REFS` (a NEW list each write), `APPLY_WAKE` (store, then `passive_state.wake` if `_passive_asleep`), `APPLY_PYTHON` (call the quiet setter: thaw descriptors, anything unrecognised), `APPLY_SLOT` (K0: `obj.<list>[i] = v` in place), `APPLY_WATCHER` (K0: the watcher's `_value`, no crossing check). The walk-offset marker calls `walk.materialise` as `apply_writes` does. Kinds are fixed for the session, like `_quiet_setters`' per-class cache.
- **Presentation queue (effect-queue spec 2026-11-02).** K2's records no longer carry resting contacts, so every K2 record's writes are applied whole before it is returned, like K0's and K1's (the pending-segment path and `combat_apply_writes` are gone). Resting contacts go to a per-session queue (`K2Rest`, carrying everything a Python effect could change: power level, shields answer, instance id, view offset) that `combat_k2_drain()` empties after `DONE`: shielded entries are presented in C++ through the same helper as the `shield_hit` binding, the rest return to Python (`_k2_present_batch`). Presentation inside a tick is order-free (ruling Q1); game state keeps exact order. The binding's re-entry guard is `k2_delivering()`.
- **Exception parity with `apply_writes`.** A raising write (materialise, a PYTHON setter) does not stop the log: later writes are applied (later markers of the failed walk skipped), then the first exception is re-raised with later ones as notes and the same `__context__` (`HandledAs`, CPython 3.11+). `combat_apply_raised()` lets `run_k1` tell an apply error from a kernel error. `apply_writes` stays as the Python reference; `combat_apply_log(writes)` applies a Python-encoded log in C for the random-log equivalence test (`tests/unit/test_native_write_apply.py`).
- **The delivering guard.** K0's record writes are a span into the session's reused log, which the next `next()` clears. Applying them runs Python (wake hooks, setters) that could call `next()` again, so `combat_k0_next` marks the delivery (`K0Session::set_delivering`, RAII, cleared on the exception path) and a `next()` inside it throws with the log and cursor untouched.
- Cost model (Debug): after `6cfde63c5` a K0 write costs ~0.21 µs, almost all CPython calls (pins/dict get and set, the `__dict__` getattr). Handle lookup reads an exact `WeakValueDictionary`'s `data` in C, falling back to `.get` for anything else. K1/K2 records still move a write vector per record (perf register SIG-169, SIG-170).

**One-call scalar push** (`combat_push_scalar(h, fid, code, value)` in `host_bindings.cc`; `NativeField._push_scalar`):
- Used by `NativeField.__set__` and `NativeWrapped._after_set` for float, int, bool, IS_TRUE and OPT_INT fields; other types (VEC3, lists) keep `_push`, which also stays as the reference for resync and repush.
- A raw `METH_FASTCALL` function registered with `m.add_object`, not an `m.def`: pybind11's argument dispatch was most of the cost (`m.def` 1,087 → 1,067 ns; raw 135 ns per push, unit microbench, Debug). The only raw CPython entry in `host_bindings.cc`; copy it only where a binding runs hundreds of times a tick.
- Encodes with the C calls that are the Python builtins (`PyNumber_Float`, `PyNumber_Long`, `PyObject_IsTrue`, `is True`, None → −1) BEFORE the handle check, as `_push` does; `TypeError`/`ValueError`/`OverflowError` → `_drop(obj)`. An int beyond int64 drops the row (ruling W4). Caller bugs (argument count, unknown code, field id out of range) raise `SystemError`, never a silent drop.

**`FieldType::FloatList` and the in-place push rule** (`mirror.h`, `NativeFloatList`):
- A whole list of doubles per row field, every bit kept (−0.0, NaN payloads); `Mirror::set_floats` / `get_floats`, `set_float_at` (one element in place, bounds-checked); binding `combat_set_floats`. First users: `TorpedoTube._reload_timers` and `_reload_advanced_at`.
- `NativeFloatList` accepts a `list` of ints and floats only (anything else drops the row) and compares by `.hex()` in the audit.
- A descriptor sees only rebinding. **Every in-place writer (`lst[i] = v`, `lst[:] = ...`) must push after mutating:** `push_field(obj, name)`, or a class helper such as `TorpedoTube._push_slots()`, placed before any event the write precedes in Python's order (e.g. before `_broadcast_reload()`). `audit_mirror` catches a missed push; `tests/unit/test_native_k0_mirror.py` pins every writer. `push_field` finds the descriptor by a linear scan (parked minor).

## Cross-cutting gotchas for the plan
- The GIL is never released anywhere in transforms/torpedo bindings, so releasing it for the kernels would be a new pattern.
- A C++ mirror singleton survives mission swap, like the store. It needs an explicit `clear()` called from GameLoop start or `_fresh_world`, and from conftest's `_reset_leakable_engine_globals` (the TorpedoScan equivalent is `get_scan()` clearing on store change, plus `torpedo_scan_clear`).
- `GameLoop.__init__` is the only place the passive switch is read. In `host_loop` there is also the mission-init path (`_init_mission`) that builds the GameLoop, so the env switch is read after the mission loads.
- CMake `COMPILE_OPTIONS` source property is replaced, not appended, per `set_source_files_properties` call.
- `host_io` manifest test: only add to `host_io.py` if you want the manifest. The transform and torpedo_scan precedent bypasses host_io.
- **Part A rule (phase 6; spec `docs/superpowers/specs/2026-11-05-phase6-engine-stages-native-design.md` §3 "Mods and patches"): a Part A stage does not fall back to Python when a script patches an App method it stands in for.** That matches BC, whose per-tick updates were internal C++ no script could override; a patch of an accessor changes what Python callers see, as in BC. The kernel-M fallback stays the rule for SDK script classes (Part C preprocessors), and our OWN hooks into a stage must be carried into the native stage explicitly. This replaces the old "a method a kernel replaces must join the override guard" rule. What each kernel still honours today (verified against `engine/appc/native_combat.py`):

  | Kernel | Still honours |
  |---|---|
  | K0 (charge/reload) | nothing: its override guard was removed (a static test, `tests/unit/test_native_k0_override_guard.py`, keeps engine classes from overriding what it stands in for) |
    | K1 (fire control) | nothing: native only, no Python copy |
  | K2 (beams) | instance patches (`_K2_SHIP_PATCHES`, `_K2_SYSTEM_PATCHES`, `_K2_BANK_PATCHES`) and class flags for foreign / non-stock classes (`_k2_flag`, `_k2_foreign`) |
  | K3 (torpedoes) | instance patches only (`_STEP_SHIP_PATCHES`) |
  | K4 (eligibility) | still snapshots module functions (`_K4_FUNCTIONS`, `_k4_unchanged`) |
  | damage | instance patches (`combat_dmg_clean`) and class flags (`dmg_class`), plus the kept `combat.apply_hit` identity check (`_kdmg_apply_hit_stock`), kept because 7 golden fights record hits through an `apply_hit` spy |

  (Moved here from CLAUDE.md's native-combat row, 2026-11-01, for the length budget; rewritten 2026-11-05.)
