# Native combat: event inventory and the presentation queue — design

**Status:** built 2026-11-02, outcome in §10; live-verified by Mark 2026-11-02 ("no issues") and merged into `project/combat_threading` (`040a588c2`). Mark asked for steps 1 and 2 of the boundary-queue work ("spec it, plan it, implement it subagent driven"); he live-tests before any merge. Campaign special cases (roadmap §5.1, §5.2) are discussed with Mark after this phase, not decided here.
**Branch:** `ws/combat-effect-queue`, off `project/combat_threading` (`245ddc618`), in worktree `.claude/worktrees/native-combat-damage`. Merges into `project/combat_threading` after Mark's live check. No main gate: focused tests, differentials, two benchmark runs.
**Roadmap:** `2026-11-01-threaded-weapons-combat-roadmap.md` workstream G (event queue), decision 6 (events queued and delivered in order at the tick boundary). Input maps: `docs/reference/engine/native-combat/remaining-fallbacks-map.md` §4 (RFM), `damage-map.md`, `k2-beams-map.md`.

## 1. Why this phase

The end state runs combat kernels off the Python lock (workstream I) and hands their results to Python at the tick boundary. Two things stand in the way, and this phase takes the first step on each.

1. **Nobody has listed what the combat path emits.** Every `ET_*` event is posted synchronously today (`TGEventManager.AddEvent`, handlers run at once, inside the K1/K2 walks). Before any event can move to a boundary queue we need the full list: which events only report, which gate an outcome (§5.1 of the roadmap), which are order-sensitive (§5.2, E1M2), and what each handler reads. That is step 1.
2. **The K2 walk still returns to Python every tick for pure presentation.** A resting beam contact (a beam on its target between damage pulses) draws a shield splash or a hull flash and does nothing else: no damage, no event, no random numbers (`k2_beams.h`, RESTING CONTACTS). Since round trips its Python rides the next record, but it still runs mid-walk, between kernel steps. That is step 2: the first boundary queue, for effects whose order does not matter to the game.

Measured 2026-11-02 (64-ship `combat_stress`, switch on, Debug, headless, 8,999 ticks, one instrumented run):

| Cost | Per tick | µs each | ms per tick |
|---|---|---|---|
| K2 step, whole (`k2_phasers`) | 1.00 | 718 | 0.718 |
| Resting contacts (`_k2_run_contact`, flush ≤ 0) | 18.2 | 9.27 | **0.169** |
| … of which `hit_feedback.beam_contact` | 18.2 | 6.50 | 0.118 |
| Damage pulses (`_k2_run_contact`, flush > 0) | 0.45 | 130 | 0.058 |
| `_k2_deliver` (queued contacts + write segments) | 1.42 | 138 | 0.197 |

**99.7% of resting contacts are on a shielded target** (163,064 of 163,563): their whole presentation is one `host_io.shield_hit`. The hull path (flash and sparks through `hit_vfx.spawn`) is 0.3%.

