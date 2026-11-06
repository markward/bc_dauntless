# Phase 6 follow-up 4 — Delete the Python beam and torpedo render builders — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the Python phaser, tractor and torpedo render builders, which survive today only as the native feeds' fallback and test oracle. Afterwards:
- the native feeds (`beam_feed.cc`, `torpedo_feed.cc`) are the only code that builds these descriptors;
- they have no Python fallback and no stand-downs;
- recorded render goldens are the test reference.

**Why:** Mark, 2026-11-06: "we definitely arent keeping duplicated code in the codebase". The spec agrees (§3: migrated stages keep no permanent Python copy). The feeds are live-verified (Mark, 2026-11-06, Release `ef3b816ce`).

**Architecture:**
- **Three refusals can happen in play, and each gets a native answer:**
  1. A beam whose target is not a ShipClass gets Python's answer for that case, ported.
  2. Part slots are refreshed (`native_combat.resolve_stale_part_slots`, O(1) when nothing is stale) right before the render feeds, so a stale pose can't reach them.
  3. Every torpedo gets the default visual record at construction (Python's `Torpedo.__init__` defaults), so the record is never missing. `Create*Model` overwrites it.
- **Every other refusal guards a state normal play can't produce.** Each becomes "skip that one beam or torpedo, count it under its reason". The rest of the frame is drawn natively.
- **The stand-downs are removed:** `DAUNTLESS_NATIVE_COMBAT=0`, the audit, unsnapped, a non-`TrackedInstances` map, and plain_active. The only early return left is "no native host module" (headless with nothing to draw into), which pushes nothing.

**Tech Stack:** C++20 combat library, pybind, Python 3.11, gtest, pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-phase6-engine-stages-native-design.md` §3 ("Python copies"). Precedent: fire control is native only (`2026-11-03-fire-control-native-only-design.md`).

## Global Constraints

- **Branch:** `ws/phase6-render-native-only`, stacked on `ws/phase6-torpedo-feed` at `b489d82cf`.
- **Testing:**
  - Never run the gate or a whole suite. Focused test files only, listed literally. Never pass pytest an empty file list.
  - Combat goldens (`tests/integration/test_golden_fights.py`) stay byte-identical. Never set `UPDATE_COMBAT_GOLDEN`.
  - The new render goldens are recorded ONCE, in Task 1, from today's Python builders. After that, never re-record them without Mark's say.
- **Bit-exact with today.** For every state the current equality tests cover, the native output must equal the recorded goldens.
  - The three ported cases must equal what the Python builder produces today. Pin each with a golden frame recorded in Task 1, before the builders go.
- **No destructive git.** Stage explicit paths. If `test_gate_tiers` fails on a `deep_pytest.txt` entry that names a renamed or deleted test, stop and report it.
- **Keep** `_color_tuple` (used by `engine/shields.py`) and `_resolve_game_texture` (torpedo creation). Delete only what has no caller left.
- **Out of scope:** the K0/K2/K3 Python copies behind `DAUNTLESS_NATIVE_COMBAT=0`. Emitter lights, particles and explosion lights stay Python. They are not duplicated.
- **Build** from the worktree root with `cmake --build build -j`. Gtests need `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game"`.

## Review Focus

1. **The goldens must be deterministic.** Run each recorded scene twice and get identical hashes before anything is deleted. A golden that flickers would hide a real change.
2. **The three ported cases:**
   - the non-ship beam target;
   - a part severed late in a tick;
   - a torpedo with no `Create*Model`.

   Each needs a golden frame recorded from Python, and a native test that reproduces it.
3. **Counted skips.** A skipped item drops only that item. Every other descriptor and light in the frame still matches the golden. Its counter and reason appear on the profiler line.
4. **Deleted helpers.** Grep `engine/`, `tools/` and `tests/` for every deleted name. Nothing may import a deleted name, and no test may monkeypatch one: such a test would silently test nothing.
5. **`DAUNTLESS_NATIVE_COMBAT=0` and `DAUNTLESS_NATIVE_AUDIT=1`.** Both now draw beams and torpedoes natively. Prove it with a test under each.

---

### Task 1: Record render goldens from today's Python builders

**Files:**
- Create: `tests/fixtures/render_goldens/beam_scene.json`, `beam_regions.json`, `torpedo_scene.json`, `edge_cases.json`. Each holds, per frame, the sha256 of the packed `phaser_beams_debug` / `tractor_beams_debug` / `torpedoes_debug` / `dynamic_lights_debug` bytes, plus the per-frame counts.
- Create: `tests/helpers/render_golden.py`:
  - `record(scene_name, frames)` writes a golden. It runs only under `UPDATE_RENDER_GOLDEN=1`.
  - `check(scene_name, frames)` asserts the native output against the golden, per frame, and names the first frame that differs.
- Modify: `tests/host/test_native_beam_feed.py` and `tests/host/test_native_torpedo_feed.py`. Add golden-checked tests that drive the same scenes as today's equality tests.
- Add an edge-case scene (`edge_cases`) covering the three cases above:
  - a phaser or tractor on a non-ShipClass target. Find whether the engine lets a beam lock one (a planet, or a non-ship `DamageableObject`) and say which you used. If no path can, record that, and the case becomes an impossible guard for Task 2.
  - a lock on an articulated part whose part generation is bumped after the last tick refresh;
  - a torpedo created without `Create*Model`.

**Interfaces:**
- Produces: `render_golden.record` / `render_golden.check` and the four golden files. Each frame record is `{"frame": i, "phasers": n, "tractors": n, "torps": n, "lights": n, "sha": hex}`.

- [ ] **Step 1: Record.** Record the goldens from the PYTHON builders (`_python_feed`), with `UPDATE_RENDER_GOLDEN=1`.
- [ ] **Step 2: Check determinism.** Record a second time into a temp dir and diff it against the first. The two must be identical.
- [ ] **Step 3: Check native against the goldens.** Make the native feeds the subject of `check`.
  - Expect PASS on the three main scenes, because the equality tests already pass.
  - On `edge_cases`, expect FAIL wherever today's native refuses a case (a fallback). Record which frames fail; Task 2 fixes them.
  - Mark those edge-case checks `xfail(strict=True)` with the reason. Task 2 removes the marker.
- [ ] **Step 4: Run** the two test files, `tests/integration/test_golden_fights.py` and `tests/unit/test_gate_tiers.py`.
- [ ] **Step 5: Commit** `test(render): record render goldens from the Python builders before deleting them`.

### Task 2: Native answers the real cases; guards become counted skips; no stand-downs

**Files:**
- Modify: `native/src/combat/src/beam_feed.cc`, `torpedo_feed.cc`, `frames_internal.h`, and `beam_geometry` (non-ship target, only if needed).
  - Every `fall_back` / `frames_fall_back` reachable from the feeds becomes either:
    - a native answer (the three cases); or
    - a per-item skip, recorded as `(reason, count)` in the feed's output.
  - A throw must never abandon the whole frame again.
- Modify: `native/src/host/host_bindings.cc` (`combat_beam_feed`, `combat_torpedo_feed`, `set_dynamic_lights_budgeted`). They return the skip counts, and they no longer raise for representability.
- Modify: `engine/appc/native_combat.py`:
  - in `beam_feed` / `torpedo_feed`, remove the stand-downs (keep the no-host return);
  - call `resolve_stale_part_slots()` before the feeds;
  - replace the fallback counters with skip counters by reason;
  - update the profiler lines in `engine/core/frame_profiler.py`.
- Modify: `engine/appc/projectiles.py`. `Torpedo.__init__` pushes the default visual record once the torpedo has a row: at row-add, through the `_vis_native` cache.
- Modify: `engine/host_loop.py` `_push_combat_render_data`. Call the native feeds unconditionally. The Python builders are no longer called; Task 3 deletes them.

- [ ] **Step 1: Write the tests.**
  - Remove the `xfail` markers from Task 1's edge-case checks.
  - ctests, one per skip reason: `BeamFeed.SkippedItemDropsOnlyItself` and `TorpedoFeed.SkippedItemDropsOnlyItself`.
  - pytests:
    - `test_feeds_draw_natively_with_native_combat_off`
    - `test_feeds_draw_natively_under_the_audit`
    - `test_skip_counts_reach_the_profiler_line`
    - `test_a_torpedo_without_create_model_draws_the_default_record`
- [ ] **Step 2: Run them. Expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new tests, all golden checks (all must PASS), the two feed test files, `tests/integration/test_golden_fights.py`, `tests/host/test_render_space_feeds.py`, `tests/integration/test_combat_vfx_routes_through_host_io.py`, the tree guards and `ctest -R combat_`. Expect PASS.
- [ ] **Step 5: Commit** `perf(render): the beam and torpedo feeds answer every case natively; no fallback`.

### Task 3: Delete the Python builders and every test that leans on them

**Files:**
- Modify: `engine/host_loop.py`. Delete `_build_phaser_beam_render_data`, `_build_tractor_beam_render_data`, `_beam_descriptor_pair`, `_beam_endpoint`, `_beam_pair_in_view`, `_firing_banks`, `_ViewMemo`, `_build_torpedo_render_data`, `_build_dynamic_light_render_data`, `_torpedo_colors`, `_torpedo_forward` and `_dim_color`, plus any constant or helper left with no caller. Keep the module constants the native ctx reads.
- Modify: `engine/appc/native_combat.py`, `engine/appc/projectiles.py`, `engine/appc/explosion_lights.py`: remove references, comments included, to the deleted names.
- Tests:
  - Every test that calls, patches or spies a deleted name (grep `tests/`) is either rewritten against the native path and the goldens, or deleted.
  - Name each one in the report, with its replacement.
  - The Python-vs-native equality tests become golden checks; their `_python_feed` helper goes.
- Docs:
  - `docs/reference/engine/native-combat/k2-beams-map.md`, `k3-k4-map.md`, `weapon-state-map.md`: the "built natively" paragraphs now say there is no Python copy, and describe the skip reasons.
  - CLAUDE.md is NOT edited. Its native-combat row says nothing about the render feeds, so nothing there implies a fallback exists.

- [ ] **Step 1: Delete.** Then grep `engine/`, `tools/` and `tests/` for each deleted name. The result must be empty, except history in `docs/superpowers/`.
- [ ] **Step 2: Rewrite or delete the dependent tests.**
- [ ] **Step 3: Run** the golden checks, both feed test files, every test file you edited, `tests/integration/test_golden_fights.py`, `tests/docs`, the tree guards (`tests/unit/test_path_indirection.py`, `tests/unit/test_install_write_guard.py`, `tests/unit/test_gate_tiers.py`) and `ctest -R combat_`. Expect PASS.
- [ ] **Step 4: Commit** `refactor(render): delete the Python beam and torpedo render builders`.

No measurement is needed: the native path is what runs today. Live check afterwards: one 64-ship fight, to confirm the visuals are unchanged.
