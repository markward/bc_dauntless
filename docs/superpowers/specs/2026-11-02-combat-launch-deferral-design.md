# Native combat: launches at the boundary, K1's walk check out of the kernel — design

**Status:** built 2026-11-02, outcome in §10; live-verified by Mark 2026-11-02 and merged into `project/combat_threading`. Mark chose this phase ("Straight to A it is"): roadmap workstream F (launch-script cache) plus moving K1's walk check out of the kernel (workstream I's known blocker), under his rule that the sim must not check in with Python mid-step.
**Branch:** `ws/combat-launch-cache`, off `project/combat_threading` (`c2b0534c1`), in worktree `.claude/worktrees/native-combat-k3`. No main gate: focused tests, differentials, benchmark runs. Mark live-tests before merge.
**Input maps:** `docs/reference/engine/native-combat/launch-map.md` (LM §n), `docs/reference/engine/native-combat/k1-walk-check-map.md` (WM §n).

## 1. Why this phase

After the fire-events phase, K1's only mid-walk Python is a torpedo-tube, pulse-weapon or dumb FIRE (0.10 records per tick at 64 ships; perf register SIG-173): the record runs the weapon pack's launch script (`Create`), builds the Python `Torpedo`, registers it with K3's table, posts `ET_TORPEDO_ENTERED_SET` and plays the launch sound, mid-walk. And K1's walk check, the instance-patch and ship-class guard, makes CPython lookups inside the kernel's `next()` at every walk start (~73 per tick), the one CPython call left inside any kernel's computation (WM §2). Both keep K1 on the lock.

The survey (LM §2-3) found **every launch script pure**: 15 of 15 stock, 2 of 2 installed mod scripts (LC Intrepid, `.pyc`-only, both lift); DCMPv2's are absent and fall back to the photon. A pure `Create` gives the same torpedo whenever it runs.

## 2. Goals, non-goals

**Goals**
1. **Launches leave the walk.** A tube, pulse or dumb FIRE becomes logged launcher writes plus one queued `SPAWN` entry, followed by the launch events already queued (`TORPEDO_FIRED`, `WEAPON_FIRED`, `AMMO_CONSUMED`). K1 returns no FIRE records.
2. **Fire-time values computed in C++** (LM §4.2): spawn position, velocity, source ship and set, target and target offset, the baked offset against the target's pose, the launcher's damage-radius override, and the pulse damage scale. Delivery must not read a pose that moved after the walk (tractors run later in the step).
3. **K1's walk check out of the kernel** (WM §4.1): a scan at session begin in the binding builds per-session C++ verdict sets; the binding re-validates them (cached, by type version and dict version, K0's caches) before each `next()` compute; the kernel's check becomes a set lookup. Exact today's semantics: a patched method is never decided natively (round-trips ruling F5, "a patched method is never decided natively").
4. Game state bit-exact with the Python reference, switch on, except the timing rulings in §5; switch off byte-identical.
5. Measured: K1 records per tick by kind; two benchmark runs against `fe2-*` (C-268/C-269).

**Non-goals**
- A per-type values cache replacing `Create` (roadmap decision 5's literal form): unnecessary while every script is pure and the `Torpedo` is a Python object built at the boundary (ruling L1). Only what fire time needs is cached: the launch speed per type (extending ruling P6's pulse cache to tubes).
- Releasing the lock. The row-lifetime blocker (mirror rows freed by weakref finalizers on any thread holding the lock, WM §2) is workstream I's.
- The pulse damage-scale ordering quirk (applied after registration, LM §1.3): kept as is for parity; a backlog item.

## 3. Constraints (programme-wide)

- Switch `DAUNTLESS_NATIVE_COMBAT=1`, default OFF; byte-identical off. The lock is held. Focused tests only; never whole suites or the gate. Banned git commands as in CLAUDE.md. Never launch the game; the controller runs the benchmark.
- Mod rule: never write lifted or decompiled mod text, never commit a mod-derived value in a test.

## 4. Design

### 4.1 The launch entry

