# Radius-Relative Dynamic-Light Falloff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make dynamic-light attenuation radius-relative above a ship-scale ceiling so large (station-scale) emitter lights actually cast on the hull, while every existing ship/torpedo light stays byte-identical.

**Architecture:** One curve change to the shared `dynamic_light_attenuation` (C++ `dynamic_lights.cc`) and its bit-matched GLSL twin (`opaque.frag`), gated by a threshold-offset so `radius ≤ R0` is unchanged. Two new shared constants. Unit-test additions. No data/persistence/shader-uniform changes.

**Tech Stack:** C++ (GoogleTest/ctest), GLSL, no Python.

**Design doc:** `docs/superpowers/specs/2026-08-05-dynamic-light-radius-relative-falloff-design.md`

## Global Constraints

- **C++ `dynamic_light_attenuation` and the GLSL in `opaque.frag` MUST stay bit-matched** (existing contract comment). Use `ratio*ratio*ratio*ratio` (NOT `pow`); `R0` and `k` appear as the **same literals** in both.
- **`radius ≤ R0` behaviour byte-identical** to today (`ref = 1`). The existing `dynamic_lights_test.cc` numeric rows use radius 10 ≤ R0 and MUST stay green unchanged — they are the regression guard.
- Invariants preserved at every radius: `att(0, r) = 1`, `att(d ≥ radius, r) = 0`, `radius ≤ 0 → 0`.
- Shader edit ⇒ `cmake -B build -S .` reconfigure BEFORE `cmake --build build`. Gate: `scripts/check_tests.sh`.
- Frame tests are assertion-based (litness / cone-gate / no-GL-error), NOT golden images — they are expected to stay green with no re-baseline.
- `R0`/`k` are constants (rebuild to change), the tuning knobs; default `R0 = 40.0`, `k = 0.3`.

---

### Task 1: Threshold-offset radius-relative attenuation

**Files:**
- Modify: `native/src/renderer/dynamic_lights.cc` (the `dynamic_light_attenuation` function)
- Modify: `native/src/renderer/include/renderer/dynamic_lights.h` (add the two constants + doc)
- Modify: `native/src/renderer/shaders/opaque.frag` (the bit-matched GLSL, ~line 505-509)
- Modify: `native/tests/renderer/dynamic_lights_test.cc` (add reach + byte-identity assertions)

**Interfaces:**
- Consumes: existing `dynamic_light_attenuation(float d, float radius)` (C++) and its GLSL twin; `light_score`/`select_dynamic_lights` (call the same function — no signature change).
- Produces: same signature, new curve. Two `constexpr float` constants (`kDynLightShipCeilingGU = 40.0f`, `kDynLightFalloffK = 0.3f`) in `dynamic_lights.h`.

- [ ] **Step 1: Write the failing test**

In `native/tests/renderer/dynamic_lights_test.cc`, ADD (do NOT modify the existing `att(0,10)`/`att(5,10)=0.0338…`/`att(10,10)`/`att(20,10)` rows — they must stay green as the byte-identity guard). Add a new test:

```cpp
TEST(DynamicLightAttenuation, RadiusRelativeReachAboveShipCeiling) {
    using renderer::dynamic_light_attenuation;
    // radius 208 (>> R0): a fragment 30 GU from the light must now be
    // substantial, not the ~0.0011 the old absolute inverse-square gave.
    const float far_att = dynamic_light_attenuation(30.0f, 208.0f);
    EXPECT_GT(far_att, 0.3f)
        << "station-scale light must reach ~30 GU; old curve gave ~0.001";
    // Sub-ceiling radius is byte-identical to the old absolute inverse-square.
    // radius 10 <= R0 => ref == 1 => (w*w)/(d*d+1).
    const float d = 5.0f, r = 10.0f;
    const float ratio = d / r;
    const float w = 1.0f - ratio*ratio*ratio*ratio;
    const float expected_old = (w*w) / (d*d + 1.0f);
    EXPECT_FLOAT_EQ(dynamic_light_attenuation(d, r), expected_old);
    // Boundary invariants hold at large radius too.
    EXPECT_NEAR(dynamic_light_attenuation(0.0f, 208.0f), 1.0f, 1e-5f);
    EXPECT_FLOAT_EQ(dynamic_light_attenuation(208.0f, 208.0f), 0.0f);
}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cmake --build build -j --target dynamic_lights_test 2>/dev/null || cmake --build build -j
ctest --test-dir build -R DynamicLightAttenuation.RadiusRelativeReachAboveShipCeiling --output-on-failure
```
Expected: FAIL — `RadiusRelativeReachAboveShipCeiling` fails on `far_att > 0.3` (old curve gives ~0.0011). The byte-identity + boundary lines pass.

- [ ] **Step 3: Add the constants**

In `native/src/renderer/include/renderer/dynamic_lights.h`, near the existing declarations, add:

```cpp
// Ship-scale ceiling (GU): dynamic lights at or below this radius keep the
// legacy absolute inverse-square falloff (ref == 1, byte-identical). Above it,
// the inverse-square reference grows so a station-scale light stays bright
// across its (large) volume instead of collapsing at a fixed 1 GU reference.
// MUST match the literal in opaque.frag.
constexpr float kDynLightShipCeilingGU = 40.0f;
// Falloff-reference growth per GU of radius above the ceiling. Tuning knob.
// MUST match the literal in opaque.frag.
constexpr float kDynLightFalloffK = 0.3f;
```

- [ ] **Step 4: Change the C++ curve**

In `native/src/renderer/dynamic_lights.cc`, replace the body of `dynamic_light_attenuation`:

```cpp
float dynamic_light_attenuation(float d, float radius) {
    if (radius <= 0.0f) return 0.0f;
    const float ratio = d / radius;
    const float w = glm::clamp(1.0f - ratio * ratio * ratio * ratio, 0.0f, 1.0f);
    // Inverse-square reference grows with radius ABOVE the ship-scale ceiling
    // (threshold-offset): ref == 1 below the ceiling => legacy curve. See
    // dynamic_lights.h. MUST bit-match opaque.frag.
    const float ref = 1.0f + std::max(0.0f, radius - kDynLightShipCeilingGU)
                              * kDynLightFalloffK;
    const float dr = d / ref;
    return (w * w) / (dr * dr + 1.0f);
}
```

(Ensure `<algorithm>` for `std::max` is included — it already is.)

- [ ] **Step 5: Change the GLSL twin (bit-matched)**

In `native/src/renderer/shaders/opaque.frag`, in the dynamic-light loop (~line 505-509), replace the attenuation lines so they compute the SAME value. Keep `ratio*ratio*ratio*ratio` (no `pow`). Use the same literals `40.0` and `0.3`:

```glsl
        float ratio = d / radius;
        // ratio*ratio*ratio*ratio, NOT pow(ratio,4): GPU pow is not correctly
        // rounded; must bit-match renderer::dynamic_light_attenuation.
        float w   = clamp(1.0 - ratio*ratio*ratio*ratio, 0.0, 1.0);
        // Threshold-offset radius-relative reference (kDynLightShipCeilingGU=40,
        // kDynLightFalloffK=0.3 in dynamic_lights.h — keep in sync).
        float ref = 1.0 + max(0.0, radius - 40.0) * 0.3;
        float dr  = d / ref;
        float att = (w * w) / (dr * dr + 1.0);
```

(Replace the existing `float ratio`/`float w`/`float att` block; leave the segment-distance, `L`, `nl`, and spot-gate code around it unchanged.)

- [ ] **Step 6: Reconfigure (shader changed), rebuild, run the unit test**

```bash
cmake -B build -S .            # REQUIRED: opaque.frag changed
cmake --build build -j
ctest --test-dir build -R DynamicLightAttenuation --output-on-failure
```
Expected: PASS — the new `RadiusRelativeReachAboveShipCeiling` test and the existing (unchanged) attenuation rows all green.

- [ ] **Step 7: Confirm the whole renderer test suite (frame tests included) stays green**

```bash
ctest --test-dir build --output-on-failure -R "DynamicLight|Frame|ConeLight|GlowRegion|Breach|Sun"
```
Expected: PASS. The assertion-based frame tests (`test_cone_light_frame` on-axis-lit / off-axis-cone-gated, `frame_test` no-GL-error) stay green with the brighter curve. If any assertion flips, investigate the specific assertion (do NOT loosen blindly) — a flip on a litness assertion should only ever be "still lit / more lit", never "went dark".

- [ ] **Step 8: Full gate**

```bash
scripts/check_tests.sh
```
Expected: OK — no new failures (1 known baselined). No golden re-baseline.

- [ ] **Step 9: Commit**

```bash
git add native/src/renderer/dynamic_lights.cc native/src/renderer/include/renderer/dynamic_lights.h native/src/renderer/shaders/opaque.frag native/tests/renderer/dynamic_lights_test.cc
git commit -m "feat(renderer): radius-relative dynamic-light falloff above ship-scale ceiling"
```

---

## Self-review notes

- **Spec coverage:** the single curve change + constants + bit-matched GLSL + unit tests = the whole spec. One task (atomic renderer change; splitting would leave the gate red between tasks).
- **Type consistency:** `dynamic_light_attenuation(float, float)` signature unchanged; constants are `constexpr float`; GLSL literals `40.0`/`0.3` match the C++ constants `kDynLightShipCeilingGU`/`kDynLightFalloffK`.
- **Risk:** bit-match drift between C++ and GLSL (mitigated: same literals, same `ratio*ratio*ratio*ratio` form, reviewer diffs both); an unexpected frame-assertion flip (Step 7 catches it). `R0`/`k` are tuned in-game post-merge by Mark.
