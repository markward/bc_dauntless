# Presentation random-number generator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cosmetic random draws come from their own generator, so visuals, sounds and bridge animations never shift gameplay rolls.

**Architecture:** `engine/appc/presentation_rng.py` holds generator P and a thread-local scope; inside the scope `GetRandomNumber` and `GetRandomPointOnModel` answer from P. Engine presentation code draws P directly; engine calls into SDK presentation scripts run in the scope; mixed death-cascade blasts are reordered.

**Tech Stack:** Python 3.11, pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-presentation-rng-design.md`. Map: `docs/reference/engine/native-combat/rng-map.md` (RM).

## Global Constraints

- Worktree `/Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/native-combat-k3`, branch `ws/combat-presentation-rng`.
- **Never launch the game binary and never benchmark** (Mark's pause). Focused pytest only (the files each task names); never whole suites, never `scripts/check_tests.sh`. NEVER `uv run --active`.
- Banned git: `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage explicit paths; `git commit -F <file>`; end messages with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Never write lifted/decompiled mod text; never commit mod-derived values in tests.
- Mutation proofs: `cp` backup, mutate, run, `cp` restore, `diff` clean. No subagents.

## Review Focus

1. A presentation call that triggers gameplay (an SDK presentation script that damages, or a death script that calls a gameplay API): the debug assert fires under tests; gameplay is never drawn from P silently.
2. Nested scopes and exceptions inside a scope: the depth always returns to 0.
3. The death cascade: same damage outcome per blast whatever the presentation draws; a damaging blast's visual coincides with its damage point.
4. Mission swap: P, the hit-sound throttle and the decal/smoke throttles all reset; a reused `id(ship)` is not silenced.
5. Every `seed_every_rng` copy resets P, so differential arms stay comparable.

---

### Task 1: The generator and the scope

**Files:** create `engine/appc/presentation_rng.py`; modify `App.py` (root shim, `_SystemWrapper.GetRandomNumber` ~998-1001), `engine/appc/objects.py` (`GetRandomPointOnModel` ~362-404 → `_random_point_on_model(rng)`), `engine/host_loop.py` (mission-swap reset ~7898-7906), `tests/conftest.py` (autouse reset), `engine/appc/damage_preview.py` (`_apply_seed`), every `seed_every_rng` copy (RM §5); test `tests/unit/test_presentation_rng.py`.

**Interfaces:** `presentation_rng.rand(n) -> int` (exactly `GetRandomNumber` semantics: `n <= 0 → 0`, else `randrange(int(n))`), `random()`, `uniform(a, b)`, `gauss(mu, sigma)`, `randrange(...)`, `reset(seed=PRESENTATION_SEED)`, `scope()` (thread-local depth, exception-safe), `in_scope() -> bool`.

- [ ] Step 1: tests (RM §7.5 test 1; scope nesting and exceptions; thread-locality; `GetRandomPointOnModel` in/out of scope; reset at mission swap; Damage Preview seed reproducible). Run → FAIL.
- [ ] Step 2: implement.
- [ ] Step 3: run `tests/unit/test_presentation_rng.py` plus the files you touched → PASS.
- [ ] Step 4: mutation: `GetRandomNumber` ignores the scope → fails. Commit.

### Task 2: Route every presentation draw, reorder the blast, game-time throttle

**Files:** `engine/appc/hit_feedback.py` (`_play_audio` pickers in scope; `_audio_should_play` on game time via `damage_decals.current_game_time()`; `reset_audio_throttle` at mission swap), `engine/appc/hull_hit_smoke.py` (H1, H2 direct; `_emit_smoke` in scope), `engine/appc/particles.py` (H4), `engine/appc/viewscreen_static.py` (X4), `engine/rocks/minor_contact.py` (X5), `engine/appc/death_cascade.py` (D3/D4/D5 reorder; D6; `_fire_final`, `_debris_explosion`, `_death_sound` in scope), `engine/bridge_idle_gestures.py` (`build_sequence_clips` in scope), `engine/appc/crew_speech.py` (`_rand5`), the NanoFX compat draws (`engine/compat/fx_api/`), `engine/appc/ship_death.py` and `engine/rocks/death.py` (`RunDeathScript` in scope, ruling R1), `engine/appc/combat.py` (debug assert); tests `tests/unit/test_presentation_rng.py` (or a second file `tests/unit/test_presentation_draws.py`), `tests/unit/test_presentation_source_guard.py`, and the existing tests of each touched module.

**Interfaces:** consumes Task 1.

- [ ] Step 1: tests: RM §7.5 tests 2, 3, 5, 6; the debug assert (Review Focus 1); mission-swap resets (Review Focus 4). Run → FAIL.
- [ ] Step 2: implement RM §7.2-7.4 and §6 (with the mission-swap reset).
- [ ] Step 3: run the new tests and each touched module's existing tests → PASS. Update any test that pinned an exact S1/S2 sequence through a moved draw, keeping its purpose.
- [ ] Step 4: mutations: one presentation site draws S1 again → the falsifier-style unit test fails; the blast draws its point before the damage roll → test 3 fails. Commit.

### Task 3: The falsifier fight and the differentials

**Files:** create `tests/integration/test_presentation_rng_falsifier.py` (RM §7.5 test 4); check `tests/integration/test_native_k1_differential.py`, `test_native_k3_differential.py`, `test_native_combat_step_differential.py`, `test_native_k0_differential.py`, `tests/host/test_native_k2_differential.py` (their coverage asserts depend on how the fight plays out; adjust thresholds only if a branch still fires, never weaken a check to zero).

- [ ] Step 1: the falsifier: the headless `combat_stress` fight twice with the same seeds; the second arm injects cosmetic noise every tick (force `_audio_should_play` True, extra `presentation_rng.rand` calls, `build_sequence_clips` for a fake officer); assert identical per-tick hull/shield/subsystem conditions, the event log, deaths and the final S1/S2 state. Prove it bites: mutate one cosmetic site (the hit-sound picker) back to S1 and show the falsifier fails; restore by `cp`, `diff` clean.
- [ ] Step 2: run the differentials; fix only what the behaviour change requires.
- [ ] Step 3: commit.

### Task 4: Documentation (controller)

- [ ] Spec §10; roadmap decision 12 (done) and §2; event-inventory R8 and F9, damage-map H9-H10 (corrected, RM §0); CLAUDE.md only if a row becomes wrong. Commit. No benchmark.
