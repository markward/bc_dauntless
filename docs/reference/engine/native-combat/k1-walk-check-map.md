# K1 walk check — code map, and moving it to the step boundary

> *Built 2026-11-02 (launch deferral, Task 1): §4.1's design, without a separate begin scan (the first `next()` scans before any compute). This map is the pre-build snapshot.*

> **Superseded (2026-11-03, fire control native only):** the walk check is deleted. The instance-patch and ship-class guards, `set_walk_check`, `k1_scan` and `k1_session_check` went with fire control's Python copy (M3), and a K1 entry the mirror cannot read is a counted no-fire. See `docs/superpowers/specs/2026-11-03-fire-control-native-only-design.md` §6.



Read-only map, 2026-11-02, worktree `native-combat-k3`, branch `ws/combat-launch-cache` (HEAD `c2b0534c1`).
Abbreviations: **K1H** `native/src/combat/include/dauntless/combat/k1_fire_control.h`, **K1C** `native/src/combat/src/k1_fire_control.cc`, **HB** `native/src/host/host_bindings.cc`, **NC** `engine/appc/native_combat.py`, **RFM** `docs/reference/engine/native-combat/remaining-fallbacks-map.md`, **PR** `docs/reference/engine/perf-register.md`, **RM** `docs/superpowers/specs/2026-11-01-threaded-weapons-combat-roadmap.md`.
Anything not read directly off the code or a doc is marked **inferred**.

---

## 1. What K1's walk check is

### 1.1 Contract

- K1H:44-55: the check (`set_walk_check`) runs **at every walk start, before any offset**. If it answers true, the walk starts the old way: a `WALK_START` record, which Python answers with `set_offset` (its own `_live_held_offset`) or `skip_walk` (an instance-patched method: Python runs the walk whole). The kernel is plain C++. The bindings' check is not: it does CPython lookups with the GIL held. "So next() needs the GIL while the check is installed (workstream I)."
- K1H:86-93: the pump's `sys_.StopFiring()` is also asked first. If the check answers true, the `STOP_SYSTEM` record is kept instead of the logged stop.
- K1H:312-314: `using K1WalkCheck = std::function<bool(int64_t system, int64_t ship)>`. K1H:335-336: `set_walk_check`. K1H:400: one `walk_check_` member on the **kernel**, not per session.
- With no check installed, every walk starts natively (K1H:53).

### 1.2 When it is called (all inside `K1Kernel::next()`, K1C:1372-1392 → `Walker::run`)

| Call site | When | How often |
|---|---|---|
| K1C:953 `case St::UW_DEAD_PRUNE` | Once per **walk start** (each system the pump walks, and each `begin_system` StartFiring session), after the dead-ship check and the `_target_list` prune write | 73.0 a tick at 64 ships (RFM:15, R1 total 657,337 over 8,999 ticks, RFM:252) |
| K1C:446-447 `system_stop()`, reached from K1C:896-901 | Once per **pump stop** (`pump_stops` true: system offline/off, held target dead or undetectable, phaser out of range) | 1.3 or fewer a tick (old `STOP_SYSTEM`/K2 rates; RFM:19, 264); **inferred** to be low |

It is **not** called per record and **not** per bank. The class half of the guard (`k1_overridden`, a mirror row flag) is read by `prescan` (K1C:571, 636). That flag is computed in Python and pushed at the step boundary (§3.1).

### 1.3 What the bindings' check does (`k1_walk_check`, HB:4319-4366; wrapper `k1_walk_needs_python`, HB:4369-4374)

It reads the refs installed by `combat_k1_set_walk_check` (HB:11746-11791; struct HB:4247-4255). The Python side sends them once, in `_k1_send_walk_check` (NC:1387-1393): the registry's `data` dict, `_K1_SYSTEM_PATCHES`, `_K1_LEAF_PATCHES`, `_K1_SHIP_PATCHES`, and ShipClass's raw `is_using_target_offset` / `GetTargetOffsetTG` (snapshotted by `k1_snapshot_ship`, NC:1376-1384).

