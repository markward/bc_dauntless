// native/tests/renderer/frame_test.cc
#include <gtest/gtest.h>

#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>

#include <scenegraph/world.h>
#include <scenegraph/camera.h>
#include <scenegraph/damage_decals.h>

#include <assets/cache.h>
#include <assets/model.h>

#include <cstring>

#include <filesystem>

// dauntless_decals toggle is declared in frame.cc; forward-declare both here.
namespace dauntless_decals { bool enabled(); void set_enabled(bool); }

TEST(DauntlessDecalsToggle, DefaultsOnAndRoundTrips) {
    EXPECT_TRUE(dauntless_decals::enabled());     // default on
    dauntless_decals::set_enabled(false);
    EXPECT_FALSE(dauntless_decals::enabled());
    dauntless_decals::set_enabled(true);          // restore for other tests
    EXPECT_TRUE(dauntless_decals::enabled());
}

namespace {

const std::filesystem::path kProjectRoot =
    std::filesystem::path(__FILE__).parent_path().parent_path().parent_path().parent_path();
const std::filesystem::path kGalaxyNif =
    kProjectRoot / "game" / "data" / "Models" / "Ships" / "Galaxy" / "Galaxy.nif";
const std::filesystem::path kGalaxyTex =
    kProjectRoot / "game" / "data" / "Models" / "SharedTextures" / "FedShips" / "High";
class FrameTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::unique_ptr<assets::AssetCache> cache;

    void SetUp() override {
        if (!std::filesystem::is_regular_file(kGalaxyNif)) {
            GTEST_SKIP() << "BC asset not available at " << kGalaxyNif;
        }
        if (!std::filesystem::is_directory(kGalaxyTex)) {
            GTEST_SKIP() << "BC texture dir not available at " << kGalaxyTex;
        }
        try {
            w = std::make_unique<renderer::Window>(256, 256, "frame-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        cache = std::make_unique<assets::AssetCache>();
    }
};

TEST_F(FrameTest, OpaquePassRunsWithoutGLError) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);

    scenegraph::World world;
    auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    // Galaxy.nif is in BC units (~660 x 644 x 140). Place it at origin and
    // pull the camera back far enough that the saucer fits inside the 60-deg
    // vertical FOV and its body sits over the center pixel.
    glm::mat4 m(1.0f);
    world.set_world_transform(iid, m);

    scenegraph::Camera cam;
    cam.eye = glm::vec3(0.0f, 0.0f, 1500.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.aspect = 1.0f;

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    renderer::FrameSubmitter submitter;
    renderer::Lighting lighting;  // default-constructed: matches the
                                  // pre-Phase-1 hardcoded values that the
                                  // existing pixel-litness assertion below
                                  // was tuned against.
    submitter.submit_opaque(world, cam, *p,
        [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        }, lighting);

    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    // Read center pixel; should be lit (non-black) — the Galaxy's saucer
    // covers the center of the viewport from this camera.
    unsigned char pixel[4] = {0};
    glReadPixels(128, 128, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
    int total = pixel[0] + pixel[1] + pixel[2];
    EXPECT_GT(total, 0) << "center pixel was black; opaque pass produced nothing";
}

TEST_F(FrameTest, OpaquePassWithRimEnabledRunsWithoutGLError) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);

    scenegraph::World world;
    auto iid = world.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    world.set_rim_eligible(iid, true);
    glm::mat4 m(1.0f);
    world.set_world_transform(iid, m);

    scenegraph::Camera cam;
    cam.eye = glm::vec3(0.0f, 0.0f, 1500.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.aspect = 1.0f;

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    renderer::FrameSubmitter submitter;
    renderer::Lighting lighting;
    submitter.submit_opaque_in_pass(world, cam, *p,
        [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        }, lighting, scenegraph::Pass::Space);

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(FrameTest, GlowContributesWithZeroAmbient) {
    // Galaxy.nif's NiImages reference "Ent-D_*_glow.tga" files directly
    // (BC's AddLOD "_glow" suffix convention). model_build.cc detects the
    // suffix and routes those textures into Material::StageSlot::Glow.
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);

    scenegraph::World world;
    auto iid = world.create_instance(
        reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));

