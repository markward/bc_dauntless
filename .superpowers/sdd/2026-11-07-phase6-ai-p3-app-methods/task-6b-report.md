# Task 6b report

## Deleted
- `_start_firing_py` and its "no host module" selection (`engine/appc/weapon_subsystems.py`). No host module or stale binary now gives `_start_firing_stale` -> AttributeError. Dropped from `_START_FIRING_SURFACE`; C++ (`host_bindings.cc`) no longer reads it, and takes `ws_d` from `PyModule_GetDict(ws)` instead of the function's globals.
- Frozen copy: `tests/helpers/start_firing_oracle.py` (from 52e5211b2; gates read as `ws.<name>` at call time so patches still bite).
- `test_native_start_firing.py` repointed to the oracle; `test_python_body_without_the_host` deleted; stale-binary test kept.

## Kept, and why (scope 2)
`_is_type_of_py`, `_subsystem_is_type_of_py`, `_point_copy_py` KEPT. The native-required argument covers fire control only. Tools such as `gen_system_maps.py`, `bake_*.py`, `bcs_inspect.py` and standalone `mission_harness.py` import `App`/`engine.appc` with no `build/python` on `sys.path` (verified: `import _dauntless_host` fails outside the test env), so these non-combat paths are reachable without the host module. I could not prove none of them calls IsTypeOf/point_copy, so I kept them. Mark's call.

## Store backend (scope 3)
`get_store()` returns `PythonTransformStore` only when `_dauntless_host` is not importable or lacks `transform_alloc`. Outside tests the only way there is those same host-less tools. Direct users of `PythonTransformStore`: tests only (test_transform_store_conformance, test_torpedo_scan_conformance, test_transform_within_radius, test_native_world_location, test_transform_sweep_candidates, test_transform_proximity_report). Production (the host) always has the native store. Nothing removed (GetWorldLocation/GetTranslate, planet.py paths untouched).

## Tests
Specified 13-file pytest command: 252 passed. Guards (tests/docs, path_indirection, install_write_guard, gate_tiers): 50 passed. Build (`cmake --build build -j`) clean. Goldens untouched.

## Files
engine/appc/weapon_subsystems.py, native/src/host/host_bindings.cc, tests/helpers/start_firing_oracle.py (new), tests/unit/test_native_start_firing.py, this report.

## Concerns
Host-less tools now raise AttributeError on any StartFiring (already true of fire control generally).
