<!-- Recon snapshot 2026-11-05 (ws/motion-phase6-a2). Line numbers drift; find sites by name. Read-only explorer for the A2-A4 quick-wins plan. -->

# Phase 6 Part A recon: A2 weapons (K0), A3 combat glue (K1/K2/K3/step_scan), A4 combat render data

## Summary
1. At 128 ships, measured kernel compute is only a small part of each stage's per-tick row. In C-327/C-329, `k0.compute` is 15-19% of `sim.weapons`, `k1.compute` 30-34% of `cb.held_weapons`, `k2.compute` 34-39% of `cb.phasers`, and `k3.compute` 12-14% of `cb.projectiles`. The rest is scans, write-back and Python.
2. **K0 begin.** `k0_scan` walks every ship, weapon system and weapon in Python's dicts to evaluate the override guard. Its exact per-object cache (keyed on the dict version) misses on exactly the objects that matter, because the tick's own write-backs move those versions every tick: kernel M on ships, the subsystem stage's power writes on every weapon system, and K0/K1/K2 writes on active weapons. `K0Session::begin` also rebuilds the whole plan every tick.
3. **Cheapest A2 win.** `combat_k0_begin` already accepts `ctx=None` ("no guard: every ship and weapon native"; host_bindings.cc:13691-13716, 5385). Under spec §3's Part A rule (no fallback for patched App methods), passing `None` cuts begin to one `_nslot` read per ship plus `plan_ship`. In the profile, begin is 36% of weapons.
4. **K0 next.** It is about 59% of weapons in the profile. Roughly a third of it is compute; the rest is the C write-back: per write, a registry/pins lookup, a kind lookup, a `PyFloat`, a dict store and a wake check. Next steps: an A1-style lean applier, then dropping unchanged writes. Making the fields native-authoritative is a bigger change, because the goldens read `__dict__` directly.
5. **K1.** `materialise` → `pin_system` costs 1.4 s of `combat_k1_next`'s 4.8 s. The cause: every sustained phaser beam re-logs `_firing`, `_target` and a walk-offset `_target_offset` every tick (k1_fire_control.cc:1431-1438). Skipping writes that change nothing (held-offset case only) is the top K1 win.
6. **K2.** About half of `k2_phasers` is glue: `combat_dmg_clean_handles` (17%), `combat_k2_scan_ships` (13%), `_k2_unchanged` (6%), `resolve_stale_part_slots` (5%). The first three are the mod-patch fallbacks that Part A is allowed to drop.
7. **K3.** `expire()` is 42% of K3, and its SDK events must stay Python, but `ObjectGroup.broadcast_membership` scans every live group per expiry (a cheap index fix). `_k3_apply` (29%) is a per-torpedo Python write-back that could be a C applier.
8. **Duplicated per-tick work.** `resolve_stale_part_slots` runs about 4× per tick over all ships (0.575 s, 4.69 M `dict.get`). `_nslot` handle lists are rebuilt about 4× per tick (K0 scan, K1 `slot()` loop, K2 scan, step scan). Class checks run twice (`step_scan` and K2).
9. **A4.** Every beam input already exists natively (beam_geometry.h, beam_trace.h; K2 computes the same geometry per tick). Beam visual parameters and torpedo visuals are not mirrored. Quick Python wins: precompute each torpedo's colour/texture fields once (`_color_tuple`, 224 k calls), and walk only firing banks. A native beam feed would remove about 58% of render data.
10. **Tests.** No golden records render descriptors (every scene passes `push_render_data=False`), and no binding reads pushed descriptors back, so an A4 change is caught only by unit tests of the Python builders.

---

## 0. Measurements used (all from local files)
- **cProfile C-320:** `/Users/mward/Documents/dauntless-perf/p6m-py-run2-cs128-exterior-20261105-0925.pstats`, commit `ddd625a1e`. 5,979 ticks over 400 profiled frames. Its line numbers are older than the current tree; I cite current lines below.
  - Cumulative totals: `_advance_weapons` 4.208 s, `_advance_combat` 14.106 s, `_push_combat_render_data` 3.820 s.
  - Per tick there is exactly one `combat_k0_next`, `combat_k2_next` and `combat_k3_next` call. There were zero K0 RUN_PYTHON, zero K2/K3 ASKs, and 661 K2 CONTACT records (`_phaser_contact`). So the fallback machinery costs its checks and is almost never taken.
- **Frame-profiler rows (not profiled):** C-329 `p6a1-on-run2-cs128-exterior-20261105-1410.log` and C-327 run1. Medians over 13 reports, per frame:
  - C-329: `sim.weapons` 1.302 / `k0.compute` 0.248; `cb.held_weapons` 1.499 / `k1.compute` 0.505; `cb.phasers` 1.103 / `k2.compute` 0.432; `cb.projectiles` 0.553 / `k3.compute` 0.067; `cb.render_data` 2.747 (per frame).
  - C-327: 3.905/0.593, 3.892/1.177, 3.207/1.087, 1.274/0.173; render 3.028.
