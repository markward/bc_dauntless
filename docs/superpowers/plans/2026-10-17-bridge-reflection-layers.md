# Bridge Reflection Layers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One base reflection probe per bridge state, glow in reflections, one animation layer per (state, whole wave) capped 2/4/8 by Bridge Quality, 384² probes, captures time-sliced across frames.

**Architecture:** Python plans the probe set (pure: which (state, wave) layers exist, every light/glow row's capture value per state and per layer, each layer's live `w^2.2`) and pushes static rows + per-frame values. C++ derives each probe's dirtiness from a per-probe input signature, captures dirty probes a step per frame into a spare slot of one R11G11B10F cube-map array, runs the state cross-fade as per-base weights, and the shader sums weighted bases + layers inside the split-sum term.

**Tech Stack:** C++17 / OpenGL 4.1 core (macOS) / GLSL 410, pybind11, Python 3.11, gtest, pytest.

**Spec:** `docs/superpowers/specs/2026-10-17-bridge-reflection-layers-design.md` (cited "spec §N"). Background: `docs/superpowers/specs/2026-10-08-bridge-emitters-spike-design.md` (cited "living §N").

## Global Constraints

- State index order everywhere (Python arrays, C++ arrays, bindings): **0 green, 1 yellow, 2 red, 3 offline, 4 special** (`behaviour.state_index`, `kBridgeStateOffline = 3`, `kBridgeStateSpecial = 4`). `kBridgeStates = 5`.
- Probe ids: base of state s = `s` (0–4); layer k = `5 + k`.
- Face size **384** (`kBridgeProbeFace`), **6 mips** (`kBridgeProbeMips`, unchanged), prefiltered format **`GL_R11F_G11F_B10F`**, raw capture scratch **RGBA16F**, one shared.
- Layer cap per state by `renderer::BridgeQuality`: **Low 2, Medium 4, High 8**.
- Wave key = the whole wave: `shape`, `period_s`, `phase`, `min`, `duty`, `soft`; several animations in one state = the sorted tuple of all of them.
- Layer live value `v = w(t)^2.2`, `w` = product of the key's `behaviour.wave_factor`s on the bridge clock.
- State cross-fade: **0.5 s**, frozen at dt 0 (pause), in C++.
- Never per frame once complete; never on a pulse; never one whole capture in one frame in production.
- Glow in a probe = `decode(glow)` added AFTER that probe's own diffuse ceiling, uncapped.
- Officers and the viewscreen stay out of every probe (living §9.6).
- Shared checkout: never `git checkout -- / restore / stash / clean / reset --hard / add -A / add .`; stage explicit paths. Mutation probes: back up with `cp`, restore with `cp`, prove with `diff`.
- Gate before declaring done: `scripts/check_tests.sh` green, no new `tests/known_failures.txt` lines. Never launch `./build/dauntless` without asking Mark.
- Build: `cmake --build build -j 8` from the worktree root (Debug tree already configured; never reconfigure the build type, never build from `native/`).

## Review Focus

1. **A bridge with no lighting file / no animation** (EBridge, Sovereign, mods): must show 5 room-light-only bases and no layers, no warnings, no errors — Task 3 adds `test_bridge_without_doc_plans_no_layers_and_five_scales`.
2. **Bridge Quality changed live mid-session** (Settings → graphics): layers above the new cap disappear from reflections with a warning, lower cap never crashes, probe storage shrinks/grows without a blank frame on bases — Task 8 adds `test_quality_change_replans_layers`, Task 4 adds `GrowKeepsExistingSlots`.
3. **Mission swap / new bridge model while a capture is in flight**: the half-captured probe must never become visible for the new room; the queue restarts — Task 6 adds `ANewBridgeModelMidCaptureDiscardsTheInFlightProbe`.
4. **Pause during a fade or a pulse**: weights and layer values freeze (dt 0), nothing recaptures — Task 7 adds `FadeFreezesAtZeroDt`; Task 8 adds `test_layer_values_freeze_under_pause`.
5. **Editor preview square clicked rapidly through all five states while bases are still filling**: weights stay continuous and sum to 1, a not-yet-valid target never shows black — Task 7 adds `RetargetMidFadeIsContinuous` and `InvalidTargetHoldsTheCurrentWeights`.

---

### Task 1: Probe-layer planner (pure Python)

**Files:**
- Create: `engine/bridge_editor/probe_layers.py`
- Modify: `engine/bridge_editor/behaviour.py` (`output`: new keyword `waves=True`)
- Test: `tests/unit/test_bridge_probe_layers.py`, `tests/unit/test_bridge_behaviour.py`

