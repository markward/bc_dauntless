// native/tests/renderer/decal_render_test.cc
//
// Hull-name decals, draw side (spec 2026-09-28-hull-name-decals-design.md
// §2 and §4 step 4-5): the opaque pass binds a material's Decal0 mask on
// texture unit 8 and opaque.frag replaces the albedo under it. Rendered
// through the REAL submit path on the real Ambassador, because shader
// errors only surface at runtime.
#include <gtest/gtest.h>

#include <renderer/aabb.h>
#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/scuff_texture.h>
#include <renderer/window.h>

#include <scenegraph/camera.h>
#include <scenegraph/world.h>

#include <assets/cache.h>
#include <assets/model.h>

// skinned_bridge_test.cc defines STB_IMAGE_WRITE_IMPLEMENTATION in this
// binary; include the same header copy so the declarations match it.
#include "../../third_party/glfw/deps/stb_image_write.h"

#include <cmath>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>
#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

#include "support/content_root.h"

namespace fs = std::filesystem;

namespace {

constexpr int kSize = 256;

fs::path ambassador_dir() {
    return test_support::game_root() / "data/Models/Ships/Ambassador";
}
fs::path ambassador_nif() { return ambassador_dir() / "Ambassador.nif"; }
std::vector<fs::path> ambassador_search() {
    return {ambassador_dir() / "High",
            test_support::game_root() / "data/Models/SharedTextures/FedShips/High"};
}

inline int current_pid() {
#ifdef _WIN32
    return _getpid();
#else
    return ::getpid();
#endif
}

struct Counts {
    int red = 0, blue = 0;
    double red_row_sum = 0.0, blue_row_sum = 0.0;
    double red_mean_row() const { return red ? red_row_sum / red : -1.0; }
    double blue_mean_row() const { return blue ? blue_row_sum / blue : -1.0; }
};

// glReadPixels row 0 is the BOTTOM of the image.
Counts count_pixels(const std::vector<std::uint8_t>& px) {
    Counts c;
    for (int y = 0; y < kSize; ++y) {
        for (int x = 0; x < kSize; ++x) {
            const std::uint8_t* p = &px[(static_cast<std::size_t>(y) * kSize + x) * 4];
            const int r = p[0], g = p[1], b = p[2];
            if (r > 2 * g && r > 2 * b) { ++c.red;  c.red_row_sum  += y; }
            if (b > 2 * r && b > 2 * g) { ++c.blue; c.blue_row_sum += y; }
        }
    }
    return c;
}

class DecalRenderTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::unique_ptr<assets::AssetCache> cache;
    fs::path tmp_dir;