- CPython is 3.11 (`build/python/_dauntless_host.cpython-311-darwin.so`), so `kK0ObjectCache` and the dict-version caches are active (host_bindings.cc:5112-5116).

---

## A2 — Weapons / K0

### 1. Per-tick call graph
`_whole_tick` (engine/host_loop.py:11153) → `sim.ship_list`: `list(_all_ships_for_tick())` (:11160) → `_combat_effect_scope()` (:959; `effect_queue.scope`) → `sim.weapons`: `_advance_weapons(ships, TICK_DT)` (:930).

1. **`native_combat.k0_weapons(ships, dt)`** (engine/appc/native_combat.py:5104):
   - Stand-downs return False and the Python walk runs: `off` (:5108), `audit` (`_audit` or the passive audit, :5110), `nested` (`combat_k0_open()`, :5112).
   - `drain()` (:2279).
   - Watcher-patch check: `_k0_watcher_update()` against `_k0_watcher_seen`, which clears the binding's caches (:5124-5127).
   - `now_ = _ws._game_time()` (:5130).
   - Retry loop, up to 8 tries (:5137-5147): `missing = _h.combat_k0_begin(ships, dt, now_, ctx)`. Any type with no cached verdict comes back; Python computes `_k0_flag(cls)` (:5071, an MRO walk against the snapshot) into `fresh`, and begin runs again.
   - `run_k0(ships, dt)` (:5179) → `effect_queue.session()` (a no-op inside the tick scope, effect_queue.py:366-379) → `_run_k0` (:5200):
     - Builds a new `_K1Walk()` and installs it with `combat_set_applier(_applier_context(walk))` (:4573).
     - Loops `combat_k0_next()`. A RUN_PYTHON record with `rec[3] < 0` runs `_k0_ship_python` (passive_weapons.advance or step_every_weapon; :5170). Otherwise it resolves `_k0_weapon` (:5152) and calls `UpdateReload` / `UpdateCharge`.
     - Ends with `combat_k0_end()`, then restores the previous applier. `_compute_taken(0)` follows.
2. **Fallback outside K0** (host_loop.py:952-956): `passive_weapons.advance` / `step_every_weapon`. This is the Python copy, still present.

cProfile: `combat_k0_begin` 1.530 s (36%), `combat_k0_next` 2.495 s (59%; no Python callees, so this is all C: compute plus apply), the rest under 0.2 s.

### 2. What begin/next do in C++ each tick, and what could persist
**`combat_k0_begin`** (host_bindings.cc:13688-13753):
- Parses ctx, then runs `k0_scan` (:5345-5420) over the Python list. Per ship:
  - `k0_dict_of` gives the dict. If `k0_same` fails, it recomputes: `k0_handle` (the `_nslot` dict get), `k0_flagged` (type-verdict table), `k1_holds(d, ship_names)` (4 dict probes), and 4 group dict gets (:5381-5399).
  - Per group system, `k0_guard_system` (:5258-5342): on a miss, the flag check, `k1_holds(system_names)` and gets of `_children` / `_ammo_by_slot`. Then each child: a fast compare, or on a miss `k0_weapon_slow` (flag check plus 5 dict probes).
  - Torpedo systems: a magazine `PyDict_Next` scan.
  - Also `k0_types_unchanged` over every cached type, every scan (:5364).
- Then, if any weapon is marked, a heap `unordered_set` wrapped in a `std::function` check (:13730-13739).
- Then `K0Session::begin` (k0_charging.cc:567-584): `make_shared<vector<ShipPlan>>`, and `plan_ship` per ship (:488-524). This allocates each ship's `weapons` vector from the mirror's `_phaser_system` .. `_torpedo_system` refs and `_children`, every tick.

**Why the object cache misses.** The cache keys on (type, dict, `ma_version_tag`), and every store bumps the version:
- Ships: kernel M's C write-back stores `_current_speed` / `_velocity` into the ship dict (motion_write_apply.h:12-16).
- Weapon systems: the subsystem stage's `write_consumer` logs `_power_wanted`, `_power_received`, `_efficiency` and `_power_factor` for every consumer every tick (subsystem_step.cc:438-448), and those are stored into the dict.
- Active weapons: K0's own `_charge_level`, K1's sustain writes and K2's `_dwell`.

So the cache only helps idle weapons. *Inferred from code; I could not run the counters (`combat_k0_cache_sizes`, `k0_logged_writes`).*

