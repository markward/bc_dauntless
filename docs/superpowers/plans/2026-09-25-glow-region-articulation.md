# Glow Regions Follow an Articulated Part — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A glow region authored on a part keeps modulating that part's surface when the part is rotated by a node override.

**Architecture:** For every mesh draw, the renderer passes `opaque.frag` one extra matrix, `u_node_rest_fix = C_i = R_i · P_i⁻¹`, which maps a posed body-frame point back to its rest position. `R_i` and `P_i` are node *i*'s rest and posed matrices composed with an identity instance world, so the ship's own transform cancels. Only the glow-region test uses it; decals, scuffs and the carve keep the posed `p_body`.

**Tech Stack:** C++20 + glm (`native/src/renderer/`), GLSL 410 (`opaque.frag`), gtest/ctest.

**Spec:** `docs/superpowers/specs/2026-09-25-glow-region-articulation-design.md`

## Global Constraints

- **Shared checkout, destructive git is BANNED:** never `git checkout -- <path>`, `git checkout .`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`. Stage with explicit pathspecs only. To mutate a file temporarily: `cp` it to the scratchpad, mutate, `cp` back, then `diff` to prove the restore is byte-identical.
- **Do not touch `engine/appc/hardpoint_overrides.py`.** It holds the user's uncommitted authored data.
- **NEVER launch the game** (`./build/dauntless`), not even with `--help`: it has no help flag and starts the game.
- **ONE build tree** at `<worktree>/build/`: `cmake -B build -S . && cmake --build build -j`. Never run cmake inside `native/`.
- **Shader edits need a reconfigure** (`cmake -B build -S .`) before the build picks them up, and **shader errors surface at RUNTIME**, so only a render test proves a shader compiles.
- **The gate is `scripts/check_tests.sh`**; clean is `OK — no new failures. 1 known failure(s) still baselined.`
- **Units:** `p_body`, glow-region uniforms and node matrices are all MODEL units. Nothing converts.
- **A real BC hull is THREE levels** (part → `__NDL_MultiMtl_Node` → mesh). Pure fixtures mirror three.
- **Only the glow test changes frame.** `opaque.frag`'s decals, scuffs and hull carve keep reading the posed `p_body`; commit `4be56165` made the carve posed on purpose.

## Review Focus

1. **Uniform leak across draws.** A uniform keeps its value until set again, so an articulated ship drawn before a plain one must not shift the plain one's glow. The expected behaviour is that the plain ship renders exactly as if drawn alone. Pinned by `GlowRegionOnPlainShipUnaffectedByArticulatedShipDrawnFirst` in Task 2.
2. **A severed part (zero-matrix override).** Expected: no NaNs, and the identity correction. Pinned by `ZeroMatrixNodeGetsIdentity` in Task 1.
3. **Overrides on both a part and its child.** Expected: the mesh node still maps posed → rest exactly. Pinned by `NestedOverridesStillMapPosedToRest` in Task 1.
4. **A model with no overrides.** Expected: pixel-identical to before. Pinned by `RestPoseOverrideRendersIdenticallyToNoOverride` in Task 2.
5. **Skinned draws (bridge officers).** Expected: unchanged. They take the skinned branch, which always sets the identity. There's no dedicated test (it needs a skinned asset in a headless render); Task 2's code sets identity on that branch explicitly, and the gate's existing character tests must stay green.

---

### Task 1: `rest_corrections`, the posed→rest matrix per node

**Files:**
- Modify: `native/src/renderer/include/renderer/node_anim.h` (declare beside `compose_node_worlds`)
- Modify: `native/src/renderer/node_anim.cc` (define after `compose_node_worlds`, which ends at ~line 47)
- Test: `native/tests/renderer/node_anim_test.cc` (append; it is already registered in `native/tests/renderer/CMakeLists.txt:23`)

**Interfaces:**
- Consumes: `renderer::compose_node_worlds(const assets::Model&, const glm::mat4& instance_world, const std::unordered_map<int, glm::mat4>& overrides)` (existing).
- Produces:
  ```cpp
  namespace renderer {
  std::vector<glm::mat4> rest_corrections(
      const assets::Model& model,
      const std::unordered_map<int, glm::mat4>& overrides);
  }
  ```
  Returns one matrix per node (same size as `model.nodes`; empty for a model with no nodes).

- [ ] **Step 1: Write the failing tests**

Append to `native/tests/renderer/node_anim_test.cc`. Read the top of that file first; reuse its existing includes, and add any missing from: `<assets/model.h>`, `<renderer/node_anim.h>`, `<glm/gtc/matrix_transform.hpp>`, `<cmath>`, `<unordered_map>`, `<vector>`. If the file already defines helpers with these names in its anonymous namespace, rename these (e.g. suffix `_rc`) rather than changing the existing ones.

```cpp
// ── rest_corrections: posed body-frame point -> its REST position ──────────
// Glow regions are authored in the NIF (rest) frame, but opaque.frag rebuilds
// a POSED body-frame position. C_i = R_i * P_i^-1 maps it back. A real BC
// hull is THREE levels (part -> __NDL_MultiMtl_Node -> mesh), so the fixture
// is too: a two-level fixture has let a bug reach live play here before.
namespace {

int rc_add_node(assets::Model& m, const char* name, int parent,
                const glm::mat4& local = glm::mat4(1.0f)) {
    const int idx = static_cast<int>(m.nodes.size());
    assets::Node n;
    n.name = name;
    n.parent_index = parent;
    n.local_transform = local;
    m.nodes.push_back(n);
    if (parent >= 0) m.nodes[parent].children.push_back(idx);
    return idx;
}

struct RcHull {
    assets::Model model;
    int root = -1, part = -1, ndl = -1, mesh = -1, body = -1;
};

// Scene Root -> "left wing" (offset +10 X) -> __NDL -> mesh node (offset +2 Y);
// Scene Root -> "birdofprey" (the body, never overridden).
RcHull rc_hull() {
    RcHull h;
    h.model.root_node = 0;
    h.root = rc_add_node(h.model, "Scene Root", -1);
    h.part = rc_add_node(h.model, "left wing", h.root,
                         glm::translate(glm::mat4(1.0f), glm::vec3(10, 0, 0)));
    h.ndl  = rc_add_node(h.model, "__NDL_MultiMtl_Node", h.part);
    h.mesh = rc_add_node(h.model, "wing mesh", h.ndl,
                         glm::translate(glm::mat4(1.0f), glm::vec3(0, 2, 0)));
    h.body = rc_add_node(h.model, "birdofprey", h.root);
    return h;
}

// The part's local, rotated 45 degrees about +Y (the BoP hinge axis).
glm::mat4 rc_rotated_part_local(const RcHull& h) {
    return h.model.nodes[h.part].local_transform *
           glm::rotate(glm::mat4(1.0f), glm::radians(45.0f), glm::vec3(0, 1, 0));
}

void rc_expect_mat_near(const glm::mat4& a, const glm::mat4& b) {
    for (int c = 0; c < 4; ++c)
        for (int r = 0; r < 4; ++r)
            EXPECT_NEAR(a[c][r], b[c][r], 1e-5f) << "col " << c << " row " << r;
}

}  // namespace

