# Native combat: cut the per-record Python round trips — design

**Status:** draft for Mark, 2026-11-01. Workstream C (second half) of `2026-11-01-threaded-weapons-combat-roadmap.md`, re-scoped by measurement.
**Branch:** `ws/combat-round-trips`, off `project/combat_threading` (after `ws/combat-posed-parts` merges back); merges back into it (no main gate — focused tests, differentials, and two benchmark runs).
**Input map:** `docs/reference/engine/native-combat/remaining-fallbacks-map.md` (MAP §n).

## 1. Why this, not "close fallbacks"

Workstream C was planned as "close the routine fallbacks". Measured (MAP §0, §2): in a 9,000-tick 64-ship headless fight every K1/K2/K4 fallback reason and ASK, and every K3 whole-step reason, counted **0**; the only non-zero question was K3 `steer_point`/`unattributed` (0.06 per tick). The posed-parts phase closed the last large fallback.

What still crosses into Python every tick is the **record protocol itself**: the kernel hands back records whose Python side is pure field writes or presentation (MAP §2.3-2.4, Debug, indicative):

| Record | Per tick | Python cost | Share |
|---|---|---|---|
| K1 `WALK_START` | 73 | 0.54 ms | ~41% of fire control's 1.31 ms |
| K1 `FIRE` on a beam already firing | 18.3 | ~0.26 ms | 98.8% of FIREs |
| K2 resting `CONTACT` | 17.6 | ~0.25 ms | 97.6% of contacts |
| K1 `BANK_STOP` on an idle bank | 3.45 | ~0.02 ms | 100% of K1 bank stops |
| K2 `SYSTEM_STOP` on an offline system | 1.3 → 4 | small, grows as ships die | — |
| K3 `steer_point` `unattributed` | 0.06 | tiny | the only K3 question left |

Removing them saves roughly **1 ms per tick** of the 2.45 ms combat step (inferred), and — more important for the roadmap — leaves K1, K2 and K3 with no routine mid-step Python except genuine SDK-contract effects (sounds, `ET_*` events, damage, projectile spawns). That is the precondition for running a kernel without the Python lock (workstream I).

## 2. Goals, non-goals

**Goals**
1. K1: no `WALK_START` record; beam-sustain FIREs and idle BANK_STOPs become logged writes.
2. K2: resting contacts leave the per-record protocol; offline `SYSTEM_STOP`s become logged writes.
3. K3: `unattributed` steer attribution native.
4. Bit-exact with Python, switch on (same writes, same order, same wakes, same VFX list order); byte-identical behaviour, switch off.
5. Measured: two benchmark runs (64-ship fight, switch on) against the posed-parts tip.

**Non-goals**
- Anything that posts an `ET_*` event, plays a sound, applies damage or spawns a projectile stays a record (MAP §4): beam-edge FIREs, tube/pulse FIREs, FIRE_FAILED, firing-bank stops, damage-pulse contacts. Deferring those is workstream G (event queue) and D (damage).
- Porting the box rule (`part_for_point`, MAP §5.4) — negligible frequency; later.
- Removing scaffolding (patch/override guards) — goes with the Python copies (workstream E).
- A native port of contact presentation (MAP §3.3 level ii) — level (i) only here.

## 3. Constraints (programme-wide)

- Bit-exact; `.hex()`; Python operand/write order. "Bit-exact" for presentation = the same VFX/shield-hit calls with the same arguments in the same order.
- A field the kernel reads MUST push; the write log applies through the existing quiet setters, so a `WakeField` write (`_firing`) still wakes a sleeping owner exactly as the Python assignment would (MAP §3.4, `passive_state.WakeField`).
- **Ruling P1 holds:** no decision outlives a Python effect. Logged writes are applied before any later Python runs (with the next record, or at `DONE`), so no Python observes a state the kernel has already moved past without the log applied.
- Every method whose Python body is replaced by logged writes joins the K1/K2 override guard while the Python copies exist (`_live_held_offset`, `is_using_target_offset`, `GetTargetOffsetTG`, `_fire_effect` (already), `StopFiring` (bank and system)).
- Switch `DAUNTLESS_NATIVE_COMBAT=1`, default OFF, byte-identical when off. GIL held.

## 4. Design

### 4.1 K1 `WALK_START` → native offset, lazy object (MAP §3.1)