**`combat_k0_next`** (host_bindings.cc:13754-13800):
- **Compute:** `released_compute(K0, k.next())` (k0_charging.cc:819-843). It copies `State` for rollback, then `Walker::run` (:730-787) steps every weapon of every planned ship: `energy_into` :251, `pulse_into` :327 plus `watch_into` :345, `tube_into` :366. Each step's writes go through `apply()` (:599-693), which logs undo, sets the mirror, logs the write and enqueues LOOP_STOP / TORPEDO_RELOAD / WATCH.
- **Write-back:** `applier.apply(r.writes)` → `apply_k0` per write (combat_write_apply.cc:809-850):
  - `walk_obj_keyed`: a pins-dict probe; on a new handle, a registry lookup and a pins `PyDict_SetItem`.
  - `kind_of` (cached per type/field).
  - `PyFloat_FromDouble`.
  - `store_and_wake` (:703-727): the dict store, then a `_passive_asleep` get for WAKE fields. `_charge_level`, `_firing`, `_cooldown_remaining` and `_num_ready` are `NativeWakeField` (weapon_subsystems.py:743-744, 2444, 2691).
  - A tube's slot writes go through `slot_store`, two per unloaded slot per tick (`tube_into` :392-393).
- Then `k0_append_entries`.
- Derived split from the rows and the profile: of next's ~0.42 ms a tick (profiled), roughly 0.13 ms is compute and about 0.29 ms is apply. Begin is about 0.25 ms.

**What would make begin cheap:**
- **(a) Drop the override guard (Part A rule).** Pass `ctx=None`; the binding already supports it. The scan is then one `_nslot` get per ship (`e.key` stays unset, so no caching, :5396-5401). That deletes `_k0_flag`, `fresh`, the retry loop, `_K0_*_PATCHES`, the watcher snapshot and `combat_k0_clear_caches`.
- **(b) A persistent plan.** Keep `std::vector<ShipPlan>` across sessions, keyed per ship row on a "weapon layout generation". Bump it when a group ref, a system's `_children` (set_ids) or a row's register/unregister changes. Reuse the vectors; drop the `make_shared` per tick.
- **(c) Ship handles from a shared per-tick roster** (see A3 item 3), so the Python list is not read for `_nslot` again.

**What would make next cheap:**
- **(a)** A lean K0 applier in the style of `subsystem_write_apply`: a registry lookup per run of same-handle writes, a fixed per-field store, no pins dict. Pins exist so objects stay alive through the apply, and K0's apply runs no Python except wake.
- **(b)** Skip the wake probe for fields that cannot be asleep: K0 never sleeps a weapon (native_combat.py:4873), but the binding still checks.
- **(c) Native-authoritative fields** (`__get__` reading the mirror), which removes the write-back entirely. This is bigger: the goldens read `__dict__` directly (k1_fight.py:455-470: `d.get("_beam_on_countdown")` and others), and the K0 differential checks the identity of the slot lists and the watcher (test_native_k0_differential.py docstring).

---

## A3 — Combat glue: K1, K2, K3, step_scan

### 1. Per-tick call graph
`_advance_combat` (host_loop.py:1275) → `step_memo.combat_step()` → `_advance_combat_step` (:1300), then `close_published` (:1297).

1. **`cb.eligibility`** (:1335-1340):
   - `native_combat.step_scan(ships_list)` (native_combat.py:6160):
     - `resolve_stale_part_slots` (:2809).
     - A torpedo-table rebuild if dirty.
     - `_k2_classes_unchanged()` (:5546; attrgetter compares over role classes and the seen-class watch).
     - `combat_step_scan` (host_bindings.cc:3840; C loop: `_nslot`, class in `seen`, instance-patch probe, then `check_rows`).
     - `_step_frames` (:6137; `frames.frame_of` per set, deliberately never cached).
     - `combat_step_frames`, `combat_step_serial`.
   - `damage_eligibility.update` → `k4_update` (:6307).
2. **`cb.projectiles`:** `projectiles.update_all` → `run_k3` (:6530):
   - `drain()`; `_k3_fallback` (:6498: off, audit, patched via `_k3_unchanged` :6448, plain_active, instances, scan, row, guard via `_k3_classes_ok` :6473).
   - `_K2Context(...).delta()` (:5762), `_k1_clocks`, `_K1Walk()`, `combat_k3_begin` (host_bindings.cc:14947), `commit`.
   - `_k3_walk` (:6570): `combat_k3_next`, with an ASK loop through `_k3_answer` (:6645), then `combat_k3_end`.
   - `_k3_apply(writes)` (:6614): per torpedo, `_mount_key`, `_last_seen_target_pos` / `_last_target_vel` TGPoint3s, `t._vel` TGPoint3 plus `_scan_table().set_velocity`, and `_age`.
   - `expire(t)` per expired torpedo (projectiles.py:609: `RemoveObjectFromSet` → `broadcast_membership` plus ET_TORPEDO_EXITED_SET).
   - `_k3_apply_hits` (:7358): `_kdmg_clean`, `_kdmg_ctx`, `combat_k3_apply_hits`, a Python `apply_hit` per hand-back.
   - Finally `clear_step()`.
