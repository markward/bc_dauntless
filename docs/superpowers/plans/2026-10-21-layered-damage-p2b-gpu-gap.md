# Layered damage production, phase 2b: close the GPU gap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring GPU `space.opaque` + `space.hull_interior` for a damaged ship to no more than twice the undamaged cost. SIG-108 has it at alive 2.0–2.8 and dying 4.6–7.0. The plan has two steps:
- first prove the cost is the PLATING program itself;
- then draw record-free meshes with the stock program.

**Architecture:**
- **Task 1: a diagnostic switch.** It forces every hull draw through the PLATING program with an empty record list. Comparing GPU attribution in the undamaged DP window with the switch off and on isolates the program's own weight.
- **Task 2, if confirmed:** within a plated instance, `draw_model` draws the meshes whose per-mesh record subset is empty with the stock opaque program, and the rest with the PLATING program, grouped so each instance switches program at most once.
- **The soot seam.** The PLATING program scales the scorch soot by `u_plating[13]` everywhere. The stock program does not, and must not change. So that scale moves to apply only near damage, and soot is the same on both sides of a mesh boundary.

**Tech Stack:** C++20, GLSL 410 core, Python 3, GoogleTest, pytest, CMake (Debug tree `build/`).

**Spec:** `docs/superpowers/specs/2026-10-21-layered-hull-damage-production-design.md` §3 (the perf rule, and no Release capture per Mark on 2026-10-21). Evidence: `docs/engine/perf-register.md` SIG-106–SIG-108, P-12.

## Global Constraints

- **Git.** Worktree `.claude/worktrees/damage-redesign`, branch `spike/damage-redesign`.
  - Never run `git checkout --`, `restore`, `stash`, `clean`, `reset --hard` or `add -A/.`.
  - Stage explicit paths. Commit with `git commit -F <file>`, ending `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- **Tests.** Focused tests only, with explicit lists; never a whole suite or the gate.
  - GL: `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game" build/native/tests/renderer/renderer_tests --gtest_filter=...`.
  - Pytest: `env -u VIRTUAL_ENV uv run pytest -q -p no:cacheprovider <files>`.
- **`opaque.frag` rules.**
  - It is optimizer-fragile: no new samplers, no early `return` in PLATING main, single discards.
  - Every hunk against `1fca3177d` is inside `#ifdef PLATING`, so the stock program is unchanged.
  - After any edit, run `HullClipTest.*` and `ScuffTest.*`.
- **Shader edits.** `cmake -B build -S .` before `cmake --build build -j`. Rebuild `dauntless` and `_dauntless_host`.
- **Perf captures.**
  - Machine idle: 1-minute load under 3, no game, tests or builds of ours.
  - The DP command, with `DAUNTLESS_DAMAGE_PREVIEW_FIRST_S=20` and `DAUNTLESS_DAMAGE_PREVIEW_SEED=7` as in C-114..C-117.
  - New C-/SIG- rows only. GPU-focus runs are attribution only (M-6).

## Review Focus

1. **A scorch decal spanning a record-free mesh and a plated mesh.** The soot must look the same on both sides of the boundary. Pinned in Task 2 (`SootIsContinuousAcrossTheProgramSplit`).
2. **An undamaged instance must stay byte-identical to the stock draw.** Pinned by the existing `UndamagedHullUsesTheStockProgramPixels`.
3. **Articulated hulls** (node overrides) keep the whole list on every mesh. So they keep the PLATING program for every mesh and are unchanged. Pinned in Task 2 (`ArticulatedPlatedDrawKeepsOneProgram`).

---

### Task 1: Prove where the GPU cost is

**Files:**
- Modify:
  - `engine/appc/plating_dials.py`: a new dial `force_program`, slot 26, default 0.0, max 1.0, step 1.0, debug only. Also an env `DAUNTLESS_PLATING_FORCE_PROGRAM=1` read at dev boot, as `DAUNTLESS_PLATING=0` is.
  - `native/src/renderer/frame.cc`: with `params[26] > 0.5`, `submit_opaque_in_pass` draws every non-rock, non-skinned hull through the PLATING program, uploading an empty list when it has no records.
  - `docs/engine/perf-register.md`.
