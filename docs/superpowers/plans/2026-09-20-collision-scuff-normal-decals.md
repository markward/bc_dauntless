# Collision Scuff Decals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship-to-ship collisions leave a scraped, slightly buckled mark on the hull at every speed — a procedural normal + albedo decal in the existing per-instance decal ring — instead of today's torpedo-style scorch-with-ember.

**Architecture:** A third `WeaponClass::Scuff` in `scenegraph::DamageDecalRing` carrying a body-frame slip tangent. `opaque.frag` gains a **pre-lighting** pass that perturbs `n_shade` and `base.rgb` from an analytic height field (buckle waves along the slip, scratch grooves across it), band-limited by screen-space derivatives; the post-lighting loop skips the class. `collisions.py` routes both the impact and grind hits with `weapon_type="collision"`, a contact-chord radius carried by a **decal-only** kwarg, and the slip direction as the tangent.

**Tech Stack:** C++17 / GLSL 410 / glm / gtest (renderer_tests, scenegraph_tests); Python 3 / pytest; pybind11 binding `_dauntless_host.damage_decal_add`.

**Spec:** `docs/superpowers/specs/2026-09-20-collision-scuff-normal-decals-design.md` — read it first; every task below cites its sections.

## Global Constraints

- **Shared checkout — NEVER run destructive git.** Stage with explicit pathspecs only. No `git add -A`, `git add .`, `git checkout --`, `git restore`, `git stash`, `git clean`, `git reset --hard`. Back up and restore by `cp`, never by git (CLAUDE.md "Shared checkout").
- Work on branch `feat/collision-scuff-decals` (already exists; spec is committed there).
- **One build tree:** `cmake --build build -j` from the project root. Never run cmake inside `native/`. Never change `CMAKE_BUILD_TYPE` in place.
- Shader edits: rebuild (`cmake --build build -j`); shaders are embedded at configure time — if a shader edit does not show up, re-run `cmake -B build -S .` first. Shader compile errors are RUNTIME errors surfaced by the first GL test that uses the program.
- C++ tests: `./build/native/tests/scenegraph/scenegraph_tests --gtest_filter='DamageDecalRing.*'` and `./build/native/tests/renderer/renderer_tests --gtest_filter='Scuff*'` (a GL context is required; the tests `GTEST_SKIP` without one — a SKIP is not a PASS, check the summary line).
- Python tests: `uv run pytest tests/unit/<file> -q`.
- Gate before merge: `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs against `tests/known_failures.txt`).
- **Game units:** collision radii/penetration are GU; the ring converts GU → model units in the binding. Shader constants (`kScuff*`) are in **model units**.
- **Rotation convention:** column-vector, right-handed; body→world direction is `R · v`. `u_ship_world_rot` is `mat3(world)` (rotation × uniform scale; normalise after use).
- Every `_h.damage_decal_add` caller goes through `engine/host_io.damage_decal_add` — never call `_h` directly from `engine/appc`.
- No `def <Name>(` greps to decide whether Appc surface exists (CLAUDE.md). Check the stub heatmap before asserting anything is a no-op.
- Commit message trailer: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

---

## File map

| File | Responsibility in this feature |
|---|---|
| `native/src/scenegraph/include/scenegraph/damage_decals.h`, `native/src/scenegraph/src/damage_decals.cc` | `WeaponClass::Scuff`, `DamageDecal::tangent_body`, `tangent_on_surface()`, `add(..., tangent)` |
| `native/tests/scenegraph/damage_decals_test.cc` | ring behaviour for Scuff |
| `native/src/host/host_bindings.cc` (`damage_decal_add`, ~line 4112) | `world_tangent` arg, class guard `> 2u` |
| `native/src/renderer/frame.cc` (decal upload, ~line 393) | `u_decal_d`, `u_ship_world_rot` |
| `native/src/renderer/shaders/opaque.frag` | `kScuff*` consts, `u_decal_d`, `u_ship_world_rot`, `apply_scuffs()`, Scuff skip in `apply_damage_decals()` |
| `native/tests/renderer/frame_test.cc` | `scuff_probe` rig + `ScuffTest` cases |
| `engine/appc/damage_decals.py` | `WEAPON_CLASS_SCUFF`, `weapon_class_for("collision")`, radius scale |
| `engine/host_io.py` | `damage_decal_add(..., world_tangent=None)` |
| `engine/appc/hit_feedback.py` | `dispatch(tangent=None, decal_radius=None)` |
| `engine/appc/combat.py` | `apply_hit(hit_tangent=None, decal_radius=None)` |
| `engine/appc/collisions.py` | `"collision"` routing, chord radius, tangents |
| `engine/appc/visible_damage.py` | `queue_body_scuff()` deferred seeding |
| `engine/dev_missions/damage_preview.py` | three seeded scuffs |
| `tests/unit/test_damage_decals.py`, `test_decal_emission.py`, `test_apply_hit_intensity.py`, `test_collision_scuff.py` (new), `test_visible_damage.py` | Python coverage |

---

### Task 1: Ring — `WeaponClass::Scuff` with a surface tangent

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/damage_decals.h`
- Modify: `native/src/scenegraph/src/damage_decals.cc`
- Test: `native/tests/scenegraph/damage_decals_test.cc`

**Interfaces:**
- Produces: `enum class WeaponClass { HeatGlow = 0, Scorch = 1, Scuff = 2 }`; `DamageDecal::tangent_body` (last field); `glm::vec3 tangent_on_surface(const glm::vec3& normal, const glm::vec3& hint)`; `DamageDecalRing::add(point, normal, radius, intensity, weapon_class, now, const glm::vec3& tangent = glm::vec3(0.0f))`.
- Spec: §1 (class), §2 (ring policy), §3 (tangent orthogonalisation lives in `add`).

- [ ] **Step 1: Write the failing ring tests**

Append to `native/tests/scenegraph/damage_decals_test.cc`:

```cpp
// ── Collision scuffs (spec 2026-09-20 §1–§3) ────────────────────────────────

TEST(TangentOnSurface, ProjectsTheHintOntoThePlaneAndNormalises) {
    const glm::vec3 t = scenegraph::tangent_on_surface({0, 0, 1}, {2.0f, 0.0f, 5.0f});
    EXPECT_NEAR(t.x, 1.0f, 1e-5f);
    EXPECT_NEAR(t.y, 0.0f, 1e-5f);
    EXPECT_NEAR(t.z, 0.0f, 1e-5f);
}

TEST(TangentOnSurface, ZeroOrParallelHintDerivesAUnitPerpendicular) {
    for (const glm::vec3 hint : {glm::vec3(0.0f), glm::vec3(0, 0, 3)}) {
        const glm::vec3 t = scenegraph::tangent_on_surface({0, 0, 1}, hint);
        EXPECT_NEAR(glm::length(t), 1.0f, 1e-5f);
        EXPECT_NEAR(glm::dot(t, glm::vec3(0, 0, 1)), 0.0f, 1e-5f);
    }
    // Deterministic: the same inputs always give the same tangent.
    EXPECT_EQ(scenegraph::tangent_on_surface({0, 1, 0}, {}),
              scenegraph::tangent_on_surface({0, 1, 0}, {}));
}

TEST(DamageDecalRing, ScuffStoresAUnitTangentOrthogonalToItsNormal) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 5.0f, 0.5f, WeaponClass::Scuff, 0.0f,
             /*tangent=*/{3.0f, 0.0f, 9.0f});
    const DamageDecal* d = first_active(ring);
    ASSERT_NE(d, nullptr);
    EXPECT_EQ(d->weapon_class, WeaponClass::Scuff);
    EXPECT_NEAR(d->tangent_body.x, 1.0f, 1e-5f);
    EXPECT_NEAR(glm::dot(d->tangent_body, d->normal_body), 0.0f, 1e-5f);
}

TEST(DamageDecalRing, ScuffWithNoTangentStillGetsAUnitPerpendicular) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 5.0f, 0.5f, WeaponClass::Scuff, 0.0f);
    const DamageDecal* d = first_active(ring);
    ASSERT_NE(d, nullptr);
    EXPECT_NEAR(glm::length(d->tangent_body), 1.0f, 1e-5f);
    EXPECT_NEAR(glm::dot(d->tangent_body, d->normal_body), 0.0f, 1e-5f);
}

TEST(DamageDecalRing, CoLocatedScuffsMergeAndTakeTheFreshTangent) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 5.0f, 0.4f, WeaponClass::Scuff, 0.0f, {1, 0, 0});
    ring.add({1, 0, 0}, {0, 0, 1}, 5.0f, 0.4f, WeaponClass::Scuff, 1.0f, {0, 1, 0});
    EXPECT_EQ(ring.count(), 1u);
    const DamageDecal* d = first_active(ring);
    ASSERT_NE(d, nullptr);
    EXPECT_NEAR(d->intensity, 0.8f, 1e-5f);
    EXPECT_NEAR(d->tangent_body.y, 1.0f, 1e-5f);
}

TEST(DamageDecalRing, ScuffDoesNotMergeIntoAScorchAtTheSamePoint) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 5.0f, 0.4f, WeaponClass::Scorch, 0.0f);
    ring.add({0, 0, 0}, {0, 0, 1}, 5.0f, 0.4f, WeaponClass::Scuff, 1.0f, {1, 0, 0});
    EXPECT_EQ(ring.count(), 2u);
}

TEST(DamageDecalRing, ScuffEvictsHeatGlowBeforeAnyScorch) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 0.2f, 1.0f, WeaponClass::Scorch, 0.0f);   // oldest
    for (int i = 0; i < 23; ++i) {
        ring.add({static_cast<float>(i + 1) * 10.0f, 0, 0}, {0, 0, 1},
                 0.2f, 0.5f, WeaponClass::HeatGlow, static_cast<float>(i));
    }
    ASSERT_EQ(ring.count(), 24u);
    ring.add({999, 0, 0}, {0, 0, 1}, 0.2f, 0.5f, WeaponClass::Scuff, 50.0f, {1, 0, 0});
    bool scorch_present = false;
    for (const auto& d : ring.slots())
        if (d.active && d.weapon_class == WeaponClass::Scorch) scorch_present = true;
    EXPECT_TRUE(scorch_present) << "a scuff evicted the persistent scorch instead of a HeatGlow";
}

TEST(DamageDecalRing, RingOfPersistentClassesEvictsTheOldestOverall) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 0.2f, 1.0f, WeaponClass::Scuff, 0.0f, {1, 0, 0});  // seq 1
    for (int i = 0; i < 23; ++i) {
        ring.add({static_cast<float>(i + 1) * 10.0f, 0, 0}, {0, 0, 1},
                 0.2f, 0.5f, WeaponClass::Scorch, static_cast<float>(i));
    }
    ASSERT_EQ(ring.count(), 24u);
    ring.add({999, 0, 0}, {0, 0, 1}, 0.2f, 0.5f, WeaponClass::Scuff, 50.0f, {1, 0, 0});
    for (const auto& d : ring.slots())
        if (d.active) EXPECT_NE(d.point_body.x, 0.0f) << "the oldest (x=0) scuff should be gone";
}

TEST(DamageDecalRing, TickNeverReclaimsAScuff) {
    DamageDecalRing ring;
    ring.add({0, 0, 0}, {0, 0, 1}, 0.2f, 1.0f, WeaponClass::Scuff, 0.0f, {1, 0, 0});
    ring.tick(1e6f);
    EXPECT_EQ(ring.count(), 1u);
}
```

- [ ] **Step 2: Build and run to verify they fail**

Run: `cmake --build build -j --target scenegraph_tests 2>&1 | tail -5`
Expected: compile error — `Scuff` is not a member of `WeaponClass`, `tangent_on_surface` undeclared, `add` takes 6 arguments.

- [ ] **Step 3: Implement the header**

In `damage_decals.h`:

```cpp
enum class WeaponClass : std::uint32_t {
    HeatGlow = 0,
    Scorch   = 1,
    Scuff    = 2,   // collision scrape: procedural relief + albedo, no ember
};
```

Add to `DamageDecal` as the **last** field (aggregate initialisers in `add` and any test stay positional-valid):

```cpp
    std::uint64_t seq = 0;             // FIFO insertion order (0 = never used)
    /// Unit slip direction in the body frame, orthogonal to normal_body.
    /// Scuff only; zero for the other classes.
    glm::vec3     tangent_body{0.0f};
```

Add a free function after `world_dir_to_body`:

```cpp
/// Unit tangent on the surface with normal `normal`, as close as possible to
/// `hint`: the hint projected onto the tangent plane and renormalised. A zero
/// or normal-parallel hint yields a deterministic perpendicular of `normal`
/// (cross with the world axis least aligned with it).
glm::vec3 tangent_on_surface(const glm::vec3& normal, const glm::vec3& hint);
```

Change `add`'s signature:

```cpp
    void add(const glm::vec3& point_body, const glm::vec3& normal_body,
             float radius, float intensity, WeaponClass weapon_class, float now,
             const glm::vec3& tangent_body = glm::vec3(0.0f));
```

and extend its doc comment: "`tangent_body` is the slip direction hint (Scuff); it is orthogonalised against `normal_body` via `tangent_on_surface`. Ignored for the other classes."

- [ ] **Step 4: Implement the source**

In `damage_decals.cc`:

```cpp
glm::vec3 tangent_on_surface(const glm::vec3& normal, const glm::vec3& hint) {
    const float nl = glm::length(normal);
    const glm::vec3 n = nl > 0.0f ? normal / nl : glm::vec3(0.0f, 0.0f, 1.0f);
    glm::vec3 t = hint - n * glm::dot(hint, n);
    float tl = glm::length(t);
    if (tl < 1e-6f) {
        // Pick the world axis least aligned with n so the cross is well-conditioned.
        const glm::vec3 a = std::abs(n.x) < std::abs(n.y)
            ? (std::abs(n.x) < std::abs(n.z) ? glm::vec3(1, 0, 0) : glm::vec3(0, 0, 1))
            : (std::abs(n.y) < std::abs(n.z) ? glm::vec3(0, 1, 0) : glm::vec3(0, 0, 1));
        t = glm::cross(n, a);
        tl = glm::length(t);
    }
    return t / tl;
}
```

In `add`: compute the tangent once at the top, only for Scuff:

```cpp
    const glm::vec3 tangent = (weapon_class == WeaponClass::Scuff)
        ? tangent_on_surface(normal_body, tangent_body)
        : glm::vec3(0.0f);
```

Merge: change the condition to persistent classes and refresh the tangent:

```cpp
    // 1. Merge into a co-located same-class decal — persistent classes only
    //    (Scorch, Scuff). ...HeatGlow must NOT merge (existing comment)...
    if (weapon_class == WeaponClass::Scorch || weapon_class == WeaponClass::Scuff) {
        ...
                d.normal_body = normal_body; // freshest surface normal
                d.tangent_body = tangent;    // freshest slip direction (Scuff)
```

After `*target = DamageDecal{...}` add `target->tangent_body = tangent;`.

Eviction needs **no change**: the existing "oldest HeatGlow, else oldest overall" rule is already the spec's "protect persistent classes" rule — the new tests pin that it stays so. `tick()` needs no change (it only reclaims HeatGlow). Add `#include <cmath>` if `std::abs` on floats is not already available.

- [ ] **Step 5: Build and run the ring tests**

Run: `cmake --build build -j --target scenegraph_tests 2>&1 | tail -3 && ./build/native/tests/scenegraph/scenegraph_tests --gtest_filter='DamageDecalRing.*:TangentOnSurface.*'`
Expected: all PASS, including the pre-existing `DamageDecalRing.*` cases.

- [ ] **Step 6: Commit**

```bash
git add native/src/scenegraph/include/scenegraph/damage_decals.h native/src/scenegraph/src/damage_decals.cc native/tests/scenegraph/damage_decals_test.cc
git commit -m "feat(decals): WeaponClass::Scuff with a surface tangent in the decal ring

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Shader relief — upload, binding, and the pre-lighting scuff pass

**Files:**
- Modify: `native/src/renderer/frame.cc` (decal upload block, ~lines 393–420)
- Modify: `native/src/host/host_bindings.cc` (`damage_decal_add`, ~line 4112)
- Modify: `native/src/renderer/shaders/opaque.frag`
- Test: `native/tests/renderer/frame_test.cc`

**Interfaces:**
- Consumes: Task 1's `WeaponClass::Scuff`, `DamageDecal::tangent_body`, `add(..., tangent)`.
- Produces: uniforms `u_decal_d[MAX_DECALS]` (`tangent_body.xyz`, 0) and `u_ship_world_rot` (`mat3`); `apply_scuffs(vec3 p_body, vec3 n_body, inout vec3 n_shade, inout vec3 base_rgb)` — this task implements the **normal** half; Task 3 fills the albedo half, Task 4 the band-limit; binding `damage_decal_add(instance_id, world_point, world_normal, radius, intensity, weapon_class, time, world_tangent=(0,0,0))`.
- Spec: §4 (shader), §3 (upload/binding).

- [ ] **Step 1: Write the failing render tests**

Add a `scuff_probe` namespace and tests to `native/tests/renderer/frame_test.cc`, after the `TangentBasisTest` cases (they reuse `block_mean`, `read_frame`, `differing_texels` and `tangent_probe::dir_light` / `uniform_rgba`, which are defined earlier in the file — check the exact names at the top of `namespace tangent_probe` before writing):

```cpp
// ── Collision scuffs: procedural relief in the decal ring ──────────────────
// Spec: docs/superpowers/specs/2026-09-20-collision-scuff-normal-decals-design.md
// A 200x200 MODEL-UNIT quad (Galaxy-scale, so the kScuff* wavelengths are in
// their intended regime), white diffuse, NO material normal map. The scuff is
// seeded straight into the ring so the test needs no game assets.
namespace scuff_probe {

constexpr float kHalf = 100.0f;

std::unique_ptr<assets::Model> build_quad(unsigned char grey = 255) {
    auto model = std::make_unique<assets::Model>();
    assets::MeshCpu cpu;
    cpu.material_index = 0;
    cpu.node_index     = 0;
    auto push = [&cpu](float x, float y, float u, float v) {
        assets::MeshCpu::Vertex vt;
        vt.position = glm::vec3(x, y, 0.0f);
        vt.normal   = glm::vec3(0.0f, 0.0f, 1.0f);
        vt.uv       = glm::vec2(u, v);
        cpu.vertices.push_back(vt);
    };
    push(-kHalf, -kHalf, 0.0f, 0.0f);
    push( kHalf, -kHalf, 1.0f, 0.0f);
    push( kHalf,  kHalf, 1.0f, 1.0f);
    push(-kHalf,  kHalf, 0.0f, 1.0f);
    cpu.indices = {0, 1, 2, 0, 2, 3};
    assets::Mesh mesh = assets::upload_mesh(cpu);
    mesh.set_cpu_data(cpu);
    model->meshes.push_back(std::move(mesh));
    model->textures.push_back(
        assets::upload_image(tangent_probe::uniform_rgba(grey, grey, grey, 2), false));
    using Slot = assets::Material::StageSlot;
    assets::Material mat;
    mat.diffuse    = glm::vec3(1.0f);
    mat.specular   = glm::vec3(0.0f);
    mat.emissive   = glm::vec3(0.0f);
    mat.glossiness = 0.0f;
    mat.stages[static_cast<size_t>(Slot::Base)].texture_index = 0;
    model->materials.push_back(mat);
    assets::Node node;
    node.name   = "scuff_quad";
    node.meshes = {0};
    model->nodes.push_back(node);
    model->root_node = 0;
    return model;
}

struct Seed {
    bool active = false;
    glm::vec3 point{0.0f};
    glm::vec3 normal{0.0f, 0.0f, 1.0f};
    glm::vec3 tangent{1.0f, 0.0f, 0.0f};
    float radius = 60.0f;      // model units
    float intensity = 1.0f;
    scenegraph::WeaponClass cls = scenegraph::WeaponClass::Scuff;
};

// Camera on +Z looking at the origin. eye_z = 150 puts ~1.48 px per model
// unit on screen (256 px / (2 * 150 * tan 30deg)); the quad overfills the view.
void render(const assets::Model& model, renderer::Pipeline& pipeline,
            const renderer::Lighting& lighting, const Seed& seed,
            float eye_z = 150.0f) {
    scenegraph::World world;
    auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(&model));
    world.set_world_transform(iid, glm::mat4(1.0f));
    if (seed.active) {
        world.get(iid)->decals.add(seed.point, seed.normal, seed.radius,
                                   seed.intensity, seed.cls, 0.0f, seed.tangent);
    }
    scenegraph::Camera cam;
    cam.eye    = glm::vec3(0.0f, 0.0f, eye_z);
    cam.target = glm::vec3(0.0f);
    cam.up     = glm::vec3(0.0f, 1.0f, 0.0f);
    cam.aspect = 1.0f;
    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    renderer::reset_model_radius_cache();
    renderer::FrameSubmitter submitter;
    submitter.submit_opaque(world, cam, pipeline,
        [](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        }, lighting, /*decal_time=*/1.0f, /*carve_cache=*/nullptr, nullptr);
}

// Population std-dev of the channel sum over a block (lower-left x0,y0).
double block_stddev(int x0, int y0, int w, int h) {
    std::vector<unsigned char> buf(static_cast<size_t>(w) * h * 4);
    glReadPixels(x0, y0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, buf.data());
    double mean = 0.0;
    for (int i = 0; i < w * h; ++i) mean += buf[i*4] + buf[i*4+1] + buf[i*4+2];
    mean /= (w * h);
    double var = 0.0;
    for (int i = 0; i < w * h; ++i) {
        const double v = buf[i*4] + buf[i*4+1] + buf[i*4+2];
        var += (v - mean) * (v - mean);
    }
    return std::sqrt(var / (w * h));
}

// Oblique light so relief shows as shading variation (head-on light hides it).
renderer::Lighting oblique() { return tangent_probe::dir_light(glm::vec3(0.5f, 0.3f, 0.8f)); }

}  // namespace scuff_probe

class ScuffTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   w;
    std::unique_ptr<renderer::Pipeline> p;
    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(256, 256, "scuff", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
    }
};

// Footprint: seed at the origin, radius 60 model units = ~89 px at eye_z 150.
// Inside block: 40x40 px centred (well inside the 0.6 plateau of `win`).
// Outside block: the top-left 40x40 corner, >150 px from the centre.
TEST_F(ScuffTest, PerturbsShadingInsideTheFootprintOnly) {
    using namespace scuff_probe;
    auto quad = build_quad();
    Seed none;
    render(*quad, *p, oblique(), none);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const auto base_frame = read_frame();
    const double base_in  = block_stddev(108, 108, 40, 40);
    ASSERT_LT(base_in, 1.0) << "the undamaged quad must be flat-lit";

    Seed s; s.active = true;
    render(*quad, *p, oblique(), s);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const auto scuffed = read_frame();
    const double in = block_stddev(108, 108, 40, 40);
    EXPECT_GT(in, 6.0) << "no relief inside the scuff footprint (stddev " << in << ")";

    // Outside the footprint: byte-identical (the loop `continue`s at r >= 1).
    size_t diff = 0;
    for (int y = 200; y < 240; ++y)
        for (int x = 8; x < 48; ++x) {
            const size_t i = (static_cast<size_t>(y) * 256 + x) * 4;
            if (base_frame[i] != scuffed[i] || base_frame[i+1] != scuffed[i+1]
                || base_frame[i+2] != scuffed[i+2]) ++diff;
        }
    EXPECT_EQ(diff, 0u) << "scuff leaked outside its radius";
}