TEST(RestCorrections, MapsAPosedVertexBackToItsRestPosition) {
    // THE POINT: a vertex drawn at P_i*v comes back to R_i*v.
    const RcHull h = rc_hull();
    std::unordered_map<int, glm::mat4> ov{{h.part, rc_rotated_part_local(h)}};
    const auto posed = renderer::compose_node_worlds(h.model, glm::mat4(1.0f), ov);
    const auto rest  = renderer::compose_node_worlds(h.model, glm::mat4(1.0f), {});
    const auto C = renderer::rest_corrections(h.model, ov);
    ASSERT_EQ(C.size(), h.model.nodes.size());

    const glm::vec4 v(1.0f, 3.0f, -2.0f, 1.0f);
    const glm::vec4 drawn = posed[h.mesh] * v;
    const glm::vec4 want  = rest[h.mesh] * v;
    const glm::vec4 got   = C[h.mesh] * drawn;
    ASSERT_GT(glm::length(glm::vec3(drawn - want)), 0.5f)
        << "guard: the override must actually move the vertex";
    EXPECT_NEAR(got.x, want.x, 1e-4f);
    EXPECT_NEAR(got.y, want.y, 1e-4f);
    EXPECT_NEAR(got.z, want.z, 1e-4f);
}

TEST(RestCorrections, NodeOutsideTheRotatedSubtreeGetsIdentity) {
    const RcHull h = rc_hull();
    std::unordered_map<int, glm::mat4> ov{{h.part, rc_rotated_part_local(h)}};
    const auto C = renderer::rest_corrections(h.model, ov);
    rc_expect_mat_near(C[h.body], glm::mat4(1.0f));
    rc_expect_mat_near(C[h.root], glm::mat4(1.0f));
}