3. `cb.vfx` / `cb.death` / `cb.damage_sys` (Python advances).
4. **`cb.held_weapons`:** `_pump_held_weapons` (:1037) → `k1_pump` (native_combat.py:4664):
   - `_k1_entry` (:4649): `fire_control_native`, `drain`, `_refresh_stale_launches` (:3041; walks `ws._pulse_modules` every call), `resolve_stale_part_slots`, `_k1_clocks` (`_game_time`, `step_memo.active`, `now()` → `App.g_kTimerManager` getattr).
   - A Python `slot(ship)` loop over every ship (:4670-4672; 771 k calls).
   - `combat_k1_begin_pump`.
   - `run_k1` (:4596): `_k1_compute_enter`, `effect_queue.session`, `_run_k1` (:4625: a new `_K1Walk`, `combat_set_applier`, ONE `combat_k1_next`, `combat_k1_result`, `combat_k1_end`), `_k1_compute_exit`.
5. **`cb.phasers`:** `k2_phasers` (:6049):
   - `drain`, `_k2_step_fallback` (:6009: nested, instances, `_k2_unchanged` :5526, audit).
   - `_k2_ship_handles` (:5660) → `combat_k2_scan_ships` (host_bindings.cc:3748), plus `_k2_python_ship` (:5600) for unclean ships.
   - `refresh_stale_pulse_params`, `resolve_stale_part_slots`, `_k2_send_present_constants` (:6037).
   - `_K2Context.delta()`.
   - `_k2_pulse_ctx` (:7335): `combat_k2_pulse_targets`, `_kdmg_clean_handles` → `combat_dmg_clean_handles` (host_bindings.cc:5846), `_kdmg_ctx` (:7289: `_dmg_unchanged`, `_kdmg_unchanged`, player, cheats, constants).
   - `_k1_clocks`, `combat_k2_begin` (host_bindings.cc:14107).
   - `run_k2` (:5934) → `_run_k2` (:5963): a loop of `combat_k2_next`, plus `combat_k2_take_hits` → `_kernel_hits_landed`.
     - ASK → `_k2_answer` (:5888) + `_heal_part_slots` + `combat_k2_answer`.
     - CONTACT → `_phaser_contact`.
     - BANK_STOP / SYSTEM_STOP → Python `StopFiring`.
     - RUN_PYTHON → `_phaser_step_ship`.
     - `cx.resend()` after each record.
     - After DONE, `combat_k2_drain` (native shield splashes) then `_k2_present_batch`.
   - If K2 stands down, the Python loop at host_loop.py:1414-1415 runs instead.

**cProfile breakdown of `_advance_combat` (14.1 s):**

| Stage (share) | Pieces |
|---|---|
| K1 pump 5.43 s (38%) | `combat_k1_next` 4.84 s total over 21,598 sessions (15,619 are AI StartFiring sessions in `gl.ai`), of which `materialise` is 1.42 s (`pin_system` 1.07 s, 235,970 calls); the `slot()` loop 0.24; `_k1_entry` 0.23 |
| K2 3.48 s (25%) | `combat_k2_next` 1.34; `combat_k2_drain` 0.22; `_k2_pulse_ctx` 0.75 (`dmg_clean_handles` 0.58); `_k2_ship_handles` 0.44; `_k2_step_fallback` 0.21; `resolve_stale_part_slots` 0.18; `delta` 0.08; begin 0.06 |
| K3 3.34 s (24%) | `expire` 1.40 (`RemoveObjectFromSet` 0.87, of which `broadcast_membership` is 0.78); `_k3_apply` 0.98 (`_scan_table` 0.24, TGPoint3 682 k, `set_velocity` 0.12); `combat_k3_next` 0.42; begin 0.14; `_k3_fallback` 0.12 |
| step_scan 0.62 s (4%) | `_k2_classes_unchanged` 0.23; `resolve_stale_part_slots` 0.19; native scan 0.09; frames 0.07 |
| Other | `particles.advance` 0.27; `damage_eligibility` 0.17 |

`resolve_stale_part_slots` over the whole profile: 33,556 calls, 0.575 s, 4.69 M `dict.get`.

### 2. K1/K2/K3 begin/next: what is packed each tick
**K1** (k1_fire_control.cc):
- `begin_pump` (:1959) copies the handle vector only; `next` (:2053) copies the `Session` for rollback and walks everything. That part is cheap.
- **The per-tick churn is in the log.** A beam already firing re-logs three writes every tick: `_firing`, `_target`, `_target_offset = K1WalkOffset` (:1431-1438, `write_target_offset` :385-404).
- The applier turns each walk-offset marker into a Python `_K1Walk.materialise` call (native_combat.py:4327). Each new walk then runs `obj`, `pin_system` (a Python loop over the children and target list, :4354-4362) and `combat_k1_walk_manual_offset`. That is about 39 walks a tick.
- **Fix:** have the kernel skip sustain writes whose value is unchanged:
  - `_firing` already True.
  - `_target` the same handle.
  - `_target_offset` when the bank already holds the same system's `_held_offset` object. This needs a per-bank "offset source" in the mirror (system handle plus a `_held_offset` push generation), because identity is recorded (golden `offset_is_held_offset` / `offset_first_holder`, golden_fight.py:121-124).
  - Manual Aim, which makes a new TGPoint3 per walk, must keep writing.
