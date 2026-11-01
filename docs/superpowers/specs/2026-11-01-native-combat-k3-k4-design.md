# Native combat step — phase 3: K3 projectiles + K4 eligibility (design)

**Date:** 2026-11-01.

**Status:** Mark asked for this phase to be specced, planned and built end to end, on a new branch "from where you did your measurements of the phaser work", with two benchmark runs of the 64-ship fight. The calls marked *(controller)* below are mine, made under that brief. Mark can overturn any of them.

**Builds on:**
- the parent design `docs/superpowers/specs/2026-10-30-native-combat-step-design.md` (§3 goals, §5 anti-goals, §7 design, §9 phases; rulings R1-R12, P1-P7, A-J in §9.1-§9.2 all still bind);
- phase 2, K2 beams (`docs/superpowers/specs/2026-10-31-native-combat-k2-beams-design.md`, rulings C2 and §10), measured at `6418f858f`.

**Input map:** `docs/reference/engine/native-combat/k3-k4-map.md`. "Map §x", "G#", "A#", "B#", "E#" cite it.

**Branch and worktree:** branch `perf/native-combat-k3`, from `c6485d10a` (K2 docs commit; code identical to the measured `6418f858f`), in worktree `.claude/worktrees/native-combat-k3`.

## 1. Why

After K2, in the 64-ship fight (K2 runs, SIG-162): `cb.projectiles` 0.806-0.848 ms per tick and `cb.eligibility` 0.275-0.278 ms per tick. Together they are a third of `sim.combat` (3.3 ms).

- **`cb.projectiles`** is `projectiles.update_all`. Its cost is per-torpedo Python overhead, not maths: guidance 44%, the per-torpedo transform-store round trip ~14%, the per-ship cache ~14%, `frames.containing_set` 9%; the narrow phase is under 1% (map §A10).
- **`cb.eligibility`** is `damage_eligibility.update`. 91% is the sort's key function, most of it `frames.system_distance` re-reading positions (map §B9). It is paid every tick, fight or quiet: it is the one combat scope a quiet-scene capture can show moving.

The map's key finding: **steps 1-3 of `update_all` (guide, advance, broadphase, narrow) post no event and call no SDK script** (map §A1 corrections). K3 is therefore a genuine batch: one kernel call decides every torpedo; Python only applies the results. No resumable mid-step fallback is needed beyond ASKs.

## 2. Goals

