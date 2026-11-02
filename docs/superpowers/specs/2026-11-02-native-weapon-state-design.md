# Native combat: weapon state (cheap sync + charging kernel K0) — design

**Status:** implemented 2026-11-02, outcome in §10; live-verified by Mark 2026-11-02 and merged into `project/combat_threading` (`ea4e59503`). Spec written without Mark (he asked for "spec, plan and build the next largest phase" and will review afterwards). Workstream re-chosen by measurement (§1); the roadmap's D (native damage) was mapped and deferred.
**Branch:** `ws/combat-weapon-state`, off `ws/combat-round-trips` (head `9102c2f34`, not yet live-verified or merged), in worktree `.claude/worktrees/native-combat-damage`. Merges into `project/combat_threading` after round trips does; no main gate — focused tests, differentials, two benchmark runs.
**Input maps:** `docs/reference/engine/native-combat/weapon-state-map.md` (WSM §n), `docs/reference/engine/native-combat/damage-map.md` (DM §n).

## 1. Why this phase

Measured 2026-11-02 (64-ship fight, switch on, Debug, one instrumented run each; logs `~/Documents/dauntless-perf/dmgmeas{,2,3,4}-*.log`), milliseconds per game tick:

| Cost | ms/tick | Notes |
|---|---|---|
| Charging/reloading (`sim.weapons`, all Python) | 0.64-0.77 | ~240 weapon steps/tick: 103 phaser banks (0.32), 127 tubes (0.12), 11 pulse (0.04), at-rest/sleep bookkeeping 0.09 |
| Mirror pushes (every `Native*Field` write, whole tick) | 0.35 | 244 pushes/tick at ~1.4 µs: `_charge_level` 110, `_velocity` 64, `_power_factor` 29, `_condition` 17, … |
| K1/K2 write-log application in Python (`apply_writes`) | 0.35 | ~780 writes/tick: `_fire_timer` 270, `_target` 254, `_target_list` 71, `_force_update` 71, `_group_fire_mode` 53, … |
| Native kernels (`combat_k1_next` 0.52, `combat_k2_next` 0.36) | 0.88 | Debug build: not this phase's lever |
| Damage application (`apply_hit`, all callers) | ~0.13 | 0.4 calls/tick; feedback is 70% of it |
| K2 resting-contact presentation | 0.13-0.18 | 17-22 calls/tick |

Native damage (roadmap D) would save at most ~0.3 ms/tick and is the hardest port left (DM §0-9: a synchronous chain of events, death cascade, shared RNG, non-presentation side effects in `hit_feedback`). The weapon-state costs above total **~1.3 ms/tick** of Python↔C++ sync and Python stepping, are mechanical by comparison, and are on the roadmap's own list of things the native combat thread owns ("charging and reloading", §1). They are the largest lever left outside AI (`gl.ai` 3.4 ms/tick, Mark's separate session) and motion (`gl.motion` 1.5 ms/tick, not on this roadmap).

## 2. Goals, non-goals

**Goals**
1. **C-applied write logs:** K1 and K2 write logs are applied to the Python objects by the binding, in C++, at the same point and in the same order as today's `apply_writes`. Target: `k1.writes` 0.35 → ≤ 0.08 ms/tick.
2. **Fast push:** the scalar `NativeField` pushes (float, int, bool, IS_TRUE, OPT_INT) encode and call in one binding call. Target: mean push ≤ 0.6 µs.
3. **K0 charging kernel:** with the switch on, `_advance_weapons` runs a native session that steps every weapon (energy `UpdateCharge`, pulse `UpdateCharge`, tube `UpdateReload`/`ReloadTorpedo`) in the reference order, logging its writes (applied by goal 1) and handing back records only for real Python effects. Target: `sim.weapons` ≤ 0.15 ms/tick.
4. Bit-exact with the Python reference switch on (`.hex()` floats incl. −0.0, same write order, same object identity, same wakes, same events in the same order); byte-identical switch off.

