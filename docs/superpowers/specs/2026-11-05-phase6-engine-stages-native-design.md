# Phase 6 — Our engine stages in C++, then the SDK boundary, then the divergences

**Status:** DRAFT for Mark, 2026-11-05.
**Project:** native motion + proximity (`project/native-motion-and-proximity`). Phase 5a (hull cull, Mac multithreaded GL) is merged and live.
**Evidence:** perf register SIG-196 (128-ship Release probe) and SIG-197 (cProfile splits, re-split by SDK versus ours on 2026-11-05).

## 1. Why

At 128 ships in Release the frame is 54–78 ms, and nearly all of it is Python.

- **The catch-up loop multiplies everything.** Per-tick Python is about 11.7 ms, which is 70% of the 16.67 ms tick, so each frame runs 3–5 ticks. Roughly, frame ≈ C / (1 − S/16.67), where S is the per-tick cost and C the per-frame cost (about 18 ms here). So 1 ms off S saves 4–5 ms a frame at 128 ships (SIG-196).
- **About 90% of the per-tick Python is ours, not the SDK's.**
  - Of AI (about 40% of the tick), SDK script code is 22–23%. The other 77–78% is our Python underneath it: the AI tree engine and the App methods the SDK calls.
  - Subsystems, weapons, combat and the combat render data contain no SDK script at all.
  - So SDK script code is about 10% of the tick (SIG-197).
- **BC ran all of that in C++.** `App.py` is SWIG-generated, so every class the SDK calls was C++ in BC: the subsystems, power, repair, weapons, `GetWorldLocation`, `GetNearObjects`. Our Python versions are left over from Phase 1. Moving them to C++ matches BC's architecture; it is not a divergence. It is also Mark's standing rule: engine logic in C++, mods get designed hooks.

## 2. Goals, non-goals, anti-goals

**Goals:**
- 64 ships stay at 60 fps or better in Release, live. Mark sees 45+ fps live today, against 60–71 headless at 1280×720.
- At 128 ships, the catch-up spiral is broken: per-tick cost at or below 8 ms in Release at 128 ships, exterior view. *(My call. It puts 128 ships at roughly 25–35 fps by the formula above. Mark may set another number.)*
- Each piece is measured before and after with the same Release commands (§7), and recorded in the perf register.

**Non-goals:**
- A render thread. Phase 5a cut the native render to about 5 ms, so it is now the smaller cost. Revisit after this phase.
- GPU work.
- 256 ships.
- Changing what SDK scripts or missions do, except for the divergences listed in §5.

**Anti-goals (a failure even if it gets faster):**
- **Breaking a mod or mission script.** A mod's own AI classes, a mission that patches a method, or a script that overrides a preprocessor must keep working. The kernel-M pattern is mandatory: native for stock code, Python as soon as a script overrides or patches something.
- **A per-tick repack of state between Python and C++.** SIG-197 shows the weapons stage is almost entirely K0's `begin` / `next` repacking its mirror every tick. A migration that moves the compute but still packs every tick has moved the cost, not removed it.
- **An undocumented behaviour change.** Every departure from BC goes into `docs/reference/engine/perf-cadences-and-latency.md`, or a new section beside it, with what it changes and how to switch it off.
- **Porting a hot SDK-facing method to C++ without measuring it first** (§4). A Python-to-C++ call plus building a new point object can cost more than today's Python method.

## 3. Part A — our engine stages, whole, into C++

These are the stages our own loop drives, so we choose how often they cross into C++: **once per stage per tick, with the stage's state living in C++ permanently.** This is the pattern of the combat kernels and kernel M, with the K0 lesson applied: no per-tick repack.

| Stage | What moves (SIG-197) | Notes |
|---|---|---|
| Subsystems (`_update_ship_subsystems`) | `PowerSubsystem.Update` (passive power pump, battery-limit property reads): 50% of the stage. `RepairSubsystem.Update`: 18%, including one native `SetCondition` push per repaired subsystem per tick. `articulation.tick_ship` on every ship every tick: 15%. `ShieldSubsystem.Update`: 4%. | Passive-state contracts (`WakeField` / `FrozenField`, the `_POWER_FREEZABLE` comment) become the C++ stage's own dirty tracking. Python field writes push to it, as `Native*` descriptors already do. Articulation: a ship with no rig does no work. |
| Weapons (`_advance_weapons`, K0) | The mirror becomes persistent, so `combat_k0_begin` / `combat_k0_next` no longer pack every tick. | Today it is about 96% native marshalling, not compute. |
| Combat glue (`_advance_combat`: K1 39%, K2 25%, K3 23%) | The Python around each kernel: handle lists, ship scans, cleanup, effect-queue drains. | About half of this stage's time is in Python. |
| Combat render data (`_push_combat_render_data`, per frame) | Phaser beam descriptors (49% of it, one Python call per beam) and torpedo descriptors (23%), built natively from state C++ already holds. | Runs per frame, so it is outside the spiral's multiplier, but it is 3–4 ms at 128 ships. |