CPython calls, in order:
1. **Registry handle → object** (`k1_registry_get`, HB:4265-4284). This does `PyLong_FromLongLong(h)` (an allocation that is not GC-tracked), `PyDict_GetItemWithError` on `WeakValueDictionary.data`, `PyWeakref_Check`, and `PyWeakref_GetObject`. Done for the system, and later for the ship.
2. **Instance dict, never built** (`k1_built_dict`, HB:4296-4310). On 3.11-3.13 it reads the managed-dict slot at `o[-3]`, and returns null when the slot is unset or tagged. Otherwise it uses `_PyObject_GetDictPtr` (through `k2_dict_of`, HB:3564-3569). A null dict means the walk goes to **Python**.
3. **System dict**: `PyDict_Contains` for each of `_K1_SYSTEM_PATCHES` (4 names: `update_weapons`, `try_fire_weapon`, `_live_held_offset`, `StopFiring`; NC:1322-1323), via `k1_holds`/`k2_holds` (HB:4312-4316, 3572-3578).
4. **Children**: `PyDict_GetItemWithError(sd, "_children")`. If that is not an exact list or tuple, Python. For **each child**: its built dict, then a `PyDict_Contains` for each of `_K1_LEAF_PATCHES` (5 names: `Fire`, `_fire_decide`, `_fire_effect`, `StopFiring`, `CanFire`; NC:1324-1325). Uses `Py_INCREF`/`Py_DECREF` on the list (HB:4330-4345).
5. **Ship** (when `ship_h >= 0`): registry get, built dict, a `PyDict_Contains` for each of `_K1_SHIP_PATCHES` (2 names; NC:1331).
6. **Ship class, MRO**: `_PyType_Lookup(type, "is_using_target_offset")` and `_PyType_Lookup(type, "GetTargetOffsetTG")`. These go through CPython's method cache, which is keyed on the type version tag. Their results are compared by identity with the stock entries. `PyType_IsSubtype(type, ShipClass)` is an MRO walk (HB:4352-4365).

There are no version-tag reads or dict-version caches. Every call probes from scratch.

**What it decides:**
- `1` hands the walk start back: `WALK_START` (K1C:953-957). Python's `_K1Walk.walk_start` (NC:2983-3006, driver NC:3380-3397) repeats the instance-patch scan in Python. A patch means `walked.update_weapons(dt)` then `skip_walk`, counted as `K1Why::InstancePatch` (K1C:1411-1418). No patch (a non-stock ship class, or an unbuilt dict) means `_live_held_offset()` and then `set_offset`.
- `0` starts the walk natively: offset from the mirror (`k1_live_held_offset`, K1C:1445+), `++logged_walk_start` (K1C:958-960).
- For the stop: `1` keeps `STOP_SYSTEM` (K1C:899-901). `0` logs the stop's writes and entries.
- A CPython error is cleared and answers true (HB:4371-4373). If no registry was sent, the answer is true (HB:4371).

### 1.4 What it costs

- **Not separately measured.** PR SIG-167 (PR:440, item 3): "K1's per-walk `_target_list` write and walk check remain (**inferred**, not separately timed)." The round-trips spec has the same: `docs/superpowers/specs/2026-11-01-native-combat-round-trips-design.md:130`.
- Before round trips, the Python `WALK_START` handling, which included the same patch scan in Python, cost 7.47 µs a record and 0.536 ms a tick (RFM:272, Debug, instrumented). The C check replaced that. Fire control went from 1.335 to 1.000 ms a tick together with §3.2 and §3.4 (RFM:317, SIG-166).
- **Inferred estimate** of the C check alone: 2 registry gets, about 4 + 5×(children) + 2 dict probes (a probe is ~20 ns, per NC:3546), and 2 method-cache lookups. That is roughly 0.5-1.5 µs a walk start, or about 40-110 µs a tick at 73 walk starts (Debug). It has not been timed.

---

## 2. Every place a kernel's `next()` touches CPython or Python objects mid-walk

The combat library itself (`native/src/combat/`) includes no `Python.h` (grep shows no `Py*` there). It has three callback seams, all `std::function`s installed by the bindings:

| Kernel | Seam | Inside the kernel compute? | Touches CPython? |
|---|---|---|---|
| **K1** | `K1WalkCheck` (K1C:447, 953) → `k1_walk_needs_python` | **yes** | **YES: the only CPython touch in any kernel compute** (§1.3) |
| K0 | `K0WeaponCheck` (K0 header `k0_charging.h:242, 306`; called K0 `.cc:744`) | yes | **no**: a closure over a `shared_ptr<unordered_set<int64_t>>` built at `combat_k0_begin` (HB:11920-11929). HB:11948: "The weapon check is a set lookup made at begin: no CPython call inside the walk." |
| K2, K3 | `TraceHooks` (`beam_trace.h:53-62`; used K2 `.cc:950-971`, K3 `.cc:445-463`) | yes | **no CPython**. They read `g_world` and `g_loaded_models` (HB:716-749, 753-772: "touching no Python"). ⚠️ This is shared host state that Python-driven host calls mutate (transform sync). Off the lock it still needs ordering against those writers (**inferred**, not a lock issue as such). |
| K2 | `python_ships` (K2 `.cc:667`) | yes | no: a C++ `unordered_set` in the context, sent at begin (NC:4654) |
| K1, K2 | `k1_overridden` row flag (K1C:571, 636; K2 `.cc:365, 550, 681`) | yes | no: a mirror field |