**Interfaces:**
- Produces:
  - `behaviour.output(material, state, t, has_map=False, for_light=False, waves=True)` — `waves=False` treats every Animation factor as 1 (the peak); otherwise unchanged. `StateFade.output` unchanged.
  - `probe_layers.LAYER_CAP = {0: 2, 1: 4, 2: 8}`; `layer_cap(quality: int) -> int` (below 0 → Low, above 2 → High).
  - `probe_layers.wave_key(material: dict, state: str) -> tuple | None` — `None` when no Animation is scoped to `state`; else `tuple(sorted((shape, float(period_s), float(phase), float(min), float(duty), float(soft)) ...))` with defaults `phase 0, min 0, duty 0.5, soft 0`; for `sine`, duty and soft are normalised to `0.0` (unused by `wave_factor`, so they must not split groups).
  - `@dataclass(frozen=True) class Layer: state: str; key: tuple; materials: tuple[str, ...]`
  - `@dataclass class ProbePlan: layers: list[Layer]; warnings: list[str]` with `layer_of(material: str, state: str) -> int` (index into `layers`, or -1) and `animated(material: str, state: str) -> bool` (`wave_key(...) is not None`, whether kept or dropped).
  - `probe_layers.plan(doc, resolved: dict[int, str], light_materials: frozenset[str], mapped: frozenset[int], cap: int) -> ProbePlan` — `resolved` = `lighting_doc.resolve` output (mesh → material name); `light_materials` = materials whose objects carry ≥1 light; `mapped` = meshes whose texture has an `_emissive` map.
  - `probe_layers.layer_values(plan: ProbePlan, t: float) -> list[float]` — per layer, `prod(wave_factor(anim, t)) ** 2.2`.
  - `probe_layers.EMPTY = ProbePlan([], [])`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_bridge_probe_layers.py` (build docs as dicts like `test_bridge_lights.py` does):
  - `test_wave_key_none_without_animation_in_state` — material with an animation scoped `["red"]` → `wave_key(m, "green") is None`.
  - `test_min_is_part_of_the_key` — two materials, same red sine 3 s phase 0, `min` 0 vs 0.2 → 2 layers.
  - `test_equal_waves_share_one_layer` — DBridge-shaped: 4 materials with `{"shape":"sine","period_s":3,"phase":0,"min":0.2,"scope":["red"]}` → `len(plan.layers) == 1`, `layers[0].state == "red"`, `materials` holds all 4 in doc order.
  - `test_sine_ignores_duty_and_soft` — sine with `duty: 0.3` vs without → one layer.
  - `test_multiplied_animations_form_one_key` — a material with two animations in red → key of length 2; another with only one of them → separate layer.
  - `test_layer_per_state` — one material animated in red AND yellow with the same wave → 2 layers (`("yellow", k)`, `("red", k)`).
  - `test_cap_keeps_authored_order_and_warns` — 3 distinct red waves, cap 2 → layers are the first two by first-material doc order; `warnings` has one entry naming the third key's materials; `plan.animated(third, "red") is True`, `plan.layer_of(third, "red") == -1`.
  - `test_material_contributing_nothing_makes_no_layer` — animation on `emission: 0`, no State, not in `light_materials` → 0 layers, no warning, does not use a cap slot.
  - `test_unused_material_makes_no_layer` — animated material not in `resolved.values()` → 0 layers.
  - `test_layer_cap_by_quality` — `layer_cap(0) == 2`, `(1) == 4`, `(2) == 8`, `(-3) == 2`, `(9) == 8`.
  - `test_layer_values_are_wave_to_the_2_2` — red sine 3 s min 0.2 at `t = 0.75` (f = 0.5 → w = 0.6) → `layer_values(plan, 0.75) == [pytest.approx(0.6 ** 2.2)]`; at `t = 0` → `[1.0]`.
  - In `tests/unit/test_bridge_behaviour.py`: `test_output_waves_false_is_the_peak` — alcove material at red, `t = 0.75`: `output(m, "red", 0.75, waves=False)[0] == output(m, "red", 0.0)[0]` and differs from `output(m, "red", 0.75)[0]`.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_bridge_probe_layers.py tests/unit/test_bridge_behaviour.py -q` — Expected: FAIL (`ModuleNotFoundError: engine.bridge_editor.probe_layers`, unexpected keyword `waves`).

- [ ] **Step 3: Implement** `behaviour.output(..., waves=True)` (skip `f *= wave_factor` when False) and `probe_layers.py`. Contribution test for a (material, state): any mesh in `resolved` with that material has non-zero `output(mat, state, 0, mesh in mapped, waves=False)[0]`, OR the material is in `light_materials` and `output(mat, state, 0, False, for_light=True, waves=False)[0]` is non-zero. Order of layers: states in index order (green, yellow, red, offline, special), then keys by first material in `doc["materials"]` insertion order.