TEST_F(ScuffTest, OnTheFarFaceLeavesTheNearFaceUntouched) {
    using namespace scuff_probe;
    auto quad = build_quad();
    Seed none;
    render(*quad, *p, oblique(), none);
    const auto base_frame = read_frame();
    Seed s; s.active = true; s.normal = glm::vec3(0, 0, -1);   // faces AWAY
    render(*quad, *p, oblique(), s);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    EXPECT_EQ(differing_texels(base_frame, read_frame()), 0u)
        << "a scuff whose normal faces away perturbed the camera-facing surface";
}

// The Scuff class must be skipped by the post-lighting scorch loop: with no
// light at all, a Scorch would still render its ember; a Scuff must be black.
TEST_F(ScuffTest, HasNoEmberSoItIsBlackWhenUnlit) {
    using namespace scuff_probe;
    auto quad = build_quad();
    renderer::Lighting dark = tangent_probe::dir_light(glm::vec3(0, 0, 1), 0.0f);
    Seed s; s.active = true;
    render(*quad, *p, dark, s);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    EXPECT_EQ(block_mean(108, 108, 40, 40), 0.0) << "unlit scuff is not black — ember/flicker leaked in";

    // Control: the same seed as Scorch is NOT black (its fresh ember glows),
    // proving the assertion above can fail.
    Seed sc = s; sc.cls = scenegraph::WeaponClass::Scorch;
    render(*quad, *p, dark, sc);
    EXPECT_GT(block_mean(108, 108, 40, 40), 0.0) << "control: scorch ember should glow unlit";
}
```

Add `#include <cmath>` at the top of the file if missing.

- [ ] **Step 2: Build and run to verify they fail**

Run: `cmake --build build -j --target renderer_tests 2>&1 | tail -3 && ./build/native/tests/renderer/renderer_tests --gtest_filter='ScuffTest.*'`
Expected: `PerturbsShadingInsideTheFootprintOnly` FAILS (`in` ≈ 0 — nothing perturbs yet); `HasNoEmberSoItIsBlackWhenUnlit` FAILS (class 2 currently takes the `> 0.5` Scorch branch and glows). If a test SKIPs for lack of a GL context, run it on a machine with one before continuing.

- [ ] **Step 3: Upload the tangent and the rotation (`frame.cc`)**

In the decal upload block (~line 393):

```cpp
        glm::vec4 a[scenegraph::DamageDecalRing::kMaxDecals];
        glm::vec4 b[scenegraph::DamageDecalRing::kMaxDecals];
        glm::vec4 c[scenegraph::DamageDecalRing::kMaxDecals];
        glm::vec4 d[scenegraph::DamageDecalRing::kMaxDecals];   // tangent_body.xyz, _
        ...
                c[n] = glm::vec4(...);
                d[n] = glm::vec4(dec.tangent_body, 0.0f);
        ...
            prog.set_vec4_array("u_decal_c", c, n);
            prog.set_vec4_array("u_decal_d", d, n);
            prog.set_mat4("u_ship_world_inv", glm::inverse(world));
            // Body->world rotation (x uniform scale) for the scuff pass's
            // tangent frame; the shader normalises after use.
            prog.set_mat3("u_ship_world_rot", glm::mat3(world));
```

(The loop variable is named `d` today — rename it to `dec` so the array `d` does not shadow it.)

- [ ] **Step 4: Extend the binding (`host_bindings.cc`)**

```cpp
    m.def("damage_decal_add",
          [](scenegraph::InstanceId id,
             std::tuple<float, float, float> world_point,
             std::tuple<float, float, float> world_normal,
             float radius, float intensity,
             std::uint32_t weapon_class, float time,
             std::tuple<float, float, float> world_tangent) {
              if (weapon_class > 2u) return;  // unknown weapon class — drop silently
              ...
              const glm::vec3 tw(std::get<0>(world_tangent),
                                 std::get<1>(world_tangent),
                                 std::get<2>(world_tangent));
              // Zero stays zero (world_dir_to_body returns a length-0 input
              // unchanged); the ring then derives a perpendicular.
              const glm::vec3 tb = scenegraph::world_dir_to_body(inst->world, tw);
              ...
              inst->decals.add(pb, nb, radius_model, intensity,
                               static_cast<scenegraph::WeaponClass>(weapon_class),
                               time, tb);
          },
          py::arg("instance_id"), py::arg("world_point"), py::arg("world_normal"),
          py::arg("radius"), py::arg("intensity"),
          py::arg("weapon_class"), py::arg("time"),
          py::arg("world_tangent") = std::make_tuple(0.0f, 0.0f, 0.0f),
          "Record an object-space damage decal on a ship instance. World-space "
          "point/normal are transformed into the ship body frame. weapon_class: "
          "0=HeatGlow (phaser), 1=Scorch (torpedo/disruptor), 2=Scuff (collision; "
          "world_tangent = slip direction, zero = no preferred direction).");
```

