# Phase 6 follow-up 1b — Native torpedo feed and torpedo lights — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the per-frame torpedo descriptors and torpedo dynamic lights in C++. They come from the native torpedo table, with each torpedo's visuals pushed once when it is created. The torpedo descriptors are written to `g_torpedoes` directly. The torpedo lights are merged into the dynamic-light budget natively. The output must be bit-identical to today's Python.

**Why:** SIG-203's cProfile split, after the beam feed. Torpedo descriptors (0.372 s), `set_torpedoes` (0.056 s) and torpedo lights (0.131 s) are 49% of `_push_combat_render_data`, about 0.35 ms a frame at 128 ships. Mark agreed on 2026-11-06.

**Architecture:**
- **Per-frame inputs already native.** The K3 torpedo table (`torpedo_table.h`) holds one row per `projectiles._active` torpedo, in list order. Each row carries `_age`, `_velocity`, `_containing_set` and its TransformStore handle.
- **What gets added.** A per-row visual record:
  - resolved texture paths;
  - the five colours, undimmed;
  - the sizes, `num_flares`, `id`, `is_disruptor` and the bolt fields;
  - the light radius base `max(glow_size_a, glow_size_b)`.

  Python pushes it from the values `CreateTorpedoModel` / `CreateDisruptorModel` set. It is pushed again whenever the table is rebuilt from Python (a dirty rebuild makes new handles).
- **The feed.** `build_torpedo_feed` walks the live rows. It converts positions with Task-3-of-1a's frame helpers: same rules, `-0.0` kept on zero shifts. It dims by `TORPEDO_BRIGHTNESS` per frame. It derives `forward` exactly as `_torpedo_forward`, and builds the lights as `_build_dynamic_light_render_data`.
- **The light budget.** A new binding takes the Python explosion and emitter light lists, adds the native torpedo lights, and applies `_budgeted_dynamic_lights`' exact slicing.
- **Fallback.** Any representability failure falls back to today's Python, all or nothing, counted. The cases are a dirty table, a row missing its visual record, or a set missing from the frames table.

**Tech Stack:** C++20 combat library, pybind, Python 3.11, gtest, pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-phase6-engine-stages-native-design.md` §3 (the combat render data row). Pattern: `docs/superpowers/plans/2026-11-06-phase6-native-beam-feed.md`: readback first, equality oracle, then native.

## Global Constraints

- **Branch.** `ws/phase6-torpedo-feed`, stacked on `ws/phase6-clean-list` at `5c5b8117f` (follow-up 3b landed).
- **Tests.** Never run the gate or a whole suite. Run focused test files only, listed literally. Never pass pytest an empty file list.
- **Git.** No destructive git. Stage explicit paths.
- **Goldens.** Byte-identical. Never set `UPDATE_COMBAT_GOLDEN`.
- **Bit-exact with today.** Every `g_torpedoes` field, strings included, and every `g_dynamic_lights` entry must be identical, in the same order, to what today's builders push through `set_torpedoes` / `set_dynamic_lights`.
- **Visuals are read once, at creation.** This is the assumption the A4 quick win already made for `_vis_colors`: SDK projectile scripts never touch a torpedo's visuals after `Create*Model`. Later writes to those attributes are not honoured, under spec Part A.
  - Texture paths are resolved at creation, not per frame. A game-root or mod-set change shows only on torpedoes created after it. This is a deliberate, recorded departure: torpedoes live for seconds.
- **Per-frame values stay live.** `TORPEDO_BRIGHTNESS`, `_TORPEDO_LIGHT_RADIUS_SCALE`, `_TORPEDO_LIGHT_INTENSITY`, `DYN_LIGHT_FADE_START_GU`, `DYN_LIGHT_CULL_GU`, the light budget constants and `_last_camera_eye` are read at call time and passed per frame.
- **Build** from the worktree root with `cmake --build build -j`. Gtests need `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game"`.
- **Benchmarks** run only in Task 4, after Mark clears an idle window.