    void SetUp() override {
        if (!fs::is_regular_file(ambassador_nif())) {
            GTEST_SKIP() << "BC asset not available at " << ambassador_nif();
        }
        try {
            w = std::make_unique<renderer::Window>(kSize, kSize, "decal-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        assets::AssetCache::Config cfg;
        cfg.keep_cpu_data = true;  // compute_model_aabb reads CPU vertices
        cache = std::make_unique<assets::AssetCache>(cfg);

        auto base = fs::temp_directory_path() / "decal-render";
        for (int i = 0; ; ++i) {
            auto candidate = base;
            candidate += "-" + std::to_string(current_pid()) + "-" + std::to_string(i);
            if (!fs::exists(candidate)) { tmp_dir = candidate; break; }
        }
        fs::create_directories(tmp_dir);
    }

    // Mirrors FrameTest::TearDown: release session-scoped GL state while
    // this test's context is still current.
    void TearDown() override {
        if (!tmp_dir.empty()) {
            std::error_code ec;
            fs::remove_all(tmp_dir, ec);
        }
        if (!w) return;
        cache.reset();
        renderer::reset_damage_decal_texture();
        renderer::reset_scuff_normal_texture();
        renderer::reset_decal_mask_sampler();
        renderer::reset_model_radius_cache();
    }

    // Opaque RGBA PNG, `top` colour on the upper half of the IMAGE (row 0
    // and down) and `bottom` on the lower half.
    fs::path write_mask(const std::string& name, const std::uint8_t top[3],
                        const std::uint8_t bottom[3]) {
        constexpr int kMask = 64;
        std::vector<std::uint8_t> px(kMask * kMask * 4);
        for (int y = 0; y < kMask; ++y) {
            const std::uint8_t* c = (y < kMask / 2) ? top : bottom;
            for (int x = 0; x < kMask; ++x) {
                std::uint8_t* d = &px[(static_cast<std::size_t>(y) * kMask + x) * 4];
                d[0] = c[0]; d[1] = c[1]; d[2] = c[2]; d[3] = 255;
            }
        }
        const fs::path path = tmp_dir / name;
        EXPECT_NE(stbi_write_png(path.string().c_str(), kMask, kMask, 4,
                                 px.data(), kMask * 4), 0);
        return path;
    }

    // Render `model` from straight above (looking down -z, up = +y, so
    // screen right = +x and screen up = +y) and read back the frame.
    std::vector<std::uint8_t> render_top_down(const assets::ModelHandle& model,
                                              const renderer::Aabb& box) {
        scenegraph::World world;
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(model.get()));
        world.set_world_transform(iid, glm::mat4(1.0f));

        const float half = std::max(box.half_extents.x, box.half_extents.y);
        scenegraph::Camera cam;
        cam.target = glm::vec3(box.center.x, box.center.y, 0.0f);
        cam.eye = glm::vec3(box.center.x, box.center.y,
                            box.center.z + box.half_extents.z +
                                1.2f * half / std::tan(cam.fov_y_rad * 0.5f));
        cam.up = glm::vec3(0.0f, 1.0f, 0.0f);
        cam.aspect = 1.0f;

        glViewport(0, 0, kSize, kSize);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        renderer::FrameSubmitter submitter;
        renderer::Lighting lighting;
        submitter.submit_opaque(world, cam, *p,
            [](scenegraph::ModelHandle h) -> const assets::Model* {
                return reinterpret_cast<const assets::Model*>(h);
            }, lighting);

        std::vector<std::uint8_t> px(static_cast<std::size_t>(kSize) * kSize * 4);
        glReadPixels(0, 0, kSize, kSize, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
        return px;
    }

    renderer::Aabb plain_aabb() {
        auto plain = cache->load(ambassador_nif(), ambassador_search());
        return renderer::compute_model_aabb(*plain);
    }
};

}  // namespace

// A solid opaque red mask over the whole saucer top turns it red; the plain
// hull has (essentially) no red-dominant pixels.
TEST_F(DecalRenderTest, SolidRedMaskCoversTheSaucer) {
    const renderer::Aabb box = plain_aabb();
    const glm::vec3 lo = box.center - box.half_extents;
    const glm::vec3 hi = box.center + box.half_extents;

    const std::uint8_t red[3] = {255, 0, 0};
    assets::DecalRequest req;
    req.shape = "amb saucer:0";
    req.origin = {lo.x, lo.y, hi.z};
    req.u_axis = {hi.x - lo.x, 0.0f, 0.0f};
    req.v_axis = {0.0f, hi.y - lo.y, 0.0f};
    req.normal = {0.0f, 0.0f, 1.0f};
    req.depth = hi.z - lo.z;
    req.mask = write_mask("red.png", red, red);

    auto plain = cache->load(ambassador_nif(), ambassador_search());
    auto decal = cache->load(ambassador_nif(), ambassador_search(), {}, {req});
    ASSERT_NE(plain.get(), decal.get());
    int decaled = 0;
    for (const auto& m : decal->materials) decaled += m.decal.enabled ? 1 : 0;
    ASSERT_GT(decaled, 0) << "decal was not attached to any material";

    const Counts without = count_pixels(render_top_down(plain, box));
    const Counts with = count_pixels(render_top_down(decal, box));
    std::fprintf(stderr, "[DecalRender] red-dominant pixels: plain=%d decal=%d\n",
                 without.red, with.red);

    EXPECT_GT(with.red, 200);
    EXPECT_LT(without.red, 10);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));

    // The clamp-to-edge sampler object on unit 8 must not outlive the pass:
    // a later pass binding a texture there would silently inherit the clamp.
    GLint sampler = -1;
    glActiveTexture(GL_TEXTURE8);
    glGetIntegerv(GL_SAMPLER_BINDING, &sampler);
    glActiveTexture(GL_TEXTURE0);
    EXPECT_EQ(sampler, 0);
}

// Pins mask row 0 = the TOP of the image: with v running toward -y and the
// camera's up = +y, the mask's red top half must land nearer the top of the
// screen than its blue bottom half. A flipped v fails this.
TEST_F(DecalRenderTest, MaskRowZeroIsTheTopOfTheImage) {
    const renderer::Aabb box = plain_aabb();
    const glm::vec3 lo = box.center - box.half_extents;
    const glm::vec3 hi = box.center + box.half_extents;

    const std::uint8_t red[3] = {255, 0, 0};
    const std::uint8_t blue[3] = {0, 0, 255};
    assets::DecalRequest req;
    req.shape = "amb saucer:0";
    req.origin = {lo.x, hi.y, hi.z};
    req.u_axis = {hi.x - lo.x, 0.0f, 0.0f};
    req.v_axis = {0.0f, -(hi.y - lo.y), 0.0f};  // mask v runs toward -y
    req.normal = {0.0f, 0.0f, 1.0f};
    req.depth = hi.z - lo.z;
    req.mask = write_mask("red_over_blue.png", red, blue);

    auto decal = cache->load(ambassador_nif(), ambassador_search(), {}, {req});
    const Counts c = count_pixels(render_top_down(decal, box));
    std::fprintf(stderr,
        "[DecalRender] orientation: red=%d (mean row %.1f) blue=%d (mean row %.1f)"
        " -- glReadPixels row 0 is the bottom\n",
        c.red, c.red_mean_row(), c.blue, c.blue_mean_row());

    ASSERT_GT(c.red, 50);
    ASSERT_GT(c.blue, 50);
    EXPECT_GT(c.red_mean_row(), c.blue_mean_row());
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}