1. `cb.projectiles` per tick at least **halves**, and `cb.eligibility` per tick at least **halves**, against the K2 build (`6418f858f`) in the 64-ship fight, with total sim per tick no higher. Judged on two runs (Mark's brief), per-tick rows (map §A10: `cb.projectiles` falls with the projectile count by itself, so the record states projectiles in flight beside it).
2. **Bit-identical** to the Python step with the switch on (parent §3.2): every torpedo position, velocity, age and guidance field (compared by `float.hex`); every `ET_TORPEDO_EXITED_SET` and `ET_WEAPON_HIT`, in the same order and tick; every hit point, normal and shield point, including object identity where an SDK handler can see it (§4.5); the eligible set per tick; every can_detect latch and memo state.
3. **Switch OFF is byte-identical** in behaviour to before.

## 3. Non-goals

- **The torpedo `apply_hit` loop** (HL:1320). It is outside the `cb.projectiles` scope (map correction 2) and is the game effect (parent §7.6.1).
- **`expire()`** (set removal + `ET_TORPEDO_EXITED_SET`). It stays Python, called in the kernel's order.
- **Render readers** of torpedo state (`_build_torpedo_render_data`, dynamic lights). They keep reading Python state, which copy-back keeps current (§4.3).
- **Fixing anything the port copies** (parent §5). Specifically: end-point-only sphere hit (tunnelling, map §A1.1); hits decided on a static world and applied afterwards, so two torpedoes can both hit a ship the first one kills; the re-emerge-from-cloak lead-acceleration spike (G3); NaN velocity flying until TTL (G9); a stub `IsDead` target going ballistic with telemetry; **mission swap never clearing `_active`** (map §A8.3.11: old torpedoes fly on and post `ET_TORPEDO_EXITED_SET` into the next mission). These go to Mark (§9).
- **Threads.** Parent §9 phase 4 decides on threads after this phase is measured.

## 4. Shape *(controller)*

### 4.1 One step scan, shared by K4 and K3

`cb.eligibility` and `cb.projectiles` are adjacent at the top of `_advance_combat_step` (HL:1312-1319) with nothing between them. One binding call at the start of `cb.eligibility`, `combat_step_scan(ships_list)`, returns:

- the mirror handle of each `ships_list` entry (−1 when it has no row), in list order, as a native-side array the next two kernels read by reference (not re-marshalled);
- whether every entry is representable for K3/K4 (row present, class seen and not patched per K2 §5.3/C2, `has_real_is_dead`, no duplicate handle);
- the distinct Set handles referenced by those rows and by the torpedo table (§4.3).

Python then resolves `frames.frame_of(set)` **for each distinct set, every step** (1-3 sets in a fight; never cached across steps, so a frame change can never be read stale) and sends the per-step **frame table**: per set handle, a frame key id (interned per step: the `("system", name)` key or the set's own identity) and the anchor as three doubles. A kernel that meets a set with no entry ASKs `frame(set)`.

K2 keeps its own `combat_k2_scan_ships` (it runs later in the step, after deaths and handlers).

### 4.2 K4 — eligibility

`damage_eligibility.update(ships)` keeps its Python player resolution (the `hasattr` + swallow chain), then, with the switch on, calls `combat_k4_eligible(player_handle, max_count, prox_w, size_w)` over the step scan. It returns indices into `ships_list` or `None` (= run `select_eligible` in Python). Python builds the frozenset of `id()`s, the player's first.

- `max_count` is `select_eligible`'s default as defined (`DEFAULT_MAX_ELIGIBLE` is bound at def time, map §B1), read from the function's kwdefaults; `PROX_WEIGHT`/`SIZE_WEIGHT` are read at call time and passed.
- **Tie-break by `id()`.** Each object row gets a constant `py_id` field (the object's `id()`) written at register. Ties are common (identical ships at equal distance; every cross-frame ship has `prox = 0.0`), so this is load-bearing.
- **Exactness:** E1 `max(..., default=0.0) or 1.0` as a left `py_max` fold then Python truthiness (`0.0`/`-0.0` → `1.0`); E2 in Python operand order; E3 distance with `dist3` (CPython's `math.dist`, never `sqrt`), `inf` when either side has no set or the frames differ; E4 sort by `(-score, id)`.
- **Falls back to Python** (whole function) when: the step scan is not representable; the player is not None and has no row; any radius, position or score is non-finite (a NaN key makes timsort's order depend on its merge pattern, map §B3); the select/score path is patched (identity snapshot of `select_eligible`, `_radius`, `frames.system_distance`, `frames.offset_between`, `frames.frame_of`, `frames.containing_set`, `math.dist`).
- `select_eligible` stays untouched as the Python reference and test entry point.

### 4.3 K3 — torpedo rows *(controller)*

Torpedoes get rows in a new combat-mirror **torpedo table** (parent §9.1 R12 is lifted for this kind only). It follows the existing `TorpedoScan` table's sync exactly (map §A9, §A8.3.1):

- a row is added at `_ActiveList` append (where the scan row is), in `_active` order, and dropped at remove; any other list mutation marks the table dirty, and K3 rebuilds it from Python state, in list order, before running;
- each row holds: the torpedo's `_xform` handle, `_age`, `_ttl`, `_guidance_lifetime`, `_guidance_initial`, `_max_angular_accel`, `_velocity`, `_target_ship` (ref), `_target_offset` (vec3 + set flag), `_source_ship` (ref), `_containing_set` (ref), `_last_seen_target_pos` and `_last_target_vel` (vec3 + set flag each), `_mount_key`'s subsystem (ref, + "attributed" flag and the key's offset);
- every writer of those fields pushes while the torpedo has a row: the SDK setters (`SetLifetime`, `SetGuidanceLifetime`, `SetMaxAngularAccel`, `SetTargetOffset`), the `_velocity`, `_source_ship`, `_containing_set` properties, `_target_ship`, and direct test writes. Use the existing `Native*` descriptor pattern (a field the kernel reads MUST push; parent §9.1 "Rule for every later phase").

**Flight state is copied back, not native-only** *(controller)*. Parent §7.6.2 made flight state native-owned; the map shows that is unsafe here: `_scan_rebuild` reads the Python `_vel` back into the scan table, and render, `EvadeTorps`, the torpedo camera and `_closing_time` read Python fields every frame (map §A8.3.2). So K3 ends with a write log (P7): every torpedo's `_age`, and for guided ones `_velocity`, `_last_seen_target_pos`, `_last_target_vel`. Python applies it without re-pushing to the torpedo row (the kernel already holds the value), but the scan table's velocity must end equal to Python's, exactly as the `_velocity` setter leaves it today. At the measured 30-110 torpedoes this costs ~10-30 µs a tick (map §A8.1, inferred); revisit only if a profile shows it.

**Positions** go straight to the `TransformStore` from the kernel, provided the torpedo's `SetTranslateXYZ` is the stock one and only writes the store (the implementer verifies; otherwise it goes in the write log).

### 4.4 K3 — the kernel

`combat_k3_begin(dt, clocks, use_memo, ctx)` then `next()` until `DONE`. `ctx` is K2's `_K2Context` (iids table, view offsets, NPC-shield cheat, player) plus the step scan and the frame table. The kernel reproduces map §A6 exactly:

1. ship cache over the step scan in list order, dead-at-start ships dropped, `bubble_bound_radius` (B1) per ship;
2. per torpedo in table order: guide if `_target_ship` set and `_age < _guidance_lifetime` (pre-increment) — `offset_between` (torpedo set → target set) before `IsDead`, `IsDead` before speed, `_target_visible` (native `can_detect` from the source, memo only for the same-set/other-frame call, `dist_sq_gu` for the cross-region one, and the `off is None` case still asks) before the steer point, the three field writes before the `dist < 1e-6` return (G1-G12); then advance (A1-A6), TTL expiries first into `expired`;
3. broadphase: the existing `sweep_candidates` kernel in-process for same-set ships, the shifted test (B2) for other regions, candidates ascending by ship-cache index;
4. narrow per moving torpedo, first passing candidate wins: `shields_block` + bubble (K2's `beam_geometry`, `max_dist = seg_len`), `sphere_hit` (A8), ray set-up (A9-A11), `resolve_hit_point` (K2's `beam_trace`, `fallback_point = seg_cur`), store write of the final position (on the bubble when it hit one, A13).

Records:

| Record | When | Python does |
|---|---|---|
| `ASK frame(set)` | a set with no frame-table entry | `frames.frame_of(set)` |
| `ASK steer_point(t)` | the target has `has_posed_parts`, or the shot needs its `_mount_key` attributed (first visible tick: once per shot, 0.06/tick) | `_steer_point(t, target, off)`, which also writes `_mount_key` (pushed); returns the point |
| `ASK guide(t)` | anything on one torpedo's guide path the kernel cannot vouch for (target with no row or a −2 ref, a target class without a real `IsDead`) | `_guide(t, dt)` whole; its writes push into the row; the kernel continues with that torpedo's advance |
| `ASK` (K2's `shields_block` / `bubble` / `resolve_hit` / `aim`-style asks) | the K2 conditions on the narrow path | as K2 |
| `DONE(writes, expired, hits)` | end | apply writes; `expire(t)` for each of `expired` in order; build and return `hits` |

ASKs run only Python that writes nothing the kernel has already decided on (the guide/steer of the torpedo being decided, pushed into its own row; or pure queries). There is no `RUN_PYTHON` after begin.

**Whole step to Python** (decided before begin, so nothing is half-done): switch off; audit mode (`DAUNTLESS_NATIVE_AUDIT=1`, as K2 C3); `type(_active) is not _ActiveList` (tests monkeypatch a plain list); the step scan not representable; a patched patch point or replaced function (identity snapshot, K2 §5.3 as amended by C2; list in map §A8.3.9); a torpedo whose row cannot be built (a non-float field); the K3/K4 static override guard failing.

### 4.5 Hits and object identity

`hits` entries carry: torpedo row, ship handle, hit point, the K2 trace tier, normal or None, bubble point or None, and a **"hit point is the bubble object"** flag. Python builds `TGPoint3`s so that, as today (map §A5): on a fallback-tier bubble hit, `hit_point`, `seg_cur` and `torpedo._bubble_entry` are **one object** (so `shield_point is hit_point` at `apply_hit`, and `WeaponHitEvent` holds it by reference); otherwise each is fresh. `_bubble_entry` is written only for the hit torpedo.

### 4.6 What stays Python per tick

`if not _active: return []` (quiet scene, before any marshalling); `update()`'s player resolution; the step scan and frame-table call; begin; the write log; `expire()` per expiry; the hit list build; ASKs.

## 5. Fallbacks — summary

| Scope | Trigger | Result |
|---|---|---|
| K4 whole | §4.2 list | `select_eligible` in Python |
| K3 whole step | §4.4 list | `update_all` in Python |
| K3 one torpedo's guide | §4.4 `ASK guide` | `_guide` in Python for that torpedo |
| K3 steer point | posed target / mount attribution | `_steer_point` in Python |

Counters: `counts()["k3_python_reasons"]`, `["k4_python_reasons"]`, and ASK counts by kind, as K1/K2.

## 6. Exactness

Parent §7.5 and K2 §6, plus (map §A3, §B3):

- `** 0.5` → `py_pow` (B1 `centre_len`, bubble); `Length` → `std::sqrt` (G1, G2, G5, A4); `acos` libm after the `py_max(-1.0, py_min(1.0, d))` clamp (G8); the three `sin` in the slerp → `py_sin` (G9); `math.dist` → `dist3` (E3); `py_min`/`py_max` with Python argument order (B1 2- and 3-arg, G7, G8, E1).
- `cur = prev + (v*dt)` and `seg = cur - prev` (not `v*dt`: rounding differs, A1-A3).
- Every NaN branch as the map lists (G1/G5 continue, G7 → 0.0/1.0, G8 → 1.0, A5 → no aim, A6 never expires, A7 NaN point, A8 no hit, B2 candidate).
- `off == (0,0,0)` is a tuple `==` (−0.0 equals 0.0); `offset_between(a, a)` short-circuits to exact zeros without resolving the frame.
- `_LEAD_ACCEL_K` (0.5) pushed as a named constant (ruling G); inline literals ported verbatim with source-line comments.
- No random numbers on the decided path.

## 7. Verification

- **Unit (ctest):** guide, advance, bubble-bound, sphere hit, frame offsets, K4 scoring and tie-break, each against values produced by the Python functions (golden `float.hex` pairs), plus NaN/inf rows.
- **Headless differential** (template `tests/integration/test_native_k1_differential.py` + `tests/helpers/fight_audio.isolate_fight_audio`): a torpedo fight, Python vs native, comparing per tick by `.hex()` every torpedo's position, velocity, age and guidance fields; the `ET_TORPEDO_EXITED_SET`/`ET_WEAPON_HIT` sequence; `apply_hit` arguments including `shield_point is hit_point`; `damage_eligibility._current` (as id sets); can_detect latch state. Branch counts > 0 for: guided visible, guided invisible (frozen last-seen), ballistic (no target / dead / other frame), guidance window ending, TTL expiry, cross-region hit and homing (the `test_frame_tripwire.py` scenario), bubble hit, sphere hit, posed target ASK, mount attribution ASK, and K4 ties and cross-frame ships.
- **Host differential** (template `tests/host/test_native_k2_differential.py`): real instances and hull boxes, so the mesh and sphere trace tiers and the bubble are exercised; extend the K2 file's scene with torpedoes or add a sibling.
- **Mutation proofs:** at least: drop the TTL-first ordering of `expired`; use `v*dt` for `seg`; use `sqrt` for `centre_len`; break the `id()` tie-break; drop the `off is None` can_detect call. Each must fail a test.
- **Static override guard** extended for the K3/K4 stood-in methods (`GetContainingSet`, `GetTranslate`, `SetTranslateXYZ`, `GetVelocityTG`, `IsDead`, `GetWorldLocation`, `GetRadius`, `GetScale` on every engine class that can be a ship, target or torpedo).
- **Scene audit** (`tests/host/test_native_combat_scene_audit.py`): the unaudited run asserts K3 and K4 ran with zero whole-step fallbacks; the audit compares torpedo rows against Python state.
- **Switch-off** tests: the existing torpedo and eligibility test files (map §A8.4, §B8) pass unchanged with native off.

Focused tests only during development; never the whole suite or the gate (CLAUDE.md "Test gate").

## 8. Measurement

Controller-run, after the code is final: two runs of the 64-ship fight with the switch on at the K3 tip (same command and scoring as SIG-162). Compare per tick against the two K2 runs (C-244, C-245). Record projectiles in flight beside `cb.projectiles`. Record a quiet-scene caveat: K4's quiet-scene gain is not measured by these runs.

## 9. Open items for Mark (copied, not fixed)

- Mission swap never clears `_active` (map §A8.3.11).
- End-point-only torpedo hit test can tunnel (map §A1.1).
- The lead-acceleration spike when a target re-emerges from cloak (G3).
- The `TorpedoScan` docstring's "~1,500 torpedoes" does not match captures (31-110).

## 10. Outcome

Built on branch `perf/native-combat-k3` (base `c6485d10a`); the tip measured is `0c5d58c81`. Default stays OFF (`DAUNTLESS_NATIVE_COMBAT` unset). **Live-verified by Mark 2026-11-01** ("it all looks good"; frame-rate comparison left to the benchmarks above). Full gate green on `0c670f768` after three pre-existing test-isolation fixes (forget_rows after the conftest mirror wipe; forget K2's seen classes with it; ShipClass.GetRadius restored via monkeypatch). Default stays OFF until Mark flips it.

**What shipped.** K3 (torpedo flight: guidance, advance, hit test, lifetime, with ASKs back to Python for the rare cases) is dispatched from `cb.projectiles`; K4 (damage eligibility) replaces `cb.eligibility`; both share one step scan (`step_scan.{h,cc}`). Fallback reasons are `k3_python_reasons` / `k4_python_reasons`; both stand down under `DAUNTLESS_NATIVE_AUDIT=1` (reason `audit`).

**Result (perf register SIG-164, SIG-165; captures C-246, C-247).** 64-ship fight, switch on, Debug, two runs each, per game tick, K2 tip `6418f858f` to K3 tip `0c5d58c81`:

| row | K2 | K3+K4 | change |
|---|---|---|---|
| `cb.projectiles` | 0.827 | 0.166 | -80% |
| `cb.eligibility` | 0.277 | 0.042 | -85% |
| `sim.combat` | 3.325 | 2.453 | -26% |
| `sim` | 10.565 | 9.986 | -5.5% (inside SIG-147's spread; not a measured gain) |

Ticks a frame 3.90 to 3.45; Python loop 65.3 to 57.2 ms a frame (tick counts differ, not like for like). Projectiles in flight medians 44/31 (K2) vs 40/53 (K3): the counts overlap. `cb.held_weapons`, `cb.phasers` and `gl.ai` stayed inside spread. `sim.combat` per tick across the three milestones: 4.466 (K1) to 3.325 (K2) to 2.453. Design goal 1 (combat step at most 1 ms a tick) is still **not met**; most of what remains is `cb.held_weapons` (~1.4), whose internal split is not measured. Evidence: Measured (rows), Derived (percentages).

**Fallbacks and coverage** (SIG-165 (3)). Differentials and scene audit run K3/K4 with zero whole-step fallbacks. Headless tpf 1 reaches 183 hits (55 on the bubble), 7 TTL expiries and 57 cross-region hits; the host differential (real hulls) reaches mesh-tier and sphere-tier hits (95/185 at tpf 1). Final test state: 191 combat ctest, 301 pytest across the 18 touched files.

**Switch-off cost.** `TorpedoField` descriptors: ~12 ns plain slot write vs ~56 ns descriptor, ~3 writes per torpedo per tick, ~13 us per tick at 100 torpedoes (Derived; whole-branch review microbench). A switch-off capture after K3 carries this.

**Rulings worth keeping.**
- A3: the step scan runs once per tick, owned by the host_loop call; K3 reuses it and never scans again (scan serial checked in `begin`).
- All K3 writes are deferred to DONE; a throw after begin is a protocol error (driver abandons and re-raises, same caveat as K2).
- Torpedo rows carry an `unrepresentable` bitmask; any set bit, a duplicate torpedo in `_active`, or a dropped-row ref sends the whole step to Python.
- Task 3's first write was refused by the safety check; Mark approved it and it was redone from the RED state.
- `isolate_fight_audio` now also resets the crew-handler announce timestamps (`Bridge.*Handlers` `g_fLast*`), which leaked across two-arm differentials and changed an SDK RNG draw order.
- Mutation testing: bubble-bound, TTL/hit order, tie-break and can_detect mutants are all caught; the bubble bound is only observable by comparing the kernel's own value each tick (the broadphase is conservative by construction).

**Parked for Mark (not done).**
- `Walker::trace` duplicates K2's `k2_beams.cc` trace; a shared helper was skipped because it touches measured K2 code.
- No guard for instance-attribute patches on torpedoes (none exist today).
- A dropped target referent sends the whole step to Python (`stale_ref`); a per-torpedo ASK would be finer.
- K1 headless differential ships have radius 0, so they never hit (K3's files seed radii).
- Earlier open items: mission swap never clears `_active`; the hit test checks the end point only (tunnelling); cloak lead-acceleration spike; the `TorpedoScan` docstring's "~1,500 torpedoes" does not match captures (31-110); gameplay hit sounds timed on the wall clock; K1 `can_detect` audit gap under `DAUNTLESS_NATIVE_AUDIT`; SDK `ConditionIncomingTorps` keeps a name-keyed registry across loads (harmless).