    scenegraph::Camera cam;
    cam.eye    = glm::vec3(0.0f, 0.0f, 1500.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.aspect = 1.0f;

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    renderer::FrameSubmitter submitter;
    renderer::Lighting zero_lighting;
    zero_lighting.ambient           = glm::vec3(0.0f);
    zero_lighting.directional_count = 0;
    submitter.submit_opaque(world, cam, *p,
        [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        }, zero_lighting);

    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    // Scan a 5×5 grid across the saucer section; at least one pixel must be
    // non-zero to prove the glow pass contributed.  Clear colour is black so
    // background pixels are also 0 — only glow raises a pixel above 0.
    int max_total = 0;
    for (int dx = -40; dx <= 40; dx += 20) {
        for (int dy = -40; dy <= 40; dy += 20) {
            unsigned char px[4] = {0};
            glReadPixels(128 + dx, 128 + dy, 1, 1,
                         GL_RGBA, GL_UNSIGNED_BYTE, px);
            int t = px[0] + px[1] + px[2];
            if (t > max_total) max_total = t;
        }
    }
    EXPECT_GT(max_total, 0)
        << "Expected glow to contribute to at least one pixel with zero "
           "ambient lighting; all sampled pixels were black.";
}

TEST_F(FrameTest, SpecularShipRendersWithDirectionalLight) {
    // Render a ship known to ship with _specular textures (Keldon).
    // Asserts:
    //   1) The opaque pass completes without GL errors after binding
    //      the spec uniforms.
    //   2) A directional light + non-zero specular term produce at
    //      least one non-black pixel near screen center.
    // Smoke test only — does not isolate the specular contribution
    // numerically; the binding test in material_build_test.cc and the
    // mapping test in lighting_test.cc cover those layers.
    const std::filesystem::path keldon_nif =
        kProjectRoot / "game" / "data" / "Models" / "Ships" / "Keldon" / "Keldon.nif";
    const std::filesystem::path keldon_tex =
        kProjectRoot / "game" / "data" / "Models" / "SharedTextures" / "CardShips" / "High";
    if (!std::filesystem::is_regular_file(keldon_nif)) {
        GTEST_SKIP() << "BC asset not available at " << keldon_nif;
    }
    if (!std::filesystem::is_directory(keldon_tex)) {
        GTEST_SKIP() << "BC texture dir not available at " << keldon_tex;
    }

    auto model_h = cache->load(keldon_nif, keldon_tex);

    scenegraph::World world;
    auto iid = world.create_instance(
        reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));

    scenegraph::Camera cam;
    cam.eye    = glm::vec3(0.0f, 0.0f, 800.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.aspect = 1.0f;

    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    renderer::FrameSubmitter submitter;
    renderer::Lighting lighting;
    lighting.ambient            = glm::vec3(0.1f, 0.1f, 0.1f);
    lighting.directional_count  = 1;
    lighting.directional_dir_ws[0] = glm::vec3(0.0f, 0.0f, 1.0f);
    lighting.directional_color[0]  = glm::vec3(1.0f, 1.0f, 1.0f);
    submitter.submit_opaque(world, cam, *p,
        [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        }, lighting);

    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    int max_total = 0;
    for (int dx = -40; dx <= 40; dx += 20) {
        for (int dy = -40; dy <= 40; dy += 20) {
            unsigned char px[4] = {0};
            glReadPixels(128 + dx, 128 + dy, 1, 1,
                         GL_RGBA, GL_UNSIGNED_BYTE, px);
            int t = px[0] + px[1] + px[2];
            if (t > max_total) max_total = t;
        }
    }
    EXPECT_GT(max_total, 0)
        << "Expected the Keldon to render at all (non-zero pixels under a "
           "directional light) — this is a pipeline smoke test, not a proof "
           "that the specular term contributes. See test docstring.";
}

TEST_F(FrameTest, DecalUploadPipelineRunsWithoutGLError) {
    // Renamed from DecalUploadDoesNotAlterRenderBeforeShaderReads (Task 2).
    // Task 3 makes the shader read decals, so a center-hit decal WILL darken
    // the center pixel. This test now just verifies the pack path is wired and
    // crash-free, and that the decal actually produces a visible effect at center.
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    scenegraph::World world;
    auto iid = world.create_instance(
        reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));