Everything else in the walks is mirror reads and writes, plus K1's `can_detect` memo and latch, which is C++ state in `sensor_detect` (K1C:743-750).

**In the binding, between records (not the kernel), all under the GIL:**
- The write applier (`WriteApplier::apply`, HB:11660-11666 for K1, 11962-11973 for K0, 12175-12178 for K2). It does handle → object through the pin dict and the registry, quiet setters, `passive_state.wake` (a Python call) for a WakeField, `APPLY_PYTHON` setters (Python calls), and `_K1Walk.materialise` → `system._live_held_offset()` (Python) on a `walk_offset` write (NC:2945-2967, 3111-3132).
- Record tuple building (pybind objects), and `k1_append_entries`/`k0_append_entries` into the C++ effect queue (HB:4046-4090).
- Python itself runs only between records: K1's tube or pulse `_fire_effect` (the launch scripts), `FireDumb`, fallback `StopFiring`, `RUN_PYTHON` (`pump_body` / `update_weapons`), ASK answers (which can run a real `Fire`, `try_fire_weapon` or `CanFire`; NC:3255-3311), and a handed-back `WALK_START`. K2: damage-pulse `CONTACT`, ASK, `RUN_PYTHON`, fallback stops, `cx.resend()` (NC:4557-4581). K0: `RUN_PYTHON` `UpdateCharge`/`UpdateReload` (NC:3828-3851). K3: ASK answers.
- Weapon events and sounds no longer run mid-walk: they go to the effect queue, delivered at the tick boundary or at the session's end (K1H:73-99).

**A second, separate blocker to releasing the GIL** (HB:11643-11653; `tests/unit/test_native_k1_holds_gil.py`): mirror rows are freed by `weakref.finalize` → `native_combat.unregister_handle`. Cyclic GC can run that on whatever thread holds the GIL (the packaged log tee allocates). So a released GIL could free a row mid-read. Moving the walk check does **not** remove this. Workstream I still needs its own row-lifetime guarantee, for example deferring unregisters to the step boundary (**inferred** remedy).

So the list of what still needs the lock *inside the kernel compute* is: **K1's walk check, and nothing else**. Plus, for all kernels, the row-lifetime hazard above, and the `g_world` ordering for the K2 and K3 trace hooks.

---

## 3. How K0 and K2 avoid in-walk lookups

### 3.1 K1's own class guard is already at the boundary
`_k1_recheck_overrides` (NC:1421-1453) runs at every K1 entry (`k1_pump` NC:3445, `k1_system` NC:3470). It does one `attrgetter` per watched class and re-pushes `k1_overridden` to rows on a change. The kernel then reads only the row flag. A class patch made mid-session is seen at the next entry (NC:1428-1429). The roadmap notes it still has the `super()` blind spot (RM:80).

### 3.2 K0: one begin scan with exact caches (HB:4380-4470 doc, `k0_scan` HB:4822-4895; Python NC:3525-3572)
- `combat_k0_begin` (HB:11881-11945) runs `k0_scan` over the **Python ship list**: ship → its 4 group slots (`_phaser_system`, ...) → each child in `_children` (and the torpedo magazine). It reads each object's `_nslot` directly (`k0_handle`, HB:4696-4709), with no registry lookup.
- **Class verdict cache**: per type, valid while `tp_version_tag` is unchanged (`k0_type_valid` HB:4625-4630). It sits behind a 64-entry direct-mapped table. A type with no verdict comes back as `missing`, Python computes `_k0_flag` (NC:3696-3712), and begin is retried (NC:3765-3775). All cached types are re-validated once per scan (`k0_types_unchanged` HB:4689-4693, called HB:4843).
- **Object answer cache**: by **position** in the scan. The key is (type, dict pointer, `ma_version_tag`) (`k0_same` HB:4608-4611). PEP 509 versions are process-wide and never repeat, so an unchanged dict is an unchanged answer. Lists and the magazine are read live, because in-place mutation doesn't bump the owning dict. This cache is used **only on CPython 3.11** (`kK0ObjectCache`, HB:4590-4596). Other versions take the uncached path: same verdicts, slower.
- The result is a C++ `unordered_set` of weapon handles plus a per-ship handback vector, handed to the kernel. **No CPython inside `next()`.**
- **Mid-session patches:** "THE BEGIN-SNAPSHOT BOUNDARY" (NC:3567-3572). A patch made by a record's handler during a session takes effect **at the next session, one tick later**. NC:3570-3572 explicitly contrasts K1: "K1 is stricter ... it rechecks per walk".
- Cost: the guard is ~14 µs a tick at 65 ships and 762 weapons, idle, Debug (PR:436, SIG-171; history ~53 µs before the caches, HB:4409).