TEST(RestCorrections, EmptyOverridesGiveIdentityEverywhere) {
    const RcHull h = rc_hull();
    const auto C = renderer::rest_corrections(h.model, {});
    ASSERT_EQ(C.size(), h.model.nodes.size());
    for (const auto& m : C) rc_expect_mat_near(m, glm::mat4(1.0f));
}

TEST(RestCorrections, ZeroMatrixNodeGetsIdentity) {
    // A severed part is hidden by a ZERO override (host_bindings.cc
    // set_instance_node_hidden). P_i is singular; the correction must be the
    // identity, never NaN.
    const RcHull h = rc_hull();
    std::unordered_map<int, glm::mat4> ov{{h.part, glm::mat4(0.0f)}};
    const auto C = renderer::rest_corrections(h.model, ov);
    for (int i : {h.part, h.ndl, h.mesh}) {
        for (int c = 0; c < 4; ++c)
            for (int r = 0; r < 4; ++r)
                ASSERT_TRUE(std::isfinite(C[i][c][r])) << "node " << i;
        rc_expect_mat_near(C[i], glm::mat4(1.0f));
    }
}

TEST(RestCorrections, NestedOverridesStillMapPosedToRest) {
    // An override on the part AND on its mesh child: the correction must use
    // the whole posed chain, not only the nearest override.
    const RcHull h = rc_hull();
    std::unordered_map<int, glm::mat4> ov{
        {h.part, rc_rotated_part_local(h)},
        {h.mesh, h.model.nodes[h.mesh].local_transform *
                 glm::rotate(glm::mat4(1.0f), glm::radians(30.0f), glm::vec3(0, 0, 1))},
    };
    const auto posed = renderer::compose_node_worlds(h.model, glm::mat4(1.0f), ov);
    const auto rest  = renderer::compose_node_worlds(h.model, glm::mat4(1.0f), {});
    const auto C = renderer::rest_corrections(h.model, ov);
    const glm::vec4 v(0.5f, -1.0f, 4.0f, 1.0f);
    const glm::vec4 got  = C[h.mesh] * (posed[h.mesh] * v);
    const glm::vec4 want = rest[h.mesh] * v;
    EXPECT_NEAR(got.x, want.x, 1e-4f);
    EXPECT_NEAR(got.y, want.y, 1e-4f);
    EXPECT_NEAR(got.z, want.z, 1e-4f);
}

