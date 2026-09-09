# Field-Authoritative Hull Holes Implementation Plan (Plan 2c)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee that every hull fragment the renderer cuts away has damage in the field behind it, so no hole can ever be see-through.

**Architecture:** The damage field becomes the *admission authority*: a hole may only exist where the field says damaged. The field cannot represent sub-cell detail, so the analytic sphere path stays on as a *refinement* that carves fine rim shape and struts strictly **inside** the field's damaged region. Containment is established by making the brush conservative — it dilates each carve to the smallest shape the lattice can actually hold — and is then locked in by a test.

**Tech Stack:** GLSL 410, C++20 (`native/src/voxel`, `native/src/renderer`), GoogleTest.

**Spec:** `docs/superpowers/specs/2026-09-08-dauntless-hull-volumes-design.md` (§7)

## Why this slice, and what changed since the spec was written

Plan 2b moved the interior onto the field. That exposed a defect the whole-plan review caught and this plan fixes:

**`breach.frag:335` bails if the field at the ray's entry point does not already read carved** — and for a fresh combat hit it usually does not. Measured coverage of the *analytically cut* hole by the field, on a real Galaxy lattice (`authored_res` 10, quality 2, cell 5.0 model units), across random sub-cell carve placements:

| carve radius (model units) | 3 | 5 | 8 | 10 | 20 | 30 |
|---|---|---|---|---|---|---|
| mean coverage | 3.7% | 6.9% | 63.4% | 67.6% | 96.5% | 98.7% |
| **worst placement** | **0%** | **0%** | **0%** | **0%** | 79.1% | 91.4% |

Combat hits start at radius 3. So today essentially every fresh hole is cut with nothing behind it, and even a radius-10 hole is see-through for unlucky placements. The root cause is representability, not a coding error: a carve's half-depth is `0.45 * radius`, which is **thinner than one cell for every radius below ~11**, so the brush's positive region does not survive trilinear reconstruction.

Two consequences for the spec:

1. **The fix is a conservative brush**, not more resolution. Flooring the carve's half-depth at `1.25` cells and adding a `1.25`-cell constant offset to the brush lifts worst-case coverage to **100%** across the full authored range (cell 3.0 / 5.0 / 7.5) and radius range (3–30), measured against `opaque.frag`'s own `e < 1.0` hole test including its rim noise and hull curvature.
2. **§7's "retire the sphere list" is NOT achievable at this lattice resolution, and this plan deliberately does not attempt it.** The rim noise is ±25% of the radius (0.75–7.5 model units) and the framework struts are thinner still — both are *sub-cell* features at cell 3.0–7.5. Baking them into the field would not sharpen the hole, it would **erase** the jagged rim and the struts, which is the exact appearance the live pass approved. The sphere list survives as the sub-cell detail layer. Task 5 records this in the spec.

The cost of the conservative brush is that the field's damaged region is **1.7× the nominal rim on average, up to 3.3×** for a tiny carve on a coarse lattice. That excess is invisible wherever a tracked carve governs (Task 2 suppresses it there) and shows only as slightly generous holes beyond the 24-carve ring.

Deliberately **NOT** in scope:

- **Switching the brush to a normalised ellipsoid SDF.** It measures better (1.55× average growth instead of 1.76×) and would improve `breach_field_gradient`'s shading normals, but it changes the shape formula *and* the dilation at once, and a bad live result would not say which. Note it for a later pass.
- **Raising `kDefaultQuality` above 2.** Would shrink the dilation proportionally, at 8× the memory per instance for quality 4. Only worth doing if the live pass says the generous beyond-ring holes read badly.
- **Deleting `carve_has_backing`.**

## Global Constraints