### 3.3 K2: begin-time C scan, no cache (HB:3540-3663; Python NC:4205-4274, entry NC:4634-4660)
- `combat_k2_scan_ships` runs every tick. It checks the ship's class is in `_k2_seen_set`, and the ship dict for `_K2_SHIP_PATCHES`. It checks that the phaser system's class is exactly the stock class, plus its dict for `_K2_SYSTEM_PATCHES`. For each bank it checks the class is exactly the stock bank, its dict for `_K2_BANK_PATCHES`, and that `_target`'s class is seen. Unclean ships go to `_k2_python_ship` (Python), and the result is the `python_ships` set in the begin context. The class and function checks (`_k2_unchanged`, NC:4131-4146) run once at entry.
- **Mid-session patches:** the set is fixed at begin. `cx.resend()` (NC:4393-4397) re-sends only iids, cheat and view. An instance patch made by a damage-pulse handler mid-step is seen next step. The K2 header says a class patch is seen "a tick late" (`k2_beams.h:337-343`).
- Cost: ~85 ns a bank in a Debug build (NC:3969).

### 3.4 Could K1's check go to the boundary?
Yes. Its inputs are exactly the K0 scan's tree, with different names: ship → group systems → children, plus the ship's type. The type half caches on `tp_version_tag` just like K0. The instance half caches on `ma_version_tag` (3.11).

- **Objects a tick at 64 ships**: 65 ships, at most 4×65 group slots (tractor systems are `pump_self_managed`, K1C:880-882, so they never reach the check), and about 762 weapons (SIG-171). That is about 1,000 objects for a full scan, with idle cost close to K0's ~14 µs (**inferred**). A scan restricted to systems whose mirror row has `_fire_held` would cover about 72 walked systems and their children (**inferred** from 73 walk starts a tick).

**Which Python runs mid-pump and could invalidate a boundary verdict:**
- Tube and pulse launch scripts (K1 `FIRE` → `_fire_effect`)
- `FireDumb`
- ASK answers (real `Fire` / `CanFire` / `try_fire_weapon`)
- `RUN_PYTHON` (`pump_body`, `update_weapons`)
- Fallback `StopFiring`
- The applier's `APPLY_PYTHON` setters, `passive_state.wake`, and `materialise` → `_live_held_offset`
- A nested `k1_system` session started from any of these

Events and sounds are queued, so no event handler runs mid-pump since fire events (K1H:73-99; `tests/integration/test_native_k1_differential.py:703-710`). None of the stock code is known to instance-patch a K1 method (**inferred**, not grepped across mods). Every existing test patches between ticks, in `script(w, t)` (§4.3).

---

## 4. Recommended design

### 4.1 Boundary scan + revalidate at each `next()` entry (exact, keeps ruling F5)
1. **Scan at begin, in the binding.** `combat_k1_begin_pump(ships, ...)` takes the Python ship list (as `combat_k0_begin` does) instead of a handle vector. A `k1_scan` walks ship → the phaser, pulse and torpedo slots → children, and computes **two verdict sets**:
   - **system set**: the system's dict ∩ `_K1_SYSTEM_PATCHES`, any child's dict ∩ `_K1_LEAF_PATCHES`, or an unbuilt dict, or a `_children` that is not a list or tuple.
   - **ship set**: the ship's dict ∩ `_K1_SHIP_PATCHES`, or a class whose `_PyType_Lookup` of the two names isn't stock (cached per type on `tp_version_tag`).

   It uses K0's object cache: keyed by position, (type, dict, `ma_version_tag`), with live list reads. `combat_k1_begin_system(system)` scans that one system and its children, plus the ship from `climb_to_ship_of`, mapped through the registry once, at begin.
