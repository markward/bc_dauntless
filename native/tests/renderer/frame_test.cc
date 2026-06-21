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

#include <algorithm>
#include <cstring>
#include <vector>

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

// dauntless_filmic toggle is declared in frame.cc; forward-declare it here.
namespace dauntless_filmic { bool enabled(); void set_enabled(bool); float ambient_scale(); }

TEST(DauntlessFilmicToggle, DefaultsOnAndRoundTrips) {
    EXPECT_TRUE(dauntless_filmic::enabled());      // default on
    dauntless_filmic::set_enabled(false);
    EXPECT_FALSE(dauntless_filmic::enabled());
    dauntless_filmic::set_enabled(true);           // restore for other tests
    EXPECT_TRUE(dauntless_filmic::enabled());
}

// Ambient is dimmed 20% (×0.8) on the exterior view when filmic is on, full
// (×1.0) when off. The exterior-only scope is enforced at the host call site;
// this just pins the scale the helper returns for each toggle state.
TEST(DauntlessFilmicToggle, AmbientScaleTracksToggle) {
    dauntless_filmic::set_enabled(true);
    EXPECT_FLOAT_EQ(dauntless_filmic::ambient_scale(), 0.8f);
    dauntless_filmic::set_enabled(false);
    EXPECT_FLOAT_EQ(dauntless_filmic::ambient_scale(), 1.0f);
    dauntless_filmic::set_enabled(true);           // restore for other tests
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

// Count "direction changes" (sign flips of consecutive deltas) in a sequence,
// ignoring deltas smaller than `eps` so floating/quantisation noise is not
// mistaken for a real reversal. A strictly monotonic sequence has 0 changes;
// an oscillating one accumulates one per reversal.
static int direction_changes(const std::vector<double>& xs, double eps) {
    int changes = 0, prev_sign = 0;
    for (size_t i = 1; i < xs.size(); ++i) {
        double d = xs[i] - xs[i-1];
        int s = (d > eps) ? 1 : (d < -eps) ? -1 : 0;
        if (s != 0 && prev_sign != 0 && s != prev_sign) ++changes;
        if (s != 0) prev_sign = s;
    }
    return changes;
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
    // Sample at decal_time = 65 s: past the transient glow-flicker window
    // (randomised per-impact, up to FLICKER_DUR_MAX = 60 s) AND past the
    // blackbody ember (~10 s to cold), so only the PERMANENT soot deposit
    // remains. (At the impact the flicker brightens the glow and the ember
    // ignites — both transient — so the permanent-darkening assertion must be
    // sampled after they settle.)
    render_galaxy(w1, *p, lut, 65.0f);
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

    // decal_time = 65 s isolates the permanent soot deposit from the transient
    // flicker (randomised, up to 60 s) + ember (~10 s), so decals-on reads as
    // darkened, not transiently brightened. (decal_time is irrelevant on the
    // disabled path.)
    dauntless_decals::set_enabled(false);
    render_galaxy(w, *p, lut, 65.0f);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double R_off = block_mean(130, 100, 25, 50);
    dauntless_decals::set_enabled(true);
    render_galaxy(w, *p, lut, 65.0f);
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

// Test 1: A SCORCH decal's glow region OSCILLATES (is non-monotonic) across
// several closely-spaced ages WITHIN the flicker window.
//
// WHY THIS IS FALSIFIABLE (and the old "brighter at birth" test was not):
// Under zero ambient the region luminance decomposes into three terms:
//   - soot deposit (via base_lit→SOOT_COLOR):  CONSTANT in time (age-independent)
//   - blackbody ember (emissive):              MONOTONICALLY DECAYS (exp(-age/τ))
//   - glow.rgb*glow.a*gf, gf = 1 + flicker:    OSCILLATES (2-sine stutter, [-1,1])
// A constant plus a monotone decay can only ever produce a MONOTONIC sequence.
// The ONLY term that can reverse direction is the flicker. So observing >=2
// direction changes across in-window ages proves the oscillating flicker is
// live. If the flicker were removed (glow_flicker never accumulates → gf≡1),
// the sequence collapses to soot+ember = monotonic and direction_changes→0,
// failing the assertion. This is robust to tuning the stutter constants: as
// long as the window contains multiple cycles (~8-12 by design) the sequence
// reverses direction many times.
TEST_F(FrameTest, ScorchGlowOscillatesWithinFlickerWindow) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    // Same body point / normal / radius as the ember + darkening tests, so the
    // sampled right block (130,100,25,50) sits squarely inside the decal.
    //
    // intensity = 0.25 (not 1.0) is deliberate: a full-intensity SCORCH ember
    // is so bright it SATURATES the 8-bit framebuffer across the whole window,
    // clipping the glow-flicker ripple out of existence (every pixel pinned at
    // 255 reads as a flat/monotone block regardless of gf). At 0.25 the region
    // stays well below saturation, so the oscillating glow*gf term remains
    // visible on top of the monotone soot+ember baseline.
    scenegraph::World w1;
    auto i1 = w1.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w1.set_world_transform(i1, glm::mat4(1.0f));
    w1.get(i1)->decals.add(glm::vec3(60.0f, 0.0f, 20.0f), glm::vec3(0, 0, -1),
                            /*radius=*/120.0f, /*intensity=*/0.25f,
                            scenegraph::WeaponClass::Scorch, /*birth_time=*/0.0f);

    // Sample N ages evenly across [0.1, 3.0] s — all strictly within the
    // SHORTEST possible randomised window (FLICKER_DUR_MIN = 5 s), so the
    // flicker is active for the whole sequence regardless of which duration
    // this decal's birth_time hashed to. All have age > 0 so the ember is
    // present (and monotonically cooling), making the soot+ember baseline a
    // clean monotone — any reversal is the flicker. The 3 s span covers several
    // oscillation cycles at STUTTER_FREQ = 15, so samples land on distinct
    // peaks and troughs.
    const int N = 16;
    std::vector<double> seq;
    seq.reserve(N);
    for (int k = 0; k < N; ++k) {
        float age = 0.1f + (3.0f - 0.1f) * static_cast<float>(k)
                                         / static_cast<float>(N - 1);
        render_galaxy_zero_ambient(w1, *p, lut, /*decal_time=*/age);
        ASSERT_EQ(glGetError(), GL_NO_ERROR);
        seq.push_back(block_mean(130, 100, 25, 50));
    }

    // Establish the swing so eps is small relative to it (and so we know the
    // glow region is actually lit — a dark region makes the test vacuous).
    double lo = seq[0], hi = seq[0];
    for (double v : seq) { lo = std::min(lo, v); hi = std::max(hi, v); }
    const double swing = hi - lo;
    ASSERT_GT(swing, 0.0) << "glow region never changed across the window; "
                              "either the region is dark or the flicker is dead";
    // eps ≈ 5% of the swing rejects 8-bit quantisation jitter but is far below
    // a real reversal of the oscillation.
    const double eps = 0.05 * swing;

    const int changes = direction_changes(seq, eps);
    EXPECT_GE(changes, 2)
        << "SCORCH glow region was (near-)monotonic across the flicker window — "
           "soot is constant and ember decays monotonically, so >=2 direction "
           "changes can ONLY come from the oscillating glow flicker. Removing the "
           "flicker would make this sequence monotonic and fail here. "
           "changes=" << changes << " swing=" << swing;

    // ── Sanity: past the window the oscillation stops. Sample closely-spaced
    // ages all > FLICKER_DUR_MAX (60 s), so the flicker is over for ANY
    // randomised duration; with gf pinned at 1.0 and the ember long cold, the
    // sequence must be monotonic (flat). ──
    std::vector<double> settled;
    settled.reserve(6);
    for (int k = 0; k < 6; ++k) {
        float age = 65.0f + 0.1f * static_cast<float>(k);  // 65.0 .. 65.5 s
        render_galaxy_zero_ambient(w1, *p, lut, /*decal_time=*/age);
        ASSERT_EQ(glGetError(), GL_NO_ERROR);
        settled.push_back(block_mean(130, 100, 25, 50));
    }
    EXPECT_LE(direction_changes(settled, eps), 1)
        << "SCORCH glow still oscillated past FLICKER_DUR_MAX (60 s); "
           "gf should be pinned at 1.0 after the window.";

    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// The 5 s stutter phase is followed, for longer randomised durations, by a
// SOLID blackout (gf clamped to 0 -> lights out in the impact region) until the
// duration ends, then the glow restores. The duration is hash-randomised per
// birth_time, so we probe a handful of birth_times for one whose duration is
// long enough to be in blackout at age 14 s (past both the 5 s stutter phase
// AND the ~10 s ember), then assert the blackout darkens the region and that it
// restores past FLICKER_DUR_MAX (60 s). Zero-ambient isolates the glow term.
TEST_F(FrameTest, ScorchFlickerBlacksOutThenRestoresForLongDurations) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    auto sample = [&](float birth, float decal_time, bool decals_on) -> double {
        dauntless_decals::set_enabled(decals_on);
        scenegraph::World w;
        auto iid = w.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
        w.set_world_transform(iid, glm::mat4(1.0f));
        w.get(iid)->decals.add(glm::vec3(60.0f, 0.0f, 20.0f), glm::vec3(0, 0, -1),
                               120.0f, 0.25f, scenegraph::WeaponClass::Scorch, birth);
        render_galaxy_zero_ambient(w, *p, lut, decal_time);
        dauntless_decals::set_enabled(true);
        return block_mean(130, 100, 25, 50);
    };

    // Glow-only baseline: same geometry, decals disabled.
    const double B = sample(0.0f, 0.0f, /*decals_on=*/false);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    ASSERT_GT(B, 0.0) << "sample region has no glow; test would be vacuous";

    // Probe birth_times for one in blackout at age 14 s (fdur > 14 ⇒ ~45% of
    // births qualify; 16 probes makes a miss astronomically unlikely).
    float found = -1.0f;
    double dark = 0.0;
    for (int b = 0; b < 16 && found < 0.0f; ++b) {
        double d = sample(static_cast<float>(b), static_cast<float>(b) + 14.0f, true);
        if (d < B * 0.4) { found = static_cast<float>(b); dark = d; }
    }
    ASSERT_GE(found, 0.0f)
        << "no probed birth_time went solidly dark at age 14 s — the blackout "
           "phase past the 5 s stutter is not driving the glow off";
    EXPECT_LT(dark, B * 0.4) << "blackout did not darken the glow region";

    // Past FLICKER_DUR_MAX (60 s) the disruption is over and the glow restores.
    const double R = sample(found, found + 65.0f, true);
    EXPECT_GT(R, B * 0.7) << "glow did not restore after the disruption ended";
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// Test 2: A HeatGlow (phaser, weapon_class == 0) decal's glow region is
// MONOTONIC across the SAME in-window ages where a SCORCH oscillates.
//
// This exercises the weapon_class gating WITHIN the active flicker window: the
// shader's weapon_class==0 branch hits `continue` BEFORE the glow_flicker
// accumulation, so gf stays 1.0 for a phaser at every age. HeatGlow's own
// additive bloom is blackbody(life)*glow where life = clamp(1 - age/T_GLOW)
// decreases monotonically over T_GLOW = 3 s; across [0.02, 0.45] that is a
// gentle monotone decrease with NO reversals.
//
// WHY THIS IS FALSIFIABLE: if the weapon_class==0 `continue` were removed so a
// phaser reached the flicker code, gf would oscillate and the region luminance
// would gain reversals (>=2 direction changes), failing the <=0 assertion. The
// direction-change metric tolerates the monotone bloom decay while rejecting
// oscillation — which is exactly the phaser-vs-torpedo distinction. (The OLD
// test sampled a single age past the window, so it never reached the guard.)
TEST_F(FrameTest, PhaserHeatGlowGlowIsMonotonicWithinFlickerWindow) {
    auto model_h = cache->load(kGalaxyNif, kGalaxyTex);
    auto lut = [model_h](scenegraph::ModelHandle h) -> const assets::Model* {
        return reinterpret_cast<const assets::Model*>(h); };

    // Same region, ages, AND intensity as Test 1 (0.25), but a HeatGlow decal.
    // Matching the intensity is what makes this test falsifiable: at 0.25 the
    // region stays unsaturated, so IF the weapon_class guard were broken and the
    // phaser reached the flicker, the glow*gf oscillation WOULD show up as
    // direction changes (exactly as it does for the SCORCH in Test 1). At full
    // intensity the bloom saturates the framebuffer and would hide any injected
    // flicker, making the guard impossible to test.
    scenegraph::World w;
    auto iid = w.create_instance(reinterpret_cast<scenegraph::ModelHandle>(model_h.get()));
    w.set_world_transform(iid, glm::mat4(1.0f));
    w.get(iid)->decals.add(glm::vec3(60.0f, 0.0f, 20.0f), glm::vec3(0, 0, -1),
                            /*radius=*/120.0f, /*intensity=*/0.25f,
                            scenegraph::WeaponClass::HeatGlow, /*birth_time=*/0.0f);

    // SAME N in-window ages as the SCORCH oscillation test.
    const int N = 12;
    std::vector<double> seq;
    seq.reserve(N);
    for (int k = 0; k < N; ++k) {
        float age = 0.02f + (0.45f - 0.02f) * static_cast<float>(k)
                                            / static_cast<float>(N - 1);
        render_galaxy_zero_ambient(w, *p, lut, /*decal_time=*/age);
        ASSERT_EQ(glGetError(), GL_NO_ERROR);
        seq.push_back(block_mean(130, 100, 25, 50));
    }

    double lo = seq[0], hi = seq[0];
    for (double v : seq) { lo = std::min(lo, v); hi = std::max(hi, v); }
    const double swing = hi - lo;
    ASSERT_GT(swing, 0.0) << "HeatGlow region never changed across the window; "
                              "the bloom decay should produce a monotone trend "
                              "(a flat sequence would make this test vacuous)";
    const double eps = 0.05 * swing;

    // Monotone: the gentle bloom decay only ever moves one direction. With the
    // phaser guard intact, gf==1.0 at every age, so there is no oscillation.
    EXPECT_LE(direction_changes(seq, eps), 0)
        << "HeatGlow (phaser) glow region oscillated within the flicker window — "
           "it must NOT flicker (the weapon_class==0 `continue` runs before the "
           "glow_flicker accumulation). Removing that guard would make this "
           "sequence non-monotonic and fail here. "
           "changes=" << direction_changes(seq, eps) << " swing=" << swing;

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