1. **Never add a `sampler3D` to `opaque.frag`** — measured to corrupt shading across `TangentBasisTest`, `ConeLightFrameTest`, `ExplosionLightFrameTest` and `CloakAmbientParityTest` even on an unreachable branch.
2. **After ANY shader change, run the FULL `renderer_tests` binary, never a filter.** The corruption appears in suites you would not think to filter for.
3. **Shaders are embedded at CONFIGURE time.** Always `cmake -B build -S .` before `cmake --build build -j` when a `.frag`/`.vert` changed, or you will test a stale shader and believe it worked.
4. **The atlas carries DAMAGE, not hull geometry.** Every cell starts at `-127` ("no damage"); only the brushes raise a cell. Untouched hull must never be discarded or shaded as interior.
5. **The encoding is `d + 128`**, so **`128/255` is the boundary, not `0.5`**. Comments asserting `0.5` have been wrong here twice.
6. **The brush must stay monotonic.** `d_new = max(d_old, ...)` — a carve may only ever remove material. Every change in Task 1 keeps the `max()` structure and never inspects `d_old`.
7. **MAIN CHECKOUT, shared with concurrent sessions.** Stage with explicit pathspecs only. `.claude/`, `mods/` and a modified `.gitignore` belong to another session — never stage or touch them. The destructive git commands banned by CLAUDE.md's "Shared checkout" section are banned here too; a PreToolUse hook enforces it. To revert a temporary mutation, `cp` the file to `/tmp` first, restore with `cp`, and `diff` to prove the restore.
8. Never spell `game` or `sdk` as a path segment. 1 model unit = 0.01 GU; 1 GU = 175 m.
9. Gate: `./scripts/check_tests.sh` exit 0 — **read its OUTPUT, not a pipeline's exit code**; it prints a `NEW FAILURES (not in baseline)` banner on failure. Only `test_shield_level_change_announces` is baselined.
10. Commit messages end with:
    `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## The invariant this plan establishes

> **Every point that `opaque.frag` discards as hull must sample the damage field above the iso margin.**

Hole ⊆ field-damaged. Task 1 makes it true, Task 4 makes a test fail if it ever stops being true. Every other task depends on it.

## File structure

| File | Responsibility |
|---|---|
| `native/src/voxel/include/voxel/field_brush.h` | The four shared constants and the brush contract |
| `native/src/voxel/src/field_brush.cc` | Conservative oblate brush (Task 1) |
| `native/src/renderer/shaders/opaque.frag` | Hole admission: suppression bound (Task 2), noisy field rim (Task 3) |
| `native/src/renderer/frame.cc` | No field ⇒ no holes (Task 2) |
| `native/tests/voxel/field_brush_test.cc` | The containment invariant (Tasks 1, 4) |
| `native/tests/renderer/hull_field_clip_test.cc` | GLSL/C++ constant parity, one-sided rim noise (Tasks 2, 3) |
| `docs/superpowers/specs/2026-09-08-dauntless-hull-volumes-design.md` | §7 correction (Task 5) |

---

### Task 1: Conservative brush — make every carve representable

**Files:**
- Modify: `native/src/voxel/include/voxel/field_brush.h`
- Modify: `native/src/voxel/src/field_brush.cc:11-76`
- Test: `native/tests/voxel/field_brush_test.cc`

**Interfaces:**
- Consumes: `voxel::DistanceField` (`dims`, `origin`, `cell` (a `glm::vec3`), `scale`, `dist`, `index(x,y,z)`), `voxel::kCarveDepthFactor`.
- Produces: four constants that Task 2's GLSL must mirror exactly —
  `voxel::kCarveDepthFactor = 0.45f` (unchanged),
  `voxel::kCarveRimAmp = 0.25f`,
  `voxel::kCarveDepthFloorCells = 1.25f`,
  `voxel::kCarveFieldOffsetCells = 1.25f`.
  `field_carve_oblate`'s signature is **unchanged**.

**Background the implementer needs.** `field_carve_oblate` today builds an oblate with lateral half-extent `radius` and half-depth `0.45 * radius`, evaluates its signed distance, and CSG-subtracts it. Three things are wrong with that for our purpose:

- The lateral extent is `radius`, but `opaque.frag` cuts out to `radius * (1 + kShapeAmp)` = `1.25 * radius` because it perturbs the rim with noise. The outer band was never carved at all.
- The half-depth `0.45 * radius` is under one cell for any radius below ~11 model units, so the brush's positive region vanishes under trilinear reconstruction.
- Even a well-resolved brush is only *tangent* to the hole at the boundary; reconstruction error then puts the reconstructed boundary slightly inside the true one.

The fix is one floor and one offset. Do not change the `max()` CSG structure, the quantisation, or the guard clauses.

- [ ] **Step 1: Write the failing test**

Add to `native/tests/voxel/field_brush_test.cc`, above the test, a helper that reproduces the shaders' reconstruction:

```cpp
// Trilinear reconstruction on CELL CENTRES, matching opaque.frag's
// sample_hull_field: it offsets by -0.5 cell, so an integer sample
// coordinate lands exactly on a stored cell's centre. Returns the value in
// STORED int8 units; the shader's `> 0.5/255` after its /255 normalisation
// is this function's `> 0.5`.
static float trilinear_int8(const voxel::DistanceField& f, const glm::vec3& p) {
    const glm::vec3 g = (p - f.origin) / f.cell - 0.5f;
    const glm::ivec3 i0(int(std::floor(g.x)), int(std::floor(g.y)),
                        int(std::floor(g.z)));
    const glm::vec3 t = g - glm::vec3(i0);
    float acc = 0.0f;
    for (int dz = 0; dz < 2; ++dz)
    for (int dy = 0; dy < 2; ++dy)
    for (int dx = 0; dx < 2; ++dx) {
        const glm::ivec3 ii = glm::clamp(i0 + glm::ivec3(dx, dy, dz),
                                         glm::ivec3(0), f.dims - 1);
        const float w = (dx ? t.x : 1.0f - t.x) * (dy ? t.y : 1.0f - t.y)
                      * (dz ? t.z : 1.0f - t.z);
        acc += w * static_cast<float>(f.dist[f.index(ii.x, ii.y, ii.z)]);
    }
    return acc;
}

