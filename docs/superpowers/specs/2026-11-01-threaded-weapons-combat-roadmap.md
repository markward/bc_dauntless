# Threaded Weapons and Combat — Roadmap

**Status:** active programme, agreed with Mark 2026-11-01. This is a direction document, not a spec: each workstream below gets its own spec and plan when it starts.

**Branch:** `project/combat_threading` is the project base (created at the K3+K4 tip, superseding the `perf/native-combat*` branches). Workstream branches fork from it and merge back into it. It merges to `main` once — when the native switch defaults ON and the first Python copy is retired (Mark, 2026-11-01): merging with the switch off would only add complication to `main`.

**Builds on:** the native-combat programme (`docs/superpowers/specs/2026-10-30-native-combat-step-design.md`), milestones K1-K4.

## 1. The goal

Large battles are limited by the simulation, not the renderer. At 64 ships one simulation tick costs about 10 ms. The sim runs at a fixed 60 Hz, so a frame that takes longer than 16.7 ms has to catch up with several ticks (about 3.5 a frame in the 64-ship fight). Every millisecond saved per tick is saved 3-4 times per frame.

The end state is a weapons and combat system split across two threads:

- **Python thread:** AI decisions, mission scripts, event handlers, and any weapon launch script that cannot be cached. SDK Python stays single-threaded, as BC requires.
- **Native combat thread (C++):** everything continuous — charging and reloading, fire control, aiming, phaser beams, torpedo flight and guidance, hit tests, damage eligibility, damage application.
- **Tick boundary handoff:** orders go down to the native side; an ordered event list and a state snapshot come up to Python.

The two halves run **pipelined, one tick apart**: AI reviews last tick's combat results and decides, while combat executes the decisions AI made last tick.

## 2. Where we are (2026-11-01)

| Milestone | Branch | What moved to C++ | State |
|---|---|---|---|
| 1a | `perf/native-combat` | sensor `can_detect` | live-verified |
| 1b (K1) | `perf/native-combat-1b` | fire control (held weapons) | live-verified (~30 fps, 33 ships) |
| K2 | `perf/native-combat-k2` | phaser beams | live-verified 2026-11-01 |
| K3+K4 | `perf/native-combat-k3` | torpedo flight + damage eligibility | live-verified 2026-11-01; full gate green |

All are behind `DAUNTLESS_NATIVE_COMBAT=1`, default OFF, unmerged.

Measured, 64-ship fight, switch on, milliseconds per game tick, average of two runs each (perf register SIG-158, SIG-162, SIG-164):

| Row | 1b | K2 | K3+K4 |
|---|---|---|---|
| fire control (`cb.held_weapons`) | 1.30 | 1.32 | 1.40 |
| phasers | 1.77 | 0.74 | 0.77 |
| torpedoes | 0.92 | 0.83 | 0.17 |
| eligibility | 0.29 | 0.28 | 0.04 |
| **combat step** (`sim.combat`) | **4.47** | **3.33** | **2.45** |
| AI (`gl.ai`) | 3.25 | 3.27 | 3.23 |
| **whole sim** | **11.86** | **10.57** | **9.99** |

Combat is down 45%, but the programme's 1 ms target is not met. Fire control is now the largest combat cost, and its internal split has never been measured. AI is now larger than combat.

## 3. Decisions taken

1. **One copy of each rule, in C++.** Today every migrated rule exists twice: the Python version (the reference) and the C++ copy. That is transition scaffolding for a safe rollout and for the bit-exact differential tests, not the end state. Once a kernel is live-verified and gate-green, its Python decision code, its override/patch guards and its whole-step Python fallback are removed.
2. **Stricter mod categories.** Initial categories: **ships, bridges, weapon packs, missions, campaigns** — "that's it for now". Anything else is a feature request or a pull request. Runtime Python patching of engine internals is not a supported mod surface. (Original BC mods could not patch these rules anyway: they lived in the compiled `Appc.dll`.) Where a category needs behaviour beyond data, it gets a deliberate, documented extension point.
3. **SDK Python stays on one thread.** CPython 3.11's interpreter lock lets only one thread run Python at a time. Free-threaded Python (3.13+) and sub-interpreters were considered and rejected for this: the engine and the SDK scripts share mutable state everywhere and assume one thread; sub-interpreters cannot share the game objects. Parallel speed comes from C++ that runs without the lock.
4. **A one-tick pipeline between AI and combat is acceptable.** AI already does not decide every tick (AI tree may sleep up to 4 ticks ≈ 66 ms; target list 2 Hz; shields charge every 0.5 s), so one more 17 ms tick is inside existing latency. Done with double-buffered state and orders it is deterministic. It is a deliberate departure from BC's same-tick order and needs its own spec and a live feel check.
5. **Weapon launch scripts are cached.** A weapon pack's projectile script runs once per launch today and mostly sets fixed values (damage, speed, guidance time, turn rate, model, glow, sounds). Run it once per torpedo type, record the values, launch from the record in C++. A script that is not pure (randomness, reads the launcher) keeps running per launch on the Python side, or becomes a feature request.
6. **Events are queued and delivered in order at the tick boundary.** The combat thread records what happened; Python delivers it to handlers, then runs AI. **Event order is part of the game rules** (see §5.2).
7. **Blanket cutscene rule: no player damage during cutscenes** (radiation and weapons), set by `StartCutscene`, cleared by `EndCutscene`, read by the native damage code as a flag; then test every mission. BC solved this with per-mission one-offs. Separate small piece of work (§4, H).
8. **Flags beat gating handlers.** BC's `SetInvincible` / `SetHurtable` are plain flags the native side can read with no Python; prefer that shape wherever a mission marks something special.