TEST(RestCorrections, ModelWithNoNodesGivesEmpty) {
    assets::Model m;
    EXPECT_TRUE(renderer::rest_corrections(m, {}).empty());
}
```

- [ ] **Step 2: Build and watch it fail**

Run: `cmake --build build -j 2>&1 | tail -20`
Expected: compile FAILURE, `'rest_corrections' is not a member of 'renderer'` (or clang's "no member named 'rest_corrections'").

- [ ] **Step 3: Declare it**

In `native/src/renderer/include/renderer/node_anim.h`, directly after the `compose_node_worlds` declaration:

```cpp
/// Per-node matrix mapping a POSED body-frame point back to its REST
/// position: C_i = R_i * P_i^-1, where R_i / P_i are node i's world matrices
/// composed with an IDENTITY instance world, without / with `overrides`.
/// The instance world cancels (p_body = W^-1 * W * P_i * v), so this needs
/// no per-instance transform.
///
/// Used by opaque.frag's glow-region test: regions are authored in the NIF
/// (rest) frame, but the shader rebuilds a POSED body position, so on a
/// rotated part the region and the surface it was authored on came apart.
///
/// Identity for every node when `overrides` is empty, for a node whose chain
/// carries no override, and for a SEVERED node (a zero-matrix override, from
/// set_instance_node_hidden), whose P_i is singular: identity, never NaN.
std::vector<glm::mat4> rest_corrections(
    const assets::Model& model,
    const std::unordered_map<int, glm::mat4>& overrides);
```

- [ ] **Step 4: Define it**

In `native/src/renderer/node_anim.cc`, directly after `compose_node_worlds`'s closing brace (add `#include <cmath>` at the top if it is not there):

```cpp
std::vector<glm::mat4> rest_corrections(
    const assets::Model& model,
    const std::unordered_map<int, glm::mat4>& overrides) {
    std::vector<glm::mat4> out(model.nodes.size(), glm::mat4(1.0f));
    if (model.nodes.empty() || overrides.empty()) return out;
    const glm::mat4 I(1.0f);
    const auto posed = compose_node_worlds(model, I, overrides);
    const auto rest  = compose_node_worlds(model, I, {});
    for (std::size_t i = 0; i < out.size(); ++i) {
        if (posed[i] == rest[i]) continue;                  // chain not overridden
        if (std::fabs(glm::determinant(posed[i])) < 1e-12f) continue;  // severed
        out[i] = rest[i] * glm::inverse(posed[i]);
    }
    return out;
}
```

- [ ] **Step 5: Build and run the tests**

Run: `cmake --build build -j && ctest --test-dir build -R RestCorrections --output-on-failure`
Expected: 6 tests PASS.

- [ ] **Step 6: Run the gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.`

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/include/renderer/node_anim.h native/src/renderer/node_anim.cc native/tests/renderer/node_anim_test.cc
git commit -m "feat(renderer): rest_corrections -- posed body point back to rest

C_i = R_i * P_i^-1 per node, both composed with an identity instance
world (it cancels). Identity with no overrides, off the overridden
chain, and for a severed zero-matrix node. Feeds the glow-region test,
whose regions are authored in the rest frame.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `opaque.frag` tests glow regions in the rest frame

**Files:**
- Modify: `native/src/renderer/frame.cc` (`draw_model`, starting ~line 362; node walk ~lines 640-680)
- Modify: `native/src/renderer/shaders/opaque.frag` (uniform block near `u_glow_region_*` ~line 306; call site ~line 1342)
- Test: `native/tests/renderer/frame_test.cc` (append after `render_galaxy_zero_ambient`, ~line 2252)

**Interfaces:**
- Consumes: `renderer::rest_corrections(const assets::Model&, const std::unordered_map<int, glm::mat4>&)` from Task 1.
- Produces: shader uniform `mat4 u_node_rest_fix`, set on EVERY mesh draw in `draw_model`.

- [ ] **Step 1: Read before writing**

Read `native/tests/renderer/frame_test.cc` lines 120-140 (the `FrameTest` fixture), 526-548 (`block_mean`, `read_frame`, `differing_texels`), 2050-2062 (`render_galaxy`) and 2252-2280 (`render_galaxy_zero_ambient`). Read `draw_model` in `frame.cc` from line 362 to the end of its mesh loop, and note the exact name of its node-override parameter (used at ~line 651 as `node_overrides`). Read `glow_region_mult` in `opaque.frag` (~lines 377-440): a region is **destroyed and fully dark** when `disable_time >= 0`, `flicker == 0`, `dim_target == 0` and `now - disable_time` exceeds `GLOW_FLICKER_SECS`.

- [ ] **Step 2: Write the failing render tests**

Append to `native/tests/renderer/frame_test.cc`, after `render_galaxy_zero_ambient`. The Galaxy's glow windows are the only light at zero ambient. A dark box region covers the saucer's +X half at rest. Spinning the whole ship 180° about **Y** (via a root-node override) mirrors X and keeps the saucer in the same screen rows, so the surface the region was authored on moves to screen-LEFT.

```cpp
// ── Glow regions follow an articulated node ────────────────────────────────
// Regions are authored in the NIF (rest) frame; opaque.frag used to test them
// against the POSED body position, so on a rotated node the region stayed put
// while the surface it was authored on moved away. See
// docs/superpowers/specs/2026-09-25-glow-region-articulation-design.md.
namespace {

// A destroyed, fully-settled (dark) box over the saucer's +X half at REST:
// body X 10..190 (the right sample block covers X ~ +14..+182), all Y and Z.
scenegraph::Instance::GlowRegion dark_right_half_region() {
    scenegraph::Instance::GlowRegion r;
    r.center       = glm::vec3(100.0f, 0.0f, 0.0f);
    r.shape        = 1.0f;                                 // box
    r.half_extents = glm::vec3(90.0f, 1000.0f, 1000.0f);
    r.dim_target   = 0.0f;                                 // off when settled
    r.disable_time = 0.0f;                                 // destroyed at t=0
    r.flicker      = 0.0f;                                 // destroyed, not disabled
    r.active       = true;
    return r;
}

// Root-node override: the model's own root local, then 180 degrees about +Y.
glm::mat4 spun_root_local(const assets::Model& m) {
    return m.nodes[m.root_node].local_transform *
           glm::rotate(glm::mat4(1.0f), glm::radians(180.0f), glm::vec3(0, 1, 0));
}

constexpr float kSettled = 65.0f;   // well past GLOW_FLICKER_SECS

}  // namespace

