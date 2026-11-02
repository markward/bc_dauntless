# Presentation random-number generator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cosmetic random draws come from their own generator, so visuals, sounds and bridge animations never shift gameplay rolls.

**Architecture:** `engine/appc/presentation_rng.py` holds generator P and a thread-local scope; inside the scope `GetRandomNumber` and `GetRandomPointOnModel` answer from P. Engine presentation code draws P directly; engine calls into SDK presentation scripts run in the scope; mixed death-cascade blasts are reordered.

**Tech Stack:** Python 3.11, pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-presentation-rng-design.md`. Map: `docs/reference/engine/native-combat/rng-map.md` (RM).

**Shape (Mark 2026-11-02, "lean, no corners cut"):** one implementation task whose acceptance test is the falsifier fight, written FIRST, so it fails today and passes only when every presentation site is routed. One independent review of the whole diff on the most capable model. The controller runs the differentials and writes the docs.

## Global Constraints

- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/native-combat-k3`, branch `ws/combat-presentation-rng`.
- **Never launch the game binary and never benchmark** (Mark's pause). Focused pytest only (the files named here plus each touched module's existing test files); never whole suites, never `scripts/check_tests.sh`. NEVER `uv run --active`.
- Banned git: `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage explicit paths; `git commit -F <file>`; end messages with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Never write lifted/decompiled mod text; never commit mod-derived values in tests.
- No known-failing tests: never commit a red or xfail test.
- Mutation proofs: `cp` backup, mutate, run, `cp` restore, `diff` clean. No subagents.

## Review Focus

1. A presentation call that triggers gameplay (an SDK presentation script that damages, or a death script that calls a gameplay API): the debug assert fires under tests; gameplay is never drawn from P silently.
2. Nested scopes and exceptions inside a scope: the depth always returns to 0.
3. The death cascade: same damage outcome per blast whatever the presentation draws; a damaging blast's visual coincides with its damage point.
4. Mission swap: P, the hit-sound throttle and the decal/smoke throttles all reset; a reused `id(ship)` is not silenced.
5. Every `seed_every_rng` copy resets P, so differential arms stay comparable.

---

### Task 1: Presentation generator, routing, and the falsifier

**Files:**
- Create: `engine/appc/presentation_rng.py`; tests `tests/unit/test_presentation_rng.py`, `tests/unit/test_presentation_source_guard.py`, `tests/integration/test_presentation_rng_falsifier.py`.
- Modify (RM §7.1-7.4, §6, §5): `App.py` (root shim, `_SystemWrapper.GetRandomNumber` ~998-1001), `engine/appc/objects.py` (`GetRandomPointOnModel` ~362-404 → `_random_point_on_model(rng)`), `engine/host_loop.py` (mission-swap resets ~7898-7906), `tests/conftest.py` (autouse reset), `engine/appc/damage_preview.py` (`_apply_seed`), every `seed_every_rng` copy (RM §5), `engine/appc/hit_feedback.py` (`_play_audio` pickers in scope; `_audio_should_play` on game time via `damage_decals.current_game_time()`; `reset_audio_throttle` at mission swap), `engine/appc/hull_hit_smoke.py` (H1, H2 direct; `_emit_smoke` in scope), `engine/appc/particles.py` (H4), `engine/appc/viewscreen_static.py` (X4), `engine/rocks/minor_contact.py` (X5), `engine/appc/death_cascade.py` (D3/D4/D5 reorder; D6; `_fire_final`, `_debris_explosion`, `_death_sound` in scope), `engine/bridge_idle_gestures.py` (`build_sequence_clips` in scope), `engine/appc/crew_speech.py` (`_rand5`), NanoFX compat draws (`engine/compat/fx_api/`), `engine/appc/ship_death.py` and `engine/rocks/death.py` (`RunDeathScript` in scope, ruling R1), `engine/appc/combat.py` (debug assert in `apply_hit`, active under tests and `--developer`).

**Interfaces (produced, used by D later):** `presentation_rng.rand(n) -> int` (exactly `GetRandomNumber` semantics: `n <= 0 → 0`, else `randrange(int(n))`), `random()`, `uniform(a, b)`, `gauss(mu, sigma)`, `randrange(...)`, `reset(seed=PRESENTATION_SEED)`, `scope()` (context manager, thread-local depth, exception-safe), `in_scope() -> bool`.

- [ ] **Step 1: Minimal generator.** `presentation_rng.py` with the interface above and its unit tests (RM §7.5 test 1; nesting; exception inside a scope; thread-locality; `GetRandomNumber` in/out of scope). RED → GREEN.
- [ ] **Step 2: Falsifier (RED).** `test_presentation_rng_falsifier.py` per RM §7.5 test 4: the headless `combat_stress` fight twice with the same `seed_every_rng`; the second arm injects cosmetic noise every tick (`_audio_should_play` forced True, `presentation_rng.rand(1000)` N times, `build_sequence_clips` for a fake officer); assert identical per-tick hull/shield/subsystem conditions, event log, deaths, final S1/S2 state. Run it: it must FAIL on today's routing. Record the failure in the report. Do not commit it red.
- [ ] **Step 3: Remaining unit tests (RED).** RM §7.5 tests 2, 3, 5, 6, 7; `GetRandomPointOnModel` in/out of scope; the debug assert fires when a scope wraps `apply_hit` (Review Focus 1); mission-swap resets incl. a reused `id(ship)` (Review Focus 4); Damage Preview's seed reproducible.
- [ ] **Step 4: Implement** RM §7.2-7.4 and §6 and the §5 resets. The blast reorder: damage roll first on S1; only a damaging blast draws its point from S2 and reuses it for the visual; a non-damaging blast draws its point from P; blast size from P (R2). Update any existing test that pinned an exact S1/S2 sequence through a moved draw, keeping its purpose. If the falsifier still fails after the RM sites are routed, find the site the map missed (it is in scope of this task) and add it to the source guard's module list where it is a presentation module.
- [ ] **Step 5: GREEN.** Run the three new test files plus every touched module's existing test files → PASS.
- [ ] **Step 6: Mutation proofs.** (a) the hit-sound picker draws S1 again → the falsifier fails; (b) the blast draws its point before the damage roll → test 3 fails; (c) `GetRandomNumber` ignores the scope → test 1 fails. Each restored by `cp`, `diff` clean.
- [ ] **Step 7: Commit** (explicit paths).

### Task 2: Differentials and documentation (controller, inline)

- [ ] Run `tests/integration/test_native_k0_differential.py`, `test_native_k1_differential.py`, `test_native_k3_differential.py`, `test_native_combat_step_differential.py`, `tests/host/test_native_k2_differential.py`. Their coverage asserts depend on how the fight plays out; adjust a threshold only if the branch still fires, never weaken a check to zero.
- [ ] Docs: spec §10; roadmap decision 12 (done) and §2; event-inventory R8 and F9, damage-map H9-H10 (corrected, RM §0); CLAUDE.md only if a row becomes wrong. Commit. No benchmark.
- [ ] One whole-branch review (most capable model); one fix round if needed.