- [ ] **Step 5: The shader — uniforms, constants, `apply_scuffs`, and the post-loop skip**

In `opaque.frag`, next to the decal uniforms (~line 101):

```glsl
uniform vec4  u_decal_d[MAX_DECALS];         // tangent_body.xyz (unit, ⟂ normal; Scuff), _
uniform mat3  u_ship_world_rot;              // body->world rotation (x uniform scale)

// ── Collision scuffs (class 2): procedural relief, pre-lighting ───────────
// Spec: docs/superpowers/specs/2026-09-20-collision-scuff-normal-decals-design.md §4
// All lengths in MODEL units (Galaxy hull ≈ ±178). Tuning constants: rebuild
// to change, same convention as kHullCarve*. Starting values, judged live.
const float kScuffBuckleAmp   = 0.35;                 // dh per unit, buckle waves
const float kScuffBuckleFreq  = 6.2831853 / 24.0;     // rad/unit: 24-unit wavelength
const float kScuffScratchAmp  = 0.25;                 // dh per unit, scratch grooves
const float kScuffScratchFreq = 6.2831853 / 3.0;      // rad/unit: 3-unit wavelength
```

After `fbm` (so `vnoise`/`dhash` exist), add:

```glsl
// 1-D value noise in [-1, 1] (a fixed row of the 2-D noise).
float snoise1(float x) { return vnoise(vec2(x, 17.3)) * 2.0 - 1.0; }

// Collision scuffs — the PRE-LIGHTING half of the decal ring. Perturbs the
// shading normal (relief) and the base albedo (Task 3) inside each Scuff
// decal. Writes ONLY n_shade and base_rgb: never the shadow-bias normal, the
// Fresnel rim, n_body, the carve loop, decal_emissive or glow_flicker.
void apply_scuffs(vec3 p_body, vec3 n_body, inout vec3 n_shade, inout vec3 base_rgb) {
    vec3 dn_ws = vec3(0.0);
    for (int i = 0; i < u_decal_count; ++i) {
        if (u_decal_c[i].y < 1.5) continue;          // Scuff only (class 2)
        vec3  point  = u_decal_a[i].xyz;
        float inten  = u_decal_a[i].w;
        vec3  dn     = u_decal_b[i].xyz;
        float radius = u_decal_b[i].w;
        if (radius <= 0.0) continue;
        vec3  d = p_body - point;
        float r = length(d) / radius;
        if (r >= 1.0) continue;                       // outside: byte-identical
        // Same far-face guard as the other classes.
        float wn = smoothstep(NORMAL_MIN, 1.0, dot(n_body, dn));
        if (wn <= 0.0) continue;

        vec3  T = u_decal_d[i].xyz;
        vec3  B = cross(dn, T);
        float u = dot(d, T);                          // along the slip
        float w = dot(d, B);                          // across the slip
        float win = (1.0 - smoothstep(0.6, 1.0, r)) * inten * wn;
        float phase = dhash(point.xy + point.z) * 6.2831853;

        // Buckle: h = A sin(k u + φ)  →  ∂h/∂u = A k cos(k u + φ)
        float gu = kScuffBuckleAmp * kScuffBuckleFreq
                 * cos(kScuffBuckleFreq * u + phase) * win;
        // Scratches: h = A n(k w)  →  ∂h/∂w = A k n'(k w), central difference.
        float x = kScuffScratchFreq * w;
        const float e = 0.05;
        float dnw = (snoise1(x + e) - snoise1(x - e)) / (2.0 * e);
        float gw = kScuffScratchAmp * kScuffScratchFreq * dnw * win;

        vec3 T_ws = normalize(u_ship_world_rot * T);
        vec3 B_ws = normalize(u_ship_world_rot * B);
        dn_ws -= gu * T_ws + gw * B_ws;
    }
    if (dot(dn_ws, dn_ws) > 0.0) n_shade = normalize(n_shade + dn_ws);
}
```

In `apply_damage_decals`, first line inside the `for`:

```glsl
        if (u_decal_c[i].y > 1.5) continue;   // Scuff: handled pre-lighting by apply_scuffs
```

In `main()`: move `vec3 p_body = ...` (currently ~line 727) and `vec3 n_body = normalize(mat3(u_ship_world_inv) * v_normal_ws);` (currently ~line 1065) up to directly after `n_shade` is computed, and move `vec4 base = texture(u_base_color, v_uv);` (currently ~line 1026) up next to them (a texture sample independent of position — safe to hoist). Then:

```glsl
    if (u_decal_count > 0) {
        apply_scuffs(p_body, n_body, n_shade, base.rgb);
    }
```

immediately after — before the Toksvig `spec_ft` line and before any lighting term reads `n_shade`. Delete the original three declarations at their old sites (leave the later `if (u_decal_count > 0) apply_damage_decals(...)` where it is).

- [ ] **Step 6: Rebuild and run the scuff tests + the existing decal/normal-map tests**