TEST_F(FrameTest, GlowRegionFollowsARotatedNode) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    const auto& model = *model_h;
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    // Guard: the SPUN ship, no region, glows in BOTH sample blocks. If not,
    // the camera/sample geometry is wrong and nothing below means anything.
    scenegraph::World w0;
    auto i0 = w0.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w0.set_world_transform(i0, glm::mat4(1.0f));
    w0.get(i0)->node_overrides[model.root_node] = spun_root_local(model);
    render_galaxy_zero_ambient(w0, *p, lut, kSettled);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double L0 = block_mean(93, 100, 25, 50);
    const double R0 = block_mean(130, 100, 25, 50);
    ASSERT_GT(L0, 0.0) << "spun ship: left block has no glow (sample geometry wrong)";
    ASSERT_GT(R0, 0.0) << "spun ship: right block has no glow (sample geometry wrong)";

    // The spun ship with the dark rest-frame region over the (rest) +X half.
    scenegraph::World w1;
    auto i1 = w1.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w1.set_world_transform(i1, glm::mat4(1.0f));
    w1.get(i1)->node_overrides[model.root_node] = spun_root_local(model);
    w1.get(i1)->glow_regions[0] = dark_right_half_region();
    render_galaxy_zero_ambient(w1, *p, lut, kSettled);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double L1 = block_mean(93, 100, 25, 50);
    const double R1 = block_mean(130, 100, 25, 50);

    // The authored (+X at rest) surface is now on screen-LEFT: it goes dark.
    EXPECT_LT(L1, L0 * 0.5) << "the region did not follow its surface to screen-left";
    // Screen-right now shows the rest -X surface, which the region never covered.
    EXPECT_NEAR(R1, R0, R0 * 0.05) << "the region stayed at its rest position";
}