- Test: `tests/unit/test_plating_dials.py`, `native/tests/renderer/plating_render_test.cc` (`ForceProgramDrawsUndamagedHullWithPlatingProgram`: the program read back from GL is the plating program, and the pixels are unchanged)

- [ ] **Step 1: Write the failing tests.** The dial key and slot 26. `ForceProgramDrawsUndamagedHullWithPlatingProgram`: with `params[26] = 1`, an undamaged hull's draw uses `pipeline.plating_shader()` (read back as `ProgramChoiceIsReadBackFromGL` does), and its pixels equal the stock draw within ±1 per channel.
- [ ] **Step 2: Run them.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `PlatingRender*:PlatingDamage*:HullInterior*` and the dials pytest. Expect PASS.
- [ ] **Step 5: Captures.** Two GPU-focus DP runs at the default distance, `DAUNTLESS_PLATING_FORCE_PROGRAM=0` and `=1`, both with FIRST_S=20 and SEED=7. Record:
  - the undamaged-window GPU `space.opaque`, off vs on;
  - the damaged-alive window for both.
- [ ] **Step 6: Record** a C- row per run, and a SIG with the verdict:
  - **Confirmed:** the undamaged window with the program forced costs at least 70% of the damaged increment SIG-108 saw, about 0.26 ms.
  - **Not confirmed:** otherwise, with the numbers. If not confirmed, STOP after this task and report.
- [ ] **Step 7: Commit.**

### Task 2: Stock program for record-free meshes; soot only near damage

Run this only if Task 1 confirms the program weight.

**Files:**
- Modify:
  - `native/src/renderer/frame.cc`: `draw_model` splits a plated instance's meshes by their cached per-mesh subset. Empty-subset meshes draw with the stock program first, then the rest with PLATING. Each program's per-instance uniforms are set once.
  - `native/src/renderer/shaders/opaque.frag`, PLATING only: the `deposit *= u_plating[13] * ...` soot scale applies only where `plating_near`. Elsewhere the deposit is unscaled, which is exactly what the stock program does.
  - `docs/engine/perf-register.md`.
- Test: `native/tests/renderer/plating_render_test.cc`

**Ruling (made by the controller, recorded for Mark's live check):**
- Outside a ship's near-damage zone, scorch soot goes back to full strength, matching undamaged hulls.
- Inside the zone it keeps the live-tuned 0.75 scale.
- This removes the seam, at the cost of slightly darker scorch away from holes. The `soot` dial still tunes the near zone.

- [ ] **Step 1: Write the failing tests:**
  - `RecordFreeMeshesDrawWithStockProgram`: on a two-quad model with damage on one quad, the far quad draws with the stock program (counter or GL read-back), and its pixels equal the stock draw.
  - `SootIsContinuousAcrossTheProgramSplit`: a scorch decal spanning both quads gives the same soot (±2 per channel) on the two pixels either side of the boundary.
  - `ArticulatedPlatedDrawKeepsOneProgram`: with node overrides, every mesh uses PLATING.
  - `PlatedInstanceSwitchesProgramAtMostOnce`.
- [ ] **Step 2: Reconfigure, build, run.** Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `PlatingRender*:PlatingDamage*:HullInterior*:UnevenBreach*:HullClipTest.*:ScuffTest.*:DecalRenderTest.*:FrameTest.*`. Expect PASS. Check the opaque.frag diff is inside `#ifdef PLATING`.
- [ ] **Step 5: Captures.** Four runs as in C-114..C-117: GPU-focus and CPU-only, default and close, FIRST_S=20, SEED=7. Record ratios per window against the undamaged window, and the P-12 verdict.
- [ ] **Step 6: Commit.**