**Python copies.** Migrated stages keep no permanent Python copy. That follows Mark's earlier ruling on render transforms ("no, all to C++") and fire control being native-only. The golden fights (`tests/integration/test_golden_fights.py`) and the focused unit tests are the reference. A stage may keep its Python path behind an env switch only while it is being built; the switch and the copy are deleted when the stage is done.

**Bit-exactness.** A stage that changes no behaviour must keep the golden fights unchanged. If a stage needs a golden re-record, that is a behaviour change and needs a ruling recorded in the plan.

**Baseline.** The baseline is the current Python output, as the goldens record it.
- The passive-state freeze and thaw (`WakeField` / `FrozenField`) was built to be behaviour-identical, and `DAUNTLESS_PASSIVE_AUDIT` checks that against the full step. So a C++ stage may simply compute every ship every tick and drop that machinery, provided the goldens hold. *(My call.)*
- Real cadences are behaviour, not optimisations, and are kept: shields charge every 0.5 s, and the rest of `perf-cadences-and-latency.md`.

**Mods and patches (Part A).** A Part A stage does not fall back to Python when a script patches an App method. That matches BC: BC's `App.py` is SWIG shadow classes with no directors, so `PowerSubsystem` exposed only accessors (`GetMainBatteryLimit`, `GetAvailablePower`, ...) and no `Update`. Its per-tick update was internal C++ that no script could override. A Python patch of an App accessor changes what Python callers see, exactly as in BC.
- The kernel-M fallback stays the rule for **SDK script classes**, meaning the Part C preprocessors.
- Our OWN Python hooks into these stages (the developer combat cheats around `combat.apply_hit`, and anything else that wraps a stage function) must be found and carried into the native stage explicitly. The plan for each stage lists them. *(My call, from BC's architecture.)*

**State of record.** Migrated state is native-authoritative. Python reads and writes it through `Native*` descriptors, the existing combat-mirror pattern (`A field the kernel reads MUST be a Native* descriptor`), and is never pushed from Python on a timer or every tick. SDK and mod reads such as `GetCondition` or `GetPowerPercentageWanted` go through those descriptors, which keeps their per-call cost a Part B concern. *(My call.)*

**Save and load.** The engine has no save system yet (persistent saves are deferred project work), so this phase does not add one. All migrated state must stay readable and writable from Python through its descriptors, so a later save system can serialize it. *(My call.)*

## 4. Part B — the SDK-facing hot methods, after a boundary benchmark

These are the methods SDK scripts call directly. The scripts decide how often, so the cost per call matters:

| Method (called from SDK code, 128 ships) | Share of AI | Calls in the window | Notes |
|---|---|---|---|
| `ai_sensor_gate._gated_find` (our wrapper around SDK `FindGoodTarget`) | 25.3% | 2,538 | Includes the SDK rating loop under it (§5) |
| `ObjectClass.GetWorldLocation` | 6.6% | 4.9 M | Builds a new `TGPoint3` per call |
| `SetClass.GetClassObjectList` | 5.6% | 167 k | |
| `GetNearObjects` (proximity) | 5.4% | 47 k | The native query is already inside it |
| `StartFiring` | 4.8% | 15 k | |
| `GetCombinedConditionPercentage` | 2.5% | 651 k | |
| `IsTypeOf`, `GetVelocityTG`, `GetObjID`, `GetTarget`, `TGPoint3` math | 1–3% each | millions each | |

**Task B0 is the boundary benchmark, and it is the first task of the phase.** It runs beside Part A, because nothing in A depends on it. At realistic call counts, measure:
- the current Python method;
- a pybind binding returning a new Python object;
- a pybind binding writing into a caller-supplied object;
- a native-backed `TGPoint3`;
- a thin Python method reading native state through a buffer or view.

Measure per-call cost, plus the allocation cost for point-returning methods. The result picks one approach per method family: "port the method", "thin Python over native data", or "make the point type native". Each choice is recorded in the plan, with its numbers, before any method moves. B0 writes its numbers into the perf register.

## 5. Part C — native stock preprocessors (BC's own design) and one divergence

**BC compiled these preprocessors into C++ itself.** The binary research recorded in `engine/appc/ai_optimized.py`'s docstring (2026-07-14) shows what `PreprocessingAI::SetContainedAI` does. It asks the bound Python preprocessor for its "optimized version", looks its class name up in a native registry, and on a hit replaces the node with a native one.
- Four classes are registered: `AvoidObstacles`, `FireScript`, `ManagePower`, `SelectTarget`.
- **In shipped BC their Python `Update` bodies are dead code.** The SDK says so itself above `FireScript`, `SelectTarget` and `AvoidObstacles`: "replaced with an optimized version in the code".
- We run those Python bodies only because we had no native versions. Three of them are SIG-197's top AI hotspots.

So item 1 below restores BC's architecture; it is not a divergence. What BC's native versions decide differently from the SDK bodies is unknown: the RE project has not reconstructed them. Our native versions reproduce the SDK bodies we run today, and any difference is recorded.


What is left after A and B is SDK script code: about 10% of the tick today, a larger share once A and B land. Mark allowed divergence from BC's behaviour in AI, subsystems and combat (2026-11-05). Two divergences are decided here.

1. **Native stock preprocessors.** A ship whose tree uses the *stock* `AvoidObstacles`, `SelectTarget` or `FireScript` class, unpatched, runs a C++ implementation of that preprocessor. Any subclass, monkeypatch or mod replacement runs the SDK Python, as kernel M does.
   - "Unpatched" means three things: the instance's class IS the stock class object (not a subclass), each method it would call is the stock function object (an identity check against a snapshot taken at SDK load, as in kernel M's stock snapshot), and the instance has no instance-level overrides.
   - The C++ version reproduces the stock script's decisions as closely as is cheap. Where it differs, it is a recorded divergence, not a bug.