- Alternatively, move `materialise` into C: one `_held_offset` dict get plus pinning the system.

**K2** (k2_beams.cc; binding :14107-14257):
- Begin builds a `K2Context` from a Python dict each tick: `npc_shields_off`, player, view offsets, iids (sent only on change), `python_ships`, `pulse` with the clean list.
- `next` is mostly compute (profile 1.34 s against `k2.compute`). Its write-back is small: `_dwell` per firing bank, plus the damage pulses' condition writes.
- **Packed each tick but avoidable:**
  - `python_ships` / `unclean` (scan_ships).
  - The pulse `clean` list (`dmg_clean_handles`): per target, ship plus every subsystem in `mount_order` plus hull plus shield. Each is a registry KeyedRef lookup and a dict-version compare; misses re-probe `_KDMG_SUB_NAMES`. They miss for every powered or charging subsystem, for the same reason as K0's cache.
  - `_k2_unchanged` (Python attrgetter over 8 modules, 7 role classes and the seen-class watch).
- To drop `clean`, the kernel needs a "clean all" mode: today a target missing from `p.clean` is `unscanned` → a CONTACT record (k2_beams.cc:678).

**K3** (binding :14947-15114):
- The torpedo table is already persistent (`torpedo_row_add` / `_drop`, native_combat.py:3809-3851). Begin is small (0.14 s).
- **Per-tick cost is the DONE write-back in Python** (`_k3_apply`). It could be a C applier like `motion_write_apply`, which already builds TGPoint3s in C. The incoming-torpedo `set_velocity` could go straight into the native scan table.
- `projectiles._scan_table` does a function-local import on every call (projectiles.py:444-446; 247 k `_handle_fromlist` calls, 0.088 s).

### 3. Glue: what can move or be cached, and what must stay Python
**Can move to C++ or be cached:**
1. **`resolve_stale_part_slots`** runs about 4×/tick, a dict-get loop over all ships each time. Make it O(1) when nothing is stale: a pending-handle set filled on register, part-gen bump or a raise, and cleared on resolve. Expected saving ≈ 0.5 s of 14.1 (≈ 4%, plus some AI share).
2. **Override and instance-patch scans** that Part A does not require: `combat_k2_scan_ships` / `_k2_python_ship`, `dmg_clean_handles` / `_kdmg_clean`, `_k2_unchanged`, `_k2_classes_unchanged` (also run in step_scan), `_k3_fallback`'s `_k3_unchanged` / `_k3_classes_ok`, `_dmg_unchanged` / `_kdmg_unchanged`, and `combat_step_scan`'s patch probe. About 1.6 s (≈ 11% of combat) plus K0's begin.
   - Keep the representability checks (a row exists, the class has mirror flags: `_k2_seen_set`) but answer them from the mirror.
3. **One per-tick native roster**, built at `sim.ship_list`, holding the ship handles in list order and reused by K0 begin, the K1 pump, K2 begin and the step scan. That replaces the K1 `slot()` loop (≈ 0.27 s with `append`) and three C scans' `_nslot` reads.
4. **K1 sustain-write skip** (above): up to ≈ 1.4 s (≈ 10% of combat), if the pump owns most `materialise` calls. *Pump vs AI split not measured.*
5. **K3 C applier**: up to ≈ 1.0 s (7%). The `_scan_table` import hoist alone saves ≈ 0.09 s.
6. **`broadcast_membership`** (objects.py:1336-1376): `list(cls._live)` (a WeakSet) is scanned in full for every expiring torpedo, 0.445 s of self time for 853 expiries. A name → groups index would cut most of it, ≈ 0.4 s of K3. The WeakSet order is already arbitrary, so an index changes nothing visible.
7. **`_K2Context.delta`** (cheat flag, player lookup, `viewing_set`) is computed per begin for K2 and K3, and `_kdmg_ctx` for K2 and the K3 hits. These could be pushed on change (the cheat toggles, player change) instead of read per tick. Small (≈ 0.25 s total).

**Must stay Python:**
- SDK events and effect delivery: `expire()`'s `RemoveObjectFromSet` with ET_OBJECT_GROUP / ET_TORPEDO_EXITED_SET (synchronous `AddEvent`), and the effect-queue flush at scope exit (`sim.effects`, `effect_queue.flush`).
- `apply_hit` hand-backs (`_k3_apply_hits`, K2 CONTACT for `python_banks`).
- `_k2_present_batch` presentations the drain cannot do natively.
- Particles.
- The `frames.frame_of` resolution per step: by design never cached (native_combat.py:6086-6089). It is small.
- The `effect_queue.session()` wrappers are no-ops inside the tick scope (effect_queue.py:376-378) and cost almost nothing.