// A carve far smaller than one cell must still leave a REPRESENTABLE hole:
// the field, reconstructed the way the shaders reconstruct it, must read
// "damaged" across the whole footprint opaque.frag would cut. Before the
// conservative brush this read -127 everywhere but (at best) one cell, which
// is exactly why breach.frag:335 bailed and holes showed space.
TEST(FieldBrushConservative, SubCellCarveSurvivesReconstruction) {
    voxel::DistanceField f;
    f.dims   = glm::ivec3(24, 24, 24);
    f.cell   = glm::vec3(5.0f, 5.0f, 5.0f);   // Galaxy: authored_res 10 / quality 2
    f.origin = glm::vec3(-60.0f, -60.0f, -60.0f);
    f.scale  = 4.0f * 5.0f / 127.0f;          // kDefaultBandCells * cell / 127
    f.dist.assign(24u * 24u * 24u, static_cast<std::int8_t>(-127));

    // Carve centre deliberately at a cell CORNER -- the worst placement, and
    // the one the coverage sweep found reading 0%.
    const glm::vec3 c(0.0f, 0.0f, 0.0f);
    const glm::vec3 n(0.0f, 0.0f, 1.0f);
    const float radius = 3.0f;                 // a fresh combat hit
    voxel::field_carve_oblate(f, c, n, radius);

    // Sample the hole opaque.frag would cut: the disc at along = 0 out to the
    // UNPERTURBED radius (a strict subset of its noise-perturbed rim).
    int total = 0, damaged = 0;
    for (int i = 0; i < 64; ++i) {
        const float th = 6.28318530718f * float(i) / 64.0f;
        for (int j = 1; j <= 8; ++j) {
            const float rad = radius * float(j) / 8.0f;
            const glm::vec3 p(rad * std::cos(th), rad * std::sin(th), 0.0f);
            ++total;
            if (trilinear_int8(f, p) > 0.5f) ++damaged;
        }
    }
    EXPECT_EQ(damaged, total)
        << "hole fragments with no damage behind them: " << (total - damaged)
        << " of " << total;
}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cmake --build build -j --target voxel_tests && \
  ./build/native/tests/voxel/voxel_tests --gtest_filter='FieldBrushConservative.*'
```

Expected: FAIL, reporting close to all 512 sample points undamaged. If the binary path differs, find it with `find build -name voxel_tests -type f`.

- [ ] **Step 3: Add the constants**

In `native/src/voxel/include/voxel/field_brush.h`, beside `kCarveDepthFactor`:

```cpp
/// Rim-noise amplitude, as a fraction of the carve radius. MUST equal
/// opaque.frag's kShapeAmp. The shader perturbs the hole's lateral radius by
/// +/- this fraction, so the brush's lateral half-extent must be
/// radius * (1 + kCarveRimAmp) to cover the OUTWARD half of that perturbation
/// -- carving only `radius` left an un-backed band around every hole.
inline constexpr float kCarveRimAmp = 0.25f;

/// Minimum carve half-depth, in CELLS. A carve's true half-depth is
/// kCarveDepthFactor * radius, which is under one cell for every radius below
/// about 11 model units -- i.e. for every ordinary combat hit. A feature
/// thinner than a cell does not survive trilinear reconstruction, so the
/// field read "no damage" inside holes the hull shader had already cut and
/// breach.frag's march bailed at its entry point: see-through hull.
/// Flooring the half-depth here is what makes a small carve exist at all.
/// MUST equal opaque.frag's kFieldDepthFloor.
inline constexpr float kCarveDepthFloorCells = 1.25f;

/// Constant offset added to the brush before the CSG max(), in CELLS. The
/// floor above makes a carve representable; this makes it representable with
/// MARGIN. Reconstruction is only tangent to the true surface at the
/// boundary, so without it the reconstructed hole edge falls slightly inside
/// the analytic one and the rim goes un-backed.
///
/// Measured: with the floor alone, worst-case coverage of the analytic hole
/// is 73%; with both, it is 100% across cell 3.0-7.5 and radius 3-30.
/// The cost is a damaged region 1.7x the nominal rim on average (3.3x for a
/// tiny carve on a coarse lattice) -- suppressed wherever a tracked carve
/// governs, and visible only as generous holes beyond the 24-carve ring.
/// MUST equal opaque.frag's kFieldSdfOffset.
inline constexpr float kCarveFieldOffsetCells = 1.25f;
```

- [ ] **Step 4: Make the brush conservative**

In `native/src/voxel/src/field_brush.cc`, replace the `depth` line and the AABB block. The current lines are:

```cpp
    const float depth = kCarveDepthFactor * radius;

    // Only cells within the brush's AABB can change. The lateral reach is the
    // full radius on every axis, so a radius-sized box bounds the oblate.
    const glm::vec3 lo = center_body - glm::vec3(radius);
    const glm::vec3 hi = center_body + glm::vec3(radius);
```

Replace with:

```cpp
    // Smallest cell axis: the field may be anisotropic, and every
    // representability floor below has to hold on the WORST axis.
    const float min_cell = std::min(f.cell.x, std::min(f.cell.y, f.cell.z));

    // Lateral half-extent covers the shader's OUTWARD rim perturbation, not
    // just the nominal radius -- see kCarveRimAmp.
    const float lat    = radius * (1.0f + kCarveRimAmp);
    const float depth  = std::max(kCarveDepthFactor * radius,
                                  kCarveDepthFloorCells * min_cell);
    const float offset = kCarveFieldOffsetCells * min_cell;

    // Only cells within the brush's AABB can change. The oblate is oriented
    // along `n`, which is arbitrary in body frame, so the axis-aligned box
    // must use the LARGEST half-extent on every axis. The offset dilates the
    // brush's zero crossing outward by offset/|grad|, and the shallowest
    // gradient is min(lat, depth)/max(lat, depth) -- so bound the reach by
    // scaling the largest extent by the same dilation factor the shader
    // computes. Under-sizing this box would silently truncate the carve at
    // the box edge.
    const float dil   = 1.0f + offset / std::min(lat, depth);
    const float reach = std::max(lat, depth) * dil;
    const glm::vec3 lo = center_body - glm::vec3(reach);
    const glm::vec3 hi = center_body + glm::vec3(reach);