## 4. Workstreams, roughly in order

- **A. Finish K1-K4.** Done 2026-11-01: K3+K4 live-verified, full gate green (with the new engine-class guard) on `b097d9948`.
- **B. Measure before moving more.**
  - Per-part timers inside fire control: the hand-off, Python answers to C++ questions, ships done wholly in Python, applying results, actual firing (projectile creation, events, sounds).
  - A breakdown of the ~4 ms per tick outside combat and AI (motion, subsystems, game loop).
- **C. Close the routine fallbacks in C++.** Ships with moving parts (posed ships/targets — today the largest fallback), ships before they acquire a target, a torpedo whose target record was dropped (per-torpedo instead of whole-step), targets outside the step scan. Until these are closed, the Python copies still do real work every tick and cannot be retired.
- **D. Move damage application to C++** (`apply_hit`: shield absorption, hull, subsystem damage), reading the invincible/hurtable/cutscene flags.
- **E. Retire the Python copies, one kernel at a time, fire control first.** Switch default ON, a play period with it on, delete the Python decision code, replace Python-vs-native differentials with recorded golden fights. First check whether anything must still run without the native module (some test setups).
- **F. Launch-script cache** (decision 5).
- **G. Event queue design.** Inventory every weapon/combat event: which only *report*, which *gate* an outcome (§5.1), which handlers read state that may already have changed; fix ordering rules (§5.2).
- **H. Cutscene damage rule** (decision 7), with the headless 26-mission campaign sweep plus Mark's playthrough of cutscene-heavy missions.
- **I. Native combat off the lock.** A kernel with no remaining Python questions becomes data-in/data-out and can release the lock. Then split per-ship work across cores with a fixed-order merge (care: sensor memo/latch, random numbers).
- **J. Pipelined AI ↔ combat** (decision 4): snapshot for AI, outbox for orders, event list up.
- **K. Render/sim overlap — investigate.** Possibly the biggest single lever: draw the last finished tick while the sim runs the next. The renderer already draws from snapshotted, smoothed transforms; unknown: how much per-frame draw setup Python builds, and where the GL context lives (macOS window/GL threading rules).
- **L. AI to C++ — Mark's plan, to be discussed.** AI is partly SDK Python in BC (AI trees, conditions, fire scripts), so the line between engine and SDK has to be drawn carefully here.

## 5. Exceptions we must design for

### 5.1 Events that decide, not just report

In BC the default effect is the last handler in an event's chain; a mission handler that does not pass the event on cancels the effect. Known uses:

- `ET_ENVIRONMENT_DAMAGE` — E3M2 `CoreDamage` swallows radiation damage to the player in the stellar-core cutscene; E3M2's Kessok probe ignores it permanently (`MissionLib.IgnoreEvent`).
- `ET_OBJECT_CONVERTED_TO_HULK` — ignored for the Kessoks in E4M5 and six freighters in E7M1.
- `ET_SHIELDS_SET_STATE` — ignored once in E8M2.

The effect cannot apply until the handlers have run: either combat pauses for that event, or the effect moves to the boundary with it, or (preferred) the special case becomes a flag the native side reads.

### 5.2 Event order is a rule

E1M2: asteroids drift toward Haven. The mission removes each asteroid from its list once — as the player's kill (`ET_OBJECT_EXPLODING`) or as a Haven hit (`ET_PLANET_COLLISION`). A lethal impact produces both. If the explosion is delivered first, a Haven hit is scored as a player kill and the mission-lost beat never fires. The collision events (`ET_PLANET_COLLISION`, `ET_OBJECT_COLLISION`, `ET_CLOAKED_COLLISION`) are therefore posted before the impact damage (`docs/reference/engine/event-emitter-gaps.md` #13; the order is inferred from BC, not reverse-engineered). The queue must preserve this order exactly, and handlers will run after the damage has applied.

## 6. Expected payoffs (bounds, not promises)

- K3+K4 took combat from 3.33 to 2.45 ms per tick. Removing the rest of combat's Python costs is bounded by what fire control's split (B) shows.
- Overlapping two jobs saves at most the **smaller** of the two. AI ↔ combat today: at most ~2.5 ms of a ~10 ms tick. The smaller combat gets, the less this overlap alone buys.
- Getting frames under 16.7 ms pulls ticks per frame toward 1, which shrinks every per-frame cost.
- AI (≈3.2 ms per tick) is the largest untouched piece.

## 7. Open questions

- Fire control's internal cost split (B).
- What the ~4 ms "everything else" per tick is made of (B).
- Which events gate outcomes, and which handlers read changed state (G).
- What still needs to run without the native module (E).
- Host loop / GL threading model for render overlap (K).
- Where the engine/SDK line falls for AI (L).
- Cutscene rule: player ship only, or also the ships a scene is about (H). Starting point: player ship only.

## 8. Parked items carried from K3+K4

From the K3+K4 ledger, for Mark: share K2's trace-context helper with K3; a torpedo instance-attribute patch guard; per-torpedo handling of a dropped target referent; `TorpedoField` switch-OFF cost (~13 µs per tick at 100 torpedoes, derived); mission swap never clears the active torpedo list; end-point-only hit test can tunnel; cloak lead-acceleration spike; hit sounds timed on the wall clock; the K1 audit gap; the `ConditionIncomingTorps` registry leak; K1's headless differential ships have radius 0 and never hit.