---

## A4 — Combat render data (per frame)

### 1. Call graph
`run()` after the camera solve: `prep.origin` / `_apply_render_origin` → `_push_combat_render_data` (host_loop.py:13508 → :1422). It makes these calls, in order:
1. `set_torpedoes(_build_torpedo_render_data())` (:1496)
2. `set_dynamic_lights(_budgeted_dynamic_lights(explosion :1810, torpedo :1566, emitter :1949))`
3. `set_shockwaves`, `set_warp_in_flashes` / `_params`, `set_hit_vfx`
4. `set_particle_emitters(_build_particle_render_data)` → `particles.snapshot_descriptors`
5. `set_phaser_beams(_build_phaser_beam_render_data)` (:2498)
6. `set_tractor_beams(_build_tractor_beam_render_data)` (:2536)

cProfile per 400 frames:
- phaser 1.941 s
- torpedo 0.784 s
- tractor 0.270 s
- emitter lights 0.247 s
- particles 0.216 s
- dynamic lights 0.164 s
- the `set_*` bindings ≈ 0.14 s

### 2. Inputs, outputs, native availability
**Phaser beams** (≈ 37 firing banks a frame, 14,685 pairs over 400 frames):
- **The loop:** `_ships_in_view` (`containing_set`, `offset_between`) over all ships. Then every ship's `GetPhaserSystem`, `GetNumWeapons` and `GetWeapon(i)`, plus `IsFiring` on each bank: 246 k calls for about 37 hits a frame.
- **`_beam_descriptor_pair` (:2385), all Python objects:**
  - `bank._target`, `containing_set`
  - `_phaser_aim_point` (:1053; locked sub `GetWorldLocation` → `subsystem_world_position`)
  - `bank._strip_emit_position` (subsystems.py:1082)
  - `_beam_endpoint` (:2349): `combat.shields_block`, `shield_bubble_entry`, else `_resolve_hit_point` (a mesh trace when instances exist)
  - About 12 PhaserProperty visual getters (`GetPhaserWidth`, `GetMainRadius`, colours, NumSides, taper, tile, `TextureSpeed`)
  - `_beam_pair_in_view` → `frames.to_render`
- **Output:** a list of dicts → `beam_from_dict` → `g_phaser_beams` (host_bindings.cc:2973, :9649).
- **Native availability:** every geometric input exists natively.
  - `phaser_aim_point`, `strip_emit_position`, `shields_block` and `shield_bubble_entry` are in beam_geometry.h:41-98. `resolve_hit_point` is in beam_trace.h:88. All read the mirror and the live TransformStore.
  - K2 computes the same `K2Contact` (emitter, target_pos, hit, bubble, `shields_block`) per firing bank per tick (k2_beams.h:450-460), but keeps only rests and pulses, not a per-bank result table.
  - **Not mirrored:** the beam visual parameters (no width/colour/sides/taper fields in mirror.h; not found).
- **What a native builder needs:**
  - The firing banks, from the mirror's `_firing`.
  - Static visuals pushed once per bank, from the property at register time and on property change.
  - Per frame, the view set and render origin plus a small per-set render-offset table from Python.
  - A native `combat_beam_feed(kind)` that writes `g_phaser_beams` / `g_tractor_beams` directly, computing from the live store at frame time.
  - Do not reuse K2's tick-time contact: the frame's `sim.collisions` and other post-tick passes run between combat and render, so the drawn beam could otherwise differ.

**Torpedoes** (≈ 112 a frame):
- **Inputs:** `projectiles._active`; `t.GetTranslate()` (the store); `containing_set`; `to_render`; `_age`; `_velocity`; and 14 static visual slots: textures, five colours via `_color_tuple` (224 k calls, 0.314 s, the `try/getattr` loop at :1451-1466), sizes, `_id`, `_is_disruptor`, bolt fields.
- **Output:** dicts → `set_torpedoes` (host_bindings.cc:9349) → `g_torpedoes`.
- **Natively available:** position (TransformStore), torpedo rows with `cset` and `_age` / `_velocity` (`_TORP_FIELDS`, native_combat.py:3654). The visuals are not mirrored.
- **Quick Python fix:** build each torpedo's static descriptor part once, at `CreateTorpedoModel` / `CreateDisruptorModel` (projectiles.py:158-197), and per frame only set position, age and forward. The torpedo dynamic light (:1566) reuses `_color_tuple(_glow_color)` and the same position work.

**Tractor beams:** 0.27 s, almost all of it scanning every ship's tractor system (104 k `GetWeapon` / `IsFiring`). `_ships_in_view` is also computed twice per frame, once per builder.