Run: `cmake -B build -S . > /dev/null && cmake --build build -j 2>&1 | tail -3 && ./build/native/tests/renderer/renderer_tests --gtest_filter='ScuffTest.*:FrameTest.*Decal*:FrameTest.*Scorch*:FrameTest.*HeatGlow*:FrameTest.UndamagedInstanceGlowMatchesEmptyRingBaseline:TangentBasisTest.*'`
Expected: every listed test PASS (or SKIP only for missing BC assets, never for a shader compile error — a compile error prints in the first failing test's output). If `PerturbsShadingInsideTheFootprintOnly` reports `in` between 1 and 6, print the number and raise the light's obliquity (`oblique()`), not the shader amplitude.

- [ ] **Step 7: Run the whole ctest suite once**

Run: `ctest --test-dir build -j 4 2>&1 | tail -5`
Expected: same failures as `tests/known_failures.txt` (currently none in ctest) — nothing new.

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/frame.cc native/src/host/host_bindings.cc native/src/renderer/shaders/opaque.frag native/tests/renderer/frame_test.cc
git commit -m "feat(renderer): collision scuff relief — pre-lighting normal perturbation from the decal ring

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Shader albedo — bare-metal scratch lines + grime rim

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag` (`apply_scuffs`, constants)
- Test: `native/tests/renderer/frame_test.cc`

**Interfaces:**
- Consumes: Task 2's `apply_scuffs`, `scuff_probe` rig.
- Produces: constants `kScuffMetal`, `kScuffAlbedoGain`, `kScuffGrime`.
- Spec: §4 "Albedo".

- [ ] **Step 1: Write the failing test**

Ambient-only light makes `lit = ambient * base`: `n_shade` cannot affect it (the ambient gradient is off), so whatever changes inside the footprint is the albedo term alone. A mid-grey base leaves headroom for the metal to read lighter.

```cpp
TEST_F(ScuffTest, AlbedoLightensScratchRidgesAndDarkensTheRimUnderAmbientOnlyLight) {
    using namespace scuff_probe;
    auto quad = build_quad(/*grey=*/80);
    renderer::Lighting amb;
    amb.ambient = glm::vec3(1.0f);
    amb.directional_count = 0;

    Seed none;
    render(*quad, *p, amb, none);
    const double base_mean = block_mean(108, 108, 40, 40);
    const double base_sd   = block_stddev(108, 108, 40, 40);
    ASSERT_LT(base_sd, 1.0);

    Seed s; s.active = true;
    render(*quad, *p, amb, s);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    // Ridges: some pixels in the core are LIGHTER than the flat base.
    std::vector<unsigned char> buf(40 * 40 * 4);
    glReadPixels(108, 108, 40, 40, GL_RGBA, GL_UNSIGNED_BYTE, buf.data());
    double brightest = 0.0;
    for (int i = 0; i < 40 * 40; ++i)
        brightest = std::max(brightest, double(buf[i*4] + buf[i*4+1] + buf[i*4+2]));
    EXPECT_GT(brightest, base_mean + 12.0) << "no bare-metal lightening on the scratch ridges";
    EXPECT_GT(block_stddev(108, 108, 40, 40), 3.0) << "albedo is uniform inside the scuff";
    // Rim band (r in 0.75..0.95 of a 60-unit radius = 45..57 units = 67..84 px
    // from the centre): a thin 6x20 block at x=128+70..76 is darker than base.
    const double rim = block_mean(198, 118, 6, 20);
    EXPECT_LT(rim, base_mean - 2.0) << "no grime darkening at the rim";
}
```

- [ ] **Step 2: Build and run to verify it fails**

Run: `cmake --build build -j --target renderer_tests 2>&1 | tail -3 && ./build/native/tests/renderer/renderer_tests --gtest_filter='ScuffTest.Albedo*'`
Expected: FAIL on `brightest` (albedo untouched; under ambient-only light the frame is flat).

- [ ] **Step 3: Implement the albedo term**

Constants, next to the other `kScuff*`:

```glsl
const vec3  kScuffMetal       = vec3(0.62);           // bare-metal albedo on scratch ridges
const float kScuffAlbedoGain  = 0.6;                  // how far ridges go toward kScuffMetal
const float kScuffGrime       = 0.25;                 // rim darkening at the patch edge
```

Inside the loop in `apply_scuffs`, after `gw` is computed (the scratch noise value is needed, so keep `nw`):

```glsl
        float nw  = snoise1(x);
        ...
        // Albedo: bare metal where the scratch field peaks (ridges), and a
        // thin grime band at the rim. Both confined by win / wn like the relief.
        float scratch = smoothstep(0.55, 0.8, nw * 0.5 + 0.5) * win;
        base_rgb = mix(base_rgb, kScuffMetal, scratch * kScuffAlbedoGain);
        float rim = smoothstep(0.75, 0.95, r) * (1.0 - smoothstep(0.95, 1.0, r));
        base_rgb *= 1.0 - kScuffGrime * rim * inten * wn;
```

- [ ] **Step 4: Build and run all scuff tests**

Run: `cmake --build build -j 2>&1 | tail -3 && ./build/native/tests/renderer/renderer_tests --gtest_filter='ScuffTest.*'`
Expected: all PASS. `HasNoEmberSoItIsBlackWhenUnlit` must still pass — the albedo term multiplies into a zero `lit`, so unlit stays black.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/shaders/opaque.frag native/tests/renderer/frame_test.cc
git commit -m "feat(renderer): scuff albedo — bare-metal scratch ridges and a grime rim

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Band-limiting — no sparkle at range

**Files:**
- Modify: `native/src/renderer/shaders/opaque.frag` (`apply_scuffs`)
- Test: `native/tests/renderer/frame_test.cc`

**Interfaces:**
- Consumes: Task 2/3's `apply_scuffs`.
- Produces: `float scuff_bandlimit(float fw, float k)`.
- Spec: §4 "Band-limiting is mandatory" — `fwidth(p_body)` ONCE before the loop, in uniform control flow.

- [ ] **Step 1: Write the failing test**

At `eye_z = 2400` one model unit is ~0.09 px: the 3-unit scratch wavelength is 0.28 px (pure aliasing if not faded) and the 24-unit buckle is 2.2 px (inside the fade band). The quad is ~18 px wide; sample its central 12×12.

```cpp
TEST_F(ScuffTest, IsBandLimitedSoItDoesNotSparkleAtRange) {
    using namespace scuff_probe;
    auto quad = build_quad();
    Seed s; s.active = true; s.radius = 100.0f;   // the whole quad is scuffed
    render(*quad, *p, oblique(), s, /*eye_z=*/150.0f);
    const double near_sd = block_stddev(108, 108, 40, 40);
    ASSERT_GT(near_sd, 6.0) << "rig sanity: relief must be visible up close";

    render(*quad, *p, oblique(), s, /*eye_z=*/2400.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double far_sd = block_stddev(122, 122, 12, 12);
    EXPECT_LT(far_sd, 3.0) << "scuff sparkles at range (stddev " << far_sd
                           << ", near " << near_sd << ")";
}
```

- [ ] **Step 2: Build and run to verify it fails**

Run: `cmake --build build -j --target renderer_tests 2>&1 | tail -3 && ./build/native/tests/renderer/renderer_tests --gtest_filter='ScuffTest.IsBandLimited*'`
Expected: FAIL — `far_sd` well above 3 (sub-pixel scratches alias into speckle). If it unexpectedly passes, print `far_sd`; if the MSAA/resolve path is smoothing it, lower `eye_z` until the near/far contrast reproduces, and record the chosen value in the test comment.

- [ ] **Step 3: Implement the fade**

Add before `apply_scuffs`:

```glsl
// Band-limit a procedural term: 1 when its wavelength spans >= 4 px, 0 at
// <= 2 px. `fw` is the axis footprint in model units per pixel, `k` rad/unit.
float scuff_bandlimit(float fw, float k) {
    float cycles_per_px = fw * k / 6.2831853;
    return 1.0 - smoothstep(0.25, 0.5, cycles_per_px);
}
```

In `apply_scuffs`, **before** the loop (uniform control flow — GLSL derivatives inside a loop that `continue`s are undefined):

```glsl
    vec3 fw_p = fwidth(p_body);               // per-pixel footprint, model units
```

Inside the loop, after `T`/`B`:

```glsl
        // Axis footprints: |T·dp| <= dot(|T|, |dp|), a conservative estimate.
        float bl_u = scuff_bandlimit(dot(abs(T), fw_p), kScuffBuckleFreq);
        float bl_w = scuff_bandlimit(dot(abs(B), fw_p), kScuffScratchFreq);
```

and multiply: `gu *= bl_u;`, `gw *= bl_w;`, `scratch *= bl_w;` (the albedo ridges are the same frequency as the grooves and alias the same way; the grime rim is low-frequency and stays).

- [ ] **Step 4: Build and run all scuff tests + the empty-ring baseline**

Run: `cmake --build build -j 2>&1 | tail -3 && ./build/native/tests/renderer/renderer_tests --gtest_filter='ScuffTest.*:FrameTest.UndamagedInstanceGlowMatchesEmptyRingBaseline'`
Expected: all PASS. The near-range tests from Tasks 2–3 must keep passing: at 1.48 px/unit the buckle is 35 px/cycle and the scratches 4.4 px/cycle, both under the 0.25 cycles/px fade start.

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/shaders/opaque.frag native/tests/renderer/frame_test.cc
git commit -m "feat(renderer): band-limit scuff relief by screen-space footprint so it cannot sparkle at range

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Python routing — class, façade kwarg, dispatch, apply_hit

**Files:**
- Modify: `engine/appc/damage_decals.py`
- Modify: `engine/host_io.py` (`damage_decal_add`, ~line 291)
- Modify: `engine/appc/hit_feedback.py` (`dispatch` signature ~line 192; decal emit ~line 360)
- Modify: `engine/appc/combat.py` (`apply_hit` signature ~line 609; `hit_feedback.dispatch(` call ~line 845)
- Modify (spies): `tests/unit/test_decal_emission.py:26`, `tests/unit/test_apply_hit_intensity.py:111`
- Test: `tests/unit/test_damage_decals.py`, `tests/unit/test_decal_emission.py`

**Interfaces:**
- Consumes: binding `damage_decal_add(..., world_tangent=(0,0,0))` from Task 2.
- Produces: `damage_decals.WEAPON_CLASS_SCUFF = 2`; `weapon_class_for("collision") == 2`; `host_io.damage_decal_add(instance_id, world_point, world_normal, radius, intensity, weapon_class, time, world_tangent=None)`; `hit_feedback.dispatch(..., tangent=None, decal_radius=None)`; `combat.apply_hit(..., hit_tangent=None, decal_radius=None)`.
- Spec: §1, §3.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_damage_decals.py`:

```python
def test_collision_maps_to_scuff():
    assert dd.weapon_class_for("collision") == dd.WEAPON_CLASS_SCUFF == 2


def test_none_still_maps_to_scorch_so_splash_and_breach_callers_are_unchanged():
    assert dd.weapon_class_for(None) == dd.WEAPON_CLASS_SCORCH


def test_scuff_radius_scale_is_identity():
    # The contact chord IS the visual size (spec §3).
    assert dd.decal_radius_scale(dd.WEAPON_CLASS_SCUFF) == 1.0
```

(Check the module alias at the top of that file — it imports `engine.appc.damage_decals`; use whatever name it binds.)

In `tests/unit/test_decal_emission.py`, extend the spy to record the tangent, and add tests:

```python
class _DecalCapture:
    """Positional-arg capture matching host_io.damage_decal_add's signature
    (instance_id, world_point, world_normal, radius, intensity, weapon_class,
    time, world_tangent=None)."""

    def __init__(self):
        self.decal_calls = []

    def __call__(self, instance_id, world_point, world_normal,
                 radius, intensity, weapon_class, time, world_tangent=None):
        self.decal_calls.append(dict(
            instance_id=instance_id, world_point=world_point,
            world_normal=world_normal, radius=radius, intensity=intensity,
            weapon_class=weapon_class, time=time, world_tangent=world_tangent))
```

and update `_dispatch` to accept and forward `tangent=None, decal_radius=None`:

```python
def _dispatch(*, absorbed_hull, weapon_type="torpedo", normal=_Pt(0, 0, 1),
              persist_decal=True, tangent=None, decal_radius=None):
    ship = _Ship()
    hit_feedback.dispatch(
        ship=ship, source=None, point=_Pt(1, 2, 3), normal=normal,
        damage=10.0, subsystem=None,
        absorbed_shields=0.0, absorbed_subsystem=0.0,
        absorbed_hull=absorbed_hull, sub_transition=None,
        ship_instances={ship: "IID"},
        weapon_type=weapon_type, radius=0.2, persist_decal=persist_decal,
        tangent=tangent, decal_radius=decal_radius,
    )
```

New tests:

```python
def test_collision_emits_scuff_with_tangent_and_decal_radius(patched, decal):
    _dispatch(absorbed_hull=5.0, weapon_type="collision",
              tangent=_Pt(0, 1, 0), decal_radius=2.5)
    assert len(decal.decal_calls) == 1
    c = decal.decal_calls[0]
    assert c["weapon_class"] == dd.WEAPON_CLASS_SCUFF
    assert c["world_tangent"] == (0, 1, 0)
    assert c["radius"] == pytest.approx(2.5)        # chord, scale 1.0 — NOT 0.2 * anything


def test_weapon_callers_pass_no_tangent_and_keep_the_weapon_radius(patched, decal):
    _dispatch(absorbed_hull=5.0)                     # torpedo, radius=0.2
    c = decal.decal_calls[0]
    assert c["world_tangent"] is None
    assert c["radius"] == pytest.approx(0.2 * dd.decal_radius_scale(dd.WEAPON_CLASS_SCORCH))


def test_decal_radius_none_falls_back_to_the_hit_radius_for_a_collision(patched, decal):
    _dispatch(absorbed_hull=5.0, weapon_type="collision")
    assert decal.decal_calls[0]["radius"] == pytest.approx(0.2)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_damage_decals.py tests/unit/test_decal_emission.py -q`
Expected: FAIL — `WEAPON_CLASS_SCUFF` missing; `dispatch() got an unexpected keyword argument 'tangent'`.

- [ ] **Step 3: Implement `damage_decals.py`**

```python
WEAPON_CLASS_HEAT_GLOW = 0   # phaser — transient emissive bloom
WEAPON_CLASS_SCORCH = 1      # torpedo / disruptor — persistent deposit + ember
WEAPON_CLASS_SCUFF = 2       # collision — procedural relief + bare-metal scratches, no ember
```

```python
_RADIUS_SCALE = {
    WEAPON_CLASS_HEAT_GLOW: 0.5,
    WEAPON_CLASS_SCORCH: 2.25,
    WEAPON_CLASS_SCUFF: 1.0,     # the contact chord IS the visual size (spec §3)
}
```

```python
def weapon_class_for(weapon_type):
    """Map a weapon_type string ("phaser" / "torpedo" / "collision" / ...) to a
    decal class.

    "phaser" -> transient heat-glow; "collision" -> scuff (collisions.py passes
    it explicitly so a scrape never inherits the torpedo ember); everything
    else (torpedo, disruptor, None, unknown) -> persistent scorch.
    """
    if weapon_type == "phaser":
        return WEAPON_CLASS_HEAT_GLOW
    if weapon_type == "collision":
        return WEAPON_CLASS_SCUFF
    return WEAPON_CLASS_SCORCH
```

- [ ] **Step 4: Implement the `host_io` wrapper**

```python
def damage_decal_add(
    instance_id: int,
    world_point: Tuple[float, float, float],
    world_normal: Tuple[float, float, float],
    radius: float,
    intensity: float,
    weapon_class: int,
    time: float,
    world_tangent: Optional[Tuple[float, float, float]] = None,
) -> None:
    """`world_tangent` is the slip direction for a Scuff decal (world space);
    None means no preferred direction (the ring derives a perpendicular)."""
    if _h is None:
        return
    _h.damage_decal_add(instance_id, world_point, world_normal, radius,
                        intensity, weapon_class, time,
                        world_tangent if world_tangent is not None
                        else (0.0, 0.0, 0.0))
```

- [ ] **Step 5: Implement `dispatch`**

Signature: add `tangent=None, decal_radius: float | None = None` after `allow_hull_carve`. Docstring addition: "`tangent` is the world-space slip direction (TGPoint3) for a collision scuff, or None. `decal_radius` overrides `radius` for the DECAL ONLY — the carve and everything else keep `radius` (spec §3: `r_hit` also sets the subsystem catchment, so it must not carry the scuff size)."

In step 4 (decal emit), replace the radius argument and add the tangent:

```python
                vis_r = float(decal_radius) if decal_radius is not None else float(radius)
                host_io.damage_decal_add(
                    iid,
                    (point.x, point.y, point.z),
                    (normal.x, normal.y, normal.z),
                    vis_r * damage_decals.decal_radius_scale(wclass),
                    damage_decals.decal_intensity(absorbed_hull),
                    wclass,
                    now,
                    world_tangent=((tangent.x, tangent.y, tangent.z)
                                   if tangent is not None else None),
                )
```

- [ ] **Step 6: Implement `apply_hit`**

Add `hit_tangent=None, decal_radius: float | None = None` to the keyword-only parameters, document both in the docstring ("hit_tangent — world-space slip direction for a collision scuff, or None. decal_radius — visual decal radius in GU; overrides `r_hit` for the decal ONLY, never for the subsystem catchment / carve / WeaponHitEvent"), and forward them in the `hit_feedback.dispatch(` call: `tangent=hit_tangent, decal_radius=decal_radius,`.

- [ ] **Step 7: Update the remaining positional spy**

`tests/unit/test_apply_hit_intensity.py:111`:

```python
    def damage_decal_add(self, instance_id, world_point, world_normal,
                         radius, intensity, weapon_class, time,
                         world_tangent=None):
```

(`test_hit_vfx_flash_anchor.py` and `test_combat_cheats.py` use `lambda *a, **k`, which already accept the keyword.)

- [ ] **Step 8: Run the Python decal/combat/collision suites**

Run: `uv run pytest tests/unit/test_damage_decals.py tests/unit/test_decal_emission.py tests/unit/test_apply_hit_intensity.py tests/unit/test_hit_feedback_dispatch.py tests/unit/test_combat_cheats.py tests/unit/test_hit_vfx_flash_anchor.py tests/unit/test_collisions.py tests/unit/test_collision_hull_carve.py tests/unit/test_host_io_binding_manifest.py -q`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add engine/appc/damage_decals.py engine/host_io.py engine/appc/hit_feedback.py engine/appc/combat.py tests/unit/test_damage_decals.py tests/unit/test_decal_emission.py tests/unit/test_apply_hit_intensity.py
git commit -m "feat(combat): route collisions to the Scuff decal class with a decal-only radius and slip tangent

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Collisions — `"collision"` type, contact-chord radius, slip tangents

**Files:**
- Modify: `engine/appc/collisions.py` (`_grind_contact` ~line 241, `_respond_pair` ~line 306)
- Test: `tests/unit/test_collision_scuff.py` (new)

**Interfaces:**
- Consumes: Task 5's `apply_hit(weapon_type=..., hit_tangent=..., decal_radius=...)`.
- Produces: `SCUFF_RADIUS_MIN_GU = 0.5`, `SCUFF_RADIUS_MAX_GU = 4.0`, `scuff_radius_gu(r_small: float, pen: float) -> float`; `_grind_contact(..., ship_instances=None, scuff_radius=0.0)`.
- Spec: §3 "Tangent source", "Radius".

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_collision_scuff.py`:

```python
"""Collisions route to the Scuff decal: weapon_type "collision", a contact-chord
decal radius, and the slip direction as the tangent (spec 2026-09-20 §3).

apply_hit is captured at the collision module's own output boundary, the same
seam test_collision_sustained_contact.py uses."""
import math

import pytest

from engine.appc import collisions
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass

GALAXY_MASS = 120.0
FRAME = 1.0 / 60.0


class _Hull:
    def IsDestroyed(self):
        return 0


def _ship(x, mass=GALAXY_MASS, vx=0.0, vy=0.0, radius=1.0):
    s = ShipClass()
    s.SetTranslateXYZ(x, 0.0, 0.0)
    s.SetRadius(radius)
    s.SetMass(mass)
    s.SetVelocity(TGPoint3(vx, vy, 0.0))
    s.GetHull = lambda: _Hull()
    s.DamageSystem = lambda sub, dmg, src=None: None
    return s


@pytest.fixture
def hits(monkeypatch):
    import engine.appc.combat as combat
    calls = []
    monkeypatch.setattr(combat, "apply_hit",
                        lambda ship, dmg, *a, **k: calls.append((ship, dmg, k)))
    return calls


def _respond(a, b, dt=FRAME):
    from engine.appc.collisions import _resolve_body, _respond_pair
    return _respond_pair(_resolve_body(a), _resolve_body(b), None, dt)


# ── radius ──────────────────────────────────────────────────────────────────

def test_scuff_radius_is_the_overlap_chord():
    # sqrt(2 * R * pen): R=1, pen=0.5 -> 1.0
    assert collisions.scuff_radius_gu(1.0, 0.5) == pytest.approx(1.0)


def test_scuff_radius_is_clamped_to_the_band():
    assert collisions.scuff_radius_gu(1.0, 1e-6) == collisions.SCUFF_RADIUS_MIN_GU
    assert collisions.scuff_radius_gu(50.0, 50.0) == collisions.SCUFF_RADIUS_MAX_GU
    assert collisions.scuff_radius_gu(1.0, 0.0) == collisions.SCUFF_RADIUS_MIN_GU


# ── impact ──────────────────────────────────────────────────────────────────

def test_impact_hits_are_collision_typed_with_a_decal_radius_and_no_splash_radius(hits):
    a = _ship(0.0, vx=2.0)
    b = _ship(1.5)                       # overlapping: reach = 2 * scale
    assert _respond(a, b) is not None, "fixture did not collide"
    assert len(hits) == 2
    for _ship_, _dmg, kw in hits:
        assert kw["weapon_type"] == "collision"
        assert collisions.SCUFF_RADIUS_MIN_GU <= kw["decal_radius"] <= collisions.SCUFF_RADIUS_MAX_GU
        assert "splash_radius" not in kw, "the scuff size must not widen collision damage"


def test_dead_on_impact_passes_no_tangent(hits):
    a = _ship(0.0, vx=2.0)
    b = _ship(1.5)
    _respond(a, b)
    assert all(kw["hit_tangent"] is None for _s, _d, kw in hits)


def test_oblique_impact_passes_the_tangential_relative_velocity_with_opposite_signs(hits):
    a = _ship(0.0, vx=2.0, vy=1.0)       # closing along +x, sliding along +y
    b = _ship(1.5)
    _respond(a, b)
    ta = next(kw["hit_tangent"] for s, _d, kw in hits if s is a)
    tb = next(kw["hit_tangent"] for s, _d, kw in hits if s is b)
    # b relative to a moves along -y (a slides +y past b) -> a's scratch runs -y.
    assert ta.x == pytest.approx(0.0, abs=1e-9)
    assert ta.y == pytest.approx(-1.0)
    assert tb.y == pytest.approx(+1.0)


# ── grind ───────────────────────────────────────────────────────────────────

def test_grind_hits_are_collision_typed_with_the_slip_as_tangent(hits):
    a = _ship(0.0, vy=1.0)               # resting overlap, sliding sideways
    b = _ship(1.5)
    for _ in range(3):
        _respond(a, b)
    grinds = [(s, kw) for s, _d, kw in hits]
    assert grinds, "fixture did not grind"
    for s, kw in grinds:
        assert kw["weapon_type"] == "collision"
        assert collisions.SCUFF_RADIUS_MIN_GU <= kw["decal_radius"] <= collisions.SCUFF_RADIUS_MAX_GU
        t = kw["hit_tangent"]
        assert t is not None and abs(t.x) < 1e-9
        assert abs(abs(t.y) - 1.0) < 1e-6
    ya = {round(kw["hit_tangent"].y) for s, kw in grinds if s is a}
    yb = {round(kw["hit_tangent"].y) for s, kw in grinds if s is b}
    assert ya == {-1} and yb == {1}, "each hull's scratch runs the way the OTHER hull moved across it"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_collision_scuff.py -q`
Expected: FAIL — `scuff_radius_gu` missing; `KeyError: 'weapon_type'`.

- [ ] **Step 3: Implement**

Constants beside the other `COLLISION_*` constants in `collisions.py`:

```python
# Scuff decal size band (GU). The decal radius is the contact chord
# sqrt(2 * R_small * pen) clamped to this band; it is VISUAL ONLY and never
# feeds apply_hit's splash radius (which sets the subsystem catchment).
# Spec: docs/superpowers/specs/2026-09-20-collision-scuff-normal-decals-design.md §3
SCUFF_RADIUS_MIN_GU = 0.5
SCUFF_RADIUS_MAX_GU = 4.0


def scuff_radius_gu(r_small: float, pen: float) -> float:
    """Chord of two overlapping spheres, from the smaller radius and the
    overlap depth, clamped to [SCUFF_RADIUS_MIN_GU, SCUFF_RADIUS_MAX_GU]."""
    chord = math.sqrt(max(0.0, 2.0 * r_small * pen))
    return min(SCUFF_RADIUS_MAX_GU, max(SCUFF_RADIUS_MIN_GU, chord))
```

`_respond_pair`: after both branches of the narrow/broad phase have set `dist`, `sum_r`, `nx..nz`, `cx..cz`, compute once:

```python
    # Scuff decal size from the contact geometry (visual only; see scuff_radius_gu).
    if narrowed:
        r_small = min(ra, rb)
    else:
        r_small = min(a.radius, b.radius) * COLLISION_RADIUS_SCALE
    scuff_r = scuff_radius_gu(r_small, sum_r - dist)
```

Pass it to the grind: `_grind_contact(a, b, cx, cy, cz, nx, ny, nz, inv_sum, dt, ship_instances, scuff_r)`.

Impact tangent, after `v_rel` is known:

```python
    # Slip direction for the scuff: relative velocity with its normal part
    # removed. Dead-on (no slip) -> None; the ring derives a perpendicular.
    tvx, tvy, tvz = rvx - v_rel * nx, rvy - v_rel * ny, rvz - v_rel * nz
    tlen = math.sqrt(tvx * tvx + tvy * tvy + tvz * tvz)
    if tlen > 1e-6:
        tan_a = TGPoint3(tvx / tlen, tvy / tlen, tvz / tlen)    # how b moves across a
        tan_b = TGPoint3(-tvx / tlen, -tvy / tlen, -tvz / tlen) # how a moves across b
    else:
        tan_a = tan_b = None
```

Both impact `apply_hit` calls: replace `weapon_type=None` with `weapon_type="collision", hit_tangent=tan_a, decal_radius=scuff_r` (and `tan_b` for b).

`_grind_contact(..., ship_instances=None, scuff_radius=0.0)`: after `slip` is computed, build the tangents from `(tx, ty, tz)`:

```python
    tlen = math.sqrt(tx * tx + ty * ty + tz * tz)
    if tlen > 1e-6:
        tan_a = TGPoint3(tx / tlen, ty / tlen, tz / tlen)
        tan_b = TGPoint3(-tx / tlen, -ty / tlen, -tz / tlen)
    else:
        tan_a = tan_b = None
```

and change both grind `apply_hit` calls to `weapon_type="collision", hit_tangent=tan_a / tan_b, decal_radius=scuff_radius`. Update the docstring line "Emits no event and applies no impulse" to add "Routes as weapon_type "collision" with the slip direction as the scuff tangent."

- [ ] **Step 4: Run the new + existing collision suites**

Run: `uv run pytest tests/unit/test_collision_scuff.py tests/unit/test_collisions.py tests/unit/test_collision_sustained_contact.py tests/unit/test_collision_hull_carve.py tests/unit/test_collision_event.py tests/unit/test_dev_key_collisions.py -q`
Expected: all PASS. `test_collision_hull_carve.py` in particular must be unchanged — it pins that the carve still reaches `hull_carve_add` with the weapon-default `r_hit`.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/collisions.py tests/unit/test_collision_scuff.py
git commit -m "feat(collisions): scuff decals — collision weapon type, contact-chord radius, slip tangent

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Audio/smoke parity, `queue_body_scuff`, and Damage Preview seeding

**Files:**
- Modify: `engine/appc/visible_damage.py`
- Modify: `engine/dev_missions/damage_preview.py`
- Test: `tests/unit/test_collision_scuff.py` (parity), `tests/unit/test_visible_damage.py`

**Interfaces:**
- Consumes: Task 5's `host_io.damage_decal_add(..., world_tangent=)`, `damage_decals.WEAPON_CLASS_SCUFF`.
- Produces: `visible_damage.queue_body_scuff(ship, x, y, z, radius_gu, tangent_body=(1.0, 0.0, 0.0), intensity=1.0)`.
- Spec: §1 (parity), §5 (live-tuning vehicle).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_collision_scuff.py`:

```python
# ── "collision" must behave exactly like None for audio and smoke (spec §1) ──

def test_hull_smoke_ignores_collision_exactly_like_none(monkeypatch):
    from engine.appc import hull_hit_smoke
    from engine import host_io
    emitted = []
    monkeypatch.setattr(hull_hit_smoke, "_emit_smoke",
                        lambda *a, **k: emitted.append(a))
    # If the weapon gate were to let "collision" through, the next gate is
    # world_to_body; make it succeed so a leak would reach _emit_smoke.
    monkeypatch.setattr(host_io, "world_to_body",
                        lambda *a, **k: ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
    ship = _ship(0.0)
    pt, n = TGPoint3(0, 0, 0), TGPoint3(0, 0, 1)
    hull_hit_smoke.maybe_emit(ship, pt, n, None, ship_instances={ship: 1})
    hull_hit_smoke.maybe_emit(ship, pt, n, "collision", ship_instances={ship: 1})
    assert emitted == []
    # Control — the gate is real: a torpedo with a forced roll DOES emit.
    import App
    monkeypatch.setattr(App.g_kSystemWrapper, "GetRandomNumber", lambda n: 0,
                        raising=False)
    hull_hit_smoke.maybe_emit(ship, pt, n, "torpedo", ship_instances={ship: 1})
    assert emitted, "control: torpedo smoke should have fired"


def test_hull_audio_picks_the_same_pool_for_collision_and_none(monkeypatch):
    from engine.appc import hit_feedback
    import App
    lookups = []

    class _Snd:
        def Play(self, position=None): return None

    class _Mgr:
        def GetSound(self, name):
            lookups.append(name); return _Snd()

    monkeypatch.setattr(App, "g_kSoundManager", _Mgr(), raising=False)
    import LoadTacticalSounds, LoadDamageHitSounds
    monkeypatch.setattr(LoadTacticalSounds, "GetRandomSound", lambda pool: pool[0])
    monkeypatch.setattr(LoadDamageHitSounds, "GetRandomSound", lambda pool: pool[0])
    hit_feedback.reset_audio_throttle()
    hit_feedback._play_audio(hit_feedback.Severity.HULL, TGPoint3(0, 0, 0), None)
    hit_feedback.reset_audio_throttle()
    hit_feedback._play_audio(hit_feedback.Severity.HULL, TGPoint3(0, 0, 0), "collision")
    assert len(lookups) == 2 and lookups[0] == lookups[1]
```

The smoke control case also depends on `particles.EffectController_GetEffectLevel() >= MEDIUM` (`hull_hit_smoke.py:71`); if the default level in tests is lower, monkeypatch `hull_hit_smoke.particles.EffectController_GetEffectLevel` to return `particles.EffectController.MEDIUM` in the test. If the control still does not fire, the test is not proving anything — fix the rig before moving on, do not delete the control.

Append to `tests/unit/test_visible_damage.py`:

```python
# ── Scuff seeding (developer Damage Preview) ────────────────────────────────

class _DecalSpy:
    def __init__(self):
        self.decals = []

    def __call__(self, iid, point, normal, radius, intensity, weapon_class, time,
                 world_tangent=None):
        self.decals.append((iid, point, normal, radius, intensity, weapon_class,
                            time, world_tangent))


@pytest.fixture
def decal_host(monkeypatch):
    spy = _DecalSpy()
    monkeypatch.setattr(host_io, "damage_decal_add", spy)
    return spy


def test_body_scuff_emits_a_scuff_decal_in_world_space(decal_host, host):
    from engine.appc.damage_decals import WEAPON_CLASS_SCUFF
    rot = TGMatrix3().MakeZRotation(3.14159265358979 / 2.0)   # body +X -> world +Y
    ship = _Ship(loc=TGPoint3(10.0, -5.0, 2.0), rot=rot)
    visible_damage.queue_body_scuff(ship, 1.0, 0.0, 0.0, radius_gu=1.5,
                                    tangent_body=(0.0, 1.0, 0.0), intensity=0.7)
    visible_damage.advance(0.0, {ship: 1})

    assert host.carves == [], "a scuff must not carve"
    (iid, point, normal, radius, intensity, cls, _t, tangent), = decal_host.decals
    assert iid == 1
    assert point == pytest.approx((10.0, -4.0, 2.0))
    assert normal == pytest.approx((0.0, 1.0, 0.0))     # outward radial (no mesh)
    assert tangent == pytest.approx((-1.0, 0.0, 0.0))   # body +Y -> world -X
    assert radius == pytest.approx(1.5)
    assert intensity == pytest.approx(0.7)
    assert cls == WEAPON_CLASS_SCUFF


def test_body_scuff_defers_until_the_instance_is_realized(decal_host):
    ship = _Ship()
    visible_damage.queue_body_scuff(ship, 1.0, 0.0, 0.0, radius_gu=1.0)
    visible_damage.advance(0.0, {})
    assert decal_host.decals == []
    visible_damage.advance(0.0, {ship: 7})
    assert len(decal_host.decals) == 1
    visible_damage.advance(0.0, {ship: 7})
    assert len(decal_host.decals) == 1, "emitted once, then dropped"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_collision_scuff.py tests/unit/test_visible_damage.py -q`
Expected: the two parity tests PASS already (they pin existing behaviour — confirm they do, and that `emitted`/`lookups` are exercised, not vacuous); the two `queue_body_scuff` tests FAIL with `AttributeError`.

- [ ] **Step 3: Implement `queue_body_scuff`**

In `visible_damage.py`, after `queue_world_capsule`:

```python
def queue_body_scuff(ship, x, y, z, radius_gu, tangent_body=(1.0, 0.0, 0.0),
                     intensity=1.0) -> None:
    """Queue a collision-scuff DECAL (no carve) at a body-frame point. Used by
    the developer Damage Preview mission to seed known scuffs for live tuning.
    `tangent_body` is the slip direction in the body frame; realised through
    host_io.damage_decal_add once the ship's render instance exists."""
    if ship is None:
        return
    _pending.append({
        "ship": ship, "kind": "scuff",
        "pt": (float(x), float(y), float(z)),
        "radius": float(radius_gu), "intensity": float(intensity),
        "tangent": tuple(float(c) for c in tangent_body), "age": 0.0,
    })
```

In `_advance_one`, after the capsule branch and before `_resolve`:

```python
    if entry.get("kind") == "scuff":
        world_pt, normal = _resolve(dict(entry, kind="body"), ship, iid)
        if world_pt is None:
            return False
        mesh = _mesh_normal(iid, world_pt, normal)
        if mesh is not None:
            normal = mesh
        tx, ty, tz = entry["tangent"]
        tangent = TGPoint3(tx, ty, tz)
        if hasattr(ship, "GetWorldRotation"):
            rot = ship.GetWorldRotation()
            if isinstance(rot, TGMatrix3):
                tangent.MultMatrixLeft(rot)
        from engine.appc import damage_decals
        host_io.damage_decal_add(
            iid,
            (world_pt.x, world_pt.y, world_pt.z),
            (normal.x, normal.y, normal.z),
            entry["radius"], entry["intensity"],
            damage_decals.WEAPON_CLASS_SCUFF,
            damage_decals.current_game_time(),
            world_tangent=(tangent.x, tangent.y, tangent.z),
        )
        return False
```

Update the module's registry comment (`"kind": "body"|"world"|"capsule"|"scuff"`).

- [ ] **Step 4: Seed the Damage Preview mission**

In `engine/dev_missions/damage_preview.py`, after `DamageAkira.AddDamage(pWreck)`:

```python
    # Three collision scuffs for live tuning of the scuff decal (spec
    # 2026-09-20-collision-scuff-normal-decals-design.md §5): small, medium
    # and large radii, three slip directions, the large one straddling the
    # saucer/hull curve. Body-frame offsets in GU (Akira: saucer ~±1 GU wide).
    from engine.appc import visible_damage
    visible_damage.queue_body_scuff(pWreck, 0.6, 0.4, 0.15, radius_gu=0.6,
                                    tangent_body=(1.0, 0.0, 0.0))
    visible_damage.queue_body_scuff(pWreck, -0.5, 0.2, 0.15, radius_gu=1.5,
                                    tangent_body=(0.0, 1.0, 0.0))
    visible_damage.queue_body_scuff(pWreck, 0.0, -0.6, 0.05, radius_gu=3.5,
                                    tangent_body=(0.7, 0.7, 0.0))
```

Before committing the offsets, check the Akira's extent with `native/tools/dump_bounds` (or `Hull.SetRadius` in `sdk/.../Hardpoints/akira.py` via `paths.sdk_scripts()`) so the three points land ON the hull rather than in space; adjust and note the measured extent in the comment.

- [ ] **Step 5: Run the suites**

Run: `uv run pytest tests/unit/test_collision_scuff.py tests/unit/test_visible_damage.py tests/unit/test_dev_mission_picker.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/visible_damage.py engine/dev_missions/damage_preview.py tests/unit/test_collision_scuff.py tests/unit/test_visible_damage.py
git commit -m "feat(dev): seed three collision scuffs in Damage Preview via visible_damage.queue_body_scuff

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Gate, docs, and hand-off for the live pass

**Files:**
- Modify: `docs/superpowers/specs/2026-09-20-collision-scuff-normal-decals-design.md` (Status line)
- Modify: `CLAUDE.md` (key reference table — one row)
- Modify: `docs/engine/damagetool-and-hull-damage-gaps.md` (one paragraph pointing at the spec, under the collision/hull-damage gaps)

- [ ] **Step 1: Run the full gate**

Run: `scripts/check_tests.sh 2>&1 | tail -20`
Expected: exits 0; any failure it names that is not in `tests/known_failures.txt` is a regression from this branch — fix it before continuing (never call it pre-existing by eye).

- [ ] **Step 2: Docs**

Spec status line → `**Status:** implemented 2026-09-20 (gate green); awaiting live verification (Damage Preview + QuickBattle ram/grind)`.

CLAUDE.md key-reference table, one row after "Shield face + impact splash":

```
| Collision scuff decals | `engine/appc/collisions.py:scuff_radius_gu`, `native/src/renderer/shaders/opaque.frag:apply_scuffs`, `docs/superpowers/specs/2026-09-20-collision-scuff-normal-decals-design.md` | Collisions route `weapon_type="collision"` → `WeaponClass::Scuff` (2): procedural relief + bare-metal scratches in a **pre-lighting** pass on `n_shade`/`base`, band-limited by `fwidth(p_body)` taken **outside** the loop. ⚠️ The scuff size travels as `decal_radius` — never `splash_radius`, which sets the subsystem-damage catchment. ⚠️ The post-lighting scorch loop must `continue` on class 2 or the ember comes back. `kScuff*` consts are model units; rebuild to tune. Live tuning: `--developer` → Damage Preview (three seeded scuffs). |
```

`docs/engine/damagetool-and-hull-damage-gaps.md`: add a short paragraph in the gaps section: collisions below the carve iso now leave a Scuff decal (spec link); the carve behaviour is unchanged.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-09-20-collision-scuff-normal-decals-design.md CLAUDE.md docs/engine/damagetool-and-hull-damage-gaps.md
git commit -m "docs: collision scuff decals — spec status, CLAUDE.md row, hull-damage gaps note

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: Hand off for the live pass (do NOT launch the game yourself)**

Report to Mark, verbatim what to look at (spec §5): (a) `--developer` → mission picker → Developer → Damage Preview: three scuffs on the Akira — relief + scratch lines readable up close, no sparkle backing off, nothing on the far side of the hull; (b) QuickBattle: ram an NPC dead-on (scuff, plus a carve if fast), then grind along its hull — a streak whose waves cross the slip direction and whose scratches run along it, on **both** hulls. The knobs are `kScuff*` in `opaque.frag` (rebuild) and `SCUFF_RADIUS_{MIN,MAX}_GU` in `collisions.py` (no rebuild). The branch stays unmerged until that pass.

---

## Self-review (done at plan-writing time)

- **Spec coverage:** §1 routing → Tasks 5–6 (+ parity test in 7); §2 ring policy → Task 1; §3 data/uniform/kwarg chain + decal-only radius → Tasks 1, 2, 5, 6; §4 shader (pre-lighting pass, post-loop skip, band-limit, albedo, contract) → Tasks 2–4; §5 live-tuning vehicle → Task 7; §6 tests → each task; out-of-scope items untouched; docs → Task 8.
- **Placeholders:** none — every code step carries its code; the one "measure before committing" note (Akira offsets, Task 7 Step 4) names the instrument.
- **Type consistency:** `add(..., now, tangent_body = vec3(0))` (Task 1) is what Task 2's binding and test rig call; `damage_decal_add(..., world_tangent=(0,0,0))` binding (Task 2) ↔ `host_io.damage_decal_add(..., world_tangent=None)` (Task 5) ↔ spies (Tasks 5, 7); `dispatch(tangent=, decal_radius=)` (Task 5) ↔ `apply_hit(hit_tangent=, decal_radius=)` (Task 5) ↔ collisions (Task 6); `scuff_radius_gu(r_small, pen)` (Task 6) ↔ its tests; `queue_body_scuff(ship, x, y, z, radius_gu, tangent_body, intensity)` (Task 7) ↔ its tests and the mission.
