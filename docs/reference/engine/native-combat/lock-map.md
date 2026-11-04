> **Superseded in part (2026-11-03, kernels off the lock):** §0's "nothing in the bindings releases the GIL" and §1's per-kernel "GIL held" are no longer true. K0-K3's compute and K3's `apply_hits` run with the GIL released; frees are deferred to drain points, and off-main pushes are queued. A compute-only timer now exists (§7.1). See spec `docs/superpowers/specs/2026-11-03-kernels-off-the-lock-design.md` §10.

# Native combat off the lock (roadmap I): lock map

Read-only map, 2026-11-02, worktree `native-combat-k3`, branch `ws/combat-native-damage`, **HEAD `ac21dc89a`**. Every line number is at that commit. Another agent is editing D's Task 3 in this worktree, so they will drift.

Abbreviations:
- **HB** `native/src/host/host_bindings.cc`
- **NC** `engine/appc/native_combat.py`
- **MH/MC** `native/src/combat/{include/dauntless/combat/mirror.h, src/mirror.cc}`
- **EQ** `native/src/host/combat_effect_queue.h`
- **WA** `native/src/host/combat_write_apply.h`
- **RM** `docs/superpowers/specs/2026-11-01-threaded-weapons-combat-roadmap.md`
- **KW** `k1-walk-check-map.md`
- **PR** `docs/reference/engine/perf-register.md`
- **DS** `docs/superpowers/specs/2026-11-02-native-damage-design.md`
- **SDK/** the BC SDK scripts root (`paths.sdk_scripts()`)

Anything not read off code is marked **inferred**.

Two scenarios are kept apart throughout, because the hazards differ completely:

- **A. Release in place.** The main thread drops the GIL around a kernel's compute and takes it back afterwards. Only *other* threads can run Python during the window.
- **B. A combat thread.** A kernel computes on another thread while the main thread runs Python (AI, scripts, render): roadmap I's end state and J. Everything the main thread does can then race.

A third option for I's second half, **C. fork-join under a held GIL**, comes up in §5 and §6. In C, the main thread keeps the GIL and waits while C++ workers compute.

---

## 0. Ground facts

- **The combat library has no Python dependency.** `native/src/combat/CMakeLists.txt:35` links only `dauntless_transforms`. A grep for `Python.h` / `pybind11` / `Py*(` in `native/src/combat/` matches only two comments: `beam_trace.h:65` and `beam_trace.cc:87`. So no CPython call and no refcount operation can be inside any kernel's compute.
- **Nothing in the bindings releases the GIL today.** The one `gil_scoped_release` is `pick_folder` (HB:5461), which is first-run only. The binding comments say so at each kernel: HB:12134-12147 (K1), 12511 (K0), 12729 (K2), 13286 (K3). `tests/unit/test_native_k1_holds_gil.py` source-guards the K1 block only: it bans `gil_scoped_release`, `Py_BEGIN_ALLOW_THREADS` and `call_guard`. There is no equivalent guard for K0/K2/K3/K4/`can_detect` (grep of `tests/` for "gil").
- **Where Python runs.** `host_main.cc:276` calls `Py_InitializeEx`, then `run_host_loop()` (`:171-172`) imports `engine.host_loop` and runs it on the main thread. Sim ticks, `frame()` (render), and CEF (`cef_lifecycle.cc:199-200`: `external_message_pump=false`, `multi_threaded_message_loop=false`; `:337` `CefDoMessageLoopWork()`) all run on that one thread, driven from Python.
- **Native RNG.** The combat library has none. A grep for `rand`/`mt19937` in `native/src/combat/src/` finds only `_reseed_all_fire_timers`, which is a timer reset, not a draw. D keeps its gameplay draws in Python at delivery: DS M5 (the death at the flush) and R3 (the cascade's S2 point).

---

## 1. Per kernel: binding entry/exit, what compute touches, CPython left inside

The drivers are in NC: `run_k1` 3565, `k1_pump` 3690, `k1_system` 3711, `run_k0` 4054, `run_k2` 4775, `k2_phasers` 4885, `run_k3` 5362, `step_scan` 4993, `clear_step` 5033. Every driver has the same shape: begin, then `next()` until DONE (Python handles each record in between), then end, or abandon on an exception.

The "compute" below is the one C++ call a release would bracket. Everything else in the binding runs with the GIL held, and much of it is CPython by design.

### 1.1 K0 charging (`sim.weapons`)

**Begin** `combat_k0_begin` (HB:12444-12505):
- `k0_scan` (HB:4994) is CPython: it walks the Python ship tree, reads `_nslot`, and checks the class and object caches on `tp_version_tag`/`ma_version_tag`.
- It builds a `shared_ptr<unordered_set>` weapon check (HB:12487-12491), then calls `k0_session().begin(...)`.

**Compute** `cb::k0_session().next()` (HB:12514).

**After compute, GIL held:**
- `applier.apply(r.writes)` inside `Delivering` (HB:12519-12529). This runs Python: wake hooks and setters.
- `k0_append_entries` (HB:4305) into the host effect queue.
- The tuple build. The interned reason strings are a function-static `PyObject**` (HB:12537-12545).

**Compute touches:**
- mirror rows: it reads them and writes them through `m_.set_f/set_i/set_float_at` (`k0_charging.cc:596-625`), and each write bumps `epoch_`;
- the session's reused log storage (`k0_charging.h:94-101`);
- the weapon-check closure, a C++ set;
- per-ship handback reasons;
- counts.

**CPython inside compute:** none (HB:12511-12512).

**Records in the fight:** only DONE (PR SIG-173: "K0 0.087 → 0 (only DONE)").

### 1.2 K1 fire control (`cb.held_weapons`)

**Begin** `combat_k1_begin_pump` (HB:12104-12120) and `combat_k1_begin_system` (HB:12121-12131). Each makes a `K1Verdicts` and a `K1SessionCheck` closure (HB:5080-5099, 5374), which is a C++ set lookup.

**Before compute, GIL held** (`combat_k1_next`, HB:12133-12152):
- `k1_scan(*sc->v)` (HB:5329) is CPython. It re-validates the top session's verdicts by probing instance dicts, MRO entries and the registry's weakrefs (KW §1.3, launch-deferral spec §10).
- `k1_launch_recheck()` (HB:4139) is CPython. It reads module dicts and `sys.modules`, and **writes mirror globals** `K1_LAUNCH_PATCHED` and `K1_PULSE_MODULE_STALE` (HB:4152, 4167).

**Compute** `cb::k1_kernel().next()` (HB:12153).

**After compute, GIL held:**
- `applier.apply` (HB:12157-12166), which runs Python: `materialise`, the `PYTHON` setters and `wake`.
- `k1_append_entries` (HB:4259-4303). A launch's entries take references here: `K1Held` (HB:4178-4206) calls `applier.live(h)` (CPython) and `Py_NewRef(module)` (HB:4239).
- The tuple build.

**Compute touches:**
- mirror rows, read and written. The writes are `m_.set_f/set_i/set_ref/set_ids/set_fv`, `k1_fire_control.cc:335-391`. `set_ids` replaces a row's vector, for example `_target_list`.
- the globals;
- `can_detect` (`k1_fire_control.cc:752`) and with it `SensorState`'s latch, memo, `walking_probes`, `rock_cache` and `pair_cache`;
- the mount memo via `subsystem_world_position` (`weapon_geometry.cc:118-130`);
- the session's verdict sets;
- `K1Record.writes` / `entries`, which are C++ values, including `K1Spawn`;
- the kernel's session stack and counts (`k1_fire_control.h` `K1Kernel`).

**CPython inside compute:** none. This is the launch-deferral outcome (spec §10: "No CPython call is left inside `K1Kernel::next()`").

**Mid-walk records in the fight:**
- DONE, about 2.3 a tick (KW §4.1);
- FIRE, 2 per 8,999 ticks (`launch_posed_offset`; launch-deferral spec §10);
- ASKs (counted, not re-measured here).

### 1.3 K2 phasers (`cb.phasers`)

**Begin** `combat_k2_begin` (HB:12683-12701). It copies `cb::installed_trace_hooks()` into the session's `K2Context` (HB:12688) and applies the ctx dict (CPython). The driver's `combat_k2_scan_ships` (HB:12710-12727, `k2_scan_ships` HB:3666) is the CPython clean check. Its result, `python_ships`, is a C++ set in the context.

**Before compute:** `k2_not_delivering("next()")`.

**Compute** `cb::k2_kernel().next()` (HB:12732).

**After compute, GIL held:**
- `applier.apply` under `K2Delivering`;
- `k1_append_entries(r.entries)`, for LOOP_STOP;
- the tuple build.

**Compute touches:**
- mirror rows, read and written (`k2_beams.cc:275-320`);
- `can_detect` (`k2_beams.cc:814`), which reaches `SensorState`;
- the mount memo;
- the context's `iids` table and `python_ships`;
- the **TraceHooks** (`beam_trace.h:54-62`, used via `resolve_hit_point`): `hooks.translation` and `hooks.trace`. These are HB's `combat_trace_hooks()` (HB:752-772) → `instance_translation_for_python` and `trace_instance_for_python` (HB:715-750). They read `g_world.get(id)` (HB:260), `inst->node_overrides` and `g_loaded_models[h-1]` (HB:661), and the pose through `hit_pose_of` (HB, beside `instance_translation_for_python`). **Since native motion phase 3a** that pose is the **TransformStore** slot named by the instance's sim source (`set_instance_sim_source`, pushed by `host_loop._push_sim_source`), composed with its scale and view offset, not the drawn `inst->world_linear` (read only for an instance with no source or a stale one). So the hooks, which run with the **GIL released** inside K2/K3 compute, now read the store as well as `g_world`. That is **native state, no Python**;
- the kernel's rest queue (`take_rests`);
- counts.

**After DONE:** `combat_k2_drain` (HB:12845-12876) presents shielded rests through `k2_present_rest` (HB:3972), which reaches the renderer's shield pass, with the GIL held and outside compute.

**CPython inside compute:** none. The hooks touch no Python (`beam_trace.h:19-20`; HB:752-753).

**Mid-walk records today:** damage pulses (CONTACT) at 0.44-0.47 a tick (SIG-173, SIG-175). Each runs Python `combat.apply_hit` between records.

### 1.4 K3 torpedoes (`cb.projectiles`)

**Begin** `combat_k3_begin` (HB:13259-13282). It copies the trace hooks into a `K2Context`, takes `n_active` and `scan_serial`, and may return a whole-step reason.

**Compute** `cb::k3_kernel().next()` (HB:13287).

**After compute, GIL held:**
- the tuple build;
- writes, expired and **hits** are handed back to Python. Python applies them: torpedo writes in `run_k3`, hits through `combat.apply_hit` in `host_loop._advance_combat` (`engine/host_loop.py:1376-1385`).

**Compute touches:**
- mirror Object and Subsystem rows (read);
- the **torpedo table**, written in `finish()` (`k3_projectiles.cc:503-535`);
- **TransformStore** `set_position` for each torpedo (`k3_projectiles.cc:531-535`). The kernel holds a non-const store;
- `step_scan()` frames, ships and sets (read; `scan_` at `:290`);
- guidance `can_detect` (`projectile_geometry.cc:291, 302`), which reaches `SensorState`;
- the trace hooks;
- counts.

**Pinning:** the kernel holds handles only. ASKs free no row, and `ships_list` plus `_active` hold every object a record names (`k3_projectiles.h:142-146`).

**CPython inside compute:** none.

### 1.5 K4 eligibility (`cb.eligibility`)

**Before:** the driver's `combat_step_scan` (HB:13422-13433 → `step_scan_ships` HB:3756) is CPython. It fills `step_scan()`: ships, sets, serial, and frames via `combat_step_frames`.

**Compute** `cb::k4_eligible(cb::mirror(), cb::step_scan(), ...)` (HB:13470). It is read-only on the mirror and the scan. The binding then bumps `k4_counts()` and builds a `PyList` (HB:13471-13489).

**CPython inside compute:** none. It is a single call that produces no records.

### 1.6 Sensor `can_detect` (Python callers)

`combat_can_detect` (HB:11627-11644) → `cb::can_detect(cb::mirror(), ...)`. It is one tiny compute per call. Its callers are Python's dispatched `sensor_detection.can_detect` (AI, contacts, fallbacks; NC `_counts["native_calls"]`).

It **writes** `SensorState`:
- latch: `_set_latched`, `sensor_detect.cc:253-258, 620-626`;
- memo;
- the `walking_probes` bool (`:374-378`);
- `rock_cache` (`:450-470`);
- `pair_cache` (`:559-564`).

The kernels' own calls (K1, K2, K3) write the same structures.

### 1.7 D: native damage (expected end state; NOT at HEAD)

`git status` is clean at `ac21dc89a`, and there is no `damage.{h,cc}` in `native/src/combat/`. The facts below come from the plan, `docs/superpowers/plans/2026-11-02-native-damage.md`, Tasks 3-4.

**Planned:**
- an entry `apply_hit(Mirror&, HitInput, Context&, WriteLog&, EffectQueue&)` "that the kernels can call without the GIL";
- K2 applies each pulse in the walk, with no CONTACT damage record;
- K3 applies its hits "at DONE";
- new mirror inputs (DS §4.1): shield faces, ramp, invincible/hurtable, watchers, and per-step flags.

**Ruling R11 (the D ledger):** the hit's H operands (the source, the killer) are pre-resolved by the binding as owned objects (the `K1Held` precedent), so "the kernel never calls CPython".

**Facts this depends on, to check when Task 3 lands:**
- **The queue type lives in the host layer.** `EffectQueue` is `dauntless::host` (EQ), and the combat library "does not link the host layer" (HB:4257-4258 comment; EQ header). A kernel that appends during compute either gets a combat-side queue or hands entries back on the record, as K0/K1/K2 do today. Not established.
- **H operands hold references.** An H operand is an `OwnedObject` "held from emission" (`fix-1-2-report.md` §2, table row H). The queue owns one reference per object operand and releases it through `Py_DECREF` (EQ "OWNERSHIP"). So every H operand appended needs a reference taken under the GIL. R11's pre-resolution must take them before compute, or the kernel must append an index that the binding converts afterwards (**inferred**: no other way to avoid a refcount change without the GIL).
- **`apply_hit` forgets the step memo on entry and on exit** (`engine/appc/combat.py:622-627`). The native counterpart for the C++ tables exists: `memo_clear(Mirror&)` (`sensor_detect.h:122`) clears the sensor memo **and** the mount memo. The Python `step_memo.table()` dicts (`engine/core/step_memo.py`) are Python objects. A hit applied inside a kernel without the GIL cannot clear them. Whether any Python reader of those dicts runs within the same step with the switch on (fallback ASK answers) is **not established**.
- **D makes damage cross-ship.** K2 and K3 then write the *target's* rows (shields, conditions, threshold state) inside compute, in today's order (ruling P1: the next bank on the same target sees the pulse's result; DS §3 goal 2). See §6.

---

## 2. What can change mirror/table state while a kernel computes (if the lock were released)

### 2.1 Threads in the process

| Thread | Created at | Runs Python? | Touches combat state? |
|---|---|---|---|
| Main: interpreter, sim, render, CEF UI loop | `host_main.cc:171-276` | yes | yes: all of it |
| Log follower (**packaged builds only**) | `engine/log_tee.py:310-315`, started from `engine/__init__.py:57-63` (`_packaged_boot`, gated on `paths.is_packaged()`) | **yes** | Its body is `os.read`, `_write_all` and `Event.wait` only (`log_tee.py:205-226`). It can run **GC and finalizers** when it holds the GIL (§2.2). |
| CEF event / load-end callbacks | `cef_set_event_handler` / `cef_set_load_end_handler`, HB:10889-10925, `py::gil_scoped_acquire` | yes | They run **on the main thread** inside `CefDoMessageLoopWork` (HB:10907-10908 docstring). They cannot run during a main-thread kernel call. |
| Renderer workers (native only) | `far_pass.cc:251`, `hull_fill_cache.cc:101`, `part_severance_jobs.cc:90` (captures by value, `:87-97`), `structure_parts_cache.cc:83`, `rock_speck.cc:197`, `system_nebula_cache.cc:72` (the warp-preload haze prebuild) | no | None found. They read their own copies, or immutable model data (**inferred** for all but severance, which states it at `:87`). |
| Lottie / ThorVG worker | `native/src/lottie/src/panel_worker.cc:329` | no | no |
| OpenAL implementation threads | inside OpenAL (`native/src/audio/src/openal_backend.cc:28` creates the context) | no | No callback into our code was found: the grep for `gil_scoped_acquire`, `PyGILState` and `py::function` finds only the two CEF handlers. |
| `pick_folder` | HB:5455-5462 releases the GIL while a modal panel is up | n/a | first-run screen only, before the game loop |
| rockgen surface threads | `native/src/rockgen/src/surface.cc:118` | no | generation tooling (**inferred**: not on the game path) |

`engine/` contains no other `threading.Thread`, `ThreadPoolExecutor` or `concurrent.futures` (grep). `presentation_rng.py:34-39` uses only `threading.local`. Mods could start threads (**inferred**, not surveyed).

**Consequence for scenario A:**
- In a **checkout build** no other Python thread exists, so a GIL released around compute lets **nothing** run Python.
- In a **packaged build** the log follower can take the GIL during the window and trigger cyclic GC. A GC-tracked allocation can trigger it, for example inside `Event.wait`'s `Condition` machinery (**inferred**: the follower's own allocations were not traced). KW §2 and HB:12141-12147 name this.

### 2.2 What GC / finalizers do on whatever thread holds the GIL

The engine never calls `gc.disable`, `freeze` or `set_threshold` (grep), so the default thresholds apply.

**(1) Mirror row frees.**
- `register` (NC:1211-1240) installs `weakref.finalize(obj, unregister_handle, h)` (NC:1235-1237).
- `ObjectClass` instead frees its transform slot **and** its row in one finalizer: `objects.py:69-82`, installed at `:113-124`.
- `unregister_handle` (NC:1265-1271) calls `_forget_part_caches(h)` (Python), then `combat_unregister` (HB:11238-11244).
- `combat_unregister` first calls `k1_launch_module_release`: a `k1_launch_modules()` map erase and a `Py_DECREF` (HB:4094-4101).
- Then it calls `Mirror::unregister_row` (MC:622-648), which does the following:
  - `by_obj_id_.erase`, an `unordered_map` mutation (MC:627-628);
  - `release()`: `t.rows[i] = T{}` destroys the row's vectors (`_children`, `_target_list`, `_known_objects`, ...); `live[i]=0`; `gen[i]+=1`; `free.push_back` (MC:542-548);
  - `SensorState::drop_object` / `drop_mounts_of` / `drop_set`: `std::erase_if` over **the whole** latch, memo and mount memo, and erase on `rock_cache` / `pair_cache` (`sensor_detect.cc` 38-55; `sensor_state.h:86-91`);
  - `++epoch_`, a plain `uint64_t` (MC:647).
- `_release_transform_slot` also runs `TransformStore::free`, which bumps the generation and pushes to the free list. `TransformStore` is "NOT internally synchronised" (`transform_store.h:38-40`).

**(2) SDK `__del__` methods run engine code on live objects.**
- Eight SDK AI condition scripts define `__del__`: `SDK/Conditions/` `ConditionInRange`, `ConditionSingleShieldBelow`, `ConditionPulseReady`, `ConditionIncomingTorps`, `ConditionSystemBelow`, `ConditionTimer`, `ConditionPowerBelow`, `ConditionInLineOfSight`.
- **Example:** `ConditionPulseReady.__del__` (`SDK/Conditions/ConditionPulseReady.py:42-51`) looks up a **live** ship by id and calls `pWeapon.GetChargeWatcher().RemoveRangeCheck(id)`. Our `RemoveRangeCheck` sets `self._owner._watch_checks = len(self._checks)` (`engine/appc/float_range_watcher.py:101-105`). That attribute is `NativeField(int)` (`weapon_subsystems.py:3021`), so the GC'd condition **pushes into a live pulse-weapon row that K0 reads** (`_watch_checks` decides whether K0 emits WATCH; `k0_charging.h:64-71`).
- `ConditionInRange.__del__` calls `pProx.RemoveAndDelete()` (`:60-66`).
- RM §7 records that these conditions sit in reference cycles (`SetInstance(self)`), so **when** they run is GC timing. **Partly superseded 2026-11-03:** the process half of the cycle is gone (the process holds its instance weakly, process-owner-lifetime spec §6); the condition ↔ `ConditionScript` half remains (that spec §7), so a dropped condition's `__del__` is still GC-timed.
- `engine/appc/debug.py:73` has one engine `__del__`.

**(3) Other finalizers:** `engine/audio/hum_allocator.py:170` (`playing.Stop`), which is audio state, not the mirror.

**(4) `WeakValueDictionary` callbacks:** `_registry`'s `KeyedRef` removal (NC:82) mutates `_registry.data`. K1's `k1_scan` and the applier read that dict in C (WA "THE REGISTRY"). Both run in the binding with the GIL held, never in compute.

**Not a hazard in scenario A:** row **allocation** (`Mirror::alloc` `emplace_back`, MC:524-539, which would dangle every row reference), `TransformStore::alloc`, `Mirror::clear`, the effect queue (`take`, `clear`, `rebind`, `append_objects`), `step_scan` rebuilds and `combat_set_*` pushes. All of them need Python code running on **some** thread. Only finalizers and `__del__` run during GC, and of these only `__del__` pushes (point 2). `_drop` (NC:446-475), which rebinds the queue, is reached from a failing push, not from a finalizer.

### 2.3 Which of those would race with a computing kernel

**Container mutations (data races):**
- These happen regardless of which row is freed, and are undefined behaviour under the C++ memory model:
  - `SensorState` `erase_if` and erase against a kernel's `can_detect` inserts and finds (K1, K2, K3);
  - `by_obj_id_.erase` against `find_by_obj_id` (`sensor_detect.cc:368`);
  - `++epoch_` against the kernels' own writes (every `set_*` bumps it, MC:678-899).
- Element writes to `gen[i]`, `live[i]` and `TransformStore` generations of **other** indices touch distinct memory locations: not a C++ race, but a kernel re-reading that handle would see it freed.

**Row content:**
- `t.rows[i] = T{}` frees the vectors a kernel may hold a `const&` to. Examples: `k2_beams.cc:721` `kids = subrow(s_.sys)->_children`, `k1_fire_control.cc:1364`.
- In scenario A that row's object must already be unreachable to be collected. The rows a walk reads are pinned or strongly held: K1's `_K1Walk.pins` (NC:3176-3263), K3's PINNING, and the step's `ships_list`. So a freed row being *read* is **inferred** unlikely. Not proven: no audit was made of which mirrored refs correspond to weak Python references. The grep found only `objects.py:48` (`_owner` weakref) and two `WeakSet`s.

**`__del__` pushes (2.2 point 2):**
- These write **live, reachable** rows: `_watch_checks`, and whatever else a mod's `__del__` touches.
- They are both a race and a determinism change. Today they happen at a GC point between records. Off-main, they would happen mid-compute.

### 2.4 Scenario B (a combat thread concurrent with Python)

Every main-thread writer races.

**Mirror writers:**
- `NativeField.__set__` pushes (NC:593-602; ~244 a tick, SIG-168), `register` (allocation: row vectors reallocate) and `_drop`;
- `combat_set_*`, `combat_push_scalar`, `combat_set_part_poses` and the like;
- torpedo table add and drop (NC:2725-2763);
- `combat_set_globals`, `k1_launch_recheck`'s globals.

**SensorState writers:**
- Python `combat_can_detect` from AI;
- `combat_occ_begin_tick` (`engine/appc/sensor_occlusion.py:94`);
- `step_memo.forget` → `combat_memo_clear` (NC:5513; `host_loop.py:1397-1448`, `combat.py:622-627`);
- `combat_set_latched`, `combat_latch_restore`.

**Other shared state:**
- `step_scan()` rebuilds;
- **TransformStore** writes from motion (`objects.py:335-428`, `gl.motion`) and alloc growth;
- **`g_world` / `g_loaded_models`**, which the trace hooks read:
  - render transform sync (`sim.render_xforms`): since phase 3a it no longer feeds the hooks' pose (that comes from the store through `hit_pose_of`), only each instance's sim source (on change);
  - articulated part `node_overrides` (`_sync_ship_articulation`): since phase 3a pushed when the pose CHANGES, from inside the sim tick (`articulation.tick_ship` and the SPV's `_store_forced` edges → `pose_sink.notify` → `host_loop._push_articulation`), once at realize, and every frame by the dev-only SPV sweep while the viewer is open; no longer from the render transform sync;
  - `frame()`'s `propagate` / `update_animations` / `resolve_render_space` (HB:1613-1662);
  - world resets (HB:1255-1258, 1351-1358);
  - model loads (`push_back`, HB:1056);
- the effect queue (Python appends, `take`, `rebind`);
- the write applier context;
- the K0/K1 PyObject caches.

This is J's snapshot and outbox problem (RM decision 4). It is listed here, not mapped further.

---

## 3. Effect queue, write logs, OwnedObject, refcounts

**Effect queue** (EQ; `effect_queue()` is a process singleton, `combat_effect_queue.cc:192`):
- An entry holds up to 35 operands (`kMaxOperands`). An `Object` operand is an opaque pointer to an **owned reference**, released through the installed `Release` (`Py_DECREF`) by `clear()` and by the destructor. `take()` hands the references to the caller.
- `append_native*` (kernel entries) store handles, numbers, `EffectInt`, `EffectBool` and `OwnedObject`, which is a reference the caller already took.
- `append_objects` (Python's) takes references.
- `rebind` (`combat_effect_queue.cc:168`) takes one reference per replaced operand through an `acquire`.
- **Today every append happens in the binding after compute, with the GIL held:** `k0_append_entries` HB:4305, `k1_append_entries` HB:4259 (also used for K2), `k1_append_spawn` HB:4214. The kernels only fill `K*Record::entries`, which are C++ values. EQ:16-17: "The lock is held for both (the kernels run under it today)."
- **Refcount operations:**
  - `K1Held` (HB:4178-4206): `applier.live(h)` returns a new reference, and the destructor `Py_DECREF`s unless `release()`;
  - `Py_NewRef(module)` per SPAWN (HB:4239);
  - `k1_launch_module_release`'s `Py_DECREF` (HB:4100), which runs from the finalizer;
  - the K0/K1 cache entries own type references (`Py_DECREF(e.type)`, HB:4695);
  - `combat_present_capture`, `combat_k1_set_*` refs.
  - All are in the binding, with the GIL held. **None is in compute.**

**Write logs:**
- They are plain C++ (`write_log.h`: handle, a `string_view` field name into static storage, a variant value).
- K0 views its session's reused log, which is valid until the next `next()` (`k0_charging.h:94-101`). K1 and K2 move a vector per record (RM §4 I).
- They are applied by the host `WriteApplier` (WA) **after** compute, with the GIL held. The applier runs Python: `REF` lookups through `pins`/`registry`, `WAKE` → `passive_state.wake`, `PYTHON` setters, and `materialise`.
- **The kernel has already written the mirror**: the log replays into Python what the mirror holds (WA:4-6).

**D (expected):** H operands are `OwnedObject`s pre-resolved by the binding (R11). Every queue reference is created and destroyed under the GIL **only if** D keeps appending after compute or pre-takes the references. See §1.7.

---

## 4. Shared mutable C++ state

| State | Owner / where | Written by | Read by | Would race with (A) / (B, or C's sibling workers) |
|---|---|---|---|---|
| `Mirror` rows, `by_obj_id_`, `globals_`, `epoch_`, `part_gen_` | `mirror()` static, MC:1053-1055 | K0, K1, K2 (rows); bindings' pushes; `k1_launch_recheck` (globals); finalizers (free) | every kernel | A: finalizer frees, `__del__` pushes. B: every push. C: rows of **other ships** a sibling writes (§6), `epoch_` (every write) |
| `TorpedoTable` | in `Mirror` (MH:523) | K3 `finish`; Python `torpedo_row_add/drop` | K3 | B: Python add/drop |
| `SensorState`: latch, memo, `walking_probes`, `tick_time`, `rock_cache`, `pair_cache`, **mount memo** `mounts` | in `Mirror` (`sensor_state.h:74-92`) | `can_detect` (K1, K2, K3, Python callers); `subsystem_world_position` (`weapon_geometry.cc:118-130`); `memo_clear` (step_memo hook NC:5513); `occ_begin_tick`; `set_latched`; `drop_*` (frees) | same | A: `drop_*` from finalizers. B and C: everything. `walking_probes` is one bool for the whole process (`sensor_detect.cc:374-378`) |
| `TransformStore` slots, generations, free list | `transform_store()` static | Python motion (`objects.py:335-428`); K3 `set_position`; finalizer `free`; `alloc` | every kernel (positions) | A: `free` (distinct elements). B: motion writes, `alloc` growth (references from `at()` dangle, `transform_store.h:101-102`) |
| `StepScan` (ships, sets, frames, serial) | `step_scan()` static, `step_scan.cc:53` | `combat_step_scan`/`frames`/`reset` (binding, CPython) | K3, K4 | B |
| K0/K1/K2/K3 kernel singletons (sessions, counts, K2's persistent `iids` table) | `k0_charging.cc:841`, `k1_fire_control.cc:1839`, `k2_beams.cc:1164`, `k3_projectiles.cc:949` | their own `begin`/`next`/`set_ctx` | their own | C: counts, and a session per thread would be needed (**inferred**). K1 sessions **nest** (KW §4.1 point 2) |
| `k4_counts()` | `k4_eligibility.cc:59` | the binding | n/a | trivial |
| TraceHooks slot | `beam_trace.cc:27-30` (static), installed at module load | `install_trace_hooks` | copied into each K2/K3 context (HB:12688, 13266) | none after install |
| `g_world`, `g_loaded_models` | HB:260, 661 | render sync (sim source on change, node overrides), `frame()`, resets, loads: all Python-driven, main thread | trace hooks (K2, K3), GIL released; their pose is read from the TransformStore via `hit_pose_of` (phase 3a) | A: none (**inferred**: no native worker writes them). B and K: all |
| Effect queue | `effect_queue()` | bindings after compute; Python | Python at the boundary | B. C if workers append directly |
| `WriteApplier` context, K0/K1 object, type and registry caches (PyObject*), `k1_launch_modules`, `K1WalkCheckRefs`, `k2_present()` | HB statics | the binding | the binding | binding-only; never in compute |
| K0 static reason strings | HB:12537-12545 | once | the binding | none |

The memos keyed by handle are generation-checked (`sensor_state.h:23-27`), so a stale key never answers for a new row.

---

## 5. Smallest change sets that would make each kernel's compute lock-free and correct (options, facts only)

### 5.1 Common to every kernel (scenario A)

The GIL release itself would bracket exactly one call per binding:
- `k0_session().next()` (HB:12514);
- `k1_kernel().next()` (HB:12153);
- `k2_kernel().next()` (HB:12732);
- `k3_kernel().next()` (HB:13287);
- `k4_eligible(...)` (HB:13470);
- `can_detect(...)` (HB:11633).

Everything before and after stays under the GIL, because it is CPython: the scans, `k1_launch_recheck`, the applier, the appends, and the tuple and list builds.

**Exceptions:** kernels throw `std::invalid_argument`/`logic_error` and `StaleInstance` (`beam_trace.h:40-42`). A `py::gil_scoped_release` re-acquires during unwind, before pybind translates the exception (pybind RAII; **inferred** from pybind semantics, not tested here).

**Cost of release and acquire:** about 2-3 records a tick for K1, 1 for K0, and K2 pulses until D. That is a few transitions a tick, against compute of 0.36-0.52 ms a tick in `combat_k*_next` (SIG-168, instrumented, before weapon state). **Inferred** negligible.

**Options for row lifetime (the named blocker):**

1. **Defer frees to a GIL-held point.**
   - `unregister_handle` (and `_release_transform_slot`'s `store.free`) would record the handle in a pending list instead of calling `combat_unregister`.
   - The list would be drained on the main thread before a compute (the top of each `combat_*_next`/`begin`) or at `_combat_tick_boundary`.
   - Fact: today frees already happen only at GC points between records (main-thread allocations). So *when* a row is freed is already GC timing. Deferral moves it to a fixed point.
   - Fact: a pending-but-unfreed row stays `valid()`. Any mirror ref to it reads live instead of `-1`. Whether a reachable ref can name a collected object is the open audit of §2.3.
   - Must also cover `k1_launch_module_release` (`Py_DECREF`, which is already GIL-held in a finalizer) and `_forget_part_caches`.

2. **A mirror lock.** A C++ mutex taken by compute and by every mutator binding: `combat_unregister`, pushes, `register`, and the SensorState mutators. TransformStore and the torpedo table would need the same.
   - The finalizer thread holds the GIL while it waits on the mutex. The kernel must release the mutex before re-acquiring the GIL, or the two deadlock (**inferred** from the lock order).
   - Covers point 2 (`__del__` pushes) too.
   - Adds an acquire to about 244 pushes a tick (SIG-168), where today each push costs ~1.4 µs (**inferred** small).

3. **No second Python thread.** The log follower's body is plain fd copying (`log_tee.py:205-226`); it could become a native thread. Releasing the GIL is then inert in every build. It does nothing for scenario B or for mods that start threads.

4. **Queue pushes made off the main thread.** A `NativeField` set on a non-main thread (`threading.get_ident`) would be queued and applied at the boundary. This covers point 2 without a lock. It changes **when** a `__del__`'s push lands (already GC timing).

5. **Fork-join under a held GIL (scenario C).** The main thread keeps the GIL and fans compute out to C++ workers, which touch no Python (§0). No Python can run anywhere during compute, so **no row-lifetime change is needed for C**. What is needed instead is §6's partitioning of shared C++ state. `test_native_k1_holds_gil.py` would still pass unchanged (no release).

### 5.2 Per kernel (A), on top of the common change

| Kernel | Extra state compute writes that something else may write | Notes |
|---|---|---|
| K0 | mirror rows (own weapons) | No `can_detect`, no hooks. After the common change it is the least exposed (**inferred**). |
| K1 | rows, `SensorState`, mount memo | `k1_launch_recheck` writes globals **before** compute: it stays outside the window. |
| K2 | rows, `SensorState`, mount memo; reads `g_world`/`g_loaded_models` and, through `hit_pose_of`, TransformStore poses | Hooks are safe in A (render is on the main thread). After D, it writes target rows and (§1.7) must clear the memo at every hit. |
| K3 | torpedo table, **TransformStore** `set_position`, `SensorState` | `step_scan` is read-only in compute. |
| K4 | none | Read-only; a single, short call. |
| `can_detect` | `SensorState` | One call per query, microseconds. A release would cost about what it saves (**inferred**). |
| D | target rows, memo clears, entries with references | Depends on §1.7's open points. |

**Test that pins the current choice:** `tests/unit/test_native_k1_holds_gil.py` (K1 block only). Releasing the GIL means revising it deliberately (KW §4.3), and probably extending the guard to K0/K2/K3, which have none.

---

## 6. Per-ship work across cores with a fixed-order merge (roadmap I, second half)

### 6.1 Per-ship independence (facts per kernel)

**K0.**
- Each ship's weapons are stepped from its own rows. It writes only that ship's weapon rows: charge, depleted, firing, beam countdown, cooldown, reload slots, `_num_ready`, watcher value (`k0_charging.h:85-93`). It reads its own PhaserSystem's `_power_level`.
- **Inferred independent across ships.**
- A RUN_PYTHON hand-back stops the walk "so no later weapon is stepped before Python has run (plan ruling P1)" (`k0_charging.h:46-48`). Python can touch anything, so ships after a hand-back cannot be computed ahead.
- In the fight K0 hands back nothing (SIG-173).

**K1.**
- It writes the walked ship's system and leaf rows: `_fire_timer`, `_target`, `_target_list`, `_force_update`, `_group_fire_mode`, `_target_offset`, `_firing`, `_dwell` (SIG-168's write list), and launch writes on its own tube and ammo rows (Ammo rows per ship: **inferred**).
- It reads other ships' rows (target position, `_dead`/`_dying`, cloak, sensors) and does not write them.
- Hand-backs (ASK, FIRE, RUN_PYTHON, WALK_START) stop the walk as K0's do. Python answering an ASK can run a real `Fire` (KW §2).

**K2, before D.**
- It writes its own banks.
- Damage leaves as CONTACT records, and Python applies it between records, mid-walk.

**K2, after D.**
- It writes **target** rows inside the walk.
- The next bank on that target must see the result (ruling P1; DS §3 goal 2).
- Shield absorption, the ramp, clamps at 0 and threshold crossings depend on the order of application (**inferred** from the arithmetic: DS §4.2's ramp and threshold state machine).
- So, in the serial order, banks on a shared target are **not** independent.

**K3.**
- Torpedo flight is per torpedo: writes to its own torpedo row and transform (`k3_projectiles.cc:503-535`).
- Hits are collected and, after D, applied "at DONE in today's order". Hits on a shared target are order-dependent, as K2's are.
- Guidance asks `can_detect(source, target)`, so torpedoes of one source share pairs.

**K4.** One read-only call. Nothing to split.

### 6.2 Shared state each split must handle

**`SensorState` latch.**
- The latch is persistent across ticks, flipped inside `can_detect` (`sensor_detect.cc:620-626`), keyed (observer, target).
- The hysteresis makes the answer depend on the **sequence** of queries for a pair.
- K1 and K2 query as the walked ship. K3 queries as the torpedo's source.
- The probe walk queries (probe, target) under the process-wide `walking_probes` flag (`:374-406`).
- A split keyed by observer keeps each pair on one thread **except** for probes and K3 (**inferred**: probe ownership per ship was not checked).

**Memo.**
- `memo` is cleared at `forget()` points (`host_loop.py:1397-1448`; every hit under D).
- A memo hit skips the latch write that a recompute would make. Bit-exactness therefore needs the same hit/miss pattern per pair as the serial run (**inferred**).

**`rock_cache` / `pair_cache`.**
- One of each per set, shared by every ship in the set.
- An entry is a function of its signature: (now, tick, ship count, min_r) and (now, tick, rock count) (`sensor_state.h:50-67`). Who builds it does not change the content (**inferred**). Concurrent inserts need a shard or a lock.

**Mount memo.**
- Keyed (subsystem, ship_arg) (`sensor_state.h:69-72`). The subsystem is often the *target's*, so many observers share keys.
- The value is a pure function of the mirror until a mount moves (damage, severance → `forget`) (**inferred**).

**RNG.** There are no native draws (§0). Merge order is not an RNG question unless D adds one, and DS keeps every draw in Python (R3, M5).

**Counts.** Kernel `Counts` are additive.

### 6.3 Merge-order requirements for bit-exactness

1. **Mirror writes.** Each worker writes only rows its partition owns, or the merge applies them in serial order. Today the kernel writes the mirror during compute (`k1_fire_control.cc:335-391`, `k2_beams.cc:275-320`, `k0_charging.cc:596-625`).
2. **Write logs into Python** in the serial (ship-list, then system, then weapon) order.
   - The applier's `WAKE` (`passive_state.wake`) and `PYTHON` setters have Python side effects. `wake` appends to awake lists, whose order later walks may read (**inferred**).
3. **Effect-queue entries** in serial emission order: event order is a game rule (RM decision 6, §5.2; the E1M2 Haven rule).
   - Per-partition entry lists are concatenated in ship order **only if** the partitions are truly independent.
4. **Hand-backs.** A record that hands back to Python ends what can be computed ahead.
   - Today: ~2.3 DONE + ~0 FIRE a tick for K1, 0 for K0. K2 pulses go away with D.
   - With D, the remaining mid-walk Python is ASKs and whole-ship fallbacks.
5. **K2/K3 damage under D.** Hits on one target apply in serial order. Partitions by target, or a serial damage pass after a parallel decide pass, are the two shapes the facts allow (**inferred**; not designed).

---

## 7. Measurement

### 7.1 Profiler rows that exist

Python `frame_profiler` scopes, printed every 120 frames (`docs/reference/engine/frame-profiler.md`):
- `sim.weapons` (K0 and its Python): `host_loop.py:12679`;
- `sim.combat`: `:12681`, which contains:
  - `cb.eligibility` (step scan + K4): `:1361`;
  - `cb.projectiles` (K3 + its Python): `:1368`;
  - `cb.vfx`, `cb.death`, `cb.damage_sys`;
  - `cb.held_weapons` (K1): `:1425`;
  - `cb.phasers` (K2): `:1433`;
  - `cb.tractors`: `:1445`;
- `sim.effects` (queue delivery): `:991`, `engine/appc/effect_queue.py:336`;
- `gl.ai`: `engine/core/loop.py:61`;
- `sim`.

There is **no compute-only timer**:
- There is no `chrono` in `native/src/combat/`.
- The binding has no per-call timing apart from an unrelated one at HB:2329.
- The only kernel/Python split ever measured used TEMPORARY scopes (SIG-168, C-254): `cb.held_weapons` 1.06 = `combat_k1_next` 0.52 + `apply_writes` 0.35 + FIRE effects 0.20; `cb.phasers` 0.78 = `combat_k2_next` 0.36 + contacts 0.18 + pulses 0.11-0.13 + pre 0.07.
- `combat_k*_next` there still includes the binding's pre- and post-compute work.
- These were measured before weapon state, fire events and launch deferral, which moved work out (PR SIG-170, -173, -175).

### 7.2 The before/after command and scoring

`docs/superpowers/plans/*` and the C-2xx entries in PR:

```bash
TS=$(date +%Y%m%d-%H%M) && OPEN_STBC_HOST_HEADLESS=1 DAUNTLESS_WINDOW_SIZE=1280x720 DAUNTLESS_MISSION=engine.dev_missions.combat_stress DAUNTLESS_COMBAT_SHIPS=64 DAUNTLESS_DEV_VIEW=bridge DAUNTLESS_PROFILE_FRAMES=1500 DAUNTLESS_NATIVE_COMBAT=1 caffeinate -i ./build/dauntless --developer > ~/Documents/dauntless-perf/<tag>-brawl-on-run1-cs64-bridge-$TS.log 2>&1
```

- **Runs:** two per condition, 90 s cool-downs, on an idle machine.
- **Scoring:** "value ÷ the report's average ticks per frame, median of reports 3-11" (SIG-157/158).
- **Build:** Debug.
- **Projectile counts:** report the median projectiles in flight, because `cb.projectiles` moves with them.

**Latest per-tick baseline** (SIG-175, C-270/C-271, launch deferral, before D):
- `cb.held_weapons` 0.604
- `sim.effects` 0.196
- `sim.combat` 1.509
- `sim` 9.27

The roadmap §2 "Presentation queue" column:
- `cb.phasers` 0.57
- `cb.projectiles` 0.15
- `cb.eligibility` 0.05
- `sim.weapons` 0.26
- `gl.ai` 3.17

D's Task 5 will re-baseline. **I's "before" is D's end state.**

**B2 / B2d** (Felix: Destroy, 5 BoP vs Sovereign, PR:72-100) are the small-fight counter-baselines.

### 7.3 What a comparison can show

- **Scenario A alone (release, nothing concurrent):** no row can drop. In a checkout build nothing else runs. Expect flat, or up by the transitions (**inferred**).
- **Scenario C (per-ship workers):** the bound is the compute share of each `cb.*` row. A compute-only timer around each `k*.next()` is needed to know that share; it does not exist today.
- **J/K (overlap):** `sim` can drop while the `cb.*` rows do not. Overlap saves at most the smaller of the two overlapped jobs (RM §6).
- **Ticks per frame change with speed** (about 3 a frame today), so per-frame rows are not like for like (PR, every SIG since 158). Compare per tick.

---

## 8. Shape implied (decisions a design must make; not chosen)

1. **Which concurrency I needs: A, C or B.**
   - A is inert in a checkout build. Its only concurrent Python is the packaged log follower (§2.1).
   - C (fork-join, GIL held) needs no row-lifetime change, because no Python can run (§5.1 point 5), but needs §6's partitioning.
   - B (a combat thread beside Python) needs J's snapshot of every main-thread writer (§2.4).
   - Evidence: §0, §2.1, §2.4.

2. **The row-lifetime mechanism, if any Python can run during compute.**
   - The options are deferred frees, a mirror lock, no second Python thread, or queued off-main pushes (§5.1 points 1-4).
   - It must cover SDK `__del__` pushes into **live** rows, not only frees of dead ones (`ConditionPulseReady` → `_watch_checks`, §2.2 point 2).
   - It must also cover `TransformStore::free` in the same finalizer.

3. **`SensorState` and the mount memo under a split.**
   - Partition by observer, shard per thread, or lock.
   - `walking_probes` is process-global, the latch is order-sensitive per pair, the caches are per set, and mount keys are shared across observers (§6.2).

4. **The partition unit, and what a hand-back does to work already computed ahead.**
   - K0 and K1 are per-ship write-private. K2 and K3 under D write targets in order.
   - Any record that runs Python ends safe look-ahead (ruling P1; `k0_charging.h:46-48`) (§6.1).

5. **How D's in-compute effects carry references and memo clears.**
   - H operands' references must be taken under the GIL (R11, EQ ownership). The queue is a host type the combat library does not link.
   - `apply_hit`'s `step_memo.forget` includes Python dicts (§1.7, §3).

6. **Measurement before choosing.**
   - A native compute-only timer per kernel call is needed. None exists (§7.1).
   - The SIG-168 split predates three phases that moved work out of compute.