- [ ] **Step 4: Run** the same command — Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add engine/bridge_editor/probe_layers.py engine/bridge_editor/behaviour.py tests/unit/test_bridge_probe_layers.py tests/unit/test_bridge_behaviour.py
git commit -m "feat(bridge-reflections): probe-layer planner and peak output"
```

---

### Task 2: C++ capture data model and per-probe signatures

**Files:**
- Modify: `native/src/renderer/include/renderer/bridge_pass.h`, `native/src/renderer/bridge_pass.cc`, `native/src/renderer/include/renderer/bridge_lighting_tuning.h`
- Test: `native/tests/renderer/bridge_probe_signature_test.cc` (new; add to `native/tests/renderer/CMakeLists.txt` beside `bridge_pass_test.cc`)

**Interfaces:**
- Produces (all in `namespace renderer`):
  - `inline constexpr int kBridgeStates = 5;` (bridge_pass.h); `kBridgeProbeFace = 384` (tuning header).
  - `BridgeSpot` / `BridgeAreaLight`: `glm::vec3 capture_radiance[kBridgeStates]` (replaces `[2]`), `int layer[kBridgeStates]` (all -1 = in no layer), `glm::vec3 layer_radiance[kBridgeStates]` — per state, the layer the row belongs to there and its at-peak radiance (`has_capture` kept). A row is in at most one layer per state.
  - `struct BridgeGlowCapture { int mesh = -1; int src = 0; glm::vec3 base[kBridgeStates]; int layer[kBridgeStates]; glm::vec3 layer_rgb[kBridgeStates]; };` (layers init -1) — display-space values, as `BridgeGlow::rgb`.
  - `void BridgePass::set_glow_captures(unsigned long long model_handle, std::vector<BridgeGlowCapture>);` `void clear_glow_captures();`
  - `void BridgePass::set_probe_scales(const std::array<float, kBridgeStates>& scales);` `float probe_scale(int state) const;` (replaces the two-float form and its two getters).
  - `void BridgePass::set_probe_layers(std::vector<int> layer_states);` `int probe_count() const;` (= 5 + layers).
  - `std::uint64_t BridgePass::probe_signature(int probe) const;` — FNV-1a over exactly the inputs that probe reads (below).
  - `void BridgePass::request_probe_capture();` keeps its name: now invalidates every probe's captured signature.
- Signature inputs: **every probe** — material overrides (+ model), probe origin, bridge box handle, unscaled `capture_ambient_`, spot/area geometry (position, direction, cones, range, centre, half_u/v), glow-capture mesh/src list. **Base s** — `probe_scale(s)`, each spot/area `capture_radiance[s]` (× the radiance when `!has_capture`), each glow `base[s]`. **Layer k** (state s = `layer_states[k]`) — s, and for rows with `layer[s] == k`: `layer_radiance[s]` / `layer_rgb[s]`. Live radiance and `set_glow` never enter a signature.
- The old setters stop calling `request_probe_capture()`; the dirtiness is derived (Task 6 compares signatures). Keep `set_spots`/`set_area_lights` return values and sanitising.

- [ ] **Step 1: Write the failing tests** in `bridge_probe_signature_test.cc` (CPU only — `BridgePass` constructs without GL; no `render()` call):
  - `RedOnlyCaptureChangeMovesOnlyTheRedBase` — spot with captures, change `capture_radiance[2]` → `probe_signature(2)` changes; 0, 1, 3, 4 unchanged.
  - `LayerMemberChangeMovesOnlyThatLayer` — two layers (`set_probe_layers({2, 2})`), a spot with `layer[2] = 1`; change its `layer_radiance[2]` → `probe_signature(6)` changes, `probe_signature(5)` and all bases unchanged.
  - `OverridesMoveEveryProbe` — `set_material_overrides` with a new metalness → all `probe_count()` signatures change.
  - `IdenticalRepushMovesNothing` — the same spots twice → every signature equal.
  - `ScaleMovesOnlyItsBase` — change `scales[3]` → only `probe_signature(3)` changes; layer signatures unchanged.
  - `LiveRadianceNeverMovesASignature` — `set_spot_radiance`, `set_glow` → all unchanged.
  - `GlowCaptureBaseMovesItsState` — `BridgeGlowCapture` `base[0]` change → only base 0.
- [ ] **Step 2: Run** `cmake --build build -j 8 --target renderer_tests && ./build/native/tests/renderer/renderer_tests --gtest_filter='BridgeProbeSignature*'` — Expected: build FAIL (no `set_glow_captures`, no `probe_signature`).
- [ ] **Step 3: Implement** the structs, setters and `probe_signature`. Update every existing user of the two-float `set_probe_scales` / `capture_radiance[0|1]` in `bridge_pass.cc` and `native/tests/renderer/*` so the tree builds (the binding is Task 3; until then `host_bindings.cc` maps its two-value `set_bridge_probe_scales(green, yr)` to `{green, yr, yr, yr, yr}` and a `(green, alert)` capture pair to `[0] = green, [1..4] = alert`). The capture still uses the old one-shot path until Task 5/6: map the old green probe to state 0 and yellow/red to state 1.
- [ ] **Step 4: Run** the filter above, then `ctest --test-dir build -R renderer -j 8` — Expected: PASS, no other renderer test regresses.
- [ ] **Step 5: Commit**
```bash
git add native/src/renderer/include/renderer/bridge_pass.h native/src/renderer/bridge_pass.cc native/src/renderer/include/renderer/bridge_lighting_tuning.h native/tests/renderer/bridge_probe_signature_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(bridge-reflections): per-state capture data and per-probe signatures"
```

---

### Task 3: Static data path — bindings, host_io, light and glow rows, runtime push

**Files:**
- Modify: `native/src/host/host_bindings.cc` (`set_bridge_spots`, `set_bridge_area_lights`, `parse_bridge_captures`, `set_bridge_probe_scales`, `bridge_probe_stash`, `bridge_probe_state`; new `set_bridge_glow_captures`, `set_bridge_probe_layers`, `bridge_probe_signatures`)
- Modify: `engine/host_io.py`, `engine/bridge_lighting.py` (`probe_scales`), `engine/bridge_editor/lights.py`, `engine/bridge_editor/glow.py`, `engine/bridge_editor/runtime.py`
- Test: `tests/unit/test_bridge_lights.py`, `tests/unit/test_bridge_glow.py`, `tests/unit/test_bridge_runtime.py`, `tests/unit/test_bridge_lighting.py`, `tests/unit/test_host_io_binding_manifest.py`, `tests/host/test_bridge_editor_bindings.py`

**Interfaces:**
- Consumes: Task 1 (`probe_layers.plan`, `ProbePlan.layer_of/animated`, `behaviour.output(waves=False)`), Task 2 setters.
- Produces:
  - Binding `set_bridge_spots(spots, captures=None)` / `set_bridge_area_lights(areas, captures=None)`: `captures` = per row `(caps5, layers5, layer_rgbs5)` — `caps5` 5 linear colours in state order, `layers5` 5 ints (-1 = none), `layer_rgbs5` 5 linear colours; colours × the row's intensity natively (as today). A length mismatch ignores them (today's rule).
  - Binding `set_bridge_glow_captures(instance_id, rows)` — rows `(mesh, src, caps5, layers5, layer_rgbs5)`, display space; None/stale id clears; non-finite rows dropped.
  - Binding `set_bridge_probe_scales(scales)` — a 5-tuple; `bridge_probe_stash()["scales"]` and `bridge_probe_state()["scales"]` return the 5-tuple.
  - Binding `set_bridge_probe_layers(states: list[int])`; `bridge_probe_state()` gains `"probe_count"`.
  - Binding `bridge_probe_signatures() -> list[int] | None` (test/diagnostic).
  - host_io wrappers of the same names and shapes; `host_io.set_bridge_spots(rows)` / `set_bridge_area_lights(rows)` take rows **`(pos3, dir3, inner_deg, outer_deg, range, rgb, intensity, caps5, layers5, layer_rgbs5)`** and **`(centre3, half_u3, half_v3, range, rgb, intensity, caps5, layers5, layer_rgbs5, joins)`** and split them into the binding's `(rows, captures)`.
  - `bridge_lighting.probe_scales() -> tuple[float, ...]` — 5 values, `ambient_scale_for_alert(i)` for i in 0..4.
  - `lights.build(doc, matched, resolved, frame_for=..., mapped=frozenset(), plan=probe_layers.EMPTY) -> Built` — rows in the shapes above. For each state s (index i): `caps5[i] = to_linear(output(mat, s, 0, has_map, for_light=True))` when `not plan.animated(name, s)`, else `(0, 0, 0)`; `layers5[i] = plan.layer_of(name, s)`; `layer_rgbs5[i] = to_linear(output(mat, s, 0, has_map, for_light=True, waves=False))` when `layers5[i] >= 0`, else `(0, 0, 0)`.
  - `glow.captures(objs, plan) -> list[(mesh, src, caps5, layers5, layer_rgbs5)]` — `objs` = `glow_objects` output; `caps5[i] = output(mat, s, 0, mapped)[0]` when not animated in s, else 0; `layer_rgbs5[i] = output(mat, s, 0, mapped, waves=False)[0]` for a kept layer. Display space (C++ decodes).
  - `BridgeRuntime.push` computes `plan = probe_layers.plan(doc, resolved, light_materials, mapped, probe_layers.layer_cap(self._io.bridge_quality()))`, stores `self._plan` and the quality it used, pushes `set_bridge_probe_layers([behaviour.state_index(l.state) for l in plan.layers])`, glow captures and rows; plan warnings go through `dev_mode.log_swallowed` and into `push()`'s returned warnings (the editor status line). `attach()` clears glow captures and layers with the other clears. New `host_io.bridge_quality() -> int` (1 headless).

- [ ] **Step 1: Write the failing tests:**
  - `test_bridge_lights.py::test_capture_per_state_zero_when_animated` — alcove material (State white green, State red 0.5 + red sine) on a spot: caps5[0] = linear white × 1, caps5[2] = (0,0,0), layers5[2] = 0, layer_rgbs5[2] = `to_linear((0.5, 0.06, 0.04))`, the other four layers5 entries -1.
  - `test_bridge_lights.py::test_dropped_layer_member_is_absent` — cap 0 plan: caps5[2] = 0 and layers5[2] = -1.
  - `test_bridge_lights.py::test_live_equals_layer_times_value` — at `t = 0.75`, `lights.live(...)` red colour == `layer_rgbs5[2] × intensity × layer_values(plan, 0.75)[0]` (approx, per channel). **This is the Python half of the linearity proof.**
  - `test_bridge_glow.py::test_glow_captures_base_and_layer` — Map 22a-shaped (map, red sine min 0.2, no State): caps5[2] = 0, caps5[0] = (1, 1, 1) (map as painted), layer_rgbs5[2] = (1, 1, 1); and `test_glow_live_decoded_equals_layer_decoded_times_value` — `decode(live rgb) == decode(layer_rgbs5[2]) × v` at `t = 0.75` with decode = `^2.2`.
  - `test_bridge_lighting.py::test_probe_scales_has_five_states` — `probe_scales() == (1.5, 1.0, 1.0, 0.4, 1.0)`.
  - `test_bridge_runtime.py::test_push_sends_layers_and_glow_captures` — fake io records `set_bridge_probe_layers([2])` for a DBridge-shaped doc and 5-value scales.
  - `test_bridge_runtime.py::test_bridge_without_doc_plans_no_layers_and_five_scales` — attach with no content hash → `set_bridge_probe_layers([])` (or never called with non-empty) and scales of length 5, no warnings.
  - `tests/host/test_bridge_editor_bindings.py::test_probe_signatures_move_with_red_captures` — real binding: push spots twice with only the red capture changed; `bridge_probe_signatures()` differs at index 2 only.
  - Update `test_host_io_binding_manifest.py` for the new names.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_bridge_lights.py tests/unit/test_bridge_glow.py tests/unit/test_bridge_runtime.py tests/unit/test_bridge_lighting.py tests/unit/test_host_io_binding_manifest.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the bindings (rebuild: `cmake --build build -j 8`), host_io wrappers, `lights.build`, `glow.captures`, `probe_scales`, runtime push. Update the existing tests that assert the old 9-tuple spot rows / 2-value scales in the same commit.
- [ ] **Step 4: Run** the Step 2 command plus `uv run pytest tests/host/test_bridge_editor_bindings.py tests/unit -k bridge -q` — Expected: PASS.
- [ ] **Step 5: Commit**
```bash
git add native/src/host/host_bindings.cc engine/host_io.py engine/bridge_lighting.py engine/bridge_editor/lights.py engine/bridge_editor/glow.py engine/bridge_editor/runtime.py tests/unit/test_bridge_lights.py tests/unit/test_bridge_glow.py tests/unit/test_bridge_runtime.py tests/unit/test_bridge_lighting.py tests/unit/test_host_io_binding_manifest.py tests/host/test_bridge_editor_bindings.py
git commit -m "feat(bridge-reflections): per-state capture rows, glow captures and layers reach the renderer"
```

---

### Task 4: Probe storage — cube-map array, spare slot, shared scratch, stepped capture

**Files:**
- Create: `native/src/renderer/include/renderer/bridge_probe_array.h`, `native/src/renderer/bridge_probe_array.cc` (add to `native/src/renderer/CMakeLists.txt`)
- Modify: `native/src/renderer/shaders/probe_prefilter.frag` only if a layered target needs it (prefer `glFramebufferTextureLayer` with the existing shader)
- Test: `native/tests/renderer/bridge_probe_array_test.cc`

**Interfaces:**
- Produces:
  ```cpp
  class BridgeProbeArray {
  public:
      bool ensure(int slots);            // >= slots usable + 1 spare; grows by blit, never shrinks below
      void shrink_to(int slots);         // frees surplus; keeps slots [0, slots)
      int  capacity() const;             // usable slots (excludes the spare)
      // Stepped capture of one probe into the spare slot:
      void begin(int slot);              // slot that will receive it on completion
      template <class DrawFace> bool step(glm::vec3 origin, DrawFace draw_face); // one step; true when the probe has been swapped in
      bool in_flight() const; int in_flight_slot() const;
      void abandon();                    // drop the in-flight probe (new room)
      int  steps_per_probe() const;      // 6 face steps + kBridgeProbeMips prefilter steps
      std::uint32_t texture() const;     // GL_TEXTURE_CUBE_MAP_ARRAY, R11F_G11F_B10F, 384², 6 mips
      int  layer_of(int slot) const;     // array layer currently holding `slot` (the spare swaps)
      bool valid(int slot) const;
  };
  ```
  Slot→array-layer indirection (`layer_of`) is how the swap works: completion swaps the in-flight slot's array layer with the spare's. The shader indexes by `layer_of(slot)`.
- `BridgeProbe` / `CubemapTarget` stay for the sky backdrop; the bridge pass stops using `BridgeProbe` in Task 6. `BrdfLut` unchanged.

- [ ] **Step 1: Write the failing tests** (GL fixture as `BridgeProbeGl` in `bridge_probe_test.cc`):
  - `SteppedCaptureMatchesOneShot` — a draw_face that clears each face to a distinct colour; stepping to completion equals `BridgeProbe::capture` texels at mip 0 and mip 3 (tolerance: R11G11B10F, 1/64 relative).
  - `OldContentShowsUntilTheSwap` — slot 0 captured red; begin a blue recapture, run all but the last step → `layer_of(0)` texels still red; last step → blue.
  - `GrowKeepsExistingSlots` — `ensure(2)`, capture slots 0 and 1, `ensure(6)` → slots 0 and 1 read back the same (blit copy, every mip).
  - `AbandonLeavesTheSlotUntouched`.
  - `StepRestoresTheCallersGlState` — FBO, viewport, program, VAO, texture bindings, enables (the `BridgeProbe` restore list).
  - `FormatIsR11G11B10F` — `glGetTexLevelParameteriv(GL_TEXTURE_CUBE_MAP_ARRAY, 0, GL_TEXTURE_INTERNAL_FORMAT)`.
- [ ] **Step 2: Run** `cmake --build build -j 8 --target renderer_tests && ./build/native/tests/renderer/renderer_tests --gtest_filter='BridgeProbeArray*'` — Expected: build FAIL.
- [ ] **Step 3: Implement.** Faces render into the shared RGBA16F raw cube (one allocation, 384², full chain); the prefilter steps write the spare slot's 6 faces at one mip each via `glFramebufferTextureLayer(..., level, layer*6 + face)`; grow = allocate a bigger array, `glBlitFramebuffer` every (layer, face, mip), delete the old. If R11G11B10F is not colour-renderable here, fall back to RGBA16F and record it in the plan's as-built note (spec §4.6).
- [ ] **Step 4: Run** the filter, then `./build/native/tests/renderer/renderer_tests --gtest_filter='BridgeProbe*:PipelineTest.*'` — Expected: PASS.
- [ ] **Step 5: Commit**
```bash
git add native/src/renderer/include/renderer/bridge_probe_array.h native/src/renderer/bridge_probe_array.cc native/src/renderer/CMakeLists.txt native/tests/renderer/bridge_probe_array_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(bridge-reflections): cube-map-array probe storage with spare slot and stepped capture"
```

---

### Task 5: Capture content per probe (glow in, per-state lights, layers isolated)

**Files:**
- Modify: `native/src/renderer/bridge_pass.cc` (capture-face draw), `native/src/renderer/shaders/bridge.frag` (capture branch)
- Test: `native/tests/renderer/bridge_probe_content_test.cc` (new; reuse `BridgePbrFrame`'s synthetic room helpers — move them to a shared `bridge_test_room.h` in `native/tests/renderer/` if both files need them)

**Interfaces:**
- Consumes: Task 2 data, Task 4 `BridgeProbeArray`.
- Produces: `void BridgePass::capture_probe_now(int probe, const scenegraph::World&, Pipeline&, const ModelLookup&, const Lighting&);` — a whole probe in one go (test seam and the body Task 6 slices). New capture uniforms: `u_capture_state` (0–4), `u_capture_layer` (-1 base / k), `u_capture_glow_rgb`, `u_capture_glow_src` per draw.
- Content rules (spec §4.1): base s — ambient × `probe_scale(s)`; lights at `capture_radiance[s]`; glow-capture meshes at `base[s]` through their `src` (map variant `bridge_emissive_texture(mat, s)`); meshes with no glow capture show the texture-level `_emissive` default for state s (dark at offline). Layer k (state s = its state) — ambient 0; lights at `layer_radiance[s]` only where `layer[s] == k`, else 0; glow only where the glow capture's `layer[s] == k`, at `layer_rgb[s]`; no texture-level default. Every probe: diffuse capped by its own ceiling (`decode(diffuse_ceiling(encode(lit)))`), then `+ decode(glow)` uncapped; officers and the viewscreen as today.

- [ ] **Step 1: Write the failing tests:**
  - `GlowShowsInTheBase` — a flat-glow quad (src 2, base[0] = (2, 2, 2)) seen by a face → that face's texel ≈ `pow(2, 2.2)` (uncapped, > the ceiling).
  - `OfflineBaseDarkensTheTextureDefault` — a mesh with an `_emissive` texture and no glow capture: base 0 shows it, base 3 does not.
  - `AnimatedMemberIsAbsentFromItsBase` — spot with `capture_radiance[2] = 0`, `layer[2] = 0`: base 2 matches a room with no spot.
  - `LayerHoldsOnlyItsMembers` — two spots, one in layer 0: layer probe 5 is black where only the non-member reaches; non-zero under the member.
  - `BasePlusWeightedLayerEqualsTheFullCapture` — **the linearity falsifier**, room lit below the knee: probe A = base 2 with the member spot's `capture_radiance[2] = L × 0.6^2.2` and no layer; probes B (base 2, member at 0) and C (layer, `layer_radiance[2] = L`) → `A ≈ B + 0.6^2.2 × C` per texel (RGB11 tolerance), for a spot member AND a flat-glow member. Mutation check (document it in the test comment, do it once): with the capture's glow `decode` removed the glow case must FAIL.
- [ ] **Step 2: Run** `cmake --build build -j 8 --target renderer_tests && ./build/native/tests/renderer/renderer_tests --gtest_filter='BridgeProbeContent*'` — Expected: FAIL.
- [ ] **Step 3: Implement** the capture-face draw (sub-pass A only, `capture_pass_` set, the probe id in a member) and the capture branch in `bridge.frag`.
- [ ] **Step 4: Run** the filter plus `--gtest_filter='BridgePbrFrame*:PipelineTest.*'` — Expected: PASS.
- [ ] **Step 5: Commit**
```bash
git add native/src/renderer/bridge_pass.cc native/src/renderer/shaders/bridge.frag native/tests/renderer/bridge_probe_content_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(bridge-reflections): probes capture glow, per-state lights and isolated layers"
```

---

### Task 6: Capture scheduler — queue, priority, time-slicing, snapshot, requeue

**Files:**
- Create: `native/src/renderer/include/renderer/bridge_probe_schedule.h` (pure, header-only)
- Modify: `native/src/renderer/bridge_pass.{h,cc}` (replace `probe_green_`/`probe_yr_`/`capture_probes` with `BridgeProbeArray` + the queue), `native/src/renderer/include/renderer/bridge_lighting_tuning.h`
- Test: `native/tests/renderer/bridge_probe_schedule_test.cc` (CPU), `native/tests/renderer/bridge_pbr_frame_test.cc` (migrate)

**Interfaces:**
- Produces:
  - `int next_probe(int shown_state, const std::vector<int>& layer_states, const std::function<bool(int)>& needs);` — order: base `shown_state`; layers of `shown_state` (index order); other bases in index order; other layers in index order; -1 when none.
  - `inline constexpr int kBridgeProbeStepsPerFrame = 1;` (tuning; tuned live with the profiler, spec §4.7).
  - `void BridgePass::set_probe_steps_per_frame(int n);` — test seam, `0` = unlimited (a whole queue drains inside one `render()`).
  - `bool BridgePass::probe_valid(int probe) const;` `bool BridgePass::probes_settled() const;` (nothing queued or in flight); `int BridgePass::probe_captures_completed(int probe) const;` (test accessor: completed captures per probe since construction). `probes_valid()` → true once the shown state's base is valid.
  - Snapshot: at a probe's `begin`, copy spots, areas, glow captures, overrides, scales, ambient and record its signature; every face of that probe draws from the snapshot. Completion stores the snapshot signature as "captured"; `needs(p)` = `!valid(p) || captured_sig[p] != probe_signature(p)`.
  - A different bridge model or a `request_probe_capture()` mid-flight → `abandon()`.
  - Storage: `ensure(probe_count())` on a layer-count change; `shrink_to` when it drops.
- Profiler: `DAUNTLESS_FRAME_SCOPE("bridge.probe_capture")` around each step (include `renderer/frame_timer.h`).

- [ ] **Step 1: Write the failing tests:**
  - CPU `BridgeProbeSchedule`: `ShownBaseFirstThenItsLayersThenOthers` — `layer_states = {0, 2}` (layer 0 = probe 5 at green, layer 1 = probe 6 at red), shown 2, every probe needed, marking each returned probe done: the sequence is exactly `2, 6, 0, 1, 3, 4, 5`; `NothingNeededReturnsMinusOne`.
  - GL in `bridge_pbr_frame_test.cc` (add helper `settle(pass)`: render until `probes_settled()`, max 500 frames):
    - `CaptureIsSpreadAcrossFrames` — steps per frame 1: the first `render()` after load leaves `probes_settled() == false` and no probe valid; after `steps_per_probe()` renders the shown base is valid.
    - `ARedOnlyEditRequeuesOnlyTheRedBase` — settled; change a spot's red capture; settle → `probe_captures_completed(2)` grew by 1, every other probe's count unchanged; `probe_valid(2)` stayed true on every frame in between.
    - `AnInputChangeMidCaptureFinishesThenRequeuesOnce` — change during flight; the probe completes (counter +1) then recaptures once more (counter +2), then settles.
    - `ANewBridgeModelMidCaptureDiscardsTheInFlightProbe`.
    - Migrate every existing `BridgePbrFrame` probe test to `set_probe_steps_per_frame(0)` or `settle()`; `ProbesAreNotRecapturedEveryFrame` becomes "no step runs once settled".
- [ ] **Step 2: Run** `cmake --build build -j 8 --target renderer_tests && ./build/native/tests/renderer/renderer_tests --gtest_filter='BridgeProbeSchedule*:BridgePbrFrame*'` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the filter, then `ctest --test-dir build -j 8` — Expected: PASS.
- [ ] **Step 5: Commit**
```bash
git add native/src/renderer/include/renderer/bridge_probe_schedule.h native/src/renderer/include/renderer/bridge_pass.h native/src/renderer/bridge_pass.cc native/src/renderer/include/renderer/bridge_lighting_tuning.h native/tests/renderer/bridge_probe_schedule_test.cc native/tests/renderer/bridge_pbr_frame_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(bridge-reflections): time-sliced probe capture queue with snapshot and spare-slot swap"
```

---

### Task 7: Shading — weighted bases + layers, C++ state fade, debug views

**Files:**
- Modify: `native/src/renderer/include/renderer/bridge_probe_schedule.h` (add `ProbeFade`), `native/src/renderer/bridge_pass.{h,cc}`, `native/src/renderer/shaders/bridge.frag`, `native/src/renderer/include/renderer/bridge_pass.h` (`BridgeDebugView::ReflectionLayers = 11`), `engine/ui/developer_options_panel.py:103` (label `"Reflection layers"`)
- Test: `native/tests/renderer/bridge_probe_schedule_test.cc`, `native/tests/renderer/bridge_pbr_frame_test.cc`

**Interfaces:**
- Produces:
  - `struct ProbeFade { float w[kBridgeStates]; void update(int target, float dt, const std::function<bool(int)>& base_valid); };` — fade 0.5 s: if the target base is invalid, weights hold; if all weights are 0 and the target is valid, target snaps to 1; else target += dt/0.5, others −= dt/0.5, clamp [0, 1], renormalise to sum 1.
  - `void BridgePass::set_probe_state(int state, float dt);` (replaces `set_probe_mix`) and `void BridgePass::set_layer_values(std::vector<float> v);` (per layer `w^2.2`; missing → 0, non-finite → 0); `float base_weight(int state) const;`.
  - Shader: `uniform samplerCubeArray u_probes;` (unit 7; unit 8 freed), `uniform int u_probe_entries;` `uniform int u_probe_layer[19];` `uniform float u_probe_weight[19];` (≤ 3 bases + 16 layers); entries sent = bases with weight > 0 + layers whose state weight > 0, weight = `layer_value × base_weight(state)`. `u_probe_mix`, `u_probe_a`, `u_probe_b` removed.
  - Debug view 9 = the composed entries sampled unprojected at mip 0; view 11 = layer entries only.
- [ ] **Step 1: Write the failing tests:**
  - CPU: `FadeSettlesOnTheTarget`, `FirstValidTargetSnaps`, `InvalidTargetHoldsTheCurrentWeights`, `RetargetMidFadeIsContinuous` (green→red at 0.3, then yellow: every step changes each weight by ≤ dt/0.5 + 1e-6, sum == 1), `FadeFreezesAtZeroDt`.
  - GL: `ALayerAddsItsWeightedReflection` — smooth metal floor, a red member spot in layer 0 at state 2: `set_layer_values({1})` brighter than `{0}`, and `{0}` equals the room without the member; `StateChangeCrossFadesTheBases` — migrate `ProbeMixCrossFadesBetweenTheTwoProbes` to `set_probe_state` (green settled → red, after 0.25 s both contribute, after 0.5 s only red); `ReflectionLayersViewShowsOnlyLayers`; keep `ReflectionOfALitRoomNeverReachesTheThreshold` and `ProbeUnitsAreUnboundAfterRender` passing (unbind unit 7 as a cube-map array).
- [ ] **Step 2: Run** `cmake --build build -j 8 --target renderer_tests && ./build/native/tests/renderer/renderer_tests --gtest_filter='BridgeProbeSchedule*:BridgePbrFrame*:PipelineTest.*'` — Expected: FAIL.
- [ ] **Step 3: Implement**; the `set_bridge_probe_mix` binding becomes a no-op (Python keeps calling it until Task 8 deletes it).
- [ ] **Step 4: Run** the filter and `ctest --test-dir build -j 8` — Expected: PASS.
- [ ] **Step 5: Commit**
```bash
git add native/src/renderer/include/renderer/bridge_probe_schedule.h native/src/renderer/include/renderer/bridge_pass.h native/src/renderer/bridge_pass.cc native/src/renderer/shaders/bridge.frag engine/ui/developer_options_panel.py native/tests/renderer/bridge_probe_schedule_test.cc native/tests/renderer/bridge_pbr_frame_test.cc
git commit -m "feat(bridge-reflections): weighted base and layer reflections with renderer-side state fade"
```

---

### Task 8: Per-frame wiring — state, layer values, quality changes

**Files:**
- Modify: `native/src/host/host_bindings.cc` (new `set_bridge_probe_state`, `set_bridge_layer_values`; remove `set_bridge_probe_mix`, stash `mix`, `bridge_probe_state()["mix"]` → `"base_weights"` 5-tuple), `engine/host_io.py`, `engine/host_loop.py` (~12885: replace `_bridge_probe_blend.update` / `set_bridge_probe_mix`; delete `_bridge_probe_blend`), `engine/bridge_lighting.py` (delete `ProbeBlend`), `engine/bridge_editor/runtime.py` (`tick`)
- Test: `tests/unit/test_bridge_runtime.py`, `tests/unit/test_bridge_lighting.py` (delete `ProbeBlend` tests), `tests/unit/test_host_io_binding_manifest.py`, `tests/host/test_bridge_editor_bindings.py`

**Interfaces:**
- Consumes: Task 1 `layer_values`, `layer_cap`; Task 7 `set_probe_state`, `set_layer_values`.
- Produces: `host_io.set_bridge_probe_state(state: int, dt: float)`, `host_io.set_bridge_layer_values(values: list[float])`. `BridgeRuntime.tick(dt)` pushes `set_bridge_layer_values(probe_layers.layer_values(self._plan, self._t))` with the glow/light live push, and re-plans (`self.push(self._doc)`) when `self._io.bridge_quality()` differs from the value the plan was built with. host_loop calls `host_io.set_bridge_probe_state(_bridge_alert_level, _bridge_dt)` where it called `set_bridge_probe_mix`.
- [ ] **Step 1: Write the failing tests:**
  - `test_tick_pushes_layer_values` — DBridge-shaped doc, `tick(0.75)` → fake io got `[≈ 0.6 ** 2.2]`.
  - `test_layer_values_freeze_under_pause` — `tick(0)` twice → equal values.
  - `test_quality_change_replans_layers` — 3 distinct red waves; io quality 1 (cap 4) → 3 layers; switch to 0 (cap 2) → next tick pushes 2 layers and a warning naming the third.
  - `tests/host/test_bridge_editor_bindings.py::test_probe_state_holds_without_a_valid_base` — real binding, no bridge drawn: `set_bridge_probe_state(2, 1.0)` is accepted and `bridge_probe_state()["base_weights"] == (0.0,) * 5` (no base valid ⇒ weights hold). The fade itself is pinned by Task 7's GL and CPU tests.
  - Manifest test updated (`set_bridge_probe_mix` gone).
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_bridge_runtime.py tests/unit/test_bridge_lighting.py tests/unit/test_host_io_binding_manifest.py tests/host/test_bridge_editor_bindings.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement**; rebuild (`cmake --build build -j 8`). `grep -rn "probe_mix\|ProbeBlend\|_bridge_probe_blend" engine native/src tests` must return nothing.
- [ ] **Step 4: Run** the Step 2 command and `uv run pytest tests/unit -k bridge -q` — Expected: PASS.
- [ ] **Step 5: Commit**
```bash
git add native/src/host/host_bindings.cc engine/host_io.py engine/host_loop.py engine/bridge_lighting.py engine/bridge_editor/runtime.py tests/unit/test_bridge_runtime.py tests/unit/test_bridge_lighting.py tests/unit/test_host_io_binding_manifest.py tests/host/test_bridge_editor_bindings.py
git commit -m "feat(bridge-reflections): per-frame probe state and layer values; quality re-plans layers"
```

---

### Task 9: Measure, document, gate, hand over

**Files:**
- Modify: `docs/superpowers/specs/2026-10-17-bridge-reflection-layers-design.md` (add §8 As built: step size chosen, measured per-step cost, storage format actually used, deviations), `CLAUDE.md` (the "Bridge PBR" row: probes = 5 per-state bases + (state, wave) layers capped 2/4/8, 384² R11G11B10F array, time-sliced, glow in reflections), `docs/reference/engine/frame-profiler.md` (the `bridge.probe_capture` scope)

- [ ] **Step 1:** Ask Mark before launching. With a yes: `OPEN_STBC_HOST_HEADLESS=1 DAUNTLESS_PROFILE_FRAMES=600 ./build/dauntless --developer` from the worktree, read `bridge` (GPU) and `bridge.probe_capture` (CPU) during the fill and once settled; tune `kBridgeProbeStepsPerFrame` (and the step definition) so a fill frame stays within a few ms of GPU over the settled `bridge` cost; record the numbers in §8.
- [ ] **Step 2:** Run `scripts/check_tests.sh` — Expected: exit 0, no new ledger lines.
- [ ] **Step 3:** Commit the docs:
```bash
git add docs/superpowers/specs/2026-10-17-bridge-reflection-layers-design.md CLAUDE.md docs/reference/engine/frame-profiler.md
git commit -m "docs(bridge-reflections): as built, CLAUDE.md row, profiler scope"
```
- [ ] **Step 4:** Hand Mark the live recipe: `cd .claude/worktrees/bridge-reflections && ./build/dauntless --developer` → Quick Battle (Galaxy → DBridge) → pause → Bridge Editor… → preview squares ⬛🟩🟨🟥🟦: each state reflects its own lighting; at 🟥 the red bars, Map 22a/27 and the alcove pulse in the glossy surfaces in step with the objects (floor 20%); no hitch on load or on a state click; Developer Options → Lighting → Bridge Debug View "Reflection layers" shows only the pulse.