```

Then in the per-cell loop, replace:

```cpp
        const float u = ld / radius;
        const float w = along / depth;
        const float unit = std::sqrt(u * u + w * w);
        const float d_brush = (unit - 1.0f) * std::min(radius, depth);
```

with:

```cpp
        const float u = ld / lat;
        const float w = along / depth;
        const float unit = std::sqrt(u * u + w * w);
        const float d_brush = (unit - 1.0f) * std::min(lat, depth);
```

and replace:

```cpp
        const float d_new = std::max(d_old, -d_brush);
```

with:

```cpp
        // `+ offset` dilates the carve by a constant in the brush's own
        // distance units. It is added to the BRUSH only, never to d_old, so
        // the max() still cannot restore material: monotonicity holds.
        const float d_new = std::max(d_old, -d_brush + offset);
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cmake --build build -j --target voxel_tests && \
  ./build/native/tests/voxel/voxel_tests --gtest_filter='FieldBrush*'
```

Expected: PASS, including every pre-existing `FieldBrush*` test. If a pre-existing test now fails, read it before touching it: a test asserting an exact carved extent is legitimately superseded (update its expected value and say so in the commit message); a test asserting *monotonicity* or *no restoration of material* failing means Step 4 was done wrong — fix the code, never the test.

- [ ] **Step 6: Run the full voxel and renderer suites**

```bash
cmake -B build -S . && cmake --build build -j && \
  ./build/native/tests/voxel/voxel_tests && \
  ./build/native/tests/renderer/renderer_tests
```

Expected: PASS. Run `renderer_tests` **whole, unfiltered** (Global Constraint 2).

- [ ] **Step 7: Commit**

```bash
git add native/src/voxel/include/voxel/field_brush.h \
        native/src/voxel/src/field_brush.cc \
        native/tests/voxel/field_brush_test.cc
git commit -m "fix(voxel): make the carve brush conservative so every hole has damage behind it

A carve's half-depth is 0.45*radius, thinner than one cell for every
radius below ~11 model units -- i.e. every ordinary combat hit -- so the
brush did not survive trilinear reconstruction and breach.frag's march
bailed at its entry point, showing space through the hull. Floor the
half-depth at 1.25 cells, extend the lateral half-extent to cover the
shader's outward rim noise, and add a 1.25-cell constant offset.

Measured worst-case coverage of the analytic hole across cell 3.0-7.5
and radius 3-30: 0% -> 100%.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Hole admission — suppression bound, and no field ⇒ no holes

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag:679-805`
- Modify: `native/src/renderer/frame.cc:519`
- Test: `native/tests/renderer/hull_field_clip_test.cc`

**Interfaces:**
- Consumes: Task 1's four constants; existing uniforms `u_carve_spheres`, `u_carve_normals`, `u_carve_count`, `u_hull_field_cell`, `u_hull_field_enabled`.
- Produces: GLSL constants `kFieldDepthFloor = 1.25`, `kFieldSdfOffset = 1.25` (mirroring Task 1); no signature changes.

**Background.** Two separate corrections here; they share a file and a test cycle so they are one task.

**(a) The suppression bound is now too small.** `opaque.frag`'s field block is gated on `!inside_any_oblate` so the field cannot override a tracked carve's jagged rim and struts. Task 1 dilated the field's damaged region past that oblate, so a ring around every tracked hole is now *outside* `inside_any_oblate` but *inside* the field — the field would cut it with a smooth edge, visibly enlarging every hole and erasing the rim the live pass approved. The gate must widen to the dilated bound, computed from the same constants.

Widening also *simplifies*: the dilated bound has `unit < dil` with `dil >= 1` and lateral extent `radius * (1 + kShapeAmp)`, which is a strict superset of both tests the current code unions (`e < 1.0` with perturbed `r_eff`, and the unperturbed `(ld/r)^2 + dz^2 < 1.0`). The union goes away.

**(b) A hull with no baked field cuts holes with no interior at all.** `breach_pass.cc:365-367` returns early when `field_cache->get(inst.id)` is null, while `frame.cc:519` sets `u_carve_enabled = 1` regardless — so a hull whose bake failed gets holes and no interior, unconditionally see-through. All 52 stock hardpoints are covered by a successful bake, so this is a mod/bake-failure path, but it is the same defect class. Consistency says: no field, no holes.

- [ ] **Step 1: Write the failing test**

Add to `native/tests/renderer/hull_field_clip_test.cc`:

```cpp
// The GLSL and C++ copies of the brush constants are separate literals in
// separately compiled languages; nothing but this test stops them drifting.
// If they drift, the shader suppresses the field over a different region
// than the brush dilated, and a ring of un-backed hull reappears around
// every tracked hole -- the exact defect Task 1 exists to remove.
TEST(HullFieldClip, GlslBrushConstantsMatchCxx) {
    const std::string src = renderer::embedded_shader_source("opaque.frag");
    auto glsl_const = [&](const char* name) -> float {
        const std::string key = std::string("const float ") + name + " = ";
        const std::size_t at = src.find(key);
        EXPECT_NE(at, std::string::npos) << name << " missing from opaque.frag";
        if (at == std::string::npos) return -1.0f;
        return std::stof(src.substr(at + key.size()));
    };
    EXPECT_FLOAT_EQ(glsl_const("kFieldDepthFloor"), voxel::kCarveDepthFloorCells);
    EXPECT_FLOAT_EQ(glsl_const("kFieldSdfOffset"),  voxel::kCarveFieldOffsetCells);
    EXPECT_FLOAT_EQ(glsl_const("kShapeAmp"),        voxel::kCarveRimAmp);
    EXPECT_FLOAT_EQ(glsl_const("kDepthFactor"),     voxel::kCarveDepthFactor);
}
```

Use whatever accessor this test file already uses to reach shader source; if none exists, look at how `breach_raymarch_test.cc`'s `IsoMarginMatchesOpaqueFragsValue` reads it and copy that mechanism exactly rather than inventing a second one. Add `#include <voxel/field_brush.h>` to the test, and if `renderer_tests` does not already link the `voxel` target, add it in `native/tests/renderer/CMakeLists.txt`.

