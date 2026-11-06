# Phase 6 follow-up 1 — Native beam feed — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the per-frame phaser and tractor beam descriptors in C++ from the combat mirror and write `g_phaser_beams` / `g_tractor_beams` directly. The output must be bit-identical to today's Python builders. Then measure, and decide with numbers whether the torpedo and torpedo-light half (follow-up 1b) is worth doing.

**Architecture:** A pure combat-library function, `build_beam_feed`, walks the ships in list order. For each ship it reads the phaser (then tractor) system's `_children`, keeps the banks with `_firing`, and for each one runs the existing K2 geometry: `phaser_aim_point`, `strip_emit_position`, `shields_block`, `shield_bubble_entry` and `resolve_hit_point`, through the installed trace hooks. It reads the sim pose from the TransformStore at the moment it is called. Per bank, the beam visuals become mirrored `Native*` fields, pushed on write: today they are written only at `__init__` and `SetProperty`. Per frame, Python sends a small context:
- the viewing set and the render origin;
- one frame entry (a frame id and its anchor) per registered set;
- the iid table (only when its key changed, as K2 does);
- the cheat flag and the player;
- four module constants.

A host binding converts the output to `PhaserBeamDescriptor`s. If the mirror cannot answer anything (a throw, a ship with no row, a set with no frame entry), the binding writes nothing and Python runs today's builders for that frame. This is a representability fallback, never a fallback for a patched method, and it is counted.