    scenegraph::Camera cam;
    cam.eye = glm::vec3(0.0f, 0.0f, 1500.0f);
    cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
    cam.aspect = 1.0f;

    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h);
    };
    renderer::FrameSubmitter submitter;
    renderer::Lighting lighting;

    // Baseline: render with an empty ring.
    glViewport(0, 0, 256, 256);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    submitter.submit_opaque_in_pass(world, cam, *p, lut, lighting,
                                    scenegraph::Pass::Space, /*decal_time=*/0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    unsigned char px_ref[4] = {0};
    glReadPixels(128, 128, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px_ref);
    EXPECT_GT(px_ref[0] + px_ref[1] + px_ref[2], 0) << "baseline center pixel black";

    // Seed a scorch decal at center. The shader now reads it — just verify no
    // GL errors and the draw completes without crashing.
    world.get(iid)->decals.add(glm::vec3(0, 0, 0), glm::vec3(0, 0, -1),
                               /*radius=*/200.0f, /*intensity=*/1.0f,
                               scenegraph::WeaponClass::Scorch, /*now=*/0.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    submitter.submit_opaque_in_pass(world, cam, *p, lut, lighting,
                                    scenegraph::Pass::Space, /*decal_time=*/0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
}



// Mean of channel-sum over a w×h block whose lower-left is (x0,y0).
double block_mean(int x0, int y0, int w, int h) {
    std::vector<unsigned char> buf(static_cast<size_t>(w) * h * 4);
    glReadPixels(x0, y0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, buf.data());
    double acc = 0.0;
    for (int i = 0; i < w * h; ++i)
        acc += buf[i*4] + buf[i*4+1] + buf[i*4+2];
    return acc / (w * h);
}

template <class Lut>
void render_galaxy(scenegraph::World& world, renderer::Pipeline& pipeline,
                   Lut&& lut, float decal_time) {
    scenegraph::Camera cam;
    cam.eye = glm::vec3(0, 0, 1500); cam.target = glm::vec3(0);
    cam.aspect = 1.0f;
    renderer::FrameSubmitter submitter;
    renderer::Lighting lighting;
    glViewport(0, 0, 256, 256);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    submitter.submit_opaque_in_pass(world, cam, pipeline, lut, lighting,
                                    scenegraph::Pass::Space, decal_time);
}

TEST_F(FrameTest, ScorchDecalDarkensHullAndDoesNotMirror) {
    // Galaxy.nif at this camera (z=1500, 256×256, fov=60°) renders with
    // the saucer occupying approx x=[93,162], y=[81,176] in screen space.
    //
    // Sample blocks are chosen to sit firmly within each half of the saucer:
    //   Left  block: screen x=[93,118], y=[100,150]  — body X ≈ -237 to -67 GU
    //   Right block: screen x=[130,155], y=[100,150] — body X ≈  +14 to +182 GU
    //
    // Decal seed at body (60, 0, 20), radius 120 GU:
    //   - Screen center x≈137, spans ~18 screen pixels on each side.
    //   - Covers most of the right block (body X -60..+180).
    //   - Left block edge (body X≈-67) is 127 GU from seed, just outside radius.
    //   - NIF normals are inward; shader uses dot(-n_body, dn) for the falloff.
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    // ── Baseline: undamaged ──
    scenegraph::World w0;
    auto i0 = w0.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w0.set_world_transform(i0, glm::mat4(1.0f));
    render_galaxy(w0, *p, lut, 0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double L0 = block_mean(93, 100, 25, 50);    // left half of saucer
    const double R0 = block_mean(130, 100, 25, 50);   // right half of saucer

    // Both blocks must have hull pixels; if they're zero the camera/model
    // setup is wrong and the rest of the test is meaningless.
    ASSERT_GT(L0, 0.0) << "left sample block has no hull pixels (baseline)";
    ASSERT_GT(R0, 0.0) << "right sample block has no hull pixels (baseline)";

    // ── Damaged: scorch on the +X (right) half of the saucer top ──
    scenegraph::World w1;
    auto i1 = w1.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w1.set_world_transform(i1, glm::mat4(1.0f));
    // point_body = (60, 0, 20): +X half, top face, near-surface Z.
    // normal_body = (0, 0, -1): the decal normal must match the convention of
    // the reconstructed fragment normal n_body (the raw NIF vertex normal here,
    // which points inward). The shader compares dot(n_body, dn) > 0, exactly as
    // the live ray_trace -> world_dir_to_body pipeline produces a dn aligned
    // with the surface's vertex normal. (Seeding an outward +Z here would be
    // rejected by the falloff -- the bug that hid all in-game decals.)
    // radius 120 GU — covers most of the right sample block.
    w1.get(i1)->decals.add(glm::vec3(60.0f, 0.0f, 20.0f), glm::vec3(0, 0, -1),
                           /*radius=*/120.0f, /*intensity=*/1.0f,
                           scenegraph::WeaponClass::Scorch, 0.0f);
    render_galaxy(w1, *p, lut, 0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double L1 = block_mean(93, 100, 25, 50);
    const double R1 = block_mean(130, 100, 25, 50);

    // Right half darkened by the scorch deposit.
    EXPECT_LT(R1, R0 * 0.95) << "scorch did not darken the struck (right) half";
    // THE REGRESSION test: the mirror (left) half is essentially unchanged.
    // The left block's nearest edge (body X≈-67) is 127 GU from the decal
    // center (X=60, radius=120), placing it just outside the decal radius.
    EXPECT_NEAR(L1, L0, L0 * 0.05) << "damage leaked onto the mirror (left) half";
}

TEST_F(FrameTest, ScorchToggleOffRendersLikeUndamaged) {
    // Same geometry as ScorchDecalDarkensHullAndDoesNotMirror.
    // Verifies that dauntless_decals::set_enabled(false) suppresses the
    // decal effect, and re-enabling it re-applies it.
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    scenegraph::World w;
    auto iid = w.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w.set_world_transform(iid, glm::mat4(1.0f));
    w.get(iid)->decals.add(glm::vec3(60.0f, 0.0f, 20.0f), glm::vec3(0, 0, -1),
                           120.0f, 1.0f, scenegraph::WeaponClass::Scorch, 0.0f);

    dauntless_decals::set_enabled(false);
    render_galaxy(w, *p, lut, 0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double R_off = block_mean(130, 100, 25, 50);
    dauntless_decals::set_enabled(true);
    render_galaxy(w, *p, lut, 0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double R_on = block_mean(130, 100, 25, 50);
    dauntless_decals::set_enabled(true);  // leave enabled

    EXPECT_GT(R_off, 0.0) << "right block should have hull pixels when decals off";
    EXPECT_LT(R_on, R_off * 0.97) << "decals-on should differ from decals-off";
}

TEST_F(FrameTest, ScorchEmberIsBrightWhenFreshAndCoolsWithGameTime) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    scenegraph::World w;
    auto iid = w.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w.set_world_transform(iid, glm::mat4(1.0f));
    // birth_time = 0; ember keyed on (u_decal_time - birth_time).
    w.get(iid)->decals.add(glm::vec3(60, 0, 20), glm::vec3(0, 0, -1),
                           120.0f, 1.0f, scenegraph::WeaponClass::Scorch, 0.0f);

    render_galaxy(w, *p, lut, /*decal_time=*/0.2f);   // fresh: hot ember
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double fresh = block_mean(130, 100, 25, 50);

    render_galaxy(w, *p, lut, /*decal_time=*/30.0f);  // long after T_EMBER: cold
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double cold = block_mean(130, 100, 25, 50);

    // The fresh ember adds emissive brightness; once cold only the soot deposit
    // remains, which is darker than the glowing-fresh state.
    EXPECT_GT(fresh, cold) << "ember did not brighten the fresh scorch, or did not cool";
}

TEST_F(FrameTest, PhaserHeatGlowIsTransientAndLeavesNoScar) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    // Undamaged baseline for the struck region.
    scenegraph::World w0;
    auto i0 = w0.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w0.set_world_transform(i0, glm::mat4(1.0f));
    render_galaxy(w0, *p, lut, 0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double base = block_mean(130, 100, 25, 50);

    scenegraph::World w;
    auto iid = w.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w.set_world_transform(iid, glm::mat4(1.0f));
    w.get(iid)->decals.add(glm::vec3(60, 0, 20), glm::vec3(0, 0, -1),
                           120.0f, 1.0f, scenegraph::WeaponClass::HeatGlow, 0.0f);

    render_galaxy(w, *p, lut, /*decal_time=*/0.1f);   // fresh glow
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double fresh = block_mean(130, 100, 25, 50);
    render_galaxy(w, *p, lut, /*decal_time=*/4.0f);   // past T_GLOW (3.0s)
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double faded = block_mean(130, 100, 25, 50);

    EXPECT_GT(fresh, base * 1.02) << "fresh phaser glow should brighten the hull";
    EXPECT_NEAR(faded, base, base * 0.03) << "phaser glow should leave no scar after T_GLOW";
}

// ─────────────────────────────────────────────────────────────────────────────
// Flicker tests (Task B2): verifies the glow-map electrical stutter added by
// Task B1 behaves correctly.
//
// Strategy: render under *zero ambient + zero directional* lighting so the
// opaque pass output reduces to:
//
//     out = glow.rgb * glow.a * gf  +  decal_emissive
//
// At exact birth (age = 0.0):
//   - SCORCH ember:   skipped   (shader guard is `age > 0.0`)
//   - SCORCH flicker: FIRES     (guard is `age >= 0.0`)
//   - HeatGlow bloom: present   (but weapon_class==0 branch `continue`s before flicker)
//
// At decal_time = 30.0 (far past FLICKER_DURATION=0.5 and T_EMBER=10s):
//   - ember: exp(-30/~3.1) ≈ 0 → decal_emissive ≈ 0
//   - flicker: age >= 0.5 → gf stays 1.0
//   - soot: modifies base_lit, but base_lit = 0 under zero ambient
//   => output ≈ glow.rgb * glow.a * 1.0  ≡  undamaged baseline
//
// For HeatGlow at decal_time = 4.0 (past T_GLOW=3.0):
//   - bloom: life = clamp(1 - 4/3, 0, 1) = 0 → decal_emissive = 0
//   - flicker: never touched (weapon_class==0 `continue` fires first)
//   => output ≡ undamaged baseline
// ─────────────────────────────────────────────────────────────────────────────

// Helper: same camera/geometry as render_galaxy but with zero ambient light.
// Under zero ambient the rendered value is exactly glow.rgb*glow.a*gf +
// decal_emissive, which isolates the glow-flicker multiplier from diffuse lit.
template <class Lut>
void render_galaxy_zero_ambient(scenegraph::World& world,
                                renderer::Pipeline& pipeline,
                                Lut&& lut, float decal_time) {
    scenegraph::Camera cam;
    cam.eye = glm::vec3(0, 0, 1500); cam.target = glm::vec3(0);
    cam.aspect = 1.0f;
    renderer::FrameSubmitter submitter;
    renderer::Lighting zero_light;
    zero_light.ambient           = glm::vec3(0.0f);
    zero_light.directional_count = 0;
    glViewport(0, 0, 256, 256);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    submitter.submit_opaque_in_pass(world, cam, pipeline, lut, zero_light,
                                    scenegraph::Pass::Space, decal_time);
}

// Test 1: The glow-stutter flicker is present at the birth frame and has
// settled (output returns to baseline) long after FLICKER_DURATION (0.5 s).
TEST_F(FrameTest, FlickerGlowDiffersFromBaselineAtBirthAndMatchesAfterWindow) {
    // Uses zero-ambient lighting so the rendered block value is exactly
    //   glow.rgb * glow.a * gf + decal_emissive
    // At age = 0 (decal_time == birth_time): no ember (guard is age > 0), but
    // flicker fires (guard is age >= 0).  stutter(0) ≈ 0.396 → gf > 1.0 →
    // the struck block is BRIGHTER than the undamaged glow baseline.
    // At age = 30 s: flicker long dead, ember cooled, soot irrelevant under
    // zero ambient → output ≡ undamaged glow baseline.
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    // ── Undamaged glow baseline (zero ambient) ──
    scenegraph::World w0;
    auto i0 = w0.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w0.set_world_transform(i0, glm::mat4(1.0f));
    render_galaxy_zero_ambient(w0, *p, lut, 0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double glow_base = block_mean(130, 100, 25, 50);
    // The glow map must be non-zero here; if it's zero the flicker has nothing
    // to modulate and the test is vacuous.
    ASSERT_GT(glow_base, 0.0) << "right block has no glow contribution at zero ambient "
                                  "(cannot test flicker on a dark region)";

    // ── SCORCH at birth (birth_time = 0, decal_time = 0, age = 0) ──
    // gf != 1.0 because stutter(0) != 0 — the patch should differ from baseline.
    scenegraph::World w1;
    auto i1 = w1.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w1.set_world_transform(i1, glm::mat4(1.0f));
    w1.get(i1)->decals.add(glm::vec3(60.0f, 0.0f, 20.0f), glm::vec3(0, 0, -1),
                            /*radius=*/120.0f, /*intensity=*/1.0f,
                            scenegraph::WeaponClass::Scorch, /*birth_time=*/0.0f);
    render_galaxy_zero_ambient(w1, *p, lut, /*decal_time=*/0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double glow_at_birth = block_mean(130, 100, 25, 50);

    // At age = 0, stutter(0) = clamp(0.6*sin(0) + 0.4*sin(1.7), -1, 1) ≈ 0.396
    // → gf > 1.0 on the struck face → brighter than undamaged baseline.
    // The 2% threshold guards against floating-point noise on llvmpipe while
    // being tight enough to catch a missing flicker (gf==1.0 exactly).
    EXPECT_GT(glow_at_birth, glow_base * 1.02)
        << "SCORCH flicker at birth (age=0) did not raise the glow above baseline; "
           "glow_base=" << glow_base << " glow_at_birth=" << glow_at_birth;

    // ── SCORCH well past the flicker window: two renders at the same post-window
    // age must be pixel-identical (gf == 1.0 at both, ember expired) ──
    // Comparing to the undamaged baseline would be confounded by the soot
    // deposit (mix(vec3(0), SOOT_COLOR, deposit) adds non-zero color under zero
    // ambient even when `lit` starts at 0). Instead we compare two renders at
    // different times both well past FLICKER_DURATION (0.5 s) and T_EMBER (10 s):
    //   decal_time = 30 s: gf=1.0, ember≈0 → output = glow*1.0 + soot-as-emissive
    //   decal_time = 31 s: gf=1.0, ember≈0 → identical
    // If the flicker were still running at 30 s (a bug), gf would differ between
    // 30 s and 31 s (different stutter phase) and these renders would diverge.
    render_galaxy_zero_ambient(w1, *p, lut, /*decal_time=*/30.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double glow_settled_30 = block_mean(130, 100, 25, 50);

    render_galaxy_zero_ambient(w1, *p, lut, /*decal_time=*/31.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double glow_settled_31 = block_mean(130, 100, 25, 50);

    // NOTE: glow_settled values will differ from glow_base because the soot
    // deposit contributes via SOOT_COLOR under zero ambient. That is expected
    // and correct. What we assert is that the two settled renders are
    // indistinguishable — proving gf is stable at 1.0 past the window.
    EXPECT_NEAR(glow_settled_31, glow_settled_30, glow_settled_30 * 0.01)
        << "SCORCH renders at age=30s and age=31s diverged past FLICKER_DURATION; "
           "the flicker multiplier gf may still be active after the window. "
           "glow@30s=" << glow_settled_30 << " glow@31s=" << glow_settled_31;

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// Test 2: HeatGlow (phaser, weapon_class == 0) decal never touches glow_flicker.
// The shader's weapon_class==0 branch `continue`s before the flicker assignment.
// Under zero-ambient at decal_time past T_GLOW (3 s), HeatGlow bloom has faded
// and gf == 1.0, so the output must equal the undamaged glow baseline.
TEST_F(FrameTest, PhaserHeatGlowDoesNotFlickerGlowMap) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    // ── Undamaged glow baseline ──
    scenegraph::World w0;
    auto i0 = w0.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w0.set_world_transform(i0, glm::mat4(1.0f));
    render_galaxy_zero_ambient(w0, *p, lut, 0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double glow_base = block_mean(130, 100, 25, 50);
    ASSERT_GT(glow_base, 0.0) << "right block has no glow contribution at zero ambient";

    // ── HeatGlow decal at age = 4 s (past T_GLOW = 3 s) ──
    // bloom: life = clamp(1 - 4/3, 0, 1) = 0  → decal_emissive = 0
    // flicker: weapon_class==0 branch uses `continue` before glow_flicker is
    //          ever written → gf stays 1.0 for all ages
    // Under zero ambient: output = glow.rgb * glow.a * 1.0 ≡ undamaged baseline.
    scenegraph::World w;
    auto iid = w.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w.set_world_transform(iid, glm::mat4(1.0f));
    w.get(iid)->decals.add(glm::vec3(60.0f, 0.0f, 20.0f), glm::vec3(0, 0, -1),
                            /*radius=*/120.0f, /*intensity=*/1.0f,
                            scenegraph::WeaponClass::HeatGlow, /*birth_time=*/0.0f);

    render_galaxy_zero_ambient(w, *p, lut, /*decal_time=*/4.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double glow_healglow_settled = block_mean(130, 100, 25, 50);

    // If HeatGlow were wrongly modifying glow_flicker (a bug introduced by B1),
    // gf would differ from 1.0 and this assert would fail.
    EXPECT_NEAR(glow_healglow_settled, glow_base, glow_base * 0.03)
        << "HeatGlow decal (weapon_class==0) modified the glow multiplier gf; "
           "it must never touch glow_flicker. "
           "glow_base=" << glow_base << " after-healglow=" << glow_healglow_settled;

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// Test 3: An undamaged instance (empty decal ring) renders within tight
// tolerance of the pre-decal baseline. Complements ScorchToggleOff by
// verifying the empty-ring fast-path (u_decal_count == 0 skips apply_damage_decals
// entirely) leaves glow_flicker at its initial value of 1.0.
TEST_F(FrameTest, UndamagedInstanceGlowMatchesEmptyRingBaseline) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    // Render A: empty decal ring, default lighting.
    scenegraph::World wa;
    auto ia = wa.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    wa.set_world_transform(ia, glm::mat4(1.0f));
    render_galaxy(wa, *p, lut, 0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double R_a = block_mean(130, 100, 25, 50);
    ASSERT_GT(R_a, 0.0) << "baseline block was black";

    // Render B: second independent instance, also empty decal ring.
    // Any state shared between FrameSubmitter renders must not bleed over.
    scenegraph::World wb;
    auto ib = wb.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    wb.set_world_transform(ib, glm::mat4(1.0f));
    render_galaxy(wb, *p, lut, 0.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double R_b = block_mean(130, 100, 25, 50);

    // Two identical undamaged renders must be pixel-identical (or very close).
    EXPECT_NEAR(R_b, R_a, R_a * 0.01)
        << "Two undamaged instances rendered to different luminances; "
           "glow_flicker initial value may be wrong.  R_a=" << R_a << " R_b=" << R_b;

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

}  // namespace