**Emitter lights / particles: keep in Python for now.**
- Emitter lights read Python glow state: `subsystem_glow.commanded_impulse_frac`, `glow_maps.is_dark`, articulation `_articulate_emitter_light`, `_warp_glow_envelope` (dash / warp VFX).
- Particles are `particles.snapshot_descriptors`, from SDK effect controllers.

---

## 5. Tests

**Goldens** (tests/integration/test_golden_fights.py; tests/helpers/golden_fight.py; fixtures in tests/fixtures/golden_fights/):
- Scenes: host_frames, host_frames_tpf1, k1_gameloop_ai, k1_midwalk_handler, k1_ops_tpf1/tpf6, motion_branches, native_subsystems_scene, posed_fight, sdk_dumb_fire, tractor_modes.
- They record per-tick state rows (golden_fight.py:116-145):
  - systems; weapons (`_charge_level`, `_cooldown_remaining`, `_num_ready`, `_target_offset`, `offset_first_holder` / `offset_is_held_offset` identity, `_beam_on_countdown`, `asleep_not_at_rest`)
  - ships (IsDead, hull, shields); torpedoes (translate, `_velocity`, `_age`, ...); poses; tractors; tube `_reload_timers`; subsystem-stage rows
  - plus events, queued effects, calls (`apply_hit`) and the presentation multiset
- Every scene runs `_advance_combat(..., push_render_data=False)` (golden_fight.py:612, k1_fight.py:535/838, posed_fight.py:820), and host_frames uses `_run_frame_sim`. **So no render descriptors are recorded.**

**Differentials:**
- tests/integration/test_native_k0_differential.py: native vs Python walk, `.hex()` plus identity of the slot lists and watcher.
- tests/integration/test_passive_weapons_differential.py
- tests/integration/test_native_combat_step_differential.py
- tests/integration + tests/host/test_native_k3_differential.py
- tests/host/test_native_k2_differential.py (real instances)

**Unit:**
- test_native_k0_dispatch / _k0_mirror / _k0_override_guard
- test_native_k1_dispatch / _k1_holds_gil / _k1_no_fire
- test_native_k2_bindings / _dispatch / _override_guard / _scan_cache
- test_native_k3_bindings / _dispatch / _override_guard
- test_native_k4_eligibility, test_native_write_apply, test_native_combat_weapons_mirror / _k2_mirror / _k3_mirror, test_native_damage_clean_cache, test_native_gil_release, test_native_compute_timers, test_effect_queue, test_damage_effect_queue
- Guard, cache and fallback-reason tests that a guard deletion would break: test_native_k0_override_guard, test_native_k0_dispatch, test_native_k2_dispatch, test_native_k2_scan_cache, test_native_damage_clean_cache, test_native_k3_dispatch, test_native_k3_bindings, tests/host/test_native_combat_scene_audit.

**ctest** (native/tests/combat/): k0_charging_test, k1_fire_control_test, k2_beams_test, k3_projectiles_test, beam_geometry_test, beam_trace_test, weapon_geometry_test, projectile_geometry_test, damage_test, fire_gates_test, mirror_test, subsystem_step_test, and others.

**Render data — unit tests of the Python builders only:**
- tests/unit/test_render_feeds_by_frame.py
- test_tractor_beam_render_data.py
- test_torpedo_render_marshal.py
- test_dynamic_light_render_marshal.py
- test_dynamic_light_budget.py / _scope.py / _camera_fade.py
- test_shield_bubble_wiring.py (beam endpoint at the bubble)
- test_explosion_lights.py, tests/test_host_loop_emitter_lights.py
- tests/host/test_render_space_feeds.py (a recording fake `r`)
- tests/integration/test_frame_tripwire.py

No binding reads `g_phaser_beams` / `g_torpedoes` back (not found). A native builder needs one, for example a `*_debug` readback like `lens_flares_brightness_debug` (host_bindings.cc:9339), or these tests lose their coverage.

---

## 6. Risks

**Ordering:**
- K0 runs before combat. The K1 pump runs after the death and damage passes and feeds K2 in the same tick.
- K3 applies its hits only after every `expire()` (native_combat.py:6604-6610).
- `resolve_stale_part_slots` before each kernel is what keeps part slots fresh after Python effects: a cached replacement must still catch generation bumps made in between (`bump_part_gen`).
- K2's `_heal_part_slots` after ASKs.

**SDK and Python inside the loops:**
- K0: RUN_PYTHON → `UpdateCharge` / `UpdateReload` / `passive_weapons.advance`.
- K1 apply: wake hooks, `materialise`.
- K2: ASK answers (can_detect fallback, aim_point, resolve_hit, bank_step), CONTACT → `apply_hit` / `hit_feedback`, RUN_PYTHON.
- K3: ASKs (guide, steer_point), `expire()`'s synchronous SDK set events, Python `apply_hit` hand-backs.
- AI-started K1 sessions flush the effect queue at their own end (2.37 s in `gl.ai`, outside this stage).

