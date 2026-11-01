# Native combat: posed parts in C++ — design

**Status:** approved by Mark 2026-11-01 ("let's just get it ported to C"). Workstream C (first fallback) of `2026-11-01-threaded-weapons-combat-roadmap.md`.
**Branch:** `ws/combat-posed-parts`, off `project/combat_threading`; merges back into it (no main merge, so no full gate — focused tests and differentials only, per CLAUDE.md "Test gate").
**Input map:** `docs/reference/engine/native-combat/posed-parts-map.md` (cited below as MAP §n). Its file:line references are the authority for Python operand order.

## 1. Intent

Articulated ("posed") parts are a Dauntless feature, not BC: a hull rig moves parts (stock: the Bird of Prey's wings, ±45° in cruise/yellow/warp, identity at red) and mods add rigs. Today any ship with a part off identity is handed to Python wholesale by the native kernels (K1 `posed_ship` / `posed_target`, K2 `posed_ship`, K3's `steer_point` ASK). This phase ports the posed path to C++ so posed ships run natively, bit-exactly.

**Why now, given the perf value is small:** in the stock 64-ship fight the posed fallback is only the Birds of Prey before red alert. The value is (a) rigged mod ships run natively in combat, and (b) this is the largest routine fallback, which must close before any kernel's Python copy can be retired (roadmap workstream E).

## 2. Goals, non-goals

**Goals**
1. K1 never hands a system to Python because its ship or target is posed (`posed_ship`, `posed_target` reasons reach 0 in the differentials), except where a part slot is stale (§4.4).
2. K2 never hands a ship to Python because it is posed; the lock-ship half of K2's `aim_point` ASK goes.
3. K3's posed-target `steer_point` ASK goes whenever the offset is a mount (bit-for-bit `== mount_sub._position`).
4. Bit-exact with Python, switch on; byte-identical behaviour, switch off.

**Non-goals**
- Manual Aim (`authored=False`, box rule): stays an ASK (player-only, rare).
- Hit attribution / `part_for_live_point`, severing, layered damage: unchanged, stay Python.
- The renderer's node overrides (float32, model units, a frame stale — MAP §2.4): never read by combat.
- Fixing Python's behaviour: arc/strip/cone DIRECTIONS are not posed in Python (MAP §1.1, R7). Copy that.
- Retiring the Python copy (workstream E). Perf benchmarks: none required; correctness is the bar.

## 3. Constraints (from the native-combat programme)

- Bit-exact: compare by `.hex()`; Python operand order; `mult_matrix_left` for the row-major pose; `py_pow`/`py_sin`/`py_cos`/`py_min`/`py_max`/`dist3` as elsewhere; every new `.cc` in the combat sources list with `#pragma clang fp contract(off)`; NaN branches as Python.
- A field the kernel reads MUST push (Native descriptor or pushing mutator). Every MAP §3.3 mutation site is covered (§4.3).
- Switch `DAUNTLESS_NATIVE_COMBAT=1`, default OFF; with it off, nothing new runs (the `has_posed_parts` gate keeps the native path byte-identical when 0 — `tests/unit/test_native_posed_flag.py`).
- `DAUNTLESS_NATIVE_AUDIT=1`: `audit_mirror` also compares the pose table and part slots (R10).
- GIL held. One copy of each effect: `part_transform_point`, `_live_part`, `authored_mount_subsystem` stay the Python reference; the C++ holds the second copy of the arithmetic only. **Part resolution (which part a mount is on) is NEVER computed in C++** — Python resolves, C++ reads the pushed slot (R4, R5).

## 4. Design (MAP §5.2 design A, with the K1 mount order mirrored)

### 4.1 Mirror data

