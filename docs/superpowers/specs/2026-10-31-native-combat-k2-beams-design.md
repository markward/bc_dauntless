# Native combat step — phase 2: K2 beams (design)

**Date:** 2026-10-31.

**Status:** Mark asked for this phase to be specced, planned and built end to end ("spec it, plan it, and build it subagent driven"). The calls marked *(controller)* below are mine, made under that brief. Mark can overturn any of them.

**Builds on:**
- the parent design `docs/superpowers/specs/2026-10-30-native-combat-step-design.md` (§3 goals, §5 anti-goals, §7 design, §9 phases; its rulings R1-R12, P1-P7 and A-J are in §9.1-§9.2 and all still bind);
- phase 1b, which is live-verified (branch `perf/native-combat-1b`).

**Input map:** `docs/reference/engine/native-combat/k2-beams-map.md`. Every citation below of the form "map §x" or "F#" refers to it.

**Branch and worktree:** branch `perf/native-combat-k2`, from 1b tip `b1f2675a5`, in worktree `.claude/worktrees/native-combat-1b`.

## 1. Why

With 1b on, `cb.phasers` is the largest combat scope: 1.71–1.84 ms per tick in the 64-ship fight (two runs at `b1f2675a5`, `ms1-1b-*` logs). Its cost is spread out:

- the idle walk, ~0.24 ms;
- ~17 contacts per tick at ~80 µs each, about 80% of which is geometry: aim point, strip, arc, hull trace, shield bubble.

Python must still run the effects (`beam_contact`, `apply_hit`, `StopFiring`): about 18% of the scope.

## 2. Goals