**Fallbacks that exist today (against spec §3 "Part A does not fall back"):**
- K0:
  - `k0_weapons` stand-downs `off` / `audit` / `nested` (native_combat.py:5108-5113), then the Python walk (host_loop.py:952-956).
  - The override guard: class verdicts (`_K0_METHODS` :4959, `_k0_flag` :5071), instance patches (`_K0_SHIP/SYSTEM/WEAPON_PATCHES` :4981-4984) and the `FloatRangeWatcher._update` check (:5124).
  - RUN_PYTHON reasons (k0_charging.cc:215-229).
- K1: native only, with no-fires instead (k1_no_fire).
- K2: `_k2_step_fallback` (:6009) → the Python `cb.phasers` loop; per-ship `_k2_python_ship` (:5600); `python_banks`; pulse `not_ok` / `unscanned`; ASK Python answers.
- K3: `_k3_fallback` (:6498) → the Python `update_all` body.
- K4: `k4_update` reasons (:6234).
- Damage: `_dmg_unchanged` / `_kdmg_unchanged` plus the clean scans.
- `DAUNTLESS_NATIVE_COMBAT=0` still switches K0/K2/K3 to Python (native_combat.py:228).
- Our own hook that must be carried, and already is: the dev combat cheats in `_kdmg_ctx` (:7323-7325) and `_K2Context` (:5780).

**Things that make a quick win harder:**
- The goldens read `__dict__` directly and record offset identity.
- The K0 differential checks the identity of the slot lists and the watcher.
- Skipping a Manual Aim `_target_offset` write would change `offset_first_holder` grouping.
- The torpedo colour objects (SDK TGColorA) could in theory be mutated after `Create*Model`; caching them at create time assumes they are not.
- A native beam feed must match the Python endpoint rules: cross-region `offset_between`, bubble ?? hull trace ?? centre, `raw_length*1.5`. There is no golden to confirm it.
- Deleting guards needs a ruling and test rewrites; the spec already allows it for Part A.

---

## 7. Ranked cheap, high-value changes

**A2 (weapons, 4.2 s profiled; ≈ 0.6 ms/tick at 128):**
1. `k0_weapons` passes `ctx=None` and the override guard is deleted (native_combat.py:4899-5150; binding unchanged). Saves most of begin: up to ≈ 36% of weapons (begin 1.53 s; what remains is about 128 `_nslot` gets plus `plan_ship`).
2. A lean K0 applier (no pins dict or kind lookup per write; one registry lookup per handle run), following subsystem_write_apply. Saves an estimated 20-30% of weapons (derived: apply ≈ 0.29 of 0.42 ms in next).
3. A persistent `ShipPlan` cache keyed by a layout generation, with reused vectors (k0_charging.cc:567-584). Saves a few % more.
4. Later and larger: native-authoritative `_charge_level`, slot lists and watch value, with `__get__` (removes the write-back; needs golden-recorder and differential changes).

**A3 (combat glue, 14.1 s profiled):**
1. Skip K1 sustain writes that change nothing, in the held-offset case (k1_fire_control.cc:1431-1438 plus a mirror offset-source field). Up to ≈ 10% of combat (the 1.42 s of `materialise`).
2. Delete the Part A override and patch scans: `scan_ships`, `dmg_clean_handles` (needs a K2/K3 "clean all" flag), `_k2_unchanged`, `_k2_classes_unchanged`, `_k3_unchanged` / `_k3_classes_ok`, `_kdmg_unchanged`. ≈ 11%.
3. An O(1) `resolve_stale_part_slots` via a pending set. ≈ 4%, more counting the AI sessions.
4. Index `broadcast_membership` by name (objects.py:1369). ≈ 3% (0.4 s).
5. A K3 C applier for `_k3_apply`, plus the `_scan_table` import hoist. Up to ≈ 7% (the hoist alone ≈ 0.6%).
6. One shared per-tick native roster for K0/K1/K2/step_scan, removing the `slot()` loop and repeated `_nslot` scans. ≈ 2-3%.

**A4 (render data, 3.8 s profiled; ≈ 2.7-3.0 ms/frame at 128):**
1. Torpedo static descriptor built once per torpedo (kills `_color_tuple` and the texture resolution per frame). ≈ 10-15% of render data (≈ 0.4-0.5 of 0.78 s).
2. Beam and tractor builders walk only firing banks, and compute `_ships_in_view` once. ≈ 10% (scan ≈ 0.2 s plus tractor ≈ 0.2 s).
3. A native beam feed: mirror-firing banks, beam_geometry.h / beam_trace.h on the live store, visuals pushed per bank, plus a readback binding for the tests. ≈ 50-58% (phaser 1.94 s plus tractor 0.27 s).
4. A native torpedo feed and torpedo lights from the torpedo table, with visuals pushed at create. ≈ 20%, after item 1 has taken the easy part.
5. Leave particles, emitter lights and hit VFX in Python.