## Review Focus

1. **The disruptor.** No light. Empty quad textures. Bolt fields from the torpedo. `forward` from a near-zero velocity is `(0, 0, 1)`.
2. **The camera fade.** It is judged on the VIEW position, and the render position is `view_to_render` of that. Lights outside the cull distance are skipped; inside the fade band they scale. With no camera eye, the fade is 1.0.
3. **Budget slicing order.** First explosions[:be], torpedoes[:bt], emitters[:bm]. Then the spill, in the same group order, capped at `_LIGHT_CAP`. Pin a case where the torpedoes overflow their budget and another category has room.
4. **A dirty table at render time.** Either rebuild it before the feed (the rebuild then re-pushes visuals) or fall back. Pin the case where a torpedo expired this frame.
5. **A torpedo in another frame's set** produces no descriptor and no light. A non-zero render origin is subtracted.

---

### Task 1: Readbacks and the equality oracle

**Files:**
- Modify: `native/src/host/host_bindings.cc`: add `torpedoes_debug()` and `dynamic_lights_debug()`. Each returns one tuple per descriptor, every field in struct order, with strings as `str` and floats widened from float32.
- Create: `tests/host/test_native_torpedo_feed.py`, with:
  - a fixture `torpedo_scene`. It is a real headless host with combat_stress realised; reuse `tests/host/test_native_beam_feed.py`'s boot, or the K3 differential's. It needs photon and quantum torpedoes and at least one disruptor in flight, a non-zero render origin, and one torpedo in a set outside the viewed frame;
  - helpers `_torps() -> list[bytes]` and `_lights() -> list[bytes]`, packed so the compare is bitwise (strings length-prefixed);
  - `_python_feed()`, which pushes today's builders and returns both readbacks.

- [ ] **Step 1:** Write `test_readback_returns_what_set_torpedoes_pushed` and `test_readback_returns_what_set_dynamic_lights_pushed`, using hand-built dicts. Also write a smoke test that the scene's Python feed holds torpedoes, a disruptor and at least one torpedo light.
- [ ] **Step 2:** Run them. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run again. Expect PASS.
- [ ] **Step 5:** Commit `test(render): read pushed torpedo and light descriptors back`.

### Task 2: Torpedo visual record in the torpedo table