TEST_F(FrameTest, RestPoseOverrideRendersIdenticallyToNoOverride) {
    // An override equal to the node's own rest local must render exactly as no
    // override at all: the correction is then the identity.
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    const auto& model = *model_h;
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    scenegraph::World w0;
    auto i0 = w0.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w0.set_world_transform(i0, glm::mat4(1.0f));
    w0.get(i0)->glow_regions[0] = dark_right_half_region();
    render_galaxy_zero_ambient(w0, *p, lut, kSettled);
    const auto plain = read_frame();

    scenegraph::World w1;
    auto i1 = w1.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w1.set_world_transform(i1, glm::mat4(1.0f));
    w1.get(i1)->node_overrides[model.root_node] =
        model.nodes[model.root_node].local_transform;
    w1.get(i1)->glow_regions[0] = dark_right_half_region();
    render_galaxy_zero_ambient(w1, *p, lut, kSettled);
    const auto overridden = read_frame();

    EXPECT_EQ(differing_texels(plain, overridden), 0u);
}

TEST_F(FrameTest, GlowRegionOnPlainShipUnaffectedByArticulatedShipDrawnFirst) {
    // u_node_rest_fix is a uniform: it keeps its value between draws unless
    // set again. A spun ship drawn BEFORE a plain one must not carry its
    // correction onto the plain ship's glow test.
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    const auto& model = *model_h;
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    // Plain ship alone, with the region.
    scenegraph::World w0;
    auto p0 = w0.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w0.set_world_transform(p0, glm::mat4(1.0f));
    w0.get(p0)->glow_regions[0] = dark_right_half_region();
    render_galaxy_zero_ambient(w0, *p, lut, kSettled);
    const double L0 = block_mean(93, 100, 25, 50);
    const double R0 = block_mean(130, 100, 25, 50);

    // A spun ship created FIRST (so drawn first), shrunk and parked in the top
    // corner of the view so it is drawn but covers neither sample block; then
    // the same plain ship.
    scenegraph::World w1;
    auto a1 = w1.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w1.set_world_transform(a1, glm::translate(glm::mat4(1.0f), glm::vec3(700, 700, 0)) *
                               glm::scale(glm::mat4(1.0f), glm::vec3(0.1f)));
    w1.get(a1)->node_overrides[model.root_node] = spun_root_local(model);
    auto p1 = w1.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w1.set_world_transform(p1, glm::mat4(1.0f));
    w1.get(p1)->glow_regions[0] = dark_right_half_region();
    render_galaxy_zero_ambient(w1, *p, lut, kSettled);

    EXPECT_DOUBLE_EQ(block_mean(93, 100, 25, 50), L0);
    EXPECT_DOUBLE_EQ(block_mean(130, 100, 25, 50), R0);
}
```

If `scenegraph::World::get` returns a `const` pointer, or `node_overrides` is not a public `std::unordered_map<int, glm::mat4>` on `scenegraph::Instance`, read `native/src/scenegraph/include/scenegraph/instance.h` and `world.h` and use whatever mutable accessor the existing tests use (the scorch tests write `w1.get(i1)->decals`). Do not add new API for the test.

- [ ] **Step 3: Build and watch the right test fail for the right reason**

Run: `cmake --build build -j && ctest --test-dir build -R "GlowRegionFollowsARotatedNode|RestPoseOverrideRendersIdentically|GlowRegionOnPlainShip" --output-on-failure`

Expected:
- `GlowRegionFollowsARotatedNode` FAILS on `EXPECT_LT(L1, L0 * 0.5)` and `EXPECT_NEAR(R1, R0, ...)`: the region still darkens screen-right. **If either `ASSERT_GT` guard fails instead, STOP and report BLOCKED** with the measured `L0`/`R0`: the sample geometry is wrong and the test proves nothing.
- `RestPoseOverrideRendersIdenticallyToNoOverride` and `GlowRegionOnPlainShipUnaffectedByArticulatedShipDrawnFirst` PASS (they are regression guards for what Steps 4-5 could break).
- If the tests SKIP (no BC assets / no GL context), STOP and report BLOCKED: the shader change cannot be verified in this environment.

- [ ] **Step 4: Set `u_node_rest_fix` on every mesh draw**

In `native/src/renderer/frame.cc`, `draw_model`: add `#include <renderer/node_anim.h>` at the top if it is not already included (`compose_node_worlds` is used here, so it very likely is).

Directly after the `world_per_node` if/else block (~line 664, before the `for` loop over nodes that issues the draws), add:

```cpp
    // Glow regions are authored in the NIF (rest) frame, but opaque.frag
    // rebuilds a POSED body position. C_i = R_i * P_i^-1 maps it back, for
    // the glow test only. Identity for every node of an unarticulated
    // instance -- computed only when there are overrides, so the common path
    // allocates nothing extra.
    const bool articulated = node_overrides != nullptr && !node_overrides->empty();
    const std::vector<glm::mat4> rest_fix =
        articulated ? rest_corrections(model, *node_overrides)
                    : std::vector<glm::mat4>{};
```

Inside the per-mesh loop, directly after the existing `prog.set_mat4("u_model", skinned ? world : world_per_node[i]);` line:

```cpp
            // EVERY draw sets it, identity included: a uniform keeps its value
            // between draws, so skipping the identity would leak the previous
            // articulated ship's correction onto this one. Skinned draws are
            // posed by the bone palette, not by node overrides: identity.
            prog.set_mat4("u_node_rest_fix",
                          (!skinned && articulated) ? rest_fix[i] : glm::mat4(1.0f));
```

Use the exact identifiers `draw_model` already uses (`node_overrides`, `skinned`, `prog`, `world_per_node`, loop index `i`). If they differ, adapt to them; do not rename existing variables.

- [ ] **Step 5: Test glow regions in the rest frame**

In `native/src/renderer/shaders/opaque.frag`, next to the other `u_glow_region_*` uniform declarations (~line 306):

```glsl
// Maps this draw's POSED body-frame position back to its REST position
// (C_i = R_i * P_i^-1, native frame.cc draw_model). Glow regions are authored
// in the rest frame; identity for anything not articulated. Used by the glow
// test ONLY -- decals, scuffs and the hull carve stay posed (4be56165).
uniform mat4 u_node_rest_fix;
```

At the glow call site (~line 1342), replace:

```glsl
        nac = glow_region_mult(p_body, n_body, u_decal_time, region_gain);  // body-frame pos + normal
```

with:

```glsl
        // REST-frame position + normal: a region authored on a part keeps
        // covering that part's surface while the part is rotated.
        vec3 p_glow = (u_node_rest_fix * vec4(p_body, 1.0)).xyz;
        vec3 n_glow = normalize(mat3(u_node_rest_fix) * n_body);
        nac = glow_region_mult(p_glow, n_glow, u_decal_time, region_gain);
```

Change nothing else in the shader.

- [ ] **Step 6: Reconfigure, build and run the render tests**

Shader edits need a reconfigure to reach the build:

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build -R "GlowRegionFollowsARotatedNode|RestPoseOverrideRendersIdentically|GlowRegionOnPlainShip|RestCorrections" --output-on-failure`
Expected: all PASS. A shader compile error shows up here at RUNTIME as failing render tests or a GL error, not as a build error.

- [ ] **Step 7: Run the gate**

Run: `scripts/check_tests.sh`
Expected: `OK — no new failures. 1 known failure(s) still baselined.` Every existing `FrameTest` (scorch, glow, cloak parity) must stay green: they render through the same shader.

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/frame.cc native/src/renderer/shaders/opaque.frag native/tests/renderer/frame_test.cc
git commit -m "fix(renderer): glow regions follow an articulated node

Regions are authored in the NIF (rest) frame, but opaque.frag tested them
against the POSED body position, so on a rotated part the region stayed
put while the surface it was authored on moved. draw_model now sets
u_node_rest_fix = R_i * P_i^-1 on every mesh draw (identity when nothing
is articulated, and on skinned draws) and the glow test maps each
fragment back through it. Decals, scuffs and the carve stay posed.

Not live-verified.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Live verification (Mark, after Task 2)

1. In the SPV, author a glow region on a Bird of Prey wing subsystem (e.g. Port Cannon) and save.
2. Damage that subsystem until disabled, so its region flickers.
3. Cycle alert states: the flicker stays on the wing as it swings, and nothing flickers at the wing's old position.
4. Revert the authored region afterwards; the file is authored data.