- [ ] **Step 2: Run test to verify it fails**

```bash
cmake -B build -S . && cmake --build build -j --target renderer_tests && \
  ./build/native/tests/renderer/renderer_tests --gtest_filter='HullFieldClip.GlslBrushConstantsMatchCxx'
```

Expected: FAIL — `kFieldDepthFloor` and `kFieldSdfOffset` do not exist in `opaque.frag` yet.

- [ ] **Step 3: Add the GLSL constants**

In `native/src/renderer/shaders/opaque.frag`, beside `kDepthFactor` and `kShapeAmp` (around line 312):

```glsl
// Field-brush dilation, in CELLS. GLSL const has no linkage across the
// C++/GLSL boundary, so these are this shader's own copies of
// voxel::kCarveDepthFloorCells and voxel::kCarveFieldOffsetCells --
// NOT independently chosen values. HullFieldClip.GlslBrushConstantsMatchCxx
// fails if they drift. See field_brush.h for the derivation and the measured
// coverage they buy.
const float kFieldDepthFloor = 1.25;
const float kFieldSdfOffset  = 1.25;
```

- [ ] **Step 4: Widen the suppression bound**

In the carve loop, replace the two lines that set `inside_any_oblate` (the `if ((ld * ld) / (r * r) + dz * dz < 1.0) inside_any_oblate = true;` line and the `inside_any_oblate = true;` inside `if (e < 1.0)`) so the flag is set from the dilated bound instead. Rename the variable to `field_suppressed` throughout for honesty about what it now means, and compute it once per carve immediately after `ld` is known:

```glsl
            // Region the FIELD BRUSH dilated this carve to (field_brush.cc).
            // The field is deliberately generous -- a carve is rounded up to
            // what the lattice can hold -- so suppressing the field only
            // inside the nominal oblate would let it cut a smooth ring
            // around every tracked hole, erasing the noise rim and the
            // struts. This bound is a strict superset of the `e < 1.0` hole
            // test below (its lateral extent is r*(1+kShapeAmp) >= r_eff),
            // which is why no union with the unperturbed test is needed.
            float cellmin = min(u_hull_field_cell.x,
                                min(u_hull_field_cell.y, u_hull_field_cell.z));
            float lat = r * (1.0 + kShapeAmp);
            float dep = max(kDepthFactor * r, kFieldDepthFloor * cellmin);
            float dil = 1.0 + (kFieldSdfOffset * cellmin) / min(lat, dep);
            float unit = sqrt((ld * ld) / (lat * lat) + (along * along) / (dep * dep));
            if (unit < dil) field_suppressed = true;
```

Declare `bool field_suppressed = false;` where `bool inside_any_oblate = false;` is today, delete the old `inside_any_oblate` assignments, and change the field block's gate from `!inside_any_oblate` to `!field_suppressed`. Leave the `e < 1.0` hole test, the noise rim, the strut lattice and the `discard` untouched — they are the sub-cell detail layer and this plan does not change what they draw.

Update the long comment above the field block: its claim that the gate is "inside a tracked oblate" is now "inside the region the brush dilated a tracked carve to", and its parenthetical "the scoop still derives from the sphere list this plan does not remove" is stale — the scoop comes from the field since plan 2b.

- [ ] **Step 5: No field ⇒ no holes**

In `native/src/renderer/frame.cc`, line 519, replace:

```cpp
            prog.set_int("u_carve_enabled", 1);
```

with:

```cpp
            // A hull with no baked field has no interior: breach_pass.cc
            // returns early on a null InstanceFieldCache entry. Cutting holes
            // anyway would show space through the ship. "A hole is a hole":
            // if we cannot draw what is behind it, we do not cut it.
            prog.set_int("u_carve_enabled", hull_field != nullptr ? 1 : 0);
```

- [ ] **Step 6: Run the tests**

```bash
cmake -B build -S . && cmake --build build -j && \
  ./build/native/tests/renderer/renderer_tests
```

Expected: PASS, whole binary, unfiltered. Some existing tests submit carves through `FrameSubmitter` without a field and assert a hole appears; those now legitimately see no hole. Fix each by giving the test an instance field entry (the honest fix — it makes the test exercise the real configuration) rather than by asserting the new empty output. If a test cannot be given a field, say so in the commit message rather than weakening the assertion.

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/shaders/opaque.frag \
        native/src/renderer/frame.cc \
        native/tests/renderer/hull_field_clip_test.cc
git commit -m "fix(renderer): widen field suppression to the dilated carve, and stop cutting holes with no field

