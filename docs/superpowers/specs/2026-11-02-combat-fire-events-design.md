# Native combat: weapon events and sounds through the boundary queue — design

**Status:** built 2026-11-02, outcome in §10; live-verified by Mark 2026-11-02 ("no issues") and merged into `project/combat_threading` (`70da394a3`). Mark: "Agreed with your next step. Spec it, plan it, implement it subagent driven." Step 3 of roadmap workstream G, under decisions 6, 9, 12 and 13 (`2026-11-01-threaded-weapons-combat-roadmap.md` §3) and Mark's rule that the sim must run without checking in with Python.
**Branch:** `ws/combat-fire-events`, off `ws/combat-effect-queue` (`e47215f19`; step 2, awaiting Mark's live check), in worktree `.claude/worktrees/native-combat-k3`. Merges after step 2. No main gate: focused tests, differentials, two benchmark runs.
**Inputs:** `docs/reference/engine/native-combat/event-inventory.md` (EI §n), `remaining-fallbacks-map.md` §4, `docs/reference/engine/event-emitter-gaps.md` #14 (the `ET_WEAPON_FIRED` bugs, decided "fix both").

## 1. Why this phase

The kernels still hand records back to Python mid-step for effects that only report or present: a weapon's fire sound and its `ET_WEAPON_FIRED`, the cannot-fire event, a firing bank's loop-sound stop, a tube's reload event. Each is a Python check-in in the middle of the walk, which a kernel running off the lock cannot make. Measured 2026-11-02 (64-ship `combat_stress`, switch on, headless, 8,999 ticks), records per tick:

| Kernel | Record | Per tick | After this phase |
|---|---|---|---|
| K0 charging | `DEPLETE_STOP` (StopFiring: loop sound) | 0.031 | queued |
| K0 | `RELOADED` (`ET_TORPEDO_RELOAD`) | 0.056 | queued |
| K0 | `WATCH` (charge-watcher crossing) | 0 here | queued |
| K1 fire control | `FIRE` PhaserBank (beam start: writes, fire sound, `ET_WEAPON_FIRED`) | 0.110 | logged writes + queued |
| K1 | `FIRE_FAILED` (`ET_WEAPON_FIRE_FAILED`) | 0.390 | queued |
| K1 | `FIRE` TorpedoTube / PulseWeapon (launch script, projectile) | 0.061 / 0.038 | **stays** (needs workstream F); its events queued from Python |
| K2 phasers | `BANK_STOP` of a firing bank (loop sound) | 0.069 | logged writes + queued |
| K2 | `CONTACT` damage pulse | 0.453 | **stays** (workstream D) |

After it, K0 returns nothing but its whole-ship fallback, K1 only launches (0.10 per tick), and K2 only damage pulses (0.45).

## 2. Goals, non-goals

**Goals**
1. **One ordered effect queue** (decision 6): every weapon event and weapon sound in §4.2 goes into it, whether a kernel or Python produces it, and is delivered in emission order at the tick boundary.
2. **K0, K1 and K2 stop returning records for them** (§4.3): the kernel logs the writes and appends queue entries.
3. **Bug fix, both switch states** (event-emitter-gaps #14): `ET_WEAPON_FIRED` carries the target ship as its object pointer, and pulse weapons post it.
4. Game state bit-exact with the Python reference, switch on, apart from the timing of the queued events themselves (§5); behaviour byte-identical, switch off, apart from goal 3.
5. Measured: two benchmark runs against step 2's (`eq-*` logs). No speed target; the expected change is small (0.66 records per tick), and must not be a slowdown.

**Non-goals**
- Torpedo and pulse launches (the launch script, the projectile): workstream F. Their events are queued (from Python) in this phase; the record stays.
- Damage pulses and everything under `apply_hit`: workstream D.
- Tractor beams: their started/stopped events and power-program thaw stay as they are (K1 `self_managed`, K0 ruling W6).
- The third random-number generator (decision 12): nothing in §4.2 draws a random number (`_play_fire_sfx` checked; Task 1 confirms the rest).

## 3. Constraints (programme-wide)

- Switch `DAUNTLESS_NATIVE_COMBAT=1`, default OFF. The lock is held throughout. Ruling P1 holds for game state.
- Focused tests only; never whole suites, never the gate. Banned git commands as in CLAUDE.md. Never launch the game; the controller runs the headless benchmark.

## 4. Design

### 4.1 The queue and its scope

- A native, ordered queue in the host layer (beside `combat_write_apply`), one per process. An entry is a kind plus its operands: mirror handles when a kernel appends, Python object references when Python appends (the lock is held for both). One emission order for both.
- **The deferral scope.** With the switch on, `host_loop` opens the scope around each sim tick's `sim.weapons` and `sim.combat` and **flushes it when the tick's combat step ends** (the tick boundary). Inside the scope every producer in §4.2 appends instead of acting. Outside it (an AI's `StartFiring` running a K1 system session from `gl.ai`, a mission script calling `StopFiring`):
  - a Python producer acts at once, as today, unless a native session is open (ruling F3, §10: a native session opens its own deferral);
  - a native session's entries are delivered when that session ends (its caller is Python already; nothing waits on a boundary).
- **Delivery** (Python, in queue order): resolve handles (an entry whose object was freed or unregistered is skipped and counted), then perform the entry's Python (§4.2). A failing entry is logged and delivery carries on (decision 13); under tests and `--developer` the flush delivers the rest, then re-raises the first error with the later ones as notes.
- Switch off: no scope is ever open; every producer acts at once. Byte-identical.

### 4.2 What goes through it

| Entry | Produced by | Delivery (Python) |
|---|---|---|
| `FIRE_SOUND(bank)` | an energy weapon's was-not-firing edge (`_EnergyWeaponFireMixin._fire_effect`) | `bank._play_fire_sfx()` (sets `_loop_handle`) |
| `LOOP_STOP(bank)` | a firing energy weapon's `StopFiring` | stop and clear `bank._loop_handle` |
| `WEAPON_FIRED(weapon, target)` | beam edge (`PhaserBank._fire_effect`), tube launch, **pulse shot (new)** | post `ET_WEAPON_FIRED`: source the weapon, destination its ship, **object pointer the target ship (new)** |
| `WEAPON_FIRE_FAILED(tube)` | `_broadcast_weapon_fire_failed` | post it as today |
| `TORPEDO_FIRED`, `AMMO_CONSUMED` | a tube launch (still a Python record) | post them as today; with `WEAPON_FIRED` they keep BC's audited order TORPEDO_FIRED → WEAPON_FIRED → AMMO_CONSUMED (EI R3) |
| `TORPEDO_RELOAD(tube)` | K0 `RELOADED`, Python `ReloadTorpedo` | `_broadcast_reload()` as today |
| `WATCH(watcher, old, new)` | a charge-watcher crossing (K0 `WATCH`, Python `_update`) | fire the watcher's events for the checks crossed between `old` and `new`, against the checks registered at delivery; the watcher's `_value` was committed at production |

Every producer appends when the scope is open, **including Python ones** (a ship run whole in Python, K2's Python records, a death path calling `StopFiring`), so a bank started natively and stopped from Python in the same tick still plays, then stops, its loop. The torpedo's own launch sound stays with the spawn (workstream F).

### 4.3 The kernels

- **K1:** a beam edge becomes logged writes (`_firing`, `_target`, `_target_offset`, `_beam_on_countdown`, `_dwell`, as the sustain FIRE already is) plus `FIRE_SOUND` and `WEAPON_FIRED`; `FIRE_FAILED` becomes an entry; a firing bank's `BANK_STOP`/`STOP_SYSTEM` becomes logged writes plus `LOOP_STOP`. Tube, pulse and dumb fires stay records.
- **K2:** a firing bank's `BANK_STOP`/`SYSTEM_STOP` becomes logged writes plus `LOOP_STOP`.
- **K0:** `DEPLETE_STOP` becomes logged writes plus `LOOP_STOP`; `RELOADED` becomes logged writes plus `TORPEDO_RELOAD`; `WATCH` becomes the watcher's committed value plus `WATCH`.
- Kernel-appended entries carry mirror handles; the native queue holds them with no Python call. An abandoned session keeps the entries it appended (ruling F5, 2026-11-02, replacing "drops them"): a kernel appends an entry only after its record's writes applied, so every entry belongs to an effect that already happened, and the Python reference posts those events too.

## 5. Rulings

- **E1. Queued events are delivered at the tick boundary,** so their handlers' changes reach combat the next tick (decision 9). The kinds here are REPORT or NONE in the inventory, except `ET_TORPEDO_FIRED` (ORDER: Episode7's handler acts between it and `ET_WEAPON_FIRED`), whose order with its siblings the queue keeps.
- **E2. Queued kinds may now arrive after synchronous events of the same tick** (an `ET_WEAPON_HIT` from a damage pulse, a collision event). No stock consumer of the queued kinds reads order against those (EI §2-3). *If wrong:* a mission that counts shots and hits together sees them in a different order within one tick.
- **E3. A watcher event is delivered after the watcher committed its new value** (today: before, EI R9). A handler reading the watcher sees the new value. *If wrong:* one tick of an AI condition seeing post-crossing charge.
- **E4. One queue per event kind.** While the scope is open, no producer of a §4.2 kind may act directly; a split path is what E1M2's rule forbids (roadmap decision 10).
- **E5. The bug fix applies in both switch states.** The differentials' Python reference arm includes it.

## 6. Testing

- **Queue unit tests:** emission order across native and Python appends; scope open/closed; native session outside the scope delivers at its end; freed objects skipped and counted; decision 13 in both modes; an abandoned session keeps its entries (ruling F5, §10).
- **Kernel tests (C++):** each converted record is now logged writes plus the right entries, in walk order; the remaining records are unchanged.
- **Dispatch tests (Python):** a bank fired natively and stopped from Python in the same tick plays then stops its loop; a tube launch's three events arrive in R3 order; a reload and a watcher crossing are delivered at the boundary.
- **Differentials (K0, K1, K2, step):** the queued kinds compare per tick as an ordered list among themselves (both arms emit them in the same order) and leave the ordered game-state event log; everything else unchanged. Every existing branch tally still fires.
- **Bug fix:** headless, E1M2's and E2M1's `WeaponFired` handlers get past their early return (the object pointer is the target ship); a pulse shot posts `ET_WEAPON_FIRED`.
- **Mutation checks:** deliver out of order; act directly from Python inside the scope; drop the object pointer. Each must fail a test.

## 7. Measurement

Controller, after the last task: records per tick by kind (the §1 table) and two benchmark runs against `eq-brawl-on-run{1,2}-cs64-bridge-20261102-0839.log`; perf register C-266/C-267 and a signal.

## 10. Outcome

Built 2026-11-02 on `ws/combat-fire-events`; awaiting Mark's live check (after step 2's). Commits: `e6279cf5a` (weapon-fired fix), `4fc567dfb`, `73e2a022a` (queue), `c1535cf8a`, `7e81d8fe9` (K1), `daf46edff`, `89ed019dc` (K0, K2), `4082388e6` (final review: `sim.effects` row, loop stops compared in the differentials, `ET_WEAPON_FIRED` as a `TGObjPtrEvent`, pulse posts only with a bolt).

### What shipped

- **`ET_WEAPON_FIRED` carries its target** as the object pointer, and pulse weapons post it (event-emitter-gaps #14). Also brings E2M2's and E6M4's `WeaponFired` handlers to life (not verified in play).
- **The effect queue** (`native/src/host/combat_effect_queue.{h,cc}`, `engine/appc/effect_queue.py`): one ordered queue for the §4.2 kinds from kernels (mirror handles) and Python (object references); the tick scope around `sim.weapons` + `sim.combat`; delivery with decision 13; a session-level deferral for native sessions outside the scope (ruling F3); entries naming a row dropped for an unencodable value are rebound to the object first, so they are still delivered.
- **Kernels:** K0 returns only `RUN_PYTHON`/`DONE`; K1 only tube/pulse/dumb `FIRE`, `ASK`, `RUN_PYTHON`, handed-back `WALK_START`, `DONE` (plus documented fallback stops: `BANK_STOP` for a gone row, `STOP_SYSTEM` when the walk check hands the stop back); K2 only `CONTACT` (damage pulse), `ASK`, `RUN_PYTHON`, `DONE` (plus documented fallback stops). One shared stop encoding (`stop_firing.h`) for all three.

### Rulings worth keeping

- **E1-E5** as §5.
- **F1.** `WATCH` covers weapon charge watchers only; shield, condition and battery watchers fire inside the hit path (workstream D).
- **F3.** A native session that begins while nothing defers opens its own deferral and delivers at its end (nested inside a delivery). Replaces §4.1's "a Python producer acts at once" outside the scope, which broke emission order within one session and could leave a loop playing.
- **F4.** Tests that relied on a handler acting mid-walk on a queued kind were re-aimed at records that still run Python mid-walk (tube/pulse launches, ASK answers); the K1 handler differential runs with the deferral open in both arms.
- **F5.** An abandoned session keeps its entries (every entry belongs to an effect already applied); the queue's mark/truncate API was removed.
- **Override guards.** `StopFiring` joined K1's system patch list; K0 now guards `StopFiring` and `_broadcast_reload` (leaf roles) and a class patch of the watcher's `_update`; an instance patch of one watcher's `_update` is not looked for.
- **Gameplay consequence (switch on):** handlers of queued events run at the tick boundary, so Episode7's `TorpedoFired` handler's `GetRandomNumber(10)` now draws after the combat step instead of mid-step. Accepted under roadmap decision 9; decision 12 covers presentation draws only.

### Measured (perf register C-266, C-267, SIG-173)

Records handed back to Python per tick (64 ships): K0 0.087 → 0; K1 0.599 → 0.103 (launches only); K2 0.522 → 0.471 (damage pulses only). Queue: 1.1 entries per tick, none skipped or failed. Benchmark, two runs against two: `cb.phasers` 0.573 → 0.526 ms per tick; `cb.held_weapons`, `sim.weapons`, `sim.combat` within spread; `sim` 8.94 → 9.31 in that pair. A third pair with the flush profiled as `sim.effects` (C-268/C-269, SIG-174): the delivery costs **0.069 ms per tick** (with audio), against `sim.combat` 1.581 → 1.545 (work moved out of the records), so the rows this branch touches net about **+0.03 ms per tick**; `sim` 8.94 → 9.13. The game loop runs ~0.18 ms higher across the four after-runs; this branch's only code there (the AI-session deferral) accounts for ~0.03, the rest is unattributed. Goal 5 (no slowdown) is therefore met only approximately: a small measured cost of ~0.03 ms per tick, plus an unexplained game-loop rise.

### Next

- Launch-script cache (workstream F): removes K1's last mid-step Python.
- Move K1's mod-patch walk check to the step boundary (workstream I's known blocker).
- Native damage (D), with the third random generator (decision 12) and severance without a renderer.