- **Object row: `part_poses`** — one entry per name of `articulation.posed_part_names(ship)`, in that order (R11). Each entry: `r[9]` (Python's `R[i][j]` → `r[3i+j]`, row-major, as stored), `t[3]`, `identity` (Python's `part_pose.is_identity`, pushed, never recomputed), `detached` (`name in ship._parts_detached`). Empty when `_posed_flag` is 0.
- **Subsystem row: `part_slot`, `part_gen`** — the index into the owning ship's `part_poses` of the name `_live_part` resolves for the subsystem's own `_position` with `prop = physical_parents.property_of(sub)`, **ignoring detachment** (the entry's `detached` bit carries that); -1 for None or a name not in the table. `part_gen` = the global part-map generation at resolution.
- **Global: `part_gen`** — bumped at every trigger in §4.3.
- **Object row: `mount_order`** — the ids of the ship's subsystems in `combat._iter_subsystems` order (each top-level subsystem, then its `_children`), so the kernel can mirror `part_severance.authored_mount_subsystem`'s first-match-within-1e-5 rule (MAP R3, PS:502-514). Pushed on subsystem attach/detach and `_children` change.

### 4.2 Resolution (Python only)

`native_combat.resolve_part_slots(ship)`: for a posed ship whose `_articulation_leaf` is already a non-empty `str` (R5 — never trigger `leaf_for`), push `part_slot`/`part_gen` for every subsystem in `mount_order`, using the same call `_live_part` makes minus the detached test. Called lazily at a step boundary (`step_scan` and `k1_pump`/`k1_system` begin, before the kernel runs) for each posed ship whose slots' generation is behind the global one. An unposed ship needs no slots (its path is identity).

### 4.3 Push and invalidation triggers (MAP §3.3)

| Input | Site | Action |
|---|---|---|
| poses (rebind, in-place) | `PosedPartsField.__set__`, `tick_ship` end-of-tick `push_posed_parts` | push the pose table (extend `push_posed_parts`) |
| `posed_part_names` change (rig, forced names) | same sites | push table; bump `part_gen` |
| `_parts_detached` | `part_severance` create / `sever` / `reset_ship` | re-push the table (detached bits), synchronously (R6) |
| `SetPhysicalParent` | `properties.py` | bump `part_gen` |
| SPV preview overlay | `physical_parents.set_preview` / `clear_preview` | bump `part_gen` |
| leaf model learned, derived boxes learned | `articulation._remember_leaf_model`, `_derived_boxes[leaf] =` | bump `part_gen` |
| rig snapshot | `articulated_part` `_GENERATION += 1` sites | bump `part_gen` |
| subsystem `_position` | existing mirrored field write | bump `part_gen` (that subsystem's slot) |
| subsystem attach/detach, `_children` | existing subsystem registration sites | push `mount_order` |

A missed trigger can only leave a slot stamped with an old generation; the kernel treats a stale stamp as "not resolved" and falls back (§4.4). Speed, never exactness.

### 4.4 Kernel arithmetic (MAP §4)

- **P1/P2 pose apply:** `mult_matrix_left(r, x) + t` componentwise; if the slot is -1, or the entry is `identity` or `detached`, return the input unchanged (branch, never multiply — signed zeros, R8).
- **P3 mount** (`mount_position`, WG:77-90): replace the `has_posed_parts` throw with: posed ship → slot lookup → P1/P2 on `_position` → existing P3 (pose before the ship rotation; no scale).
- **P4 target offset** (`target_offset_world`, WG:217-226): find the mount subsystem — K3: the pushed `_mount_key` mount (`row.mount_attributed`), used only when `offset == mount._position` bit for bit (else ASK as today); K1 `_RESOLVE`: first subsystem in `mount_order` whose `_position` is within 1e-5 per Python's comparison (copy PS:511-512 operand order exactly), else no mount → `authored=False` path → identity (copy `part_transform_point` semantics for no part). Then P1/P2 on the offset → existing P4 (pose before scale).
- **Stale slot:** a posed ship/target whose needed slot has `part_gen != global part_gen` → K1/K2: the existing per-system/ship fallback with a NEW reason `part_stale` (replacing `posed_ship`/`posed_target`); K3: ASK `steer_point` as today. After §4.2 runs at the step boundary this should be 0 in steady state; the differentials assert it.
- K2 `aim_point` ASK: keep it only for Manual Aim (`authored=False`); the lock-ship case uses P3 on the lock's own ship.

### 4.5 Reasons and counters

`posed_ship`/`posed_target` stay in the reason enums (counted 0) for one release so dashboards don't break; add `part_stale`. Counts: `k1_python_reasons`, `k2_python_reasons`, K3 `k3_asks["steer_point"]` + a `steer_point` reason split if the K3 counters allow it.

## 5. Testing

- Unit `.hex()` differentials vs Python for P1-P4 on random poses incl. identity (signed zeros), detached, scaled target, NaN, near-1e-5 mount matches, parent/child sharing a point with different physical parents (R3).
- Trigger tests: each §4.3 site bumps/pushes; a missed bump yields `part_stale`, never a wrong value.
- Kernel tests: K1/K2/K3 posed cases now native; reasons.
- Differentials (headless + host): Birds of Prey mid-transition AND settled in cruise, firing and being fired at (phasers, pulse, torpedoes, subsystem locks), at 1 and 4 ticks per frame; a severed wing mid-fight; per-tick `.hex()` compare as the K3 differentials (`tests/helpers/k3_fight.py` pattern); posed fallbacks 0 and `part_stale` 0 asserted.
- Scene audit: combat_stress unaudited → posed reasons 0; audited → pose table and slots audited clean.
- Mutation proofs: pose applied after rotation; direction posed; identity multiplied instead of branched; stale stamp ignored; parent-before-child order reversed.
- Switch off: existing posed tests (`test_native_posed_flag.py`, `test_target_offset_articulation.py`, `test_physical_parents.py`, `test_physical_parent_consumers.py`, `test_part_severance.py`, `test_articulation_transitions.py`, `test_part_pose.py`) unchanged and green.

## 6. Left to the builder

File layout of the new native code (a `part_pose` helper in the combat library is expected), exact binding names (follow `combat_set_*` patterns), how `mount_order` is encoded (Ids list like `combat_set_ids`), and where exactly the lazy resolution hooks sit at the step boundary.

## 7. Open items for Mark (not blocking)

- Live check: a Bird of Prey fight with the switch on (wings moving while firing) after the build.

## 10. Outcome

(Filled at the end.)