- The kernel computes the walk's offset VALUE at UW_DEAD_PRUNE from mirrored rows with Python's predicate (`_live_held_offset`: the ship is a ShipClass row with `is_using_target_offset()` true → the manual offset; else the system's `_held_offset`; "unset" ↔ `None`).
- No `WALK_START` record. The walk's FIRST real record (FIRE, BANK_STOP, FIRE_FAILED, FIRE_DUMB, ASK, STOP_SYSTEM, RUN_PYTHON) carries the walked system; on it the driver calls `walked._live_held_offset()` once for the offset OBJECT (ruling P5), runs the instance-patch scan, and pins — the same Python in the same order, just later, with no Python in between (equivalent because the walk start runs no Python). A walk that produces no record runs no Python at all.
- The pruned `_target_list` write stays in the log on EVERY walk (Python's `_prune_targets` builds a new list each time; identity matters for `AddTarget`'s in-place append). Applied with the next record or at `DONE`.
- Verify no `__getattr__` stub sits on `_live_held_offset`'s path (MAP flags it inferred).

### 4.2 K1 `FIRE` for a beam already firing → logged writes (MAP §3.2)

In `TF_FIRE`, a Beam decision with `was_firing` true logs `_firing = True`, `_target = target`, `_target_offset = walk_offset` (Python's order) and continues to `TF_FIRED` with no record. The edge case (`was_firing` false: sound + `ET_WEAPON_FIRED`) stays a FIRE record. `_target_offset` uses the walk-offset marker so the OBJECT identity rule (P5) holds — confirm the marker resolves to the object fetched at the walk's first record; if no record has occurred yet in the walk, the object fetch must happen when the log is applied (define it precisely in the plan).

### 4.3 K1 `BANK_STOP` on an idle bank → logged writes (MAP §3.4)

When the bank row's `_firing` is 0, log the class's `StopFiring` writes in order (energy bank: `_firing = False`, `_beam_on_countdown = 0.0`; tube: `_firing = False`; pulse: `_firing = False`, `_target = None`, `_target_offset = None`). A firing bank keeps the record (loop sound).

### 4.4 K2 resting `CONTACT` → contacts batched in walk order (MAP §3.3 level i)

Resting contacts are queued by the kernel and delivered with the NEXT record that runs Python (or with `DONE`); the driver runs `_phaser_contact`/`beam_contact` for each queued contact **before** that record's own effect. Order of presentation calls is therefore unchanged (a damage-pulse contact's `apply_hit` still runs after every earlier resting contact's VFX, exactly as today). No context re-send per resting contact. Python cost stays (presentation), round trips go.

### 4.5 K2 `SYSTEM_STOP` on an offline system → logged writes (MAP §3.5)

When every bank of the system is idle: log the system's five writes (`_fire_held = False`, `_held_target = None`, `_held_offset = None`, `_target_list = []` — a NEW list, `_last_group_fired = -1`) and each bank's `StopFiring` writes (§4.3), in Python's order. K2's write log grows a value variant (it carries only `_dwell` today). Any firing bank → keep the record. No "skip if already equal" (every write wakes; `[]` replaces the list object).

### 4.6 K3 `steer_point` `unattributed` → native attribution (MAP §3.6)

In the attribution check, call `authored_mount_subsystem`; `kMountUnknown` or a non-ShipClass target keeps the ASK. Otherwise write the row's mount natively and log a `_mount_key` entry that `_k3_apply` turns into `(target_obj, x, y, z, mount_obj or None)` quietly. A mount-less offset on an unposed target steers at the offset itself (Task 7's bake); on a posed target the existing baked path applies.

### 4.7 Counters

Add per-kind counters of records NOT emitted (`k1_logged.walk_start`, `.beam_sustain`, `.idle_bank_stop`; `k2_batched_contacts`, `k2_logged_system_stop`; `k3_native_attributions`) so differentials can assert the new paths ran.

## 5. Testing and measurement

- Unit/kernel tests per item: the logged writes equal Python's writes in order (`.hex()` for floats, identity for list objects where it matters), the WakeField wake fires, the edge/firing cases still emit records.
- Differentials: extend the K1, K2, K3 and posed differentials to assert the new counters > 0 and per-tick parity unchanged; the VFX/shield-hit call sequence compared per tick for K2 (order).
- Mutation proofs: wrong write order; skipping `_target_list` write when unchanged (identity); emitting no record for a beam EDGE; delivering batched contacts AFTER the next record's effect; missing wake.
- Benchmarks: 2 runs of the 64-ship fight, switch on, at the posed-parts tip and 2 at this branch's tip (the established harness; machine idle; Debug like the register's captures — note it). Report cb.held_weapons, cb.phasers, cb.projectiles, sim.combat per tick and Python loop per frame.

## 6. Open items for Mark

- None blocking. Live check after the build (a big fight, switch on).

## 10. Outcome

(Filled at the end.)