**Non-goals**
- C++-owned fields with lazy Python reads (WSM §7b). Ruled out for this phase: a `__get__` on every read lands on per-frame render and HUD readers (WSM B7), costs with the switch off (B1), is invisible to every `__dict__` reader (B2) and breaks the identity rules for `_target_list`/`_target_offset` (B5). The Python copies go away in roadmap E instead.
- Native damage (DM). Deferred; DM stays as its map.
- Tractor beams in K0: always handed back (they have 0 steps/tick in the fight; their stop thaws a power program) (superseded by ruling W6, §10: idle tractors step natively).
- Release-build or kernel-speed work on `combat_k*_next`.

## 3. Constraints (programme-wide)

- Switch `DAUNTLESS_NATIVE_COMBAT=1`, default OFF; byte-identical off. `DAUNTLESS_NATIVE_AUDIT=1` and `DAUNTLESS_PASSIVE_AUDIT=1` make K0 stand down (Python step, counted reason `audit`). GIL held throughout.
- A field the kernel reads MUST push (every writer, including in-place list writers). Ruling P1: no Python sees state the kernel has moved past without the log applied. Python copies and override guards stay while the copies exist.
- Focused tests only; never whole suites, never the gate (`scripts/check_tests.sh`). Banned git commands as in CLAUDE.md. Never launch the game; the controller runs the headless benchmark.

## 4. Design

### 4.1 C-applied write logs (WSM §4.1-4.3)

`combat_k1_next`/`combat_k2_next` today return each record's writes as a `py::list` of `(handle, field_str, value)` tuples that Python's `apply_writes` applies one by one (~0.45 µs each). New: the driver passes the binding, once per session (`combat_k1_begin_*`, `combat_k2_begin`, the K0 begin), an **applier context**: the walk's pins dict, the `_registry` mapping, the walk object (for `materialise`), and a small table of field descriptors (attribute name → apply kind) built from `_quiet_setter`. The binding then applies every write of a record itself, in order, before returning the record, and returns the record **without** its writes (or an empty list). One exception keeps today's interleaving: a K2 record carrying queued resting contacts, whose contacts must each run after the writes logged before it and before the later ones. Its writes stay pending in the binding and `_k2_deliver` applies them in segments (`combat_apply_writes(upto)`) between contacts.

Apply kinds, each reproducing `_apply_write` exactly:
| Kind | Action |
|---|---|
| plain (NativeField, NativeRefField, plain attribute) | `PyDict_SetItem(obj.__dict__, name, value)` |
| ref | value = object for the handle (pins, else registry, `_nslot` checked; −1 → None) |
| ref list | a NEW Python list of objects |
| wake (NativeWakeField) | dict store, then if `obj.__dict__["_passive_asleep"]` is true, call `passive_state.wake(obj)` |
| python (ThawParentWakeField, anything unrecognised) | call the Python quiet setter |
| walk-offset marker | call `walk.materialise(walk_id, system_handle)` (once per walk, as today) |
| slot element (K0, §4.3) | in-place `list[i] = value` on the object's existing list |

Exception semantics are today's: if a write raises (a materialise, a python-kind setter), the binding applies every later write of that record (skipping later markers of the failed walk, as `_apply_rest` does), then re-raises the first exception with later ones as notes. Python's `apply_writes` stays as the reference for the tests and for any caller outside the drivers. Float, int and bool values are boxed with their Python type (bools as `True`/`False`, WSM B8).

### 4.2 Fast scalar push

`NativeField.__set__` and `NativeWrapped._after_set` call one new binding, `combat_push_scalar(h, fid, code, value)`, for the scalar types (float, int, bool, IS_TRUE, OPT_INT): encoding in C++ with Python's exact rules (`float(value)`, truthiness, `is True`, `None` → −1), raising the same exception types so `_drop(obj)` still happens on an unencodable value. Other types keep `_push`.

### 4.3 K0: the charging kernel

**Session.** `_advance_weapons(ships, dt)` with the switch on calls `native_combat.k0_weapons(ships, dt)`: ship handles in list order, `dt`, and the game clock `now` (one read per session, the same value every tube in this step reads, WSM D5). The kernel walks ships in order and, per ship, the groups phaser → pulse → tractor → torpedo and each group's weapons by index (WSM D7).