Task 1's brush dilates each carve to what the lattice can hold, so the
old !inside_any_oblate gate left a ring where the field would cut a
smooth edge around every tracked hole, erasing the noise rim and struts.
Suppress the field over the same dilated bound the brush used, computed
from shared constants a new parity test pins.

Also: a hull whose bake failed got holes from the sphere path and no
interior from breach_pass, i.e. unconditional see-through. No field now
means no holes.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: A jagged rim for field-cut holes

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag` (field block, ~line 788)
- Test: `native/tests/renderer/hull_field_clip_test.cc`

**Interfaces:**
- Consumes: `sample_hull_field`, `vnoise3`, `kHullFieldIsoMargin`.
- Produces: GLSL constants `kFieldRimNoise = 0.06`, `kFieldRimFreq = 0.35`.

**Background.** Beyond the 24-carve ring the field is the only hole authority, and its edge is the brush's smooth ellipsoid — visibly different from the noisy rim tracked carves get. There is no per-carve frame available out there (that is the whole point of being beyond the ring), so the rim noise must come from a body-space field rather than a per-carve azimuth.

**The noise must only ever SHRINK the hole.** Raising the iso threshold shrinks it; lowering it grows the hole past where the interior is guaranteed and re-creates the see-through defect at the rim. So the perturbation term is strictly non-negative, and `breach.frag` is left alone — its plain margin stays a *lower* threshold than the hull's, which keeps hole ⊆ interior by construction.

**Amplitude derivation.** `sample_hull_field` returns stored int8 divided by 255. `f.scale = 4 * cell / 127` model units per int8 step, so half a cell is `0.5 * cell / scale = 0.5 * 127 / 4 = 15.875` int8 steps, i.e. `15.875/255 = 0.0623` in return units. `kFieldRimNoise = 0.06` therefore jitters the boundary by about half a cell — and, because `scale` is proportional to `cell`, does so **independently of the ship's authored resolution**, with no uniform needed.

- [ ] **Step 1: Write the failing test**

Add to `native/tests/renderer/hull_field_clip_test.cc`:

```cpp
// The field rim perturbation must be one-sided. A term that can LOWER the
// threshold grows the hole past the region Task 1 guaranteed damage in,
// which is the see-through defect this whole plan exists to remove. Guard
// the source: the noise must be added to the margin, and its factor must be
// a bare vnoise3 in [0,1] with no remap into [-1,1].
TEST(HullFieldClip, FieldRimNoiseOnlyShrinksTheHole) {
    // read_shader_source() is the helper Task 2 added to this file (adapted
    // from breach_raymarch_test.cc). There is NO renderer::
    // embedded_shader_source() -- an earlier draft of this plan invented one.
    const std::string src = read_shader_source("opaque.frag");
    const std::size_t at = src.find("kFieldRimNoise * ");
    ASSERT_NE(at, std::string::npos) << "field rim noise term missing";
    const std::string line = src.substr(at, src.find('\n', at) - at);
    // A "* 2.0 - 1.0" remap on this term would make it signed.
    EXPECT_EQ(line.find("2.0 - 1.0"), std::string::npos)
        << "rim noise is signed; it must only raise the threshold: " << line;
    EXPECT_NE(src.find("kHullFieldIsoMargin + kFieldRimNoise"), std::string::npos)
        << "rim noise must be ADDED to the iso margin";
}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cmake -B build -S . && cmake --build build -j --target renderer_tests && \
  ./build/native/tests/renderer/renderer_tests --gtest_filter='HullFieldClip.FieldRimNoiseOnlyShrinksTheHole'
```

Expected: FAIL — `kFieldRimNoise` does not exist yet.

- [ ] **Step 3: Add the constants and the term**

Beside `kFieldDepthFloor` in `opaque.frag`:

```glsl
// Body-space erosion of the FIELD's hole edge, so a hole cut beyond the
// 24-carve ring gets a broken rim instead of the brush's smooth ellipsoid.
// Tracked carves do not use this -- they have a real per-carve azimuth and
// their own noise.
//
// ONE-SIDED BY CONSTRUCTION: vnoise3 returns [0,1] and the term is ADDED to
// the iso margin, so it can only ever raise the threshold and shrink the
// hole. A signed version would grow the hole past the region field_brush.cc
// guarantees damage in, putting un-backed hull at the rim -- the defect this
// plan removes. HullFieldClip.FieldRimNoiseOnlyShrinksTheHole guards it.
//
// 0.06 in sample_hull_field's return units is about half a cell: scale is
// 4*cell/127 model units per step, so 0.5*cell is 15.875 steps = 0.0623
// after the /255 normalisation. Because scale is proportional to cell, this
// is the same half cell on every ship without needing a uniform.
const float kFieldRimNoise = 0.06;
const float kFieldRimFreq  = 0.35;   // cycles per model unit
```

In the field block, replace:

```glsl
        bool field_cut = sample_hull_field(p_body) > kHullFieldIsoMargin;
```

with:

```glsl
        bool field_cut = sample_hull_field(p_body)
                       > kHullFieldIsoMargin + kFieldRimNoise * vnoise3(p_body * kFieldRimFreq);
