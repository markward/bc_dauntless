# Presentation random-number generator — design

**Status:** built 2026-11-02 (§10); not live-verified. Roadmap decision 12 ("presentation gets its own random-number generator", Mark 2026-11-02), the one prerequisite of native damage (D) on the threading path (Mark: the trimmed path is this phase → D → off the lock → the AI ↔ combat pipeline). Mark ruled 2026-11-02 that mission death scripts run in the presentation scope.
**Branch:** `ws/combat-presentation-rng`, off `project/combat_threading` (`c286fbac6`), in worktree `.claude/worktrees/native-combat-k3`. No main gate; focused tests. **No benchmarking and no game runs** unless Mark says (he asked for a pause on 2026-11-02); this phase's cost is negligible by construction.
**Input map:** `docs/reference/engine/native-combat/rng-map.md` (RM §n).

## 1. Why

Two random streams serve everything today: S1, `App.g_kSystemWrapper.GetRandomNumber` (one `random.Random` in the root `App.py` shim), and S2, Python's process-global `random` (the AI's `random.choice` draws it too). Cosmetic code draws from both: 18 presentation sites against 6 gameplay sites plus every SDK AI and mission draw, with 6 mixed (RM §1). So any change in a cosmetic roll — a hit sound played or throttled, a smoke puff, a bridge animation, a frame-rate-dependent idle gesture — shifts every later gameplay roll. The map also found that the player's view changes gameplay: bridge crew animations draw S1 on every player hit and on frame time (RM §0.3), and switching view re-arms the hit-sound throttle, which then draws an extra S1 number (RM §0.2). And the hit-sound throttle is timed on the wall clock (RM §6), so whether a sound roll happens depends on real time.

Native damage (D) moves the hit chain into C++, where cosmetic and gameplay draws are interleaved today. Separating them first means D can move the gameplay draws without reordering anything, and the presentation draws can go wherever presentation goes.

## 2. Goals, non-goals

**Goals**
1. A presentation generator P (`engine/appc/presentation_rng.py`, RM §7.1): fixed seed, reseeded at every mission load, at the test reset, and by Damage Preview's seed.
2. A thread-local presentation scope (RM §7.2): inside it, `GetRandomNumber` and `GetRandomPointOnModel` answer from P. Every engine call into an SDK script that only presents runs inside it (the RM §7.2 list, including `RunDeathScript`, ruled by Mark).
3. Engine presentation code draws P directly (RM §7.3).
4. Mixed death-cascade blasts (RM §7.4): the damage roll is drawn first on S1; only a damaging blast draws its point from S2 (gameplay) and reuses it for the visual; a non-damaging blast draws its point from P. The blast size is presentation (P).
5. The hit-sound throttle runs on game time and resets at mission swap (RM §6).
6. Proven: a fight with cosmetic noise injected (extra sounds, extra P draws, extra bridge animations) produces exactly the same gameplay (conditions, events, deaths, final S1/S2 state) as without it (RM §7.5 test 4), and a source guard keeps presentation modules off the gameplay streams.

**Non-goals**
- SDK line picks inside gameplay handlers (RM §7.4 M2/A3) and `DynamicMusic.ProcessQueue` (X6): stay on S1; residual, documented.
- Debris spin (D12): stays on S2 (collidable bodies).
- The wall-clock budget in `visible_damage.advance` and the wall-clock speech expiry (RM §8): other timing leaks, recorded for later.
- Any change with native combat on vs off: this phase is switch-independent.

## 3. Constraints

- This is a deliberate behaviour change in both switch states (roadmap decision 12): gameplay roll sequences change once. The native-vs-Python differentials compare two arms of the same code, so they stay comparable once every `seed_every_rng` copy resets P too (RM §5).
- Focused tests only; never whole suites or the gate. Banned git commands as in CLAUDE.md. Never launch the game; never benchmark (Mark's pause).
- Never write lifted or decompiled mod text; never commit mod-derived values in tests.

## 4. Design

As RM §7.1-7.4. Two additions:
- **A debug assert** in `combat.apply_hit` that the presentation scope depth is 0 (a presentation call that triggers gameplay would otherwise draw gameplay numbers from P). Active under tests and `--developer`.
- **Scope is thread-local** (the roadmap moves Python work to its own thread later; a global flag would leak).

## 5. Rulings

- **R1 (Mark).** Mission death scripts run in the presentation scope: every stock death script draws only for debris, sounds and sparks. *If wrong:* a mod death script that draws for gameplay draws from P; documented as a mod caveat.
- **R2.** The blast size (`roll_blast_scale`, D4) is presentation, though its visible hole can break parts off an already-dying ship (live only). Consistent with Mark's rule: pick the reading that keeps gameplay independent of cosmetics. *If wrong:* breakup of a dying ship varies with presentation draws.
- **R3.** Seeding per mission, not per session: a capture of mission N looks the same whatever ran before.
- **R4.** The view-change throttle reset stays (once audio draws P it is presentation-only).

## 6. Testing

RM §7.5 tests 1-7, plus: the debug assert fires when a presentation scope wraps `apply_hit`; Damage Preview's seed reproduces captures.

## 10. Outcome

Built 2026-11-02 on `ws/combat-presentation-rng` (`4eafae6be`, `aa2419d3e`), as one task with one end review (plan `2026-11-02-presentation-rng.md`, made lean at Mark's request).

- **The falsifier did its job.** Written before any routing, the noisy fight diverged at tick 63: the AI aimed Friend-3's forward torpedo at a different point, because hit-sound picks and officer animation builders had moved its `GetRandomNumber` rolls. With every RM site routed, the fights are identical tick for tick (conditions, events, the hit log, final S1/S2 state). No site was missing from the map.
- **Mutation proofs.** Putting the hit-sound picker back on S1 makes the falsifier fail at tick 434. Drawing a blast's point before its damage roll fails the cascade test. A `GetRandomNumber` that ignores the scope fails the scope test.
- **Resets.** P and the hit-sound stamps reset in `host_loop._reset_session_scratch`, not the swap block RM §7.1 names. It runs on every load path (first load, swap, Quick Battle, in-transit mission change), so R3 holds on loads the swap block never sees.
- **Damage Preview** now seeds S2 as well as S1 and P. Damaging blast points come from S2, so its captures would differ otherwise.
- **Ruling, NanoFX spin.** `CreateRotationSeq` and `SetNanoRotation` stay on S1 (RM classed them presentation). They set a ship's angular velocity, a physics write, like debris spin (D12). The source guard exempts them by name and pins that they draw S1.
- **Residuals, as designed.** SDK line picks inside gameplay handlers (M2/A3), `DynamicMusic.ProcessQueue` (X6) and debris spin stay on S1/S2. R1's caveat stands: a mod death script that draws for gameplay draws P, and if it damages, the debug assert in `apply_hit` raises under tests and `--developer` only.
- **Differentials.** K2, K3 and the step differential passed unchanged. Two needed test-only fixes. K1's game-loop fight no longer produced a failed aim by luck, so Friend-3 now starts facing away from its foe (`fdb28869f`). K0's had been broken since launch deferral (`c286fbac6`), because its spy skipped a launch's weapon-fired event posted during queue delivery; it now logs at the posting call (`74a20a0c3`). There was no engine divergence: 72 posts in each arm, same order.
- **Cost.** None measured (benchmarks paused); the change is a few generator swaps and a thread-local depth check per scoped call.