1. `cb.phasers` per tick at least **halves** against the 1b build in the 64-ship fight, with total sim per tick no higher. Judged on two runs each (Mark's brief).
2. **Bit-identical** to the Python step with the switch on, per the parent §3.2:
   - every event, damage value, hit point, normal, shield point, `_dwell`, and every `StopFiring` call;
   - the same count, order and tick.
3. **Switch OFF is byte-identical** in behaviour to before.

## 3. Non-goals

- **The beam render builder** (`_build_phaser_beam_render_data`, `cb.render_data`). It recomputes the same geometry once per frame. It is a follow-on that can reuse K2's kernels (map §9).
- **Tractor beams.** They keep their own Python path.
- **Fixing anything the port copies.** The anti-goals in the parent §5 stand. Specifically:
  - the ship-wide subsystem lock aiming at another ship (map §1.2);
  - the 62% sphere-tier rate (map §8.3.2);
  - the stale render pose the trace reads (map §8.3.9);
  - the per-tick `StopFiring` on systems that are off (map §1.1).

  These are recorded as open items for Mark (§9).

## 4. Shape *(controller)*

**K2 copies K1's protocol.** It is a resumable C++ walk of the `cb.phasers` loop (map §1.1, verbatim in structure) over the phase 1 mirror.

- It returns **one record per Python effect** and resumes against the live mirror after each.
- No decision outlives an effect, so P1 applies: there is no epoch check.
- The GIL is held throughout (ruling J).

### 4.1 Records

**Common form.** Every record ends with `writes`, the ordered write log, which Python applies before acting (rulings A and P7).

| Record | What Python does |
|---|---|
| `WALK_START(ship, writes)` | nothing (cursor bookkeeping only); may be omitted if not needed |
| `SYSTEM_STOP(system, writes)` | `sys_.StopFiring()`, every tick for an offline or off system |
| `BANK_STOP(bank, writes)` | `bank.StopFiring()` (dead or None target, undetectable, cross-set, arc fail) |
| `CONTACT(bank, target, ship, contact…, writes)` | see below |
| `RUN_PYTHON(ship, writes)` | runs today's loop body for that ship (§5.1) |
| `ASK(query, args…, writes)` | answers via `combat_k2_answer(value)` by running the exact Python function (§5.2) |
| `DONE(writes)` | ends the session |

**`CONTACT` carries:**
- `emitter_xyz`, `target_pos_xyz`, `dist`, `aim_unit_xyz | None`;
- `impact_xyz`, `normal_xyz | None`;
- the impact **tier**: `mesh`, `sphere`, `fallback` or `origin`, so Python rebuilds object identity where Python's code returns the very same object (map §8.1);
- `bubble_xyz | None`, `shields_block`, `flush_dwell`.

Python then:
- calls `hit_feedback.beam_contact(...)` if `flush_dwell <= 0.0`;
- otherwise calls `combat.apply_hit(...)` if the damage is positive.

**Effect arithmetic stays in Python** *(controller)*: the damage falloff (F14), `PHASER_INTENSITY_SCALE[level]`, `weapon_splash_radius` and `damage_hull`. The cost is small (~17 evaluations per tick). It keeps one copy of each effect rule and avoids mirroring `_max_damage`, `_max_damage_distance`, `_damage_radius_factor` and `_power_level`.

**`beam_contact` and `shields_block`.** `beam_contact` gains an optional `shields_block=` argument. The K2 path passes the kernel's answer, because nothing runs between the decision and the effect. The Python path omits the argument and is unchanged.

### 4.2 The hull trace *(controller)*

The kernel must produce the renderer's exact float results.

1. Refactor the body of the `ray_trace_mesh` binding (`host_bindings.cc` ~7625) into a C++ function, `trace_instance_for_python(iid, origin_rel_f, dir_f, max_dist_f)`. It covers the float narrowing, the normalisation and the call to `renderer::ray_trace_instance_linear` on `g_world`.
2. The binding calls this function.
3. K2 receives it as a `std::function` callback installed by `host_bindings.cc` at `combat_k2_begin`.

As a result:
- the combat library never links the renderer;
- `ray_trace.cc` is never recompiled with the combat flags;
- the two paths are the same code by construction.

**Marshalling.** The kernel reproduces `host_io.ray_trace_mesh`'s steps in double (F17):
- `instance_translation`;
- `rel = origin − t`;
- the float narrowing that pybind does;
- `hit + t`;
- the view shift.

**Three outcomes stay distinct** (map §8.3.6):
- no instance gives the fallback point;
- a stale instance makes the call throw, then the sphere tier;
- a live instance traces, and on a miss falls to the sphere tier.

### 4.3 State K2 reads that the mirror lacks (map §2, §8.3.5)

- **Ship:** `_target_subsystem` (ref), `_use_target_offset`, `_manual_target_offset` (fv3 or unset) and `_shield_subsystem` (ref).
- **Target:** `_shield_hull_box` (6 doubles plus a set flag).
- **Render instance ids** *(controller)*:
  - `session.ship_instances` becomes a dict subclass that bumps a version counter on every set, pop and clear.
  - The K2 driver sends the ship→iid table at begin, and re-sends it on resume whenever the version moved.
  - K2 runs native only when the step's `ship_instances` argument IS that tracked dict. A test's sentinel dict, or None with tracing expected, runs Python. Exception: None is representable as "no instance for anyone".
- **Bank:** `_length`, `_beam_on_countdown` (float, written every tick by `UpdateCharge`) and `_dwell`.
  - `_dwell` is computed by the kernel and copied back by the write log (P7).
  - Its other writers (K1's `_fire_effect`, `tests/helpers/beams.py`) push through the descriptor.
  - An idle write of `0.0` over `0.0` is elided. It is a plain field, so there is no side effect to preserve.
- **Shield subsystem:** a derived `has_shields` flag (`sum(_max_shields) > 0.0`, computed in Python exactly as `HasShields` does). It is pushed by every `_max_shields` writer, including the in-place `SetMaxShields` write (SS:2119), which becomes a pushing mutator (parent §7.1 rule).
- **Per-step context**, passed at begin and re-sent on resume only if changed (Python checks after each effect):
  - the dev "disable NPC shields" flag and the current player handle;
  - the viewing set and its per-set view offsets (map §8.3.10).
- **Globals** (pushed from Python, ruling G): `BEAM_DWELL_FLUSH_S` and `SHIELD_ELLIPSOID_AXIS_SCALE`.
- **Class flags:** `has_real_get_shields`, plus override detection for every Python function K2 replaces (§5.3).

## 5. Fallbacks *(controller)*

### 5.1 Whole ship (`RUN_PYTHON`, before any write for that ship)

The kernel pre-scans the ship and hands it to Python whole when any of these hold:

- the ship is posed (`has_posed_parts`);
- the phaser system or a bank has an unregistered, -2 or stale row;
- a bank class is overridden (§5.3);
- the ship is unslotted.

To make this possible, the `cb.phasers` loop body moves into `_phaser_step_ship(ship, …)`. The Python path calls it in the same loop, so there is one copy.

### 5.2 Per bank (`ASK`)

Some sub-results become unrepresentable only because of the target or the lock. For these the kernel asks Python for that one result, by running the exact Python function:

- the lock's ship is posed, or its row is stale → `ASK aim_point` → `_phaser_aim_point(ship, target)`;
- a Manual Aim target is posed → `ASK aim_point`;
- the target has no real `IsDead` → `ASK is_dead`;
- the target is not a ShipClass, or lacks a real `GetShields` → `ASK shields_block`, and `ASK bubble` if needed;
- the target's set is not representable in the view-offset table → `ASK resolve_hit` → `combat._resolve_hit_point(...)`.

Also, a row a handler drops mid-walk follows K1 ruling H: `ASK` where exact, otherwise the documented invariant and `RuntimeError`.

### 5.3 Whole step

The K2 entry checks, by identity against an import-time snapshot (as 1b does), every module function and method K2 stands in for. These include:
- `host_io.ray_trace_mesh`;
- `combat._resolve_hit_point`, `ray_sphere_entry`, `shields_block`, `shield_bubble_entry`, `cloak_shields_suspended` and `_hull_box_for`;
- `host_loop._phaser_aim_point`;
- `frames.view_offset`;
- the bank's `IsFiring`, `take_dwell`, `accumulate_dwell` and `_strip_emit_position`;
- the ship's `GetTargetSubsystem`, `is_using_target_offset`, `GetTargetOffsetTG` and `GetShields`;
- `ShipSubsystem.GetWorldLocation`.

A patched module function sends the whole `cb.phasers` step to Python. A patched class flags that class (as `k1_overridden`). Many existing tests monkeypatch these functions, which is why the check is needed (map §8.3.7).

## 6. Exactness

The parent §7.5 rules and the 1b rules apply:
- `py_pow` for `** 0.5`, `py_min`/`py_max`, operand order, `-ffp-contract=off` with the pragma, and NaN branches as in Python.

K2-specific points (map §3):
- F7's explicit zero test;
- F8's **unsorted** clamp, so a reversed width always yields `lo`;
- F16 returns a NaN point, not None, on NaN inputs;
- F2 NaN gives no trace and no bubble;
- F14 NaN gives no `apply_hit`;
- the trace's pose is the last synced `g_world` pose. The kernel calls it at the same point in the order and never re-syncs.

## 7. Verification

**Unit differentials.** Each new geometry function is compared against its Python original by `.hex()` over seeded random cases plus the map's edges:
- strip (F5-F10), dwell (F13), sphere tier (F18), `shields_block`, bubble (F15-F16) and the lock and manual aim points;
- the trace marshalling, on a real Galaxy instance in a headless host (`tests/host/test_mesh_ray_trace.py` style), against `combat._resolve_hit_point`. Thousands of rays, covering hits, misses, stale and absent instances.

**Step differential at host level** (map §8.3.1, risk 1).

The 1b differentials are headless: no instances, no hull boxes. They cannot see the trace or the bubble. A new test therefore uses:
- a headless host with real `g_world` instances and cached hull boxes;
- a seeded fight of at least 8 ships (phasers in arc and out, locks, Manual Aim, shields up and down, a cloaking target, a posed ship).

It runs native against Python per tick, comparing every bank's `_dwell` (hex), every `StopFiring` call, and the full ordered event log including `ET_WEAPON_HIT` payloads. It also captures the `beam_contact` arguments, by spying on the function, compared by hex.

**Existing tests.** The 1b differentials, the scene audit and the existing phaser tests (map §8.4) stay green with the switch off. The step differentials also run with it on.

**Mutation proofs.** Each differential must fail under a mutation its scene exercises.

## 8. Measurement

Two runs of the 64-ship fight with the switch on at the K2 tip, compared against the two 1b runs (`ms1-1b-*`, 2026-10-31 22:26). The scoring follows SIG-157: value ÷ average ticks per frame, median of reports 3-11.

The results go in the perf register and in §10 of this file.

## 9. Open items for Mark (copied, not fixed)

- **62% sphere tier.** 62% of phaser traces miss the mesh and fall back to the sphere tier (map §8.3.2). The possible cause is the ship-wide subsystem lock aiming at a different ship than `bank._target`.
- **Stale trace pose.** The trace reads the last frame's pose while the sim has advanced several ticks.
- **Per-tick `StopFiring`.** Off phaser systems call `StopFiring` every tick, waking every bank.
- **Render beam builder.** `cb.render_data` recomputes the beam geometry once per frame. It is a K2-render follow-on.

## 10. Outcome

Built on branch `perf/native-combat-k2`; the tip measured is `6418f858f`. Default stays OFF (`DAUNTLESS_NATIVE_COMBAT` unset); the default flip awaits Mark's live check.

**Result (perf register SIG-162, SIG-163; captures C-242..C-245).** 64-ship fight, switch on, Debug, two runs each, per game tick (SIG-157 method), K1 tip `b1f2675a5` to K2 tip `6418f858f`:

| row | K1 | K2 | change |
|---|---|---|---|
| `cb.phasers` | 1.774 | 0.739 | -58% |
| `sim.combat` | 4.466 | 3.325 | -26% |
| `sim` | 11.859 | 10.565 | -11% |

The goal in §8, halve `cb.phasers`, is **met**. `cb.held_weapons`, `cb.projectiles`, `cb.eligibility` and `gl.ai` stayed inside run-to-run spread. The Python loop fell 81.8 to 65.3 ms a frame, but ticks a frame also fell (4.95 to 3.90), so per-frame rows are not like for like. The K1 runs had a code-reading agent running at the same time; the K2 runs were on an idle machine. The `sim` change is inside SIG-147's spread. Evidence: Measured (rows), Derived (percentages).

**Fallbacks.** Host differential, 9 ships, 600 ticks: 0 whole-step fallbacks and 80 ship fallbacks, all `posed_ship`; every ASK was `aim_point`. A 5-minute 16-ship real-AI fight ran no ship in Python. New fallback reason `audit`: K2 stands down when `DAUNTLESS_NATIVE_AUDIT=1`.

**Driver overhead** (microbench, Debug, 9 ships / 46 banks). Per-bank check 9.8-10.3 us to 5.2-5.7 us (bank scan moved into the binding, `combat_k2_scan_ships`). Begin 11.0-11.4 us to 6.7-7.2 us (iids table kept in the kernel, re-sent only when it changes). Extrapolated ~145 to ~50 us per tick at 500 banks / 64 ships.

**Switch-off cost.** Behaviour is unchanged, but `_dwell` became a `NativeField`, so every idle bank's `take_dwell` write goes through a Python `__set__`: 71 ns against 26 ns plain, about 23 us per tick at 500 banks, plus the extra call layer of `_phaser_step_bank`. A switch-off capture after K2 carries this.

**Rulings that amended this spec.**
- **C2 amends §5.3.** The override rule is "non-engine code, or changed since K2 first saw the class". It is guarded by `tests/unit/test_native_k2_override_guard.py` (allowlist: `DamageableObject.IsDead`, `ProximityCheck.GetRadius`).
- **§4.2 wording.** The trace hooks are installed at module load, which is equivalent to what §4.2 describes.

**Found on the way.** `host_loop.run` installs the AI sensor gate as a class-level SDK patch and nothing removed it between tests, which made the K1 differential order-dependent. `conftest` now calls `uninstall_ai_sensor_gate()`, and `tests/helpers/fight_audio.isolate_fight_audio` isolates hit-audio state in both differentials.

**Known limits.**
- K1's in-kernel `can_detect` skips the per-call `_audit_can_detect` under `DAUNTLESS_NATIVE_AUDIT`; K2 stands down instead.
- The unseen-class check is per class, not per row: a `__class__` swap without `reclassify` is not detected (rocks call `reclassify`).
- Instance-attribute patches on targets are not detected (accepted trade-off).
- Copied behaviours are unchanged (§9): 62% of traces fall to the sphere tier, the trace reads the render pose, off phaser systems call `StopFiring` every tick.
- Gameplay hit sounds are timed on the wall clock (Mark's call).
- SDK `ConditionIncomingTorps` keeps a name-keyed registry across loads (harmless).
- The golden trace digest test is tied to build type and mesh-fix hash, and skips elsewhere.
- Linux/Windows exactness of `py_sin`/`py_cos` is not verified.