- New queue kind `SPAWN`. Operands: the launcher (handle), the projectile kind (tube torpedo, pulse bolt, dumb fire), and a fire-time record: spawn position, velocity, source ship, set, target, target offset, baked offset, damage-radius override (or none), damage scale (pulses). Emitted by K1 at the point Python's `_fire_effect` would have called `_spawn_torpedo` / `_spawn_projectile` / `FireDumb`, after the launcher writes, before the launch events.
- **Delivery** (Python, in queue order): run today's spawn path with the fire-time values substituted for the ones it would read live: build the `Torpedo`, run the module's `Create` (pure), set position, velocity, offsets and overrides from the record, apply the pulse damage scale where Python does today, `register` it (K3 row), post `ET_TORPEDO_ENTERED_SET`, play the launch sound. Factor the Python spawn path so the reference (switch off) and the delivery share one body, the live reads replaced by parameters.
- **Launcher writes** (logged, in Python's order; LM §4.2): tube `_num_ready`, `_last_fire_time`, the parent's `_last_system_fire_time`, the slot cooldown, `_target`/`_target_offset`, the finite ammo debit (`AddAvailable(-1)`'s writes); pulse charge drain and cooldown.
- **Fire-time computation in C++**: the tube direction (Direction, plus the 0.033 Right skew) × ship rotation, the pulse's led `world_dir` the kernel already has, `unit(dir) · launch_speed + ship velocity`, the emitter mount in world space, and the baked offset (PR:1080-1094). Launch speed per projectile type comes from the per-type cache (P6 extended), invalidated as today (`_reset_projectile_module_cache`, `mark_pulse_stale`).
- A launch whose module cannot be resolved, or whose type has no cached launch speed yet, is handed back as a FIRE record (counted by reason), never guessed.

### 4.2 The walk check

As WM §4.1: `combat_k1_begin_pump` / `combat_k1_begin_system` scan in the binding (system set, ship set) with K0's object and type caches; the sets live on the session (K1 sessions nest); `combat_k1_next` re-validates the top session's sets before the kernel compute; the kernel's check is `sys_set.count(sys) || ship_set.count(ship)`. Unbuilt dicts are handed back, never built; name tuples changing drop the caches; the ship key is the climbed ship. WM §4.3 lists the risks the tests must cover.

## 5. Rulings

- **L1. Defer the launch, don't cache it.** Every launch script is pure (LM §2-3), so running `Create` at the boundary equals a cached record, with no cache and no guard that `Create` is unchanged. Decision 5's purpose (no launch script on the combat thread) is met. *If wrong:* an impure script (a future mod) draws its randomness at the boundary instead of mid-walk. Amended during the build (rulings L5, L6): every launch, pure or impure, tube or pulse, goes through `SPAWN` while the queue defers, Python fallbacks included (ruling E4, one path per kind); a purity check would decide nothing, so there is none. The kernel hands a launch back to Python only when it cannot compute the fire-time values, and that Python run defers its spawn too.
- **L2. `ET_TORPEDO_ENTERED_SET` moves to the boundary** with the spawn (ConditionIncomingTorps, E8M2's handler that calls `SetLifetime`): decision 9.
- **L3. Object ids are allocated at delivery** (`TGObject` ids, `projectiles._next_id`): later than mid-walk, in the same order. *If wrong:* something else allocating an id inside the walk would interleave differently. The K1 differential now labels torpedoes in their own sequence (needed for deferral), so it no longer catches an id-interleaving change; nothing in the engine allocates object ids inside the walk today.
- **L4. The torpedo's first flight is unchanged:** K3 (`cb.projectiles`) runs before K1 (`cb.held_weapons`) in the step, so a torpedo spawned at the boundary first flies next tick, as today.

## 6. Testing

- **Spawn parity:** the K1 differential compares every in-flight torpedo field by field (`.hex()`) per tick, switch on (delivered at the boundary) against the reference (spawned mid-walk); the K3 differential compares kinematics and target; unit tests compare each spawned torpedo at `ENTERED_SET`; a torpedo fired by a ship a tractor moves in the same step spawns where it fired. (The step differential gains a torpedo row in the final-review fixes.)
- **Event order:** `SPAWN` → `ENTERED_SET` (in delivery) → `TORPEDO_FIRED` → `WEAPON_FIRED` → `AMMO_CONSUMED`; E8M2's `SetLifetime` handler acts on the spawned torpedo.
- **Fallbacks:** unresolved module, uncached speed, a bake the kernel cannot make, or a patched launch function → FIRE record, counted by reason (no purity check: ruling L6).
- **Walk check:** every existing pin (WM §4.4) still passes; new: a K1 method patched mid-pump (from an ASK answer) is obeyed by a later walk in the same tick; nested sessions keep separate sets; unbuilt dicts stay unbuilt.
- **Mutation checks:** read the launcher pose at delivery instead of fire time; skip a launcher write; let the kernel's check see a stale set.

## 7. Measurement

Records per tick by kind (K1 target: no FIRE), and two benchmark runs against C-268/C-269; perf register C-270/C-271 and a signal.

## 10. Outcome

Built 2026-11-02 on `ws/combat-launch-cache`. Commits: `3d867df40` (walk check in the binding), `e1b37beae`, `0eb1fc8ce` (tube and dumb launches, Python pulse deferral), `8c16e2ae2`, `76fdb5c39` (native pulse launches), `df0b07f42` (Task 5, added by Mark: the launch cache is filled when a torpedo type is loaded, not on its first shot), `1ab1e5b2f` (final review: a SPAWN holds its launcher, ship and set as objects, so a freed row still spawns; a reset during delivery stops the batch; the differentials assert native launches and the step differential compares torpedoes; a raising `GetLaunchSpeed` at load no longer pins its type to Python).

### What shipped

- **K1's walk check left the kernel**: per-session C++ verdict sets, re-scanned in the binding before every `combat_k1_next` with K0's object and type caches; the kernel's check is a set lookup. Same semantics as before (a patched method is never decided natively; a patch made between records is seen by the next walk start). No CPython call is left inside `K1Kernel::next()`.
- **Every launch goes through `SPAWN`** while the queue defers: K1 computes the fire-time values (spawn point, velocity, target, offsets, bake, DRF, pulse damage scale) and logs the launcher writes; delivery runs one shared Python spawn body (`_new_projectile`, `_launch_projectile`) with those values, then `ET_TORPEDO_ENTERED_SET`, the launch sound and the queued trio. The fire-time module object rides the entry. Per-type launch speed cached (ruling P6 extended to tubes).
- **K1 hands back** a launch only when it cannot compute it natively, counted: `launch_uncached` (a type's first launch), `launch_unresolved` (also a pulse module re-imported since it was cached), `launch_patched` (a launch function patched: Python spawns through the patch mid-walk, ruling L7), `launch_posed_offset` (a posed target whose AI offset has no Manual Aim slot to bake), `launch_other`.
- `arriving` is now pushed by every writer of a ship's warp-engine slot (`WarpSlotField`).

### Rulings worth keeping

- **L1** (amended), **L5, L6:** every launch, pure or impure, tube or pulse, Python fallback included, defers while the queue defers; no purity check (it would decide nothing). An impure mod script draws its randomness at the boundary.
- **L7:** a patched launch function spawns mid-walk through the patch.
- **L8:** K1's instance-level patch scan covers entry points only; the deeper launch getters are guarded at class level (`k1_fire_control.h`, WHAT A LAUNCH OBEYS).
- **The P6 window** (`k1_fire_control.h`): a `SetModuleName` after `SetProperty`, or a projectile-cache reset mid-session, leaves the cached module and launch params stale until the next reset.
- Parked: the pulse module's stale flag is global and sticky until the next cache reset (test-only in practice).

### Measured (perf register C-270, C-271, SIG-175)

K1 FIRE records per tick 0.103 → 0.0004 (4 per 8,999 ticks, all a type's first launch); after Task 5's load-time fill, **2 per 8,999 ticks, both `launch_posed_offset`** (a posed target's AI offset), `launch_uncached` 0 (re-measured 2026-11-02, headless; no benchmark pair was taken after Task 5 and the final fixes, which should not change speed — deferred while Mark is in meetings). Launch work moved from `cb.held_weapons` (0.664 → 0.604 ms per tick) to `sim.effects` (0.069 → 0.196): net about +0.07 ms per tick in the touched rows; `sim.combat` 1.545 → 1.509; `sim` 9.13 → 9.27, with more torpedoes in flight in this pair. The phase's gain is structural, not speed.

### Next (roadmap)

Damage prerequisites (third random generator, collisions into the sim tick, severance without a renderer), then native damage (D), then kernels off the lock (I: the row-lifetime blocker, K1 now has no in-compute CPython), then the AI ↔ combat pipeline (J).