**Every weapon is stepped (the per-tick model).** K0 does not consult the passive awake list: the passive-state contract is that stepping an at-rest weapon is a no-op and that the passive walk equals stepping every weapon (passive spec §6.3), so the per-tick model is the reference K0 reproduces, and stepping a sleeper in C++ costs nothing. K0 never calls `put_to_sleep`. The weapon list per ship is snapshotted at session begin (the passive walk's stale-registry rule: a mid-walk invalidate does not change this tick's walk).

**Native steps** (formulas, operand order and NaN/signed-zero rules from WSM §1.3-1.6 and D1-D11; `py_min`/`py_max`):
- Energy `UpdateCharge` (phaser bank; pulse and tractor reach it via super): countdown branch, drain branch (discharge rate = `PHASER_DISCHARGE_BY_POWER_LEVEL[parent power level]` for a phaser bank, `_normal_discharge_rate` otherwise; IndexError/TypeError → 0.0), depletion, idle early-out, recharge (`_recharge_rate * power_factor * condition_factor * dt`, `min(want, headroom)`), `IsOn` check.
- Pulse `UpdateCharge`: cooldown, the mixin, then the watcher (below).
- Tube `UpdateReload` + `ReloadTorpedo`: slot self-heal check (a length mismatch → that tube is handed back, the rebinding is Python's), per-slot progress with the session `now`, one reload attempt per call, ammo denial (Python's `_reload_denied_by_ammo`: available ≤ rounds loaded system-wide — the reload gate, not fire_gates' `ammo_exhausted` CanFire gate), oldest-slot pick with strict `>`.

**New mirrored inputs** (each pushes from every writer; audited): `_recharge_rate` (float), the phaser system's `_power_level` (int) with the discharge table as a pushed global, the tube's `_reload_delay` (float), `_reload_timers` and `_reload_advanced_at` (new mirror `FieldType` **FloatList**), and the pulse watcher's check count `_watch_checks` (int, pushed by every check add/remove). In-place slot writers (`_start_slot_cooldown`, `_sync_slots_to_num_ready`, `_resize_slots`, `ReloadTorpedo`, `UpdateReload`, `UnloadTorpedo`) push the list after mutating (the `_add_target` + `push_field` precedent).

**Writes** are logged with the K1 encoding and applied by §4.1: `_charge_level`, `_beam_on_countdown`, `_depleted`, `_cooldown_remaining`, `_num_ready` (wake kinds where the descriptor is a WakeField), slot elements (`_reload_timers[i]`, `_reload_advanced_at[i]`, in place), and the watcher value (below).

**Records** (Python runs at the point the reference runs it; the kernel stops there so later weapons are not yet stepped — P1):
| Record | When | Python |
|---|---|---|
| `DEPLETE_STOP` | a firing bank's charge reaches 0 | `bank.StopFiring()` (sound, wake) — `_depleted=True` is logged before it |
| `RELOADED` | a tube loads a round | `tube._broadcast_reload()` (synchronous `ET_TORPEDO_RELOAD`) — the slot and `_num_ready` writes are logged before it |
| `WATCH` | a pulse weapon whose watcher has checks (`_watch_checks > 0`) after its step | `weapon._charge_watcher._update(weapon.GetChargePercentage())`; with no checks the kernel logs the watcher's `_value` write instead (a store on the watcher object, applied in C) |
| `RUN_PYTHON` | ship or weapon K0 cannot stand in for | the Python step of that ship (`step_every_weapon` semantics for a ship with no registry) or that one weapon (`UpdateCharge`/`UpdateReload`) |
| `DONE` | end of walk | — |

**Hand-backs** (`RUN_PYTHON`, counted by reason): tractor beams (per weapon) (superseded by ruling W6, §10: idle tractors step natively); a ship with no Object row or with groups that are not `WeaponSystem`s; a weapon with no row or with an unrepresentable value; a weapon whose row went stale mid-walk (by ship index + weapon index); a tube needing slot self-heal; an override of any method in WSM A6 on the class or the instance (a K0 override guard, built like K1's `_K1_LEAF_METHODS`/walk check, rechecked per session; narrowed by ruling W9, §10); audits on (whole step, reason `audit`).

**Records after handlers.** A record's Python may write fields K0 reads later in the walk (SDK `SetChargeLevel`, a nested `StartFiring` → K1 system session). Those writes push to the mirror and the kernel reads the mirror when it reaches the weapon, as K1 does. A row dropped by a handler for a weapon not yet stepped → that weapon is handed back.

**Counters** (in `native_combat.counts()`): `k0_steps`, `k0_records` by kind, `k0_python_reasons`, `k0_logged_writes`; plus `c_applied_writes` (K1/K2/K0) and `fast_pushes`.

## 5. Testing and measurement

- Unit/dispatch tests per task; gtests for every K0 formula against the Python reference including NaN, −0.0, NaN condition reading as full, the NaN tube factor stall, ties, and one-attempt-per-call.
- **Differential:** a headless fight with switch on vs off records per tick, per weapon, by `.hex()`: `_charge_level`, `_beam_on_countdown`, `_depleted`, `_cooldown_remaining`, `_num_ready`, both slot lists, plus the ordered event log (`ET_TORPEDO_RELOAD`, `ET_CHARGE_TOGGLE`, `ET_WEAPON_FIRED`) and the identity checks already in the K1 differential (`_target_list` newness, offset identity). The passive differential's `==` compare gains `.hex()` (WSM D3). Counters asserted > 0 for each native path.
- Mutation proofs: wrong operand order, `max` argument order (−0.0), a skipped slot push, a write applied after its record's Python, a wake not fired, watcher record emitted after a later weapon's step.
- Benchmarks (controller): two 64-ship runs at `9102c2f34` and two at the branch tip, switch on, idle machine, the established harness; score per tick.

## 6. Open items for Mark

1. Phase choice: this replaces D (native damage) as "next" on measured grounds (§1). D's map is committed for later.
2. K0 steps every weapon instead of the passive awake list (the per-tick model, §4.3). Passive state then saves nothing with the switch on; it still does with the switch off.
3. Not live-verified until Mark plays a large battle with the switch on (watch: beams running dry, torpedo reload pacing, pulse-cannon AI firing).

## 10. Outcome

Implemented 2026-11-02 on branch `ws/combat-weapon-state` (off `ws/combat-round-trips` `9102c2f34`; merges into `project/combat_threading` after round trips does). Commits: spec `79303db63`; Task 1 `5492fca58`; Task 2 `9ecd6e8e6` + review minors `608169e78`; Task 3 `5cf6e53d8`; Task 4 `805ebbeff`; Task 5 `11178edf4`, fix round 1 `da2eee30b` + `3c8f5be23`, fix round 2 `a6d68b2ba` + `6cfde63c5`; Task 6 `ec1e18c1c` + `1d714e767`. Everything is behind `DAUNTLESS_NATIVE_COMBAT=1`, default OFF; switch off is unchanged. **Live-verified by Mark 2026-11-02** with the switch on (an 87-ship battle at about 8 fps, his reading, not a capture; the only console error was the unrelated `apply_texture_replacements` miss for the named Nebula `TKumbra.tga`, whose name comes from the hull decal). Merged into `project/combat_threading` (`ea4e59503`) after round trips (`547de0cce`).

### What shipped

- **Task 1, C-applied write logs (§4.1).** New `native/src/host/combat_write_apply.{h,cc}`. The drivers install an applier context per session (`combat_set_applier`, which returns the previous context, so nested K1 sessions restore it in `finally`); `combat_k1_next` and `combat_k2_next` then apply each record's writes in C and return `[]`. Apply kinds are keyed by (class, field), because the same field is WAKE on a phaser bank, PYTHON on a tractor beam and PLAIN on a tube: `APPLY_PLAIN, REF, REFS, WAKE, PYTHON, SLOT, WATCHER`, plus the walk-offset marker. A K2 record with queued resting contacts keeps its writes pending in the binding; `_k2_deliver` applies them in segments (`combat_apply_writes(upto)`). Exception semantics are `apply_writes`' own (apply the rest, skip later markers of a failed walk, re-raise the first with notes, the same `__context__`). Python's `apply_writes` stays as the reference. Extra bindings: `combat_apply_log` (a Python-encoded log applied in C: the random-log equivalence test's entry), `combat_apply_raised`, counts.
- **Task 2, one-call scalar push (§4.2).** `combat_push_scalar(h, fid, code, value)` is a raw `METH_FASTCALL` function (the first in `host_bindings.cc`): an `m.def` version saved only ~3% because pybind11's argument dispatch was most of the cost. Push 1,065 → 135 ns (`NativeField(float)`), wake field 1,133 → 205 ns (unit microbench, Debug). Caller bugs (argument count, unknown code, field id out of range) raise `SystemError`, never a silent drop. `_velocity` (VEC3) and non-scalar types keep `_push`.
- **Task 3, K0's inputs mirrored.** New mirror `FieldType::FloatList` (`_reload_timers`, `_reload_advanced_at`; `NativeFloatList` accepts a list of ints and floats only, compares by `.hex()`), `_recharge_rate`, `_reload_delay`, `_watch_checks`, the phaser system's `_power_level` (`INDEX`), and the discharge table as globals `PHASER_DISCHARGE_0/1/2` + `PHASER_DISCHARGE_LEN`. Every writer pushes; in-place slot writers call `push_field` / `TorpedoTube._push_slots()` after mutating. `_watch_checks` follows the watcher through an owner back-reference; `audit_mirror` checks it against `len(_checks)`.
- **Task 4, the K0 kernel (§4.3).** `native/src/combat/{include/dauntless/combat/k0_charging.h,src/k0_charging.cc}` and the shared write type `write_log.h` (ruling W3). Energy, pulse and tube steps, records `DEPLETE_STOP`, `RELOADED`, `WATCH`, `RUN_PYTHON`, `DONE`, eleven hand-back reasons (the spec's plus `power_level`, `parent`, `unrepresentable`, `unknown_kind`), undo of every mirror write on a throw from `next()`.
- **Task 5, the driver.** `host_loop._advance_weapons` calls `native_combat.k0_weapons(ships, dt)` with the switch on; it stands down (`off`, `audit`, `nested`) by returning False. The override guard checks every WSM A6 name on the class but `StopFiring` and `_broadcast_reload` (ruling W9; compared as the whole MRO chain since fix round 2, so a patch reached through `super()` is seen) and a cheap subset on the instance (ruling W9); verdicts are cached per type by `tp_version_tag` and per object by its dict's PEP 509 version (3.11 only, `combat_k0_object_cache()`). `PulseWeapon._charge_watcher` is a `ChargeWatcherField`: a replaced watcher is adopted or forces `WATCH_ALWAYS`. Idle tractors step natively (ruling W6). Fix round 2 (ruling W8): the K0 log is reused storage (`K0Record::writes` is a span, valid until the next `next()`), fields are ids and `string_view`s instead of `std::string`, a slot list's undo is taken once per (tube, list) per step, and the applier reads an exact `WeakValueDictionary`'s `data` in C instead of calling `.get`.
- **Task 6, hardening and differentials.** A delivery re-entry guard (`K0Session::set_delivering`: a `next()` while a record's writes are being applied fails loudly with the log untouched), a bound on K0 field ids, one kind lookup per K0 write. New `tests/integration/test_native_k0_differential.py` (the K1 differential's scene plus K0 ops; every reload, charge-toggle and weapon-fired event carries the ship's K0 state at the post). No porting bug found.

### Rulings worth keeping

- **W1:** Task 1 implements and tests all seven apply kinds, including SLOT and WATCHER that only K0 uses, through `combat_apply_log`.
- **W2:** the round-trips pair C-252/C-253 (same code as `9102c2f34`: only docs commits since) is this phase's baseline; no re-run.
- **W3:** the Python-free write representation (handle, field, value variant incl. slot and watcher) lives in the combat library (`write_log.h`); the host applier consumes it without conversion.
- **W4:** an int beyond int64 written to an int or OPT_INT field drops the row (switch on). The old path wrote the dict, then pybind's `TypeError` escaped the setter and left the row stale.
- **W5:** K0 answers the discharge lookup natively only for power levels Python's tuple answers with entries 0..2 (negative levels mapped as Python indexes); any other level hands back `power_level` (Python gives 0.0 by IndexError there: exact via Python). A firing bank whose parent row is not a PhaserSystem hands back `parent`.
- **W6:** an idle tractor (`_firing` false) is the mixin's energy step and runs natively; a firing tractor hands back. Replaces §2's "tractors always handed back": 132 tractor round trips a tick idle were most of K0's first idle cost.
- **W7:** the override guard's ~14 µs/tick (target 10, Debug) is accepted.
- **W8:** a write-path fix round before Task 6, after the first fight benchmark showed no win (below).
- **W9:** K0's instance-attribute checks cover a cheap subset (weapon update entry points, `IsOn`/`GetNormalPowerPercentage`/`GetPowerLevel` on systems, the group getters on ships), K1's precedent; full A6 coverage is class-level only. Cost if wrong: an instance patch of a deeper helper diverges with the switch on until the Python copies are retired (roadmap decision 2). `StopFiring` and `_broadcast_reload` are not looked for at all, on the class or the instance (`native_combat._K0_CALLED_IN_PYTHON`, final review): K0's `DEPLETE_STOP` / `RELOADED` records call them in Python, so a patch of either is honoured with the walk still native. A class patch of `FloatRangeWatcher._update` is not looked for either: for a pulse cannon whose watcher has no checks K0 stores the watcher's `_value` in C (a watcher write) instead of calling `_update`, so with the switch on such a patch is not called there (a watcher with checks is a `WATCH` record: `_update` runs in Python). *Superseded 2026-11-02 by the fire-events phase (spec `2026-11-02-combat-fire-events-design.md`): K0 no longer returns `DEPLETE_STOP`, `RELOADED` or `WATCH`; they are logged writes plus effect-queue entries, so `StopFiring` and `_broadcast_reload` (bank, pulse and tube roles) and a class patch of the watcher's `_update` are now in K0's override guard; an instance patch of one watcher's `_update` is not looked for.*

### First integration showed no win (perf register SIG-169)

At `3c8f5be23` (K0 integrated, before fix round 2), one fight run (C-258): `sim.weapons` 0.691 ms/tick against the baseline's 0.571-0.625. The counters (C-259) showed K0 running natively every session (4,955 sessions, 0 hand-backs), 457 K0 logged writes and 1,256 C-applied writes a tick. A `sample` profile (C-260) of the K0 `next` binding, 386 samples: kernel 157 (write-log vector growth relocating each `LoggedWrite` with its `std::string` field ~64; mirror write + undo ~86), C applier 147 (handle → object through `WeakValueDictionary.get` as a Python call per handle per session), charging maths ~15. The cost was the write path, not the stepping. After fix round 2 (`6cfde63c5`), unit microbench: ~1.2 → ~0.21 µs per K0 write; all-recharging 1,460 → 290 µs/tick (Python walk 1,090). One fight run (C-261): `sim.weapons` 0.245, `cb.held_weapons` 0.715, `sim.combat` 1.809 ms/tick.

### Measured (perf register C-262, C-263, SIG-170; counter-signal SIG-171)

64-ship `combat_stress` fight, switch on, headless, **Debug**, two runs each on an idle machine, milliseconds per game tick (value ÷ the report's average ticks per frame, median of reports 3-11), round trips (C-252/C-253) → weapon state (C-262/C-263):

| Row | Before (runs) | After (runs) | Change |
|---|---|---|---|
| charging/reloading (`sim.weapons`) | 0.598 (0.625/0.571) | 0.248 (0.250/0.245) | **−59%** |
| fire control (`cb.held_weapons`) | 1.000 (1.004/0.995) | 0.662 (0.677/0.646) | **−34%** |
| phasers (`cb.phasers`) | 0.737 (0.754/0.719) | 0.733 (0.786/0.680) | flat |
| torpedoes (`cb.projectiles`) | 0.146 (0.138/0.154) | 0.160 (0.156/0.164) | flat, within spread |
| **combat step** (`sim.combat`) | **2.111** (2.064/2.157) | **1.761** (1.742/1.780) | **−17%** |
| subsystems (`gl.subsystems`) | 0.630 (0.657/0.602) | 0.563 (0.588/0.537) | −11% (the fast push: **inferred**) |
| AI (`gl.ai`) / motion (`gl.motion`) | 3.334 / 1.380 | 3.311 / 1.385 | unchanged (counter-signal) |
| **whole sim** (`sim`) | **9.799** (9.756/9.841) | **9.120** (9.154/9.086) | **−0.68 ms, −7%** |

Both after runs of `sim` are below both before runs; the same-build spread of `sim` itself is not known (SIG-167 measured ~10% on `sim.combat`). Python loop 53.9 (55.61/52.21) → 49.4 (50.04/48.74) ms a frame, ticks a frame 3.3/3.1 → 3.0/3.0, so per-frame rows are not like for like. Median projectiles in flight 43/36 → 32/22.

About **0.68 ms per tick** saved in `sim`, against the ~1 ms expected (spec §1 bounds the sync and stepping at ~1.3). Why it is less (**inferred**, not separately timed):
- **Phasers did not move.** K2's write path was not reworked, and resting contacts still run their Python presentation.
- **K1/K2 logs still move a vector per record** (fix round 2 reused only K0's log storage; K1's and K2's record types own their writes).
- **Debug `-O0`:** CPython 3.11's static-inline helpers (`Py_DECREF`, `Py_TYPE`, ...) are real calls in the applier and the guard (fix round 2's profile: ~300 of 3,738 samples).

Targets of §2: `sim.weapons` ≤ 0.15 **not met** (0.248; W8's ≤ 0.25 met); push ≤ 0.6 µs met (0.135-0.205 µs, unit microbench); `k1.writes` ≤ 0.08 not measured (its scope was temporary). W8's `cb.held_weapons` ≤ 0.75 met. Counter-signal: with nothing charging, K0 costs ~53 µs/tick against the passive walk's ~6 µs (SIG-171): the per-tick model steps every weapon, the passive walk sleeps them.

### What is left / next levers

- **K1/K2 write logs** still move a vector per record: give them K0's reused storage (span records; K2's pending writes across queued contacts). The next lever for fire control and phasers.
- **K1's override guard has K0's fixed `super()` blind spot** (MRO-first compare; pre-existing). Parked for Mark.
- K0's idle cost exceeds the passive walk's (SIG-171); acceptable in a fight, visible in a quiet scene.
- Parked minors: `push_field`'s linear descriptor scan (`_repush_field`), slot-list copies, moving the K1 differential scene to `tests/helpers` (the K0 differential imports it).
- An optimised build of the combat library would cut the native and applier cost; a BUILD_TYPE change is Mark's call.
- Native damage (roadmap D) stays mapped (`docs/reference/engine/native-combat/damage-map.md`) and deferred.

### Tests

Task 6: 14 focused files, 134 passed in both orders; `ctest -R combat_` 291/291. Mutation proofs 12/12 caught (recharge operand order needed a tightened gtest and new differential ops first; the delivery-guard gtest needed strengthening). Caught only by unit tests, not the differentials: the C applier's wake (K0 never sleeps a weapon; the K1 differential with K0 stood down catches it), bool fast push, and (in one of five differential cases) the recharge operand order. Over the phase `ctest -R combat_` grew 238 → 291; each task's focused pytest set and mutants are in its report (SDD folder `.superpowers/sdd/2026-11-02-native-weapon-state/`, not committed).