So the queue can present almost every resting contact in C++ at the end of the step, from data the kernel already holds (the target's instance id, the view offset, the impact point, the bubble entry, the shields answer). The rare hull contact goes to Python in one batch at the same point.

## 2. Goals, non-goals

**Goals**
1. **Step 1, inventory:** `docs/reference/engine/native-combat/event-inventory.md` lists every `ET_*` event and every presentation effect the per-tick combat path produces (§4.1). Each is classified REPORT / GATE / ORDER-SENSITIVE, with its stock SDK consumers and what they read. The doc ends in the ordering rules a boundary queue must keep.
2. **Step 1, order pins:** a headless test pins the E1M2 rule: a lethal asteroid impact on Haven counts as a Haven hit, not a player kill. Add the same kind of test for any other ordering rule the inventory finds that no test pins (§4.2), at most three in this phase. The rest go on the inventory's list for step 3.
3. **Step 2, presentation queue:** K2 stops handing resting contacts back on records. It appends them to a native presentation queue, in walk order, with every value a Python effect could change resolved at contact time (§4.3).
4. **Step 2, boundary drain:** after the K2 session's `DONE`, one drain presents the queue in order: shielded contacts natively (the shield splash, in C++), everything else in one Python batch through the existing `hit_feedback.beam_contact` (§4.4).
5. Measured: K2 step −0.12 ms per tick or better (two benchmark runs against `245ddc618`).
6. **Unchanged:** game state bit-exact with the Python reference, switch on (writes, damage, events, deaths, in order); behaviour byte-identical, switch off.

**Non-goals**
- Queueing any `ET_*` event, sound, damage or projectile spawn. That is step 3, and it waits for the inventory and for Mark's decisions on the campaign special cases.
- Moving the hull flash (`hit_vfx`) native. It is 0.3% of contacts; its registry is Python and feeds the render push.
- Releasing the lock (workstream I) or changing K1/K3 presentation (they hand back none mid-walk that is presentation only, RFM §4).
- Changing the Python reference path. It still presents inline.

## 3. Constraints (programme-wide)

- Switch `DAUNTLESS_NATIVE_COMBAT=1`, default OFF; byte-identical off. The lock is held throughout.
- Ruling P1 holds for game state: no Python runs on state the kernel has moved past without the log applied. This phase moves only presentation past later Python.
- Focused tests only; never whole suites, never the gate. Banned git commands as in CLAUDE.md. Never launch the game; the controller runs the headless benchmark.

## 4. Design

### 4.1 The inventory document (step 1)

`event-inventory.md` is a reference map in the style of the other native-combat maps: every claim cites `file:line`, and anything not read off the code is marked **inferred**. Contents:

1. **Events:** every `ET_*` posted from the per-tick combat path. The path is `host_loop._advance_combat_step` (eligibility, K3 and torpedo hits, VFX ageing, deaths, subsystem cascade, held weapons/K1, phasers/K2, tractors), the weapons walk (K0), collisions and environment (radiation) damage. For each event: emitting function, source and destination, trigger, whether it is posted before or after the state change it reports, frequency class.
2. **Consumers:** each event's stock SDK handlers (missions by episode, `Conditions/`, AI, Bridge UI, `MissionLib`), and the classification REPORT / GATE / ORDER-SENSITIVE, with how our `events.py` runs the default effect after the handler chain.
3. **What handlers read:** for each consumer that reads game state, what it reads, and whether that could change between emission and a delivery moved to the end of the tick.
4. **Presentation effects:** sounds, hit VFX, shield splashes, camera shake, particles, beam visuals, lights. For each: emitting function, game state it reads, whether it draws from a random stream shared with game logic, and whether it runs inside a kernel walk today.
5. **Ordering rules for step 3**, including roadmap §5.2 (collision event before impact damage before `ET_OBJECT_EXPLODING`) and any handler that changes state the rest of the tick reads (e.g. a `ET_WEAPON_FIRED` handler that calls `StopFiring`).
6. **Tests that pin order today**, and the gaps.

The controller commissions a research draft (a read-only agent, 2026-11-02); Task 1's implementer checks it against the code, corrects it, and commits it.

### 4.2 Order pins (step 1)

The E1M2 test runs the real mission scripts headless (as `tests/integration/test_e1m2_rocks.py` does). It drives an asteroid into Haven with enough closing speed that the impact damage kills it, in one tick. It asserts that the mission scores a Haven hit: the rock leaves the mission's list through the collision handler, and the player-kill path did not take it. The test pins today's synchronous order, so step 3 cannot change it silently. If the inventory finds the scenario already pinned, Task 1 says so and adds no duplicate.

### 4.3 The presentation queue (kernel side)

- A per-session `std::vector<K2Rest>` in the K2 kernel (or a small `PresentQueue` type in the combat library, reused by later kernels). It is cleared at `begin`, at `end` and at `abandon`, so an abandoned step presents nothing it queued. Records lose their `contacts` vector and the `(…, queued, writes)` tail becomes `(…, writes)`; the `at` bookkeeping goes.
- An entry is today's `K2Contact` plus what Python would otherwise read later:
  - `level`: the firing system's `_power_level`, read from the mirror at contact time (it indexes `PHASER_INTENSITY_SCALE`; today `_k2_run_contact` reads `GetPowerLevel()` when the contact runs).
  - `shields`: the loop's own answer, **always carried**, including when an ASK supplied it. Today `None` is sent for an ASK answer so `beam_contact` re-evaluates; deferred, that re-evaluation would read shields after later pulses. When the loop never evaluated shields (no aim direction), the kernel evaluates `shields_block` natively for the entry. If that would need an ASK, the entry's shields stay unknown and Python evaluates at the drain (ruling Q3).
  - `iid`: the target's instance id from the kernel's instance table at contact time, or none.
  - `view_offset`: the offset of the target's set from the kernel's view-offset table at contact time, or none.
- The kernel never returns to Python for a resting contact. Counter `k2_batched_contacts` keeps its name (ten readers) and now counts entries queued for the drain; new counters `k2_present_native` and `k2_present_python` count how the drain presented them.

### 4.4 The drain (boundary side)

One binding call after `DONE` and before `combat_k2_end`, from `run_k2`:

- An entry is **presented natively** when `shields` is true and `iid` and `view_offset` are both known. That is exactly `beam_contact`'s shield branch: `anchor = bubble if bubble else impact point`, the view-shifted anchor (double addition, as `hit_feedback._mesh_xyz`), minus the instance's double translation (as `host_io._instance_relative`), cast to float, through the same body conversion and `ShieldPass` push the `shield_hit` binding does. Arguments: `rgba (0,0,0,0)`, `intensity = shield_impact_intensity("phaser")` (today `SHIELD_IMPACT_INTENSITY`, 0.325), `radius = weapon_splash_radius(bank, None)` (the bank's `GetDamageRadiusFactor()` when > 0, else `PHASER_DEFAULT_DAMAGE_RADIUS`). The intensity and the default radius are sent from Python once per session, never copied into C++ as literals. The bank's factor is read at the drain by calling the bank's own `GetDamageRadiusFactor` through the C API (§5, Q2): the drain is at the boundary, where Python calls are allowed, and one attribute call per entry is cheap next to the 9 µs it replaces. Headless (no shield pass) or a stale instance drops it, as the binding does.
- **Every other entry goes to Python**, in queue order, as one list returned by the drain: `_k2_run_contact` with the carried `level` and `shields` (unknown → `beam_contact` evaluates its own).
- Native and Python presentations interleave in queue order only within each group: native entries first, then the Python batch (§5, Q1).
- A **capture hook** for tests: `combat_present_capture(list | None)`. While set, every natively presented entry is also appended as a tuple: the entry's identity (bank, target handles), the instance id, the view-shifted point (what a `host_io.shield_hit` spy would see), the instance-relative point (what the binding converts), rgba, intensity and radius. Off in production; it costs one null check per drain.
- The drain is inside `cb.phasers`, so the profiler's scope still covers it.

## 5. Rulings

- **Q1. Presentation has no order inside a tick.** Shield splashes and hull flashes from the same tick are drawn together. The hit-VFX pass blends additively (`glBlendFunc(GL_SRC_ALPHA, GL_ONE)`, order-independent), and shield hits go to per-ship state that the renderer ages by time. Arrival order does decide two things: which slot a new splash reuses on a busy bubble (the dimmest), and which ring texture it draws from the renderer's own generator (`shield_state.cc` `push_hit`). Both are renderer-private and visual only. So moving a resting contact's presentation after later pulses' presentation changes nothing a player can see. The differentials compare presentation per tick as a **multiset** of exact values (`.hex()`), and game state in exact order as before. *If wrong:* a flash drawn in a different order within one frame, invisible in practice.
- **Q2. The drain reads only static data and render state.** `GetMaxDamage`, `GetMaxDamageDistance`, `GetDamageRadiusFactor` (hardpoint properties) and the instance transform are read at the drain. Python effects between contact and drain (pulses, stops, whole-ship Python) do not change them in normal play. Anything they can change (power level, shields) rides the entry. *If wrong:* a mission script that changes a phaser's hardpoint data mid-tick gives one tick of flashes sized by the new value.
- **Q3. Unknown shields evaluate at the drain.** Only when the beam has no aim direction (emitter on the target) and the native evaluation needs an ASK. *If wrong:* one tick's flash on the hull instead of the bubble, or the reverse, when a pulse in the same step dropped the shields.
- **Q4. A dying target still flashes.** A later pulse in the same step may kill the target before the drain. Python's order presented the contact before the death, so the flash shows either way, in the same frame. The drain does not check `IsDead`.

## 6. Testing

- **C++ (`native/tests/combat/`):** K2 queues resting contacts in walk order with `level`, `shields` (including ASK-answered and no-aim cases), `iid` and `view_offset`. Records carry no contacts. The queue is cleared on begin, end and abandon.
- **Binding/Python unit (`tests/unit/test_native_k2_dispatch.py` and a new `test_native_present_queue.py`):** the drain's split (native vs Python); the Python batch runs `_k2_run_contact` with carried values; an exception in one Python presentation still presents the rest before re-raising; the capture hook's tuples equal what `host_io.shield_hit` would have pushed for the same contact (bit-exact).
- **Differentials (`tests/host/test_native_k2_differential.py`, `tests/helpers/k3_fight.py`'s `spy_presentation`, the K1 and K3 differentials that use it):** presentation becomes a per-tick multiset. The native arm's natively presented splashes come from the capture hook and compare against the reference arm's `shield_hit` calls (the reference's `beam_contact` entries for shielded contacts drop out of the comparison, their `shield_hit` stays). Game state and events compare in exact order, unchanged. Every existing branch tally still has to fire.
- **Mutation checks** (reviewer, backup-and-copy): drop an entry; swap `level` for a later read; present a shielded entry with a stale view offset. Each must fail a test.
- **Step 1:** the E1M2 order test (§4.2), run against the real mission script.

## 7. Measurement

Controller, after the last task: two runs of the headless 64-ship benchmark (`bench_fight.sh`, `compare_native2.py`, per tick) against the `245ddc618` baseline (`ms6-weaponstate-*` logs). Report `cb.phasers`, `sim.combat`, `sim`. Perf register: one change (C-264) and its signals.

## 8. Open items for Mark (after this phase)

- The campaign special cases (roadmap §5.1, §5.2, and anything new the inventory turns up), before step 3 queues any event.
- Whether hull-flash presentation (`hit_vfx`) should move native later (only worth it if the inventory or a profile finds more Python presentation per tick).

## 10. Outcome

Built 2026-11-02 on `ws/combat-effect-queue`; awaiting Mark's live check. Commits: `0d0f6db13`, `fc1379366` (inventory, order pin), `b4664cc9e`, `e4d675a2b` (queue, Python drain), `005d01d45`, `331e96a5d` (native shield splash).

### What shipped

- **Inventory** (`docs/reference/engine/native-combat/event-inventory.md`): 1 GATE (`ET_ENVIRONMENT_DAMAGE`), 6 ORDER-SENSITIVE, 17 REPORT, 3 with no reachable consumer; `ET_OBJECT_CONVERTED_TO_HULK` and `ET_SHIELDS_SET_STATE` are never posted. §5 lists the ordering rules step 3 must keep, §6 the tests that pin them, §7 nine findings outside the ordering rules (among them: E3M1's invincible player takes no collision damage; `SetConditionPercentage` is a stub on every subsystem, so several scripted kills are no-ops; part severance runs only with a renderer; collisions run once per frame after all sim ticks, so "the tick boundary" is not one point; the `WeaponFired` handlers of four missions are inert; presentation draws from both gameplay random streams).
- **Order pins:** the E1M2 lethal-impact rule was already pinned (`test_e1m2_rocks.py::test_moving_asteroid_hitting_haven_counts`, mutation-proved). New: `tests/unit/test_killing_hit_event_order.py` pins today's order on a killing hit (`ET_OBJECT_EXPLODING` before that hit's `ET_WEAPON_HIT`, the firer as killer).
- **Queue:** `K2Rest` (contact, `level`, `iid`, `view_offset`, `view_known`), `take_rests()`, `combat_k2_drain()`. Records end `(..., writes)`; the pending-segment path and `combat_apply_writes` are gone.
- **Drain:** shielded entries with a known instance and view offset are presented in C++ through the helper the `shield_hit` binding now shares; the rest go to `_k2_present_batch`. Capture hook `combat_present_capture` for tests. Counters `k2_present_native`, `k2_present_python`, `k2_present_gone`. In the K2 host differential: native 3,258 / Python 1,230 (one tick per frame), 4,392 / 99 (four), none gone.

### Rulings worth keeping

- **Q1-Q4** as §5.
- **Q5. Presentation functions are not watched.** `hit_feedback.beam_contact`, `hit_feedback._mesh_xyz`, `host_io.shield_hit` and `combat.weapon_splash_radius` are not in K2's stand-in guard: presentation internals are not a mod surface (roadmap decision 2), and the differentials spy them (they compare through the capture hook). A patch of them is not obeyed for a natively drawn splash. `frames.view_offset`/`shifted`/`containing_set` stay watched.
- **`GetPowerLevel` joins K2's guard.** Carrying the mirror's `_power_level` made K2 stand in for it; an override sends the ship to Python.
- **Freed or unregistered objects** at the drain are skipped and counted (`k2_present_gone`), not raised: presentation only.
- **A raising `GetDamageRadiusFactor`** sends the entry to the Python batch (the call runs again there); `KeyboardInterrupt`/`SystemExit` propagate.
- Parked: a `bad_alloc` while `next()` backs up the session loses that step's queued rests (allocation failure only).

### Measured (perf register C-264, C-265, SIG-172)

Before the build, instrumented: resting contacts 18.2 per tick at 9.27 µs, 0.169 ms of K2's 0.718; 99.7% shielded. After, two runs against two (64 ships, switch on, Debug), per tick: `cb.phasers` **0.733 → 0.573** (−22%), `sim.combat` **1.761 → 1.581** (−10%), `sim` 9.12 → 8.94. Goal 5 (−0.12 ms) met. Fire control (0.69) is now the largest combat cost.

### Next

- Mark: the campaign special cases (roadmap §5.1-5.2, inventory §5 and §7) before step 3 queues any event.
- The inventory's step-3 preconditions: one sequence across sources; collisions are per frame, not per tick; the E1M2 test must call the queue's flush once one exists.