```

- [ ] **Step 4: Add a BEHAVIOURAL test, not just the source guard**

The Step 1 test reads shader text. It passes even if `kFieldRimNoise` is declared and never used, which is exactly the failure mode Task 2 found in its own constant-parity test. Add a second test that renders.

Model it on `HullFieldClipTest.FieldSuppressedOutToTheBrushesDilatedBound`, which Task 2 added to this same file — copy its harness rather than inventing another. The behaviour to pin: **with a field value only marginally above the plain iso margin and no tracked carve in play, some fragments survive that would have been cut without the noise term.** Set the field so a patch reads just above `kHullFieldIsoMargin` but below `kHullFieldIsoMargin + kFieldRimNoise`, render, and assert that patch is **not** uniformly discarded. Assert both directions where you can — a test that only checks "something survived" passes against a shader that cuts nothing at all.

Prove its teeth the same way Task 2 did: delete the `+ kFieldRimNoise * vnoise3(...)` term behind a `cp` backup, confirm the new test fails, restore, and `diff` to prove the restore is byte-identical.

- [ ] **Step 5: Run the tests**

```bash
cmake -B build -S . && cmake --build build -j && \
  ./build/native/tests/renderer/renderer_tests
```

Expected: PASS, whole binary, unfiltered.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/shaders/opaque.frag \
        native/tests/renderer/hull_field_clip_test.cc
git commit -m "feat(renderer): break up the field-cut hole rim with body-space noise

Beyond the 24-carve ring the field is the only hole authority and its edge
was the brush's smooth ellipsoid. Erode it with body-space noise. The term
is one-sided -- added to the iso margin, never subtracted -- so the hole can
only shrink, keeping it inside the region the brush guarantees damage in.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Lock the invariant across the whole parameter range

**Files:**
- Test: `native/tests/voxel/field_brush_test.cc`

**Interfaces:**
- Consumes: Task 1's brush, constants, and `trilinear_int8` helper.
- Produces: nothing; this task is purely the regression net.

**Background.** Task 1's test covers one radius on one lattice. The defect it fixes was radius- *and* placement-dependent, and the review found that no existing test ever put the two shaders' disagreement in front of a pixel (`breach_pass_test.cc:440`'s `mark_hull_cut()` stamps stencil over the entire frame, so the hull's own decision is never consulted). This task sweeps the real parameter space so a future tuning change cannot quietly reintroduce a coverage hole.

The sweep is the same one used to choose the constants, so it is expected to pass on the first run — that is fine and is not a TDD violation, **provided Step 2 proves it fails against the pre-Task-1 brush.** Do not skip Step 2: a test that has never failed is not known to test anything.

- [ ] **Step 1: Write the sweep test**

Add to `native/tests/voxel/field_brush_test.cc`:

```cpp
// The invariant the whole plan rests on: every point opaque.frag would
// discard as hull must read damaged in the field. Swept across BC's full
// authored resolution range (cell = authored_res/quality, authored_res 6-15,
// quality 2 => cell 3.0-7.5), the full carve radius range hit_feedback can
// produce (3-30 model units), and sub-cell placements -- because the defect
// this guards was placement-dependent and read 0% at cell corners.
TEST(FieldBrushConservative, HoleIsAlwaysBackedAcrossTheParameterRange) {
    const float cells[]   = {3.0f, 5.0f, 7.5f};
    const float radii[]   = {3.0f, 5.0f, 8.0f, 10.0f, 20.0f, 30.0f};
    // Deliberately includes 0.0 (cell centre) and 0.5 (cell corner).
    const float offsets[] = {0.0f, 0.25f, 0.5f, 0.75f};

    for (float cell : cells)
    for (float radius : radii)
    for (float off : offsets) {
        // Box big enough for the dilated brush plus a margin, on any axis.
        const int n = int(std::ceil((radius * 4.0f + cell * 8.0f) / cell)) + 4;
        voxel::DistanceField f;
        f.dims   = glm::ivec3(n, n, n);
        f.cell   = glm::vec3(cell);
        f.scale  = 4.0f * cell / 127.0f;
        f.origin = glm::vec3(-0.5f * float(n) * cell) + glm::vec3(off * cell);
        f.dist.assign(std::size_t(n) * n * n, static_cast<std::int8_t>(-127));

        voxel::field_carve_oblate(f, glm::vec3(0.0f),
                                  glm::vec3(0.0f, 0.0f, 1.0f), radius);

        // opaque.frag cuts where its perturbed rim allows, out to
        // radius * (1 + kShapeAmp) at the extreme. Sample that whole disc.
        const float rim = radius * (1.0f + voxel::kCarveRimAmp);
        int total = 0, undamaged = 0;
        for (int i = 0; i < 48; ++i) {
            const float th = 6.28318530718f * float(i) / 48.0f;
            for (int j = 1; j <= 12; ++j) {
                const float rad = rim * float(j) / 12.0f;
                const glm::vec3 p(rad * std::cos(th), rad * std::sin(th), 0.0f);
                ++total;
                if (trilinear_int8(f, p) <= 0.5f) ++undamaged;
            }
        }
        EXPECT_EQ(undamaged, 0)
            << "cell=" << cell << " radius=" << radius << " offset=" << off
            << ": " << undamaged << " of " << total
            << " hole fragments have no damage behind them";
    }
}
```

- [ ] **Step 2: Prove the test has teeth**

Temporarily revert the brush to its pre-Task-1 behaviour and watch the sweep fail. **Back up by copy, never with git** (Global Constraint 7 — a reviewer once wiped another session's uncommitted work reverting a probe mutation with git):

```bash
cp native/src/voxel/src/field_brush.cc /tmp/field_brush.cc.bak
```

Then edit `field_brush.cc` with the Edit tool to set `offset` to `0.0f`, `lat` to `radius`, and `depth` back to `kCarveDepthFactor * radius`. Rebuild and run:

```bash
cmake --build build -j --target voxel_tests && \
  ./build/native/tests/voxel/voxel_tests --gtest_filter='FieldBrushConservative.HoleIsAlwaysBacked*'