**Files:**
- Modify: `native/src/combat/include/dauntless/combat/torpedo_table.h` and its source. Add `TorpedoVisual` to the row: strings, `std::array<double,4>` colours, doubles, ints and bools, plus `bool visual_set`.
- Modify: `native/src/host/host_bindings.cc`: add `combat_torpedo_set_visual(handle, tuple)`.
- Modify: `engine/appc/projectiles.py`: at the end of `CreateTorpedoModel` / `CreateDisruptorModel`, push the record. Resolve textures with `host_loop._resolve_game_texture`; the colours are `_color_tuple` of each, undimmed.
- Modify: `engine/appc/native_combat.py`: the table rebuild re-pushes each torpedo's record, cached on its dict as `_vis_native`.
- Tests: ctests in `native/tests/combat/torpedo_table_test.cc` (or the existing table test); pytests in `tests/unit/test_native_combat_k3_mirror.py` (or the table's mirror test).

**Interfaces:**
- Produces: `TorpedoRow::visual` and `visual_set`; the binding `combat_torpedo_set_visual`.

- [ ] **Step 1:** Write the tests.
  - `test_a_created_torpedo_carries_its_visual_record`: every field equals what the Python builder reads.
  - `test_a_rebuilt_table_keeps_visual_records`.
  - `test_a_disruptor_record_has_empty_textures`.
  - The ctest `TorpedoTable.VisualSurvivesCompaction`.
- [ ] **Step 2:** Run them. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them, plus `tests/integration/test_golden_fights.py`, the K3 differential(s) and `ctest -R combat_`. Expect PASS, with the goldens byte-identical.
- [ ] **Step 5:** Commit `feat(native): torpedoes carry their visual record in the torpedo table`.

### Task 3: `build_torpedo_feed`, the budgeted lights, and the frame wiring

**Files:**
- Create: `native/src/combat/include/dauntless/combat/torpedo_feed.h` and `src/torpedo_feed.cc`. Reuse 1a's frame helpers by moving them to a shared internal header if needed; do not copy them.
- Modify: `native/src/host/host_bindings.cc`: add `combat_torpedo_feed(ctx) -> (n_torps, n_lights_built)`, which writes `g_torpedoes`, and `set_dynamic_lights_budgeted(explosions, emitters, torpedo_ctx, caps)`. Both build into locals and assign only on success.
- Modify: `engine/appc/native_combat.py`: add `torpedo_feed(...) -> bool` with counters like `beam_feed`'s (native, fallbacks, stand-downs by reason), shown on the frame profiler's report line.
- Modify: `engine/host_loop.py` `_push_combat_render_data`: native first. On False, today's three Python calls run unchanged.
- Test: `tests/host/test_native_torpedo_feed.py` (extend); ctests `native/tests/combat/torpedo_feed_test.cc`.

**Interfaces:**
- Consumes: Task 1's oracle and Task 2's records.
- Produces: `native_combat.torpedo_feed`, its counters, and the two bindings.

- [ ] **Step 1:** Write the tests.
  - ctests:
    - `TorpedoFeed.OneTorpedoMatchesPython` (dimming, sizes, forward);
    - `TorpedoFeed.NearZeroVelocityFacesZ`;
    - `TorpedoFeed.DisruptorHasNoLight`;
    - `TorpedoFeed.ZeroShiftKeepsNegativeZero`;
    - `TorpedoFeed.OtherFrameDrawsNothing`;
    - `TorpedoFeed.FadeBandScalesIntensity`;
    - `TorpedoFeed.BeyondCullBuildsNoLight`;
    - `TorpedoFeed.NoEyeMeansFullIntensity`;
    - `Budget.SlicingMatchesPython`, with torpedoes overflowing and room left elsewhere;
    - `TorpedoFeed.MissingVisualThrows`.
  - pytest `test_native_torpedo_feed_equals_python_every_frame`: 300 frames of the scene. Seed both native vectors with sentinels before each native call. Assert bitwise equality of both readbacks and the returned counts. Assert coverage counts > 0 for disruptors, torpedo lights, fade-band lights and a culled light.
  - pytest `test_a_throw_leaves_no_partial_feed_and_python_fills_the_frame`.
  - pytest `test_torpedo_feed_counts_reach_the_profiler_report`.
- [ ] **Step 2:** Run them. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the new tests, plus every test file that patches or asserts `set_torpedoes`, `set_dynamic_lights`, `_build_torpedo_render_data` or `_build_dynamic_light_render_data` (grep `tests/`; make each one force the Python path explicitly where its intent needs it), `tests/integration/test_golden_fights.py`, the tree guards and `ctest -R combat_`. Expect PASS.
- [ ] **Step 5:** Commit `perf(render): torpedoes and torpedo lights built natively from the torpedo table`.

### Task 4: Measure (idle window from Mark), with follow-up 3b

- Release, back to back:
  - `dda9402b2`;
  - the 3b tip (`5c5b8117f`);
  - this tip.
- 64 and 128 ships, exterior, two runs each.
- One cProfile run at 128 on this tip.
- Score `cb.render_data` per frame, `cb.phasers` / `sim.combat` per tick, ticks a frame, and the native/fallback counter lines.
- Perf register: the captures and one signal.
- Live-check list (folded into Mark's pending live check of 1a and 3):
  - torpedoes of several types plus disruptors look unchanged;
  - torpedo light on nearby hulls, fading with distance.
