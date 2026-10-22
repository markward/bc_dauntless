// native/tests/renderer/decal_render_test.cc
//
// Hull-name decals, draw side (spec 2026-09-28-hull-name-decals-design.md
// §2; per-model list: 2026-09-28-spv-decal-editing-design.md §2.4): the
// opaque pass binds up to four Model::decals masks on texture units 8..11 and
// opaque.frag composites them over the albedo in list order. Rendered
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
#include <assets/decal_override.h>
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
        // The committed Ambassador mesh fix is applied (as in game) so the
        // real-placement figures below stay comparable with the pre-list
        // baselines. Decals no longer depend on it.
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
        renderer::reset_scuff_normal_texture();
        renderer::reset_decal_mask_sampler();
        renderer::reset_model_radius_cache();
    }

    // Opaque RGBA PNG, `top` colour on the upper half of the IMAGE (row 0
    // and down) and `bottom` on the lower half.
    fs::path write_mask(const std::string& name, const std::uint8_t top[3],
                        const std::uint8_t bottom[3], std::uint8_t alpha = 255) {
        constexpr int kMask = 64;
        std::vector<std::uint8_t> px(kMask * kMask * 4);
        for (int y = 0; y < kMask; ++y) {
            const std::uint8_t* c = (y < kMask / 2) ? top : bottom;
            for (int x = 0; x < kMask; ++x) {
                std::uint8_t* d = &px[(static_cast<std::size_t>(y) * kMask + x) * 4];
                d[0] = c[0]; d[1] = c[1]; d[2] = c[2]; d[3] = alpha;
            }
        }
        const fs::path path = tmp_dir / name;
        EXPECT_NE(stbi_write_png(path.string().c_str(), kMask, kMask, 4,
                                 px.data(), kMask * 4), 0);
        return path;
    }

    // Render `model` from straight above (looking down -z, up = +y, so
    // screen right = +x and screen up = +y) -- or, with `from_below`, from
    // straight below looking up +z -- and read back the frame. A narrow
    // `fov_y_rad` approaches an orthographic view, so a surface facing away
    // from the camera axis can't peek out at the silhouette.
    std::vector<std::uint8_t> render_top_down(const assets::ModelHandle& model,
                                              const renderer::Aabb& box,
                                              bool from_below = false,
                                              float fov_y_rad = scenegraph::Camera{}.fov_y_rad) {
        scenegraph::World world;
        auto iid = world.create_instance(
            reinterpret_cast<scenegraph::ModelHandle>(model.get()));
        world.set_world_transform(iid, glm::mat4(1.0f));
        return render_world_top_down(world, box, from_below, fov_y_rad);
    }

    // render_top_down for a caller-built world (every instance at its own
    // transform), through the same submit_opaque path.
    std::vector<std::uint8_t> render_world_top_down(
            const scenegraph::World& world, const renderer::Aabb& box,
            bool from_below = false,
            float fov_y_rad = scenegraph::Camera{}.fov_y_rad) {
        const float half = std::max(box.half_extents.x, box.half_extents.y);
        const float dist = box.half_extents.z +
                           1.2f * half / std::tan(fov_y_rad * 0.5f);
        scenegraph::Camera cam;
        cam.fov_y_rad = fov_y_rad;
        cam.target = glm::vec3(box.center.x, box.center.y, 0.0f);
        cam.eye = glm::vec3(box.center.x, box.center.y,
                            from_below ? box.center.z - dist : box.center.z + dist);
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

    // A whole-hull (x, y) footprint projected along `normal` = +z (from
    // the top face of the box) or -z (from the bottom face), `shape`
    // optional ("" = every mesh).
    assets::DecalRequest whole_hull(const renderer::Aabb& box, bool from_below,
                                    const fs::path& mask,
                                    const std::string& shape = "") {
        const glm::vec3 lo = box.center - box.half_extents;
        const glm::vec3 hi = box.center + box.half_extents;
        assets::DecalRequest req;
        req.shape = shape;
        req.origin = {lo.x, lo.y, from_below ? lo.z : hi.z};
        req.u_axis = {hi.x - lo.x, 0.0f, 0.0f};
        req.v_axis = {0.0f, hi.y - lo.y, 0.0f};
        req.normal = {0.0f, 0.0f, from_below ? -1.0f : 1.0f};
        req.depth = hi.z - lo.z;
        req.mask = mask;
        return req;
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
    ASSERT_EQ(decal->decals.size(), 1u) << "decal was not attached";

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
    ASSERT_EQ(decal->decals.size(), 1u) << "decal was not attached";

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
// placement. Before the glow fix this changed only 18 pixels against the
// plain render; the name was invisible in-game. LEGACY REGRESSION for the
// per-model list: the per-material Decal0 path measured 224 here.
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
    ASSERT_EQ(decal->decals.size(), 1u) << "decal was not attached";

    const auto plain_px = render_top_down(plain, box);
    const auto decal_px = render_top_down(decal, box);
    const int changed = count_changed_pixels(plain_px, decal_px, 30);
    std::fprintf(stderr, "[DecalRender] real Zhukov mask changed pixels: %d"
                         " (per-material baseline 224)\n", changed);

    // Pinned EXACTLY: the 16-projector / 4-slot list must render the one
    // committed placement exactly as the 4-decal list did (spec §2.4a
    // compatibility constraint).
    EXPECT_EQ(changed, 224);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

// ── Reusable masks: 16 projectors over up to 4 mask slots (spec §2.4a) ──────

namespace {

// Red-dominant pixels in screen columns [x0, x1).
int count_red_in_columns(const std::vector<std::uint8_t>& px, int x0, int x1) {
    int n = 0;
    for (int y = 0; y < kSize; ++y) {
        for (int x = x0; x < x1; ++x) {
            const std::uint8_t* p = &px[(static_cast<std::size_t>(y) * kSize + x) * 4];
            if (p[0] > 2 * p[1] && p[0] > 2 * p[2]) ++n;
        }
    }
    return n;
}

int count_green(const std::vector<std::uint8_t>& px) {
    int n = 0;
    for (std::size_t i = 0; i + 3 < px.size(); i += 4)
        if (px[i + 1] > 2 * px[i] && px[i + 1] > 2 * px[i + 2]) ++n;
    return n;
}

}  // namespace

// Review Focus 1, draw side: ONE red mask shared by two placements -- the
// left half and the right half of the hull footprint -- is one slot, and
// both halves turn red.
TEST_F(DecalRenderTest, SharedMaskPairPaintsBothLocations) {
    const renderer::Aabb box = plain_aabb();
    const std::uint8_t red[3] = {255, 0, 0};
    const fs::path mask = write_mask("red.png", red, red);

    auto left = whole_hull(box, false, mask);
    left.u_axis.x *= 0.5f;
    auto right = left;
    right.origin.x += left.u_axis.x;

    auto decal = cache->load(ambassador_nif(), ambassador_search(), {}, {left, right});
    ASSERT_EQ(decal->decals.size(), 2u);
    ASSERT_EQ(decal->decal_masks.size(), 1u) << "one shared mask, one slot";
    EXPECT_EQ(decal->decals[0].mask_slot, decal->decals[1].mask_slot);

    const auto px = render_top_down(decal, box);
    const int red_left = count_red_in_columns(px, 0, kSize / 2 - 8);
    const int red_right = count_red_in_columns(px, kSize / 2 + 8, kSize);
    std::fprintf(stderr, "[DecalRender] shared mask: left red=%d right red=%d\n",
                 red_left, red_right);
    EXPECT_GT(red_left, 200);
    EXPECT_GT(red_right, 200);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

// Review Focus 3, draw side: 17 placements -> the 16th (index 15, blue from
// below) draws and the 17th (green from above) is dropped; the decal at
// index 10 (red, restricted to the saucer shape) paints exactly what the
// same decal alone paints -- so enable bit 10 reaches the shader. Indices
// 0..9 and 11..14 are fully transparent masks, which leave the hull as is.
TEST_F(DecalRenderTest, SixteenPlacementsHonourIndexTenAndDropTheSeventeenth) {
    const renderer::Aabb box = plain_aabb();
    const std::uint8_t red[3] = {255, 0, 0};
    const std::uint8_t blue[3] = {0, 0, 255};
    const std::uint8_t green[3] = {0, 255, 0};
    const fs::path clear_mask = write_mask("clear.png", red, red, /*alpha=*/0);
    const fs::path red_mask = write_mask("red.png", red, red);

    std::vector<assets::DecalRequest> reqs(15, whole_hull(box, false, clear_mask));
    reqs[10] = whole_hull(box, false, red_mask, "amb saucer:0");
    reqs.push_back(whole_hull(box, true, write_mask("blue.png", blue, blue)));
    reqs.push_back(whole_hull(box, false, write_mask("green.png", green, green)));
    ASSERT_EQ(reqs.size(), 17u);

    auto sixteen = cache->load(ambassador_nif(), ambassador_search(), {}, reqs);
    auto alone = cache->load(ambassador_nif(), ambassador_search(), {},
                             {whole_hull(box, false, red_mask, "amb saucer:0")});
    ASSERT_EQ(sixteen->decals.size(), 16u);
    EXPECT_EQ(sixteen->decal_masks.size(), 3u);

    const auto top = render_top_down(sixteen, box);
    const Counts c_top = count_pixels(top);
    const Counts c_alone = count_pixels(render_top_down(alone, box));
    const Counts c_bot = count_pixels(render_top_down(sixteen, box, /*from_below=*/true));
    const int green_px = count_green(top);
    std::fprintf(stderr,
        "[DecalRender] 17 placements: top red=%d (index-10 alone %d) green=%d; "
        "bottom blue=%d\n", c_top.red, c_alone.red, green_px, c_bot.blue);

    EXPECT_GT(c_alone.red, 200);
    EXPECT_EQ(c_top.red, c_alone.red);
    EXPECT_EQ(green_px, 0) << "the 17th placement must be dropped";
    EXPECT_GT(c_bot.blue, 200) << "the 16th placement must draw";
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

// Review Focus 4: 16 strips across the hull sharing 4 masks (one of them
// half-transparent, so premultiplication is exercised), alternating
// unrestricted and saucer-only -- baked into the model vs pushed as a
// per-instance override on the plain model: pixel-for-pixel identical.
TEST_F(DecalRenderTest, OverrideMatchesBakedForSixteenSharedMaskEntries) {
    const renderer::Aabb box = plain_aabb();
    const std::uint8_t red[3] = {255, 0, 0};
    const std::uint8_t blue[3] = {0, 0, 255};
    const std::uint8_t white[3] = {255, 255, 255};
    const fs::path masks[4] = {
        write_mask("red.png", red, red),
        write_mask("blue.png", blue, blue),
        write_mask("red_over_blue.png", red, blue),
        write_mask("half_white.png", white, white, /*alpha=*/128),
    };

    std::vector<assets::DecalRequest> reqs;
    for (int i = 0; i < 16; ++i) {
        auto r = whole_hull(box, false, masks[i % 4], (i % 2) ? "amb saucer:0" : "");
        r.u_axis.x /= 16.0f;
        r.origin.x += static_cast<float>(i) * r.u_axis.x;
        reqs.push_back(r);
    }

    auto plain = cache->load(ambassador_nif(), ambassador_search());
    auto baked = cache->load(ambassador_nif(), ambassador_search(), {}, reqs);
    ASSERT_EQ(baked->decals.size(), 16u);
    ASSERT_EQ(baked->decal_masks.size(), 4u);

    assets::DecalMaskCache mask_cache;
    int resolves = 0;
    auto ov = assets::build_decal_override(*plain, reqs,
        [&](const fs::path& p) { ++resolves; return mask_cache.get(p); });
    ASSERT_EQ(ov.decals.size(), 16u);
    EXPECT_EQ(resolves, 4);

    scenegraph::World world;
    const auto iid = world.create_instance(
        reinterpret_cast<scenegraph::ModelHandle>(plain.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));
    renderer::set_instance_decal_override(iid, std::move(ov));
    const auto via_override = render_world_top_down(world, box);
    renderer::clear_instance_decal_overrides();

    const auto via_baked = render_top_down(baked, box);
    const auto via_plain = render_top_down(plain, box);
    const int changed = count_changed_pixels(via_plain, via_baked, 30);
    int differing = 0;
    for (std::size_t i = 0; i < via_baked.size(); ++i)
        if (via_baked[i] != via_override[i]) ++differing;
    std::fprintf(stderr,
        "[DecalRender] 16 shared-mask strips: changed vs plain=%d, "
        "baked vs override differing bytes=%d\n", changed, differing);

    EXPECT_GT(changed, 1000);
    EXPECT_EQ(differing, 0);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    mask_cache.clear();
}

// Two decals on one model, both unrestricted (no shape): an opaque red one
// projected from above (normal +z) and an opaque blue one from below
// (normal -z) over the same (x, y) footprint. The facing test keeps each on
// its own side: from above only red shows, from below only blue.
TEST_F(DecalRenderTest, TwoDecalsFromOppositeSidesStayOnTheirSide) {
    const renderer::Aabb box = plain_aabb();
    const std::uint8_t red[3] = {255, 0, 0};
    const std::uint8_t blue[3] = {0, 0, 255};

    auto plain = cache->load(ambassador_nif(), ambassador_search());
    auto decal = cache->load(ambassador_nif(), ambassador_search(), {},
        {whole_hull(box, /*from_below=*/false, write_mask("red.png", red, red)),
         whole_hull(box, /*from_below=*/true, write_mask("blue.png", blue, blue))});
    ASSERT_EQ(decal->decals.size(), 2u);

    // Near-orthographic: under the default 60-degree perspective, faces whose
    // normals tilt slightly AWAY from the camera still show at the saucer
    // rim, and the facing test (correctly) paints them with the far-side
    // decal -- MEASURED 28 such blue pixels from above and 24 red from below.
    constexpr float kNarrowFov = 0.1f;
    const Counts plain_top = count_pixels(render_top_down(plain, box, false, kNarrowFov));
    const Counts plain_bot = count_pixels(render_top_down(plain, box, true, kNarrowFov));
    const Counts top = count_pixels(render_top_down(decal, box, false, kNarrowFov));
    const Counts bot = count_pixels(render_top_down(decal, box, true, kNarrowFov));
    std::fprintf(stderr,
        "[DecalRender] two decals: top red=%d blue=%d (plain %d/%d); "
        "bottom red=%d blue=%d (plain %d/%d)\n",
        top.red, top.blue, plain_top.red, plain_top.blue,
        bot.red, bot.blue, plain_bot.red, plain_bot.blue);

    EXPECT_GT(top.red, 200);
    EXPECT_LE(top.blue, plain_top.blue + 10);
    EXPECT_GT(bot.blue, 200);
    EXPECT_LE(bot.red, plain_bot.red + 10);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));

    // None of the four clamp-sampler units may outlive the pass.
    for (int unit = 8; unit < 12; ++unit) {
        GLint sampler = -1;
        glActiveTexture(GL_TEXTURE0 + unit);
        glGetIntegerv(GL_SAMPLER_BINDING, &sampler);
        EXPECT_EQ(sampler, 0) << "unit " << unit;
    }
    glActiveTexture(GL_TEXTURE0);
}

// `shape` restricts a decal to that shape's meshes: the same whole-hull red
// projection limited to the saucer paints strictly fewer pixels than the
// unrestricted one (which also reaches the engineering hull and nacelles),
// and still paints the saucer.
TEST_F(DecalRenderTest, ShapeRestrictsTheDecalToThatShapesMeshes) {
    const renderer::Aabb box = plain_aabb();
    const std::uint8_t red[3] = {255, 0, 0};
    const fs::path mask = write_mask("red.png", red, red);

    auto all = cache->load(ambassador_nif(), ambassador_search(), {},
                           {whole_hull(box, false, mask)});
    auto saucer = cache->load(ambassador_nif(), ambassador_search(), {},
                              {whole_hull(box, false, mask, "amb saucer:0")});
    ASSERT_NE(all.get(), saucer.get());

    const Counts c_all = count_pixels(render_top_down(all, box));
    const Counts c_saucer = count_pixels(render_top_down(saucer, box));
    std::fprintf(stderr, "[DecalRender] shape restriction: all=%d saucer-only=%d\n",
                 c_all.red, c_saucer.red);

    EXPECT_GT(c_saucer.red, 200);
    EXPECT_LT(c_saucer.red + 200, c_all.red);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

// ── Per-instance override (set_instance_decals, spec §2.5) ─────────────────

// The plain Ambassador has no baked decals; an override on ONE instance
// paints it, a second instance of the same model in the same world stays
// plain, and clearing the override restores the plain hull.
TEST_F(DecalRenderTest, InstanceOverridePaintsOnlyThatInstanceAndClears) {
    const renderer::Aabb box = plain_aabb();
    const std::uint8_t red[3] = {255, 0, 0};
    auto plain = cache->load(ambassador_nif(), ambassador_search());
    ASSERT_TRUE(plain->decals.empty());

    scenegraph::World world;
    const auto handle = reinterpret_cast<scenegraph::ModelHandle>(plain.get());
    const auto a = world.create_instance(handle);
    const auto b = world.create_instance(handle);
    world.set_world_transform(a, glm::mat4(1.0f));
    world.set_world_transform(b, glm::mat4(1.0f));

    assets::DecalMaskCache masks;
    renderer::set_instance_decal_override(a, assets::build_decal_override(
        *plain,
        {whole_hull(box, false, write_mask("red.png", red, red), "amb saucer:0")},
        [&](const fs::path& p) { return masks.get(p); }));

    // Only A visible: painted. Only B visible: plain.
    world.set_visible(b, false);
    const Counts a_on = count_pixels(render_world_top_down(world, box));
    world.set_visible(b, true);
    world.set_visible(a, false);
    const Counts b_only = count_pixels(render_world_top_down(world, box));
    world.set_visible(a, true);
    world.set_visible(b, false);
    renderer::clear_instance_decal_override(a);
    const Counts a_cleared = count_pixels(render_world_top_down(world, box));
    std::fprintf(stderr,
        "[DecalRender] override: A=%d, second instance B=%d, A cleared=%d\n",
        a_on.red, b_only.red, a_cleared.red);

    EXPECT_GT(a_on.red, 200);
    EXPECT_LT(b_only.red, 10);
    EXPECT_LT(a_cleared.red, 10);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    for (int unit = 8; unit < 12; ++unit) {
        GLint sampler = -1;
        glActiveTexture(GL_TEXTURE0 + unit);
        glGetIntegerv(GL_SAMPLER_BINDING, &sampler);
        EXPECT_EQ(sampler, 0) << "unit " << unit;
    }
    glActiveTexture(GL_TEXTURE0);
    renderer::clear_instance_decal_overrides();
    masks.clear();
}

// The override REPLACES the baked list: an empty override on a model with a
// baked red decal draws no decal; clearing it brings the baked one back.
TEST_F(DecalRenderTest, InstanceOverrideReplacesTheBakedList) {
    const renderer::Aabb box = plain_aabb();
    const std::uint8_t red[3] = {255, 0, 0};
    auto baked = cache->load(ambassador_nif(), ambassador_search(), {},
        {whole_hull(box, false, write_mask("red.png", red, red), "amb saucer:0")});
    ASSERT_EQ(baked->decals.size(), 1u);

    scenegraph::World world;
    const auto a = world.create_instance(
        reinterpret_cast<scenegraph::ModelHandle>(baked.get()));
    world.set_world_transform(a, glm::mat4(1.0f));

    renderer::set_instance_decal_override(
        a, assets::build_decal_override(*baked, {}, {}));
    const Counts overridden = count_pixels(render_world_top_down(world, box));
    renderer::clear_instance_decal_override(a);
    const Counts restored = count_pixels(render_world_top_down(world, box));
    std::fprintf(stderr,
        "[DecalRender] empty override on baked: %d, cleared: %d\n",
        overridden.red, restored.red);

    EXPECT_LT(overridden.red, 10);
    EXPECT_GT(restored.red, 200);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    renderer::clear_instance_decal_overrides();
}

// ── Decals follow an articulated node (spec 2026-10-18-articulated-hull-decals
//    §2/§6.1) ────────────────────────────────────────────────────────────────
// opaque.frag used to test decal projectors against the POSED body position,
// so a decal slid off a part that an override had moved. It now tests them in
// the REST frame through u_node_rest_fix, exactly like the glow regions.
namespace {

// Opaque red over the body +X half of the saucer top only (asymmetric).
assets::DecalRequest right_half_saucer(const renderer::Aabb& box,
                                       const fs::path& mask) {
    const glm::vec3 lo = box.center - box.half_extents;
    const glm::vec3 hi = box.center + box.half_extents;
    assets::DecalRequest req;
    req.shape = "amb saucer:0";
    req.origin = {box.center.x, lo.y, hi.z};
    req.u_axis = {hi.x - box.center.x, 0.0f, 0.0f};
    req.v_axis = {0.0f, hi.y - lo.y, 0.0f};
    req.normal = {0.0f, 0.0f, 1.0f};
    req.depth = hi.z - lo.z;
    req.mask = mask;
    return req;
}

// Red pixels in the screen-left (x < kSize/2) or screen-right half.
int red_in_half(const std::vector<std::uint8_t>& px, bool right) {
    int n = 0;
    for (int y = 0; y < kSize; ++y) {
        for (int x = (right ? kSize / 2 : 0); x < (right ? kSize : kSize / 2); ++x) {
            const std::uint8_t* p = &px[(static_cast<std::size_t>(y) * kSize + x) * 4];
            if (p[0] > 2 * p[1] && p[0] > 2 * p[2]) ++n;
        }
    }
    return n;
}

// The node's own rest local, then 180 degrees about body +Z (up) around
// `pivot`, so the hull stays centred in view with its top still facing +Z.
glm::mat4 spun_about_up(const assets::Model& m, int node, const glm::vec3& pivot) {
    return m.nodes[node].local_transform *
           glm::translate(glm::mat4(1.0f), pivot) *
           glm::rotate(glm::mat4(1.0f), glm::radians(180.0f), glm::vec3(0, 0, 1)) *
           glm::translate(glm::mat4(1.0f), -pivot);
}

// The "part" node (a child of the node named "Scene Root", the rule in
// renderer/model_parts.h) that owns the mesh built from `shape`, or -1.
int part_of_shape(const assets::Model& m, const std::string& shape) {
    int scene_root = -1;
    for (std::size_t i = 0; i < m.nodes.size(); ++i)
        if (m.nodes[i].name == "Scene Root") { scene_root = static_cast<int>(i); break; }
    if (scene_root < 0) return -1;
    for (const auto& mesh : m.meshes) {
        if (mesh.shape_name() != shape) continue;
        int n = mesh.node_index();
        while (n >= 0 && m.nodes[n].parent_index != scene_root) n = m.nodes[n].parent_index;
        return n;
    }
    return -1;
}

// count_pixels over everything except the top-right corner (screen x, y >= 192;
// GL row 0 is the bottom) where test 3 parks its shrunk articulated ship.
Counts count_outside_corner(std::vector<std::uint8_t> px) {
    for (int y = 192; y < kSize; ++y)
        for (int x = 192; x < kSize; ++x)
            for (int c = 0; c < 4; ++c)
                px[(static_cast<std::size_t>(y) * kSize + x) * 4 + c] = 0;
    return count_pixels(px);
}

// Texels that differ between `a` and `b` INSIDE that corner: non-zero only
// if something is drawn there in one render and not the other.
std::size_t differing_corner_texels(const std::vector<std::uint8_t>& a,
                                    const std::vector<std::uint8_t>& b) {
    std::size_t n = 0;
    for (int y = 192; y < kSize; ++y)
        for (int x = 192; x < kSize; ++x) {
            const std::size_t i = (static_cast<std::size_t>(y) * kSize + x) * 4;
            if (a[i] != b[i] || a[i + 1] != b[i + 1] || a[i + 2] != b[i + 2]) ++n;
        }
    return n;
}

std::size_t differing_texels(const std::vector<std::uint8_t>& a,
                             const std::vector<std::uint8_t>& b) {
    std::size_t n = 0;
    for (std::size_t i = 0; i + 3 < a.size(); i += 4)
        if (a[i] != b[i] || a[i + 1] != b[i + 1] || a[i + 2] != b[i + 2] ||
            a[i + 3] != b[i + 3]) ++n;
    return n;
}

}  // namespace

TEST_F(DecalRenderTest, DecalFollowsANodeRotatedAboutUp) {
    const renderer::Aabb box = plain_aabb();
    const std::uint8_t red[3] = {255, 0, 0};
    auto decal = cache->load(ambassador_nif(), ambassador_search(), {},
        {right_half_saucer(box, write_mask("red.png", red, red))});
    ASSERT_EQ(decal->decals.size(), 1u);

    const auto base = render_top_down(decal, box);
    const int base_right = red_in_half(base, true);
    const int base_left = red_in_half(base, false);
    const int base_total = count_pixels(base).red;
    ASSERT_GT(base_right, 200) << "guard: unrotated decal must sit screen-right";
    ASSERT_LT(base_left, base_right / 10) << "guard: unrotated decal must not reach screen-left";

    scenegraph::World world;
    const auto iid = world.create_instance(
        reinterpret_cast<scenegraph::ModelHandle>(decal.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));
    world.get(iid)->node_overrides[decal->root_node] =
        spun_about_up(*decal, decal->root_node, box.center);
    const auto spun = render_world_top_down(world, box);
    const int spun_left = red_in_half(spun, false);
    const int spun_right = red_in_half(spun, true);
    const int spun_total = count_pixels(spun).red;
    std::fprintf(stderr,
        "[DecalRender] spun: left=%d right=%d total=%d (unrotated right=%d total=%d)\n",
        spun_left, spun_right, spun_total, base_right, base_total);

    EXPECT_GE(spun_left, 0.8 * base_right) << "the decal did not follow its surface";
    EXPECT_LE(spun_right, 0.1 * base_right) << "the decal stayed at its rest position";
    EXPECT_NEAR(spun_total, base_total, 0.1 * base_total);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(DecalRenderTest, RestPoseOverrideRendersDecalIdentically) {
    const renderer::Aabb box = plain_aabb();
    const std::uint8_t red[3] = {255, 0, 0};
    auto decal = cache->load(ambassador_nif(), ambassador_search(), {},
        {right_half_saucer(box, write_mask("red.png", red, red))});

    const auto plain = render_top_down(decal, box);

    scenegraph::World world;
    const auto iid = world.create_instance(
        reinterpret_cast<scenegraph::ModelHandle>(decal.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));
    world.get(iid)->node_overrides[decal->root_node] =
        decal->nodes[decal->root_node].local_transform;
    const auto overridden = render_world_top_down(world, box);

    ASSERT_GT(count_pixels(plain).red, 200);
    EXPECT_EQ(differing_texels(plain, overridden), 0u);
}

TEST_F(DecalRenderTest, ArticulatedShipDrawnFirstDoesNotShiftAPlainShipsDecal) {
    const renderer::Aabb box = plain_aabb();
    const std::uint8_t red[3] = {255, 0, 0};
    auto decal = cache->load(ambassador_nif(), ambassador_search(), {},
        {right_half_saucer(box, write_mask("red.png", red, red))});
    const auto handle = reinterpret_cast<scenegraph::ModelHandle>(decal.get());

    scenegraph::World w0;
    const auto p0 = w0.create_instance(handle);
    w0.set_world_transform(p0, glm::mat4(1.0f));
    const Counts alone = count_pixels(render_world_top_down(w0, box));
    ASSERT_GT(alone.red, 200);

    // A rotated, shrunk ship created FIRST (drawn first), parked IN VIEW in
    // the top-right corner (so it stays drawn even if culling is ever added);
    // u_node_rest_fix must not leak from it onto the plain ship's decal. Only
    // pixels outside that corner are counted, in both renders.
    scenegraph::World w1;
    const float half = std::max(box.half_extents.x, box.half_extents.y);
    const auto a1 = w1.create_instance(handle);
    w1.set_world_transform(a1,
        glm::translate(glm::mat4(1.0f), glm::vec3(box.center.x + half, box.center.y + half, 0.0f)) *
        glm::scale(glm::mat4(1.0f), glm::vec3(0.1f)));
    w1.get(a1)->node_overrides[decal->root_node] =
        spun_about_up(*decal, decal->root_node, box.center);
    const auto p1 = w1.create_instance(handle);
    w1.set_world_transform(p1, glm::mat4(1.0f));
    const auto px_alone = render_world_top_down(w0, box);
    const auto px_after = render_world_top_down(w1, box);
    const std::size_t corner = differing_corner_texels(px_alone, px_after);
    std::fprintf(stderr, "[DecalRender] corner ship texels: %zu\n", corner);
    ASSERT_GT(corner, 50u)
        << "guard: the corner ship must be drawn in the corner or the test is vacuous";
    const Counts a = count_outside_corner(px_alone);
    const Counts b = count_outside_corner(px_after);

    EXPECT_EQ(b.red, a.red);
    EXPECT_DOUBLE_EQ(b.red_mean_row(), a.red_mean_row());
}

// The NORMAL correction: a bottom-facing decal (normal -Z) on a hull flipped
// 180 degrees about body +X. Seen from above, the posed surface faces +Z; only
// the rest-frame normal (-Z) passes the decal's facing test. A position-only
// correction would leave the posed normal and paint nothing.
TEST_F(DecalRenderTest, DecalNormalIsCorrectedForARotatedNode) {
    const renderer::Aabb box = plain_aabb();
    const std::uint8_t red[3] = {255, 0, 0};
    auto decal = cache->load(ambassador_nif(), ambassador_search(), {},
        {whole_hull(box, /*from_below=*/true, write_mask("red.png", red, red), "amb saucer:0")});
    ASSERT_EQ(decal->decals.size(), 1u);

    constexpr float kNarrowFov = 0.1f;
    const Counts rest_top = count_pixels(render_top_down(decal, box, false, kNarrowFov));
    ASSERT_LT(rest_top.red, 10) << "guard: the bottom decal must be hidden from above";

    scenegraph::World world;
    const auto iid = world.create_instance(
        reinterpret_cast<scenegraph::ModelHandle>(decal.get()));
    world.set_world_transform(iid, glm::mat4(1.0f));
    world.get(iid)->node_overrides[decal->root_node] =
        decal->nodes[decal->root_node].local_transform *
        glm::translate(glm::mat4(1.0f), box.center) *
        glm::rotate(glm::mat4(1.0f), glm::radians(180.0f), glm::vec3(1, 0, 0)) *
        glm::translate(glm::mat4(1.0f), -box.center);
    const Counts flipped = count_pixels(render_world_top_down(world, box, false, kNarrowFov));
    std::fprintf(stderr, "[DecalRender] flipped bottom decal from above: red=%d\n", flipped.red);

    EXPECT_GT(flipped.red, 200) << "the decal normal was not rest-corrected";
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

TEST_F(DecalRenderTest, SeveredNodeTakesItsDecalToTheChunk) {
    const renderer::Aabb box = plain_aabb();
    const std::uint8_t red[3] = {255, 0, 0};
    auto decal = cache->load(ambassador_nif(), ambassador_search(), {},
        {right_half_saucer(box, write_mask("red.png", red, red))});
    const auto handle = reinterpret_cast<scenegraph::ModelHandle>(decal.get());

    const int saucer = part_of_shape(*decal, "amb saucer:0");
    ASSERT_GE(saucer, 0) << "saucer part node not found";
    int scene_root = decal->nodes[saucer].parent_index;
    ASSERT_GE(scene_root, 0);

    const Counts plain = count_pixels(render_top_down(decal, box));
    ASSERT_GT(plain.red, 200);

    // The ship with the saucer severed (what set_instance_node_hidden writes).
    scenegraph::World w0;
    const auto ship = w0.create_instance(handle);
    w0.set_world_transform(ship, glm::mat4(1.0f));
    w0.get(ship)->node_overrides[saucer] = glm::mat4(0.0f);
    const Counts severed = count_pixels(render_world_top_down(w0, box));
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    EXPECT_EQ(severed.red, 0) << "the severed part's decal stayed on the ship";

    // The chunk: every OTHER part hidden.
    scenegraph::World w1;
    const auto chunk = w1.create_instance(handle);
    w1.set_world_transform(chunk, glm::mat4(1.0f));
    for (int child : decal->nodes[scene_root].children)
        if (child != saucer) w1.get(chunk)->node_overrides[child] = glm::mat4(0.0f);
    const Counts chunked = count_pixels(render_world_top_down(w1, box));
    std::fprintf(stderr, "[DecalRender] severed: ship=%d chunk=%d plain=%d\n",
                 severed.red, chunked.red, plain.red);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    EXPECT_NEAR(chunked.red, plain.red, 0.05 * plain.red);
}