```

Expected: FAIL, on the small radii especially. Then restore and PROVE the restore:

```bash
cp /tmp/field_brush.cc.bak native/src/voxel/src/field_brush.cc
diff native/src/voxel/src/field_brush.cc /tmp/field_brush.cc.bak && echo "restore is byte-identical"
```

- [ ] **Step 3: Run the sweep against the real brush**

```bash
cmake --build build -j --target voxel_tests && \
  ./build/native/tests/voxel/voxel_tests --gtest_filter='FieldBrush*'
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add native/tests/voxel/field_brush_test.cc
git commit -m "test(voxel): sweep the hole-is-always-backed invariant across cell and radius

Verified to fail against the pre-conservative brush before being committed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Correct the spec, and run the gate

**Files:**
- Modify: `docs/superpowers/specs/2026-09-08-dauntless-hull-volumes-design.md` (§7)

**Interfaces:** none.

**Background.** §7 says the sphere list is retired once the rim noise is baked into the brush. The measurements in this plan show that is not achievable at this lattice resolution, and a future reader acting on the stale sentence would delete the detail layer and regress the appearance. The spec is the artefact that travels; correct it.

- [ ] **Step 1: Correct §7**

Edit §7 to record, in the spec's own voice:

- The sphere list is **not** retired. It survives as the sub-cell detail layer: the rim noise (±25% of radius = 0.75–7.5 model units) and the framework struts are smaller than one cell at every authored resolution (cell 3.0–7.5), so baking them into the field would erase them, not sharpen them.
- The field is the **admission authority**: a hole may exist only where the field reads damaged. The analytic layer refines shape strictly inside that region.
- The brush is deliberately **conservative** — it rounds a carve up to the smallest shape the lattice can hold — which is what makes the containment hold. Cite `kCarveDepthFloorCells` and `kCarveFieldOffsetCells` and the measured 0% → 100% worst-case coverage.
- The residual cost: the field's damaged region is ~1.7× the nominal rim (up to 3.3× for a tiny carve on a coarse lattice), visible only as generous holes beyond the 24-carve ring. Raising `kDefaultQuality` shrinks it proportionally at 8× memory per instance for quality 4 — the lever to reach for if the live pass says the beyond-ring holes read badly.

- [ ] **Step 2: Run the full gate**

```bash
./scripts/check_tests.sh
```

**Read the output**, not a pipeline exit code (Global Constraint 9). Expected: no `NEW FAILURES (not in baseline)` banner. Only `test_shield_level_change_announces` may appear.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-09-08-dauntless-hull-volumes-design.md
git commit -m "docs(spec): the sphere list is not retired -- rim noise and struts are sub-cell

Measured: at cell 3.0-7.5 the rim perturbation and the strut lattice are
both smaller than one cell, so baking them into the field would erase
them. Record the field's actual role -- admission authority, with the
analytic layer refining shape inside it -- and the conservative brush
that makes the containment hold.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Noted during execution — not blocking, do not fix inside this plan

**Task 1's write AABB is loose.** `reach = max(lat, depth) * dil` scales the *largest* half-extent by a dilation computed from the *smallest*, so a carve visits roughly 3× the cells it needs: ~10,500 instead of ~3,800 for radius 30 on a Galaxy lattice, ~300 instead of ~110 for radius 3. The exact axis-aligned bound for an oblate with axis `n`, lateral half-extent `A` and along half-extent `B` is per-axis `sqrt(A²(1-(e·n)²) + B²(e·n)²)` — three cheap evaluations, strictly tighter, never truncating.

Left alone deliberately. The cost is a few hundred thousand flops per carve, and a large carve already visited 1,728 cells before this plan, so the order of magnitude is unchanged. Worth tightening only if a profile ever points at `field_carve_oblate`; correctness does not depend on it.

**Task 1 trap for Task 2's implementer:** in `field_brush.cc` the loop-local `lateral` vector was named `lat`, colliding with the new `float lat` half-extent. It shadowed silently and would have reverted the whole rim dilation had the types been compatible; the vector is now `lat_vec`. `opaque.frag` already calls its vector `lateral`, so `float lat` is safe there — but check, do not assume.

## Live verification briefing

Green tests cannot see this. When the plan is done, the live pass should check, in order:

1. **A single fresh hit has an interior.** Fire once at a large hull. The hole must show recessed interior, not stars. This is the defect the plan exists to fix and the one that was worst (0% backed at radius 3).
2. **Sustained fire on one spot still looks right.** The hole grows; the rim should stay jagged and struts should still bridge it. If the rim went smooth, Task 2's suppression bound is wrong.
3. **Damage past ~24 hits.** Keep firing until the ring is exhausted. New holes out there are cut by the field: expect slightly *generous* holes with a broken (not smooth) rim, and interior behind all of them. Generous is expected; see-through is a failure.
4. **Undamaged ships are unchanged.** Any change to a pristine hull means a stock-path regression.

If (1) still shows space, the brush dilation is not reaching the shader — check that `cmake -B build -S .` ran before the build (Global Constraint 3).