**Tech Stack:** C++20 combat library (`native/src/combat`, `-ffp-contract=off`), pybind (`native/src/host/host_bindings.cc`), Python 3.11, gtest (`ctest -R combat_`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-phase6-engine-stages-native-design.md` §3 (Part A rules; the combat render data row) and §7. Recon: `docs/superpowers/plans/2026-11-05-phase6-a2-a4-recon.md`, A4 items 3–4.

## Global Constraints

- Branch `ws/phase6-beam-feed` in `.claude/worktrees/native-motion`, cut from `main` at `ea9ed08cb`. The project branch `project/native-motion-and-proximity` at `ecbeec5a0` is already in `main`.
- **Never run the gate or a whole suite.** Run focused test files only, listed literally. Never hand pytest an empty or unsplit file list.
- No destructive git. Stage with explicit paths.
- Goldens (`tests/integration/test_golden_fights.py`) stay byte-identical. Never set `UPDATE_COMBAT_GOLDEN`.
- Bit-exact with today: every beam field must equal what the Python builders' dicts give after `beam_from_dict`, compared as float32 bits.
- Part A: the feed never stands down because an App method or a host_loop function was patched. That includes `GetPhaserWidth`, `IsFiring`, `GetWeapon`, `_phaser_aim_point` and `_beam_endpoint`. The Python builders stay only as the representability fallback and as the test oracle.
- Build from the worktree root: `cmake --build build -j`. Combat and renderer gtests need `DAUNTLESS_GAME_DIR="/Users/mward/Documents/Star Trek Bridge Commander/game"`.
- Benchmarks only in Task 5, on an idle machine, after Mark clears it.

## Review Focus

1. **A zero shift is not an addition.** `frames.shifted` / `in_view` / `view_to_render` return the point UNTOUCHED when the offset (or the origin) compares equal to `(0,0,0)`, and `-0.0` compares equal. A C++ `p + 0.0` turns `-0.0` into `+0.0`. Task 3 pins this with a `-0.0` coordinate.
2. **Python's `or` defaults.** `x or d` keeps NaN (it is truthy) and replaces both `0.0` and `-0.0`. `int(GetNumSides() or 6)` truncates toward zero. Task 3 pins NaN, `-0.0` and `6.7`.
3. **Cross-region pairs.** The ship and its target are in two mapped regions of one system. The geometry runs in the TARGET's set; each endpoint is in its own set's coordinates, then goes to render space. Task 4's equality scene must include such a pair, and a target in another frame (no beam).
4. **Order.** All phaser pairs come before all tractor pairs, ship order is the list order, bank order is `_children` order, and within a pair the outer shell comes before the inner core. The renderer draws additively, so a wrong order looks fine and only the equality test catches it.
5. **A feed that throws halfway leaves the previous frame's beams.** The binding builds into locals and swaps both vectors only on success. A fallback must still push this frame's Python result. Task 4 forces a throw and checks this.

---

### Task 1: Readback binding and the equality oracle

**Files:**
- Modify: `native/src/host/host_bindings.cc`: add `phaser_beams_debug()` and `tractor_beams_debug()` next to `beam_from_dict`.
- Create: `tests/host/test_native_beam_feed.py`.

**Interfaces:**
- Produces: `_h.phaser_beams_debug() -> list[tuple]` (and `tractor_beams_debug`). One 20-tuple per descriptor, in vector order: `emitter xyz, target xyz, color rgba, width, u_tiles, num_sides, taper_radius, taper_ratio, taper_min_length, taper_max_length, perimeter_tile, texture_speed, end_width_scale`. Each float is the float32 widened to a Python float, so the value is exact.
- Produces, in the test file: `_beams(kind) -> list[bytes]`, each tuple packed with `struct.pack("<12f i 7f"...)` in field order so the compare is bitwise; and `_python_feed(ships, ship_instances)`, which calls today's `_build_phaser_beam_render_data` / `_build_tractor_beam_render_data` (sharing one `_ViewMemo`), pushes both through `host_io`, and returns `(_beams("phaser"), _beams("tractor"))`.
- Scene fixture `beam_scene`: boot the host and realise combat_stress with real instances exactly as `tests/host/test_native_k2_differential.py` does. Reuse its helpers by import if they are importable; otherwise copy the minimal boot. Open fire so that phasers fire, one tractor tows, and at least one target has shields up and one has them down.

- [ ] **Step 1:** Write `test_readback_returns_what_set_phaser_beams_pushed`. Push two hand-built dicts, one with `end_width_scale` and one without. Assert the readback equals the float32 rounding of the inputs, field for field, and that the second one's `end_width_scale == 1.0`.
- [ ] **Step 2:** Run `uv run pytest tests/host/test_native_beam_feed.py -v`. Expect FAIL (no attribute `phaser_beams_debug`).
- [ ] **Step 3:** Implement the two bindings.
- [ ] **Step 4:** Rebuild, then re-run. Expect PASS.
- [ ] **Step 5:** Commit `test(render): read pushed beam descriptors back`.

### Task 2: Mirror the beam visuals per bank

**Files:**
- Modify: `engine/appc/subsystems.py`: the class that declares `_length = NativeField(float)` (~line 366). Declare `_length_texture_tile_per_unit`, `_phaser_width`, `_main_radius`, `_core_scale`, `_taper_radius`, `_taper_ratio`, `_taper_min_length`, `_taper_max_length`, `_perimeter_tile` and `_texture_speed` as `NativeField(float)`, `_num_sides` as `NativeField(int)`, and `_outer_shell_color` and `_inner_core_color` as `NativeField(native_combat.RGBA)`.
- Modify: `engine/appc/native_combat.py`: add the kind `RGBA = "rgba"`. A 4-tuple of real numbers pushes 4 doubles. Anything else pushes "unset", which the feed treats as unrepresentable and throws on.
- Modify: `native/src/combat/include/dauntless/combat/mirror.h` and the mirror sources (field enum, `SubsystemRow`, the setters), `native/src/host/host_bindings.cc` (push parsing for the new kind), and any field-table drift test that lists Subsystem fields.
- Test: `tests/unit/test_native_combat_weapons_mirror.py` (or the closest existing mirror test for Subsystem fields), and `ctest -R combat_Mirror`.

**Interfaces:**
- Produces: `SubsystemRow` doubles with the same names as the Python attributes, `int64_t _num_sides`, `std::array<double,4> _outer_shell_color, _inner_core_color`, and `bool outer_shell_color_set, inner_core_color_set`.

- [ ] **Step 1:** Write tests.
  - `test_bank_visuals_reach_the_mirror_after_set_property`: a PhaserBank with a stock Galaxy `PhaserProperty`. After `SetProperty`, each mirrored value read back through the existing mirror read binding equals the Python attribute.
  - `test_a_non_tuple_colour_is_unrepresentable`: assign `_outer_shell_color = None`. The row reports the colour unset.
- [ ] **Step 2:** Run the tests. Expect FAIL.
- [ ] **Step 3:** Implement. The fields need register-time packing like every other `NativeField`; follow `_length`.
- [ ] **Step 4:** Run the new tests, plus `tests/integration/test_golden_fights.py`, `tests/unit/test_native_write_apply.py` and `ctest --test-dir build -R combat_`. Expect PASS, goldens unchanged.
- [ ] **Step 5:** Commit `feat(native): mirror the beam visuals of each emitter`.

### Task 3: `build_beam_feed` in the combat library

**Files:**
- Create: `native/src/combat/include/dauntless/combat/beam_feed.h`, `native/src/combat/src/beam_feed.cc` (add to `native/src/combat/CMakeLists.txt`).
- Test: `native/tests/combat/beam_feed_test.cc` (register it with the combat tests).

**Interfaces:**
- Consumes: `beam_geometry.h` (`phaser_aim_point`, `strip_emit_position`, `shields_block`, `shield_bubble_entry`), `beam_trace.h` (`resolve_hit_point`, `TraceHooks`, `InstanceId`), `py_math.h`, `K2Context::Iid`, and Task 2's fields.
- Produces:

```cpp
struct BeamFrame { int64_t id; Vec3 anchor; };      // frames.frame_of(set)
struct BeamFeedCtx {
    int64_t view = -1;                  // frames.viewing_set() Set handle; -1 none
    Vec3 origin{0, 0, 0};               // frames.render_origin()
    std::unordered_map<int64_t, BeamFrame> frames;  // every registered Set
    std::unordered_map<int64_t, K2Context::Iid> iids;
    TraceHooks hooks;
    bool npc_shields_off = false; int64_t player = -1; bool use_memo = false;
    double width_mutator, phaser_brightness, tractor_brightness,
           tractor_end_width_scale;
};
struct BeamOut { Vec3 emitter, target; std::array<double,4> color;
                 double width, u_tiles; int64_t num_sides;
                 double taper_radius, taper_ratio, taper_min_length,
                        taper_max_length, perimeter_tile, texture_speed,
                        end_width_scale; };
// Throws std::invalid_argument wherever the mirror cannot answer as the
// Python would: a -1 ship, a set missing from ctx.frames, an unset colour,
// and every throw of the geometry it calls.
void build_beam_feed(Mirror& m, const std::vector<int64_t>& ships,
                     const BeamFeedCtx& ctx, std::vector<BeamOut>& phasers,
                     std::vector<BeamOut>& tractors);
```

- The function is a line-for-line port of these, in their order, early returns included:
  - `_build_phaser_beam_render_data` and `_build_tractor_beam_render_data`;
  - `_firing_banks` (the stock path: `_children` and `_firing`);
  - `_ViewMemo.set_of`;
  - `_beam_descriptor_pair`, `_beam_endpoint` and `_beam_pair_in_view`.
- The `frames` functions it needs are ported as file-local helpers with Python's exact rules:
  - `offset_between`: the same set gives zero if the set is a Set, else None; frames with different ids give None; otherwise `b - a` per component, `fb.anchor - fa.anchor`.
  - `in_view`, `view_to_render` and `shifted`: an offset equal to zero, compared with `==` so `-0.0` counts, returns the point untouched.
  - `view_offset`: None for a zero offset or no offset.
- Python's `x or d`, `int(...)`, `max(1.0, ...)` and `** 0.5` go through `py_math.h`. The colour is multiplied by brightness on the rgb channels only. The inner colour's alpha is `0.35`.
- Return `[]`, meaning no beam and no throw, exactly where the Python does. In particular, a `None` `to_ship` is checked BEFORE the aim point.

- [ ] **Step 1:** Write the ctests on a hand-built Mirror, as `beam_geometry_test.cc` does:
  - `BeamFeed.OnePhaserBankYieldsOuterThenInner`: widths `outer = width·mut` and `inner = main_radius·core_scale·mut`, the inner alpha 0.35, the rgb × brightness.
  - `BeamFeed.PhasersBeforeTractorsInShipThenBankOrder`.
  - `BeamFeed.TractorPairCarriesEndWidthScale`.
  - `BeamFeed.OrDefaultsMatchPython`: core_scale `-0.0` → 0.5; taper_ratio NaN stays NaN; num_sides 6.7 → 6; num_sides 0 → 6.
  - `BeamFeed.ZeroShiftKeepsNegativeZero`: emitter x `-0.0`, same set, origin zero. The output x has its sign bit set.
  - `BeamFeed.RenderOriginIsSubtracted`.
  - `BeamFeed.CrossRegionPairMeetsInTheTargetsSet`: two sets with one frame id and different anchors. The emitter is in the ship's coordinates and the target in the target's, both shifted to the view.
  - `BeamFeed.OtherFrameTargetDrawsNothing`.
  - `BeamFeed.ShipOutOfViewDrawsNothing`.
  - `BeamFeed.ShieldsUpEndsOnTheBubble`, `BeamFeed.ShieldsDownEndsOnTheHullTrace` (a fake TraceFn), `BeamFeed.NoInstanceEndsOnTheAimPoint`.
  - `BeamFeed.UTilesIsAtLeastOne` (`tile_per_unit` 0, and a tiny length).
  - `BeamFeed.MissingFrameEntryThrows`, `BeamFeed.UnsetColourThrows`, `BeamFeed.NoRowShipThrows`.
- [ ] **Step 2:** Run `ctest --test-dir build -R combat_BeamFeed`. Expect FAIL (no target / no symbol).
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `ctest --test-dir build -R combat_`. Expect PASS.
- [ ] **Step 5:** Commit `feat(native): build_beam_feed — beam descriptors from the mirror`.

### Task 4: Wire the feed into the frame, proven equal to the Python builders

**Files:**
- Modify: `native/src/host/host_bindings.cc`: add `combat_beam_feed(ships, ctx) -> tuple[int, int]`. It reads `_nslot` per ship (−1 when there is no slot), parses `ctx`, calls `build_beam_feed` into locals, converts each `BeamOut` to a `PhaserBeamDescriptor` by `static_cast<float>` (`num_sides` stays `int`), and only then assigns BOTH `g_phaser_beams` and `g_tractor_beams`. On a throw it raises `ValueError` and leaves both vectors untouched. The iid table persists in the binding and is replaced only when `ctx` carries `"iids"`, as K2 does.
- Modify: `engine/appc/native_combat.py`: add `beam_feed(ships, ship_instances) -> bool`.
  - It builds `ctx`: `view`, `origin`, and `frames` for every set in `App.g_kSetManager._sets` with a slot. The frame id is a per-call `dict` from `Frame.key` to a small int; anchors come from `frames.frame_of`.
  - `iids` uses its own sent-key `_beam_iids_sent`, like K3's `_k3_iids_sent`: `_K2Context(ship_instances, sent=_beam_iids_sent)`.
  - Also `npc_shields_off`, `player` (as `_K2Context.delta` computes them), `use_memo=step_memo.active()`, and the four constants read from `engine.host_loop` at call time.
  - On `ValueError` it bumps the counter `beam_feed_fallbacks`, logs the first reason once (`[native-combat] beam feed: <reason>` on stderr), and returns False.
  - Returns False without calling native when `DAUNTLESS_NATIVE_COMBAT=0` or the audit is on, which are today's stand-downs.
  - Add `beam_feed_fallbacks` to `reset()`, and the sent-key to the reset that clears `_k3_iids_sent`.
- Modify: `engine/host_loop.py` `_push_combat_render_data`: `if not _native_combat.beam_feed(ships_list, ship_instances):` then run today's two builders and setters unchanged.
- Test: `tests/host/test_native_beam_feed.py` (extend), plus `tests/host/test_render_space_feeds.py`, `tests/unit/test_tractor_beam_render_data.py`, `tests/unit/test_render_feeds_by_frame.py` and `tests/unit/test_shield_bubble_wiring.py` (still pass; any test that monkeypatches a builder now forces the fallback or patches `beam_feed`. Say which).

**Interfaces:**
- Consumes: Task 1's `_beams` / `_python_feed`, Task 3's `build_beam_feed`.
- Produces: `native_combat.beam_feed`, `native_combat.beam_feed_fallbacks` (an int, read by tests and Task 5).

- [ ] **Step 1:** Write tests in `tests/host/test_native_beam_feed.py`:
  - `test_native_feed_equals_python_every_frame`: on `beam_scene`, for 300 frames of the K2 differential's seeded op stream (fire, re-target, stop, shields off and on, Manual Aim on and moved, a subsystem lock on a posed part, a tractor tow), each frame takes `_python_feed(...)` then `beam_feed(...)` plus `_beams(...)`, and asserts the two lists of bytes are equal. Also assert `beam_feed_fallbacks == 0`, and that at least one frame had a bubble end, a hull-trace end, a tractor pair and a Manual Aim pair (assert the counts the scene produced, so the test cannot pass on an empty feed).
  - `test_native_feed_equals_python_across_regions`: the `far_scene` fixture of `tests/host/test_render_space_feeds.py` (import it), with a non-zero render origin, one pair split across two regions of one system, and one target in another frame.
  - `test_a_throw_leaves_no_partial_feed_and_python_fills_the_frame`: unset one bank's colour mid-scene. `beam_feed` returns False, the counter is 1, and the pushed frame equals `_python_feed`.
  - `test_a_patched_getter_is_not_honoured`: monkeypatch `PhaserBank.GetPhaserWidth` to return 9.0. The native feed's widths are the mirrored value, with no fallback.
- [ ] **Step 2:** Run them. Expect FAIL.
- [ ] **Step 3:** Implement the binding, `beam_feed`, and the host_loop call.
- [ ] **Step 4:** Run `tests/host/test_native_beam_feed.py`, the four files above, `tests/integration/test_golden_fights.py`, `tests/integration/test_frame_tripwire.py`, the cheap tree guards (`tests/docs`, `tests/unit/test_path_indirection.py`, `tests/unit/test_install_write_guard.py`, `tests/unit/test_gate_tiers.py`) and `ctest --test-dir build -R combat_`. Expect PASS.
- [ ] **Step 5:** Commit `perf(render): phaser and tractor beams built natively from the mirror`.

### Task 5: Measure, record, decide 1b

- Release in `.claude/worktrees/release-macos`.
  - **Before:** detach at `ea9ed08cb` and build.
  - **After:** detach at the branch tip and build.
  - Same session, idle machine.
- Run the phase0-runbook §1 command with `DAUNTLESS_DEV_VIEW=exterior` and `=bridge`, `DAUNTLESS_COMBAT_SHIPS=64` and `=128`, two runs each, on both commits. Add one cProfile run at 128 exterior on the tip (`DAUNTLESS_PROFILE_PY`, frames 500:400).
- Score:
  - `cb.render_data` per frame, frame ms and ticks a frame: the median of reports 3–11;
  - `beam_feed_fallbacks` from the log;
  - from the cProfile: the shares of `_push_combat_render_data` taken by the torpedo builder, the torpedo light builder, `set_torpedoes` and the rest.
- Perf register: captures, plus one signal saying plainly what it bought. Note that per-frame savings are amplified by the catch-up loop at 128 ships (SIG-196), and that 64-ship frames may pin at 16.6 ms (SIG-200 caveat).
- **Decide 1b with the numbers.** If torpedo plus torpedo lights are under ~0.2 ms a frame at 128 ships, say so and stop. Otherwise write a short 1b plan: a native torpedo feed from the torpedo table with visuals pushed at create, and the torpedo light list built natively and merged by a `set_dynamic_lights` variant that applies `_budgeted_dynamic_lights`' exact slicing.
- Commit `docs(perf): phase 6 native beam feed (SIG-…)`.
- Live-check list for Mark:
  - a 64-ship fight, phasers and tractors looking as before;
  - beams hitting raised shields (the bubble) and bare hulls;
  - Manual Aim on a moving target;
  - a subsystem lock on an LC Intrepid nacelle;
  - a cross-region shot, if a mapped system offers one.