2. **Target selection rates only the nearest candidates.** Stock `FindGoodTarget` rates every enemy, so the cost grows with the square of the ship count (10% of AI at 64 ships, 25% at 128). Instead, rate only the nearest **8** candidates, using the native proximity query, plus the current target and any target the mission has forced.
   - The sensor gate (`ai_sensor_gate`) filters FIRST. The nearest 8 are chosen among candidates the ship can detect, so the gate never leaves it with fewer than 8 when more are detectable.
   - "Forced" means whatever inputs the stock `SelectTarget` script itself treats as priority targets (its constructor and setter arguments). Part C's plan names them from the SDK source; every one stays in the candidate set.
   - *(The 8 is my call; it should become a dial.)*
   - Off switch: an env var, named in the plan.

Any further divergence (cadence changes, approximations in conditions) needs Mark's explicit ruling. It is not covered by this design.

## 6. Order and phase shape

1. **B0, the boundary benchmark,** runs alongside A1.
2. **A1 Subsystems**, then **A2 Weapons (K0 persistent mirror)**, then **A3 Combat glue**, then **A4 Combat render data**. Each is its own measured step with a perf-register signal.
3. **B, the SDK-facing methods,** in the order B0 recommends.
4. **C, the divergences.**
5. Mark's live check after each part, not only at the end.

**Pass and fail.** Measured on `combat_stress`, Release, in both views. The 64-ship goal is the primary gate. The 128-ship per-tick goal is a target, not a gate. Part C goes ahead whether or not A and B reach it, because its target-selection change fixes the cost growing with the square of the ship count, which A and B can only make cheaper. *(My call.)*

Each part is its own plan and its own phase branch, cut from the project branch and merged back after its live check, as phases 2–5a were.

## 7. Measurement protocol

- The Release build in `.claude/worktrees/release-macos`, detached at the commit under test.
- The phase0-runbook §1 capture command at `DAUNTLESS_COMBAT_SHIPS=64` and `=128`, exterior and bridge, 1,500 frames, two runs each. Score with the median of reports 3–11.
- For splits: `DAUNTLESS_PROFILE_PY=<path>`, frames 500:400. Read relative splits only, never frame times.
- The gate runs only when the project branch merges to main, and only when Mark says so.

## 8. Left to the builder

- The C++ data layout for each stage, and how it shares the combat mirror.
- How each stage's dirty tracking replaces the `WakeField` / `FrozenField` machinery.
- Test structure, within "golden fights unchanged unless a ruling says otherwise".
- Names of env switches and dials.
