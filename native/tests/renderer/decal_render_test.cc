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

// Number of pixels whose Rec.709 luminance drops by more than `threshold`
// going from `before` to `after`. Used to detect the black-lettering-kills-
// the-glow bug: under the pre-fix shader the glow map's own RGB still shone
// through a black mask, so this stayed small even where the mask was 100%
// opaque black.
int count_luminance_drop(const std::vector<std::uint8_t>& before,
                          const std::vector<std::uint8_t>& after, int threshold) {
    int n = 0;
    for (std::size_t i = 0; i + 3 < before.size(); i += 4) {
        const double lb = 0.2126 * before[i] + 0.7152 * before[i + 1] + 0.0722 * before[i + 2];
        const double la = 0.2126 * after[i]  + 0.7152 * after[i + 1]  + 0.0722 * after[i + 2];
        if (lb - la > threshold) ++n;
    }
    return n;
}

// Number of pixels whose |ΔR|+|ΔG|+|ΔB| exceeds `threshold` between two
// renders of the same view.
int count_changed_pixels(const std::vector<std::uint8_t>& before,
                          const std::vector<std::uint8_t>& after, int threshold) {
    int n = 0;
    for (std::size_t i = 0; i + 3 < before.size(); i += 4) {
        const int d = std::abs(static_cast<int>(before[i]) - static_cast<int>(after[i])) +
                      std::abs(static_cast<int>(before[i + 1]) - static_cast<int>(after[i + 1])) +
                      std::abs(static_cast<int>(before[i + 2]) - static_cast<int>(after[i + 2]));
        if (d > threshold) ++n;
    }
    return n;
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
        // Decals only attach on top of a mesh the committed Ambassador
        // fix actually patched (cache.cc's gate) -- without this, both
        // tests below would silently draw the plain hull.
        cfg.mesh_fix_dir = [] {
            return fs::path(OPEN_STBC_PROJECT_ROOT) / "native/assets/mesh_fixes";
        };
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

    // The committed real "top" placement from
    // native/assets/replacements/data/Models/Ships/Ambassador/Masks/decals.json
    // -- the actual saucer-lettering rectangle, not the whole-hull box the
    // other tests in this file synthesize. `mask` is left unset; callers fill
    // it in.
    assets::DecalRequest real_top_placement() {
        assets::DecalRequest req;
        req.shape  = "amb saucer:0";
        req.origin = {58.13181686401367f, 149.3275146484375f, 51.149471282958984f};
        req.u_axis = {-119.56663513183594f, -0.011889359913766384f, -0.0024647493846714497f};
        req.v_axis = {-0.005896189250051975f, 59.74415969848633f, -2.1634225845336914f};
        req.normal = {-2.4198923711082898e-05f, 0.03618772700428963f, 0.9993450045585632f};
        req.depth  = 2.0f;
        return req;
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

// BC's _glow textures are one image: RGB = albedo, alpha = an 8-bit emissive
// map, and the saucer's window band sits under the lettering rectangle. A
// black hull-name mask must black out the glow term's RGB the same way it
// blacks out albedo, or the lit window band shines straight through the
// letters (the live-verified bug: Zhukov's real lettering changed only 18
// pixels because the glow term still emitted the hull's ORIGINAL colour
// under the mask).
TEST_F(DecalRenderTest, BlackLetteringSuppressesGlow) {
    const renderer::Aabb box = plain_aabb();
    const std::uint8_t black[3] = {0, 0, 0};

    assets::DecalRequest req = real_top_placement();
    req.mask = write_mask("black.png", black, black);

    auto plain = cache->load(ambassador_nif(), ambassador_search());
    auto decal = cache->load(ambassador_nif(), ambassador_search(), {}, {req});
    ASSERT_NE(plain.get(), decal.get());
    int decaled = 0;
    for (const auto& m : decal->materials) decaled += m.decal.enabled ? 1 : 0;
    ASSERT_GT(decaled, 0) << "decal was not attached to any material";

    const auto before = render_top_down(plain, box);
    const auto after  = render_top_down(decal, box);
    const int dropped = count_luminance_drop(before, after, 30);
    std::fprintf(stderr, "[DecalRender] black-lettering luminance-drop pixels: %d\n", dropped);

    // A solid opaque black mask darkens the whole placement rectangle's
    // ALBEDO regardless of the glow fix (zeroing base.rgb alone already
    // drops plenty of pixels by >30 luminance where the hull texture wasn't
    // already near-black), so 200 alone does not discriminate pre/post fix
    // here -- MEASURED (mutation-proved below): 301 with the glow composite
    // reverted, 946 with it in place. 500 sits strictly between the two.
    EXPECT_GT(dropped, 500);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

// Same real placement, but the mask itself is coloured (opaque red): the
// letters should emit their OWN colour where the glow band lit them, not
// just replace albedo. Compares against the pre-fix figure of ~910 changed
// pixels (measured with the whole-saucer SolidRedMaskCoversTheSaucer
// geometry's counting style, on this test's narrower real placement) to make
// sure the glow-term composite adds coverage rather than only matching it.
TEST_F(DecalRenderTest, RedLetteringTintsGlow) {
    const renderer::Aabb box = plain_aabb();
    const std::uint8_t red[3] = {255, 0, 0};

    assets::DecalRequest req = real_top_placement();
    req.mask = write_mask("red_top.png", red, red);

    auto plain = cache->load(ambassador_nif(), ambassador_search());
    auto decal = cache->load(ambassador_nif(), ambassador_search(), {}, {req});
    ASSERT_NE(plain.get(), decal.get());

    const auto before = render_top_down(plain, box);
    const auto after  = render_top_down(decal, box);
    const int changed = count_changed_pixels(before, after, 30);
    std::fprintf(stderr, "[DecalRender] red-lettering changed pixels (real placement): %d\n",
                 changed);

    EXPECT_GT(changed, 910);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

// The real content: Zhukov's actual black lettering mask at its committed
// placement. Before the fix this changed only 18 pixels against the plain
// render; the name was invisible in-game.
TEST_F(DecalRenderTest, RealZhukovMaskIsVisibleOverTheGlowBand) {
    // The Zhukov mask ships as a PROJECT replacement asset (engine.mods'
    // native/assets/replacements overlay, resolved in Python via
    // paths.game_asset), not under the player's BC install -- so this C++
    // test reaches it directly rather than through ambassador_dir().
    const fs::path zhukov_mask = fs::path(OPEN_STBC_PROJECT_ROOT) /
        "native/assets/replacements/data/Models/Ships/Ambassador/Masks/Zhukov/top.png";
    if (!fs::is_regular_file(zhukov_mask)) {
        GTEST_SKIP() << "Zhukov mask not available at " << zhukov_mask;
    }

    const renderer::Aabb box = plain_aabb();
    assets::DecalRequest req = real_top_placement();
    req.mask = zhukov_mask;

    auto plain = cache->load(ambassador_nif(), ambassador_search());
    auto decal = cache->load(ambassador_nif(), ambassador_search(), {}, {req});
    ASSERT_NE(plain.get(), decal.get());
    int decaled = 0;
    for (const auto& m : decal->materials) decaled += m.decal.enabled ? 1 : 0;
    ASSERT_GT(decaled, 0) << "decal was not attached to any material";

    const auto plain_px = render_top_down(plain, box);
    const auto decal_px = render_top_down(decal, box);
    const int changed = count_changed_pixels(plain_px, decal_px, 30);
    std::fprintf(stderr, "[DecalRender] real Zhukov mask changed pixels: %d\n", changed);

    EXPECT_GT(changed, 150);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}