2. **Kernel check becomes data**: `check(sys, ship) = sys_set.count(sys) || ship_set.count(ship)`, a pure C++ lookup like K0's `set_weapon_check`. **Store it on the Session**, not on the kernel (K1H:400). K1 sessions nest (a damage pulse's handler starts another ship's K1 session, `tests/unit/test_native_k2_dispatch.py:2465`), so each session needs its own sets.
3. **Revalidate before each `next()` compute.** Python can run only between records. So at the top of `combat_k1_next`, still under the GIL in the binding and before the kernel compute, re-run the cached scan for the top session. Unchanged objects cost a pointer and version compare. Any changed dict or type is re-probed. A verdict used at a walk start is then current as of the last Python, which is **exactly today's semantics** (today the check runs at the walk start, and no Python runs inside a `next()`). Records a tick are now few (DONE ~2.3, tube or pulse FIRE ~0.05; RFM:256-260, post-fire-events kinds K1H:100-103), so this costs about 2-3 cached rescans a tick (**inferred**).
4. The kernel compute then contains **no CPython call**. It can run with the GIL released once the row-lifetime blocker (§2) is solved.

### 4.2 Cheaper alternative: K0/K2 semantics
Scan once at begin and never revalidate. A patch made mid-pump is seen next tick. This matches K0 (NC:3567-3572) and K2. But it **reverses ruling F5** ("a patched method is never decided natively", round-trips spec:108; RFM:317), so it **needs Mark's ruling**. It saves the per-record rescan, which is small anyway.

### 4.3 Risks
- **The ship key.** Today the check uses `climb_to_ship_of(sys)` (K1C:447, 925). A pump scan naturally has the *pump list's* ship. They differ only for a system whose parent isn't the listed ship. `prescan` rejects such children (K1C:637-641) but not the system itself (**inferred** rare). Key the ship set by the climb ship's handle, and add a ship found by climbing but not in the list (a registry lookup at begin).
- **Coverage.** Every system the pump can walk must be scanned. A group slot swapped mid-pump changes the ship dict version, so the rescan catches it. A child appended in place changes the list, not the dict, so read `_children` live (K0 does).
- **Python ≠ 3.11.** There is no object cache there (HB:4590-4596): every rescan probes everything. That is about 1,000 objects × 3 rescans a tick, about 0.1+ ms in Debug (**inferred**). Restrict the scan to `_fire_held` systems (a mirror read) to cut it to about 72.
- **Unbuilt dicts must still be handed back, never built** (HB:4285-4295). K0's `k0_dict_of` has the same rule.
- **`__class__` swaps**: compare the type in the key (K0 does).
- **Name tuples or registry changed** (a test re-sending the check, `test_walk_check_hands_back_an_unmaterialised_dict`) must drop the caches, as K0 does when its names change (HB:4833-4841).
- **The test hook changes shape.** The C++ `K1WalkCheck` signature can stay. Only the binding's implementation changes, so `k1_fire_control_test.cc` keeps working.
- **This doesn't by itself release the GIL** (row lifetime, §2; `test_native_k1_holds_gil.py` must then be revised deliberately).
- **Retiring instead.** RM:80 and the round-trips spec:135 say the check is scaffolding and could go with the Python copies (workstream E). If E lands first, deleting it beats moving it.

### 4.4 Tests that pin current behaviour
- `tests/unit/test_native_k1_dispatch.py`:
  - `test_instance_patch_runs_python` (:589-611): `tube.Fire` instance patch → `instance_patch` reason, ON == OFF.
  - `test_ship_class_without_is_using_target_offset_hands_walk_back` (:1822-1840)
  - `test_stop_firing_override_runs_python[class|instance]` (:1843-1878)
  - `test_walk_check_hands_back_an_unmaterialised_dict` (:1881-1941; installs a fake registry via `combat_k1_set_walk_check`, asserts the dict stays unbuilt)
  - `test_system_instance_stop_patch_runs_python` (:2317-2343)
  - the no-`WALK_START` block (:1236-1283)
  - the class-flag test ending at :586
- `tests/unit/test_native_k1_holds_gil.py` (no GIL release in the K1 bindings).
- `tests/integration/test_native_k1_differential.py` (:228-229, :584 no `WALK_START`; :703-800 handler mid-walk, `test_handler_stops_and_restarts_mid_walk`).
- `tests/host/test_native_combat_scene_audit.py:124, 166`; helpers `tests/helpers/k3_fight.py:891`, `tests/helpers/posed_fight.py:908` (they assert no `WALK_START`).
- `native/tests/combat/k1_fire_control_test.cc`: a `legacy` always-true check (:43-48), the `WALK_START` sequences (:330 onward), `skip_walk` (:1419-1431), `instance_patch` naming (:1345).
- For comparison: `tests/unit/test_native_k0_override_guard.py:215, 306` and `tests/unit/test_native_k2_dispatch.py:1104` (instance patches handed back at begin).
- **Gap:** no test patches a K1 method *mid-pump* (from a launch script or an ASK answer) and checks it is obeyed by a later walk in the same tick. Add one before choosing between §4.1 and §4.2.
