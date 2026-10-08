// native/tests/renderer/planet_surface_draw_test.cc
//
// The planet_ program (spec docs/superpowers/specs/2026-10-08-planet-surface-
// detail-design.md §5.4, §6): opaque.frag compiled with PLANET_SURFACE samples
// the clipmap atlas (unit 12) and applies land relief + albedo variation to
// the geosphere draw. Disabled, it draws what opaque_ draws.
//
// IcePlanet.NIF is drawn at world scale kScale, so the sphere is a ~3600 GU
// planet and a camera 150 GU up sees BC texels many pixels wide (detail on).
#include <gtest/gtest.h>

#include <renderer/frame.h>
#include <renderer/hdr_target.h>
#include <renderer/nonfinite_probe.h>
#include <renderer/pipeline.h>
#include <renderer/planet_clipmap_atlas.h>
#include <renderer/planet_clipmap_schedule.h>
#include <renderer/planet_detail_noise.h>
#include <renderer/planet_detail_uniforms.h>
#include <renderer/scuff_texture.h>
#include <renderer/shader.h>
#include <renderer/window.h>

#include <glad/glad.h>

#include <glm/gtc/matrix_transform.hpp>

#include <scenegraph/camera.h>
#include <scenegraph/world.h>

#include <assets/cache.h>
#include <assets/model.h>

#include <algorithm>
#include <climits>
#include <cmath>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

#include "support/content_root.h"

namespace {

namespace pd = renderer::planet_detail;
using test_support::game_root;

const std::filesystem::path kEnvDir =
    game_root() / "data" / "Models" / "Environment";
const std::filesystem::path kIcePlanetNif = kEnvDir / "IcePlanet.NIF";

constexpr int kSize = 256;
constexpr float kScale = 40.0f;   // IcePlanet r 90.0099 -> R ~3600 GU

// One baked clipmap plus the uniforms that sample it.
struct Detail {
    std::unique_ptr<pd::ClipmapAtlas> atlas;
    pd::SampleUniforms u;
};

class PlanetSurfaceDrawTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::unique_ptr<assets::AssetCache> cache;
    assets::ModelHandle geo;
    GLuint white_ = 0, black_ = 0;

    void SetUp() override {
        if (!std::filesystem::is_regular_file(kIcePlanetNif)) {
            GTEST_SKIP() << "BC asset not available at " << kIcePlanetNif;
        }
        try {
            w = std::make_unique<renderer::Window>(kSize, kSize, "planet-surface-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        // keep_cpu_data, as the production host cache: apply_geosphere's
        // sphere gate reads the source MeshCpu (see geosphere_draw_test.cc).
        assets::AssetCache::Config cfg;
        cfg.keep_cpu_data = true;
        cache = std::make_unique<assets::AssetCache>(cfg);
        geo = cache->load(kIcePlanetNif, std::vector<std::filesystem::path>{kEnvDir},
                          {}, {}, 1.0f, /*geosphere=*/true);
        ASSERT_TRUE(geo->sphere_map.has_value());
        white_ = make_1x1(255);
        black_ = make_1x1(0);
    }

    void TearDown() override {
        if (!w) return;
        glDeleteTextures(1, &white_);
        glDeleteTextures(1, &black_);
        renderer::reset_damage_decal_texture();
        renderer::reset_scuff_normal_texture();
        renderer::reset_decal_mask_sampler();
        renderer::reset_model_radius_cache();
    }

    static GLuint make_1x1(unsigned char v) {
        GLuint t = 0;
        const unsigned char px[4] = {v, v, v, 255};
        glGenTextures(1, &t);
        glBindTexture(GL_TEXTURE_2D, t);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glBindTexture(GL_TEXTURE_2D, 0);
        return t;
    }

    static glm::mat4 world() { return glm::scale(glm::mat4(1.0f), glm::vec3(kScale)); }
    float R() const { return geo->sphere_map->radius * kScale; }
    glm::vec3 centre_ws() const { return geo->sphere_map->center_body * kScale; }

    // Camera `alt` GU above the surface along planet-local direction `dir`,
    // looking straight down, screen-right = the anchor's E, screen-up = N.
    scenegraph::Camera nadir_cam(glm::vec3 dir, float alt) const {
        dir = glm::normalize(dir);
        const pd::Anchor a = pd::make_anchor(dir, R());
        scenegraph::Camera cam;
        cam.eye = centre_ws() + dir * (R() + alt);
        cam.target = centre_ws();
        cam.up = a.N;
        cam.aspect = 1.0f;
        cam.near = std::max(0.1f, alt * 0.01f);
        cam.far = 1.0e6f;
        return cam;
    }

    // Oblique sun (~39 deg off the zenith at dir) so the bump shows.
    renderer::Lighting sun_over(glm::vec3 dir) const {
        const pd::Anchor a = pd::make_anchor(glm::normalize(dir), R());
        renderer::Lighting l;
        l.ambient = glm::vec3(0.05f);
        l.directional_count = 1;
        l.directional_dir_ws[0] = glm::normalize(a.A + 0.8f * a.E + 0.3f * a.N);
        l.directional_color[0] = glm::vec3(1.0f);
        return l;
    }

    // Bake every level (unbounded budget) around the nadir of `dir`.
    // `level_seeds` (one per level) bakes each level with its own seed, so the
    // levels hold DIFFERENT content; empty = one seed, one field (production).
    Detail bake(glm::vec3 dir, int levels,
                pd::SurfaceType type = pd::SurfaceType::Rocky,
                const pd::TypeParams& tp = pd::default_params(pd::SurfaceType::Rocky),
                const std::vector<std::uint32_t>& level_seeds = {}) const {
        Detail d;
        const pd::Anchor a = pd::make_anchor(glm::normalize(dir), R());
        std::vector<int> oct;
        for (int L = 0; L < levels; ++L)
            oct.push_back(pd::octaves_for_texel(tp, 1.0f, 0.1f * std::exp2(float(L))));
        pd::ClipmapSchedule sch(0.1f, oct);
        std::vector<pd::BakeRect> rects;
        sch.update(glm::vec2(0.0f), LLONG_MAX, rects);
        d.atlas = std::make_unique<pd::ClipmapAtlas>(levels);
        if (level_seeds.empty()) {
            d.atlas->bake(rects, pd::BakeParams{a, type, tp, 1.0f, 7u, 0.1f, oct});
        } else {
            for (int L = 0; L < levels; ++L) {
                std::vector<pd::BakeRect> mine;
                for (const auto& r : rects)
                    if (r.level == L) mine.push_back(r);
                d.atlas->bake(mine, pd::BakeParams{a, type, tp, 1.0f,
                                                   level_seeds[static_cast<std::size_t>(L)],
                                                   0.1f, oct});
            }
        }
        d.u.enabled = true;
        d.u.atlas = d.atlas->texture();
        d.u.levels = levels;
        d.u.ts0 = 0.1f;
        for (int L = 0; L < levels; ++L) {
            const pd::Rect& v = sch.valid(L);
            d.u.valid[static_cast<std::size_t>(L)] =
                glm::vec4(float(v.x0), float(v.y0), float(v.x1), float(v.y1));
        }
        d.u.A = a.A;
        d.u.E = a.E;
        d.u.N = a.N;
        d.u.R = R();
        d.u.scale_local = kScale;
        d.u.type = static_cast<int>(type);
        d.u.params = tp;
        return d;
    }

    // One planet draw through `prog`; `pd_u` (planet_ only) is applied first.
    std::vector<float> draw(renderer::Shader& prog, const scenegraph::Camera& cam,
                            const renderer::Lighting& l, renderer::HdrTarget& hdr,
                            const pd::SampleUniforms* pd_u) {
        hdr.bind();
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        prog.use();
        prog.set_mat4("u_view", cam.view_matrix());
        prog.set_mat4("u_proj", cam.proj_matrix());
        prog.set_vec3("u_camera_pos_ws", cam.eye);
        renderer::set_ambient_uniforms(prog, l, 1.0f);
        prog.set_int("u_dir_light_count", l.directional_count);
        prog.set_vec3_array("u_dir_light_dir_ws", l.directional_dir_ws, l.directional_count);
        prog.set_vec3_array("u_dir_light_color", l.directional_color, l.directional_count);
        if (pd_u) pd::apply(prog, *pd_u);
        scenegraph::DamageDecalRing decals;
        std::array<scenegraph::Instance::GlowRegion, scenegraph::Instance::kMaxGlowRegions> glow{};
        scenegraph::HullCarveField carve;
        renderer::draw_model(*geo, world(), prog, p->skinned_shader(), white_, black_,
                             0.0f, decals, glow, 0.0f, 1.0f, {}, carve, {}, 0,
                             nullptr, false, nullptr, nullptr, nullptr,
                             renderer::geosphere_level_for(*geo, world(), cam));
        std::vector<float> px(static_cast<std::size_t>(kSize * kSize * 4), 0.0f);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, hdr.fbo());
        glReadPixels(0, 0, kSize, kSize, GL_RGBA, GL_FLOAT, px.data());
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        return px;
    }

    static float lum(const std::vector<float>& px, int x, int y) {
        const std::size_t i = static_cast<std::size_t>((y * kSize + x) * 4);
        return 0.2126f * px[i] + 0.7152f * px[i + 1] + 0.0722f * px[i + 2];
    }

    static bool differs(const std::vector<float>& a, const std::vector<float>& b, int x, int y) {
        const std::size_t i = static_cast<std::size_t>((y * kSize + x) * 4);
        for (int c = 0; c < 4; ++c)
            if (a[i + c] != b[i + c]) return true;
        return false;
    }

    // One fp16 ulp at |v| (RGBA16F target): 2^(floor(log2|v|) - 10).
    static float fp16_ulp(float v) {
        const float a = std::max(std::fabs(v), 6.103515625e-05f);   // smallest normal
        return std::exp2(std::floor(std::log2(a)) - 10.0f);
    }
};

// R5: the define reaches planet_ only.
TEST_F(PlanetSurfaceDrawTest, ProgramCompilesAndOthersUnchanged) {
    const GLuint planet = p->planet_shader().program();
    GLint linked = GL_FALSE;
    glGetProgramiv(planet, GL_LINK_STATUS, &linked);
    EXPECT_EQ(linked, GL_TRUE);
    EXPECT_NE(glGetUniformLocation(planet, "u_pd_enabled"), -1)
        << "planet_ was not compiled with PLANET_SURFACE";
    for (renderer::Shader* s : {&p->opaque_shader(), &p->skinned_shader(),
                                &p->minor_shader(), &p->impostor_shader()}) {
        EXPECT_EQ(glGetUniformLocation(s->program(), "u_pd_enabled"), -1)
            << "PLANET_SURFACE leaked into program " << s->program();
    }
    const GLint atlas_loc = glGetUniformLocation(planet, "u_pd_atlas");
    ASSERT_NE(atlas_loc, -1);
    GLint unit = -1;
    glGetUniformiv(planet, atlas_loc, &unit);
    EXPECT_EQ(unit, 12) << "the clipmap atlas lives on texture unit 12";
}

TEST_F(PlanetSurfaceDrawTest, DisabledMatchesOpaqueExactly) {
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    const glm::vec3 dir = glm::normalize(glm::vec3(0.3f, -0.5f, 0.8f));
    Detail d = bake(dir, 2);
    const auto l = sun_over(dir);
    // A nadir view (detail would be on) and a whole-disc view.
    const scenegraph::Camera cams[2] = {nadir_cam(dir, 150.0f), nadir_cam(dir, 2.0f * R())};
    for (const auto& cam : cams) {
        // Dirty planet_ first: a stale enabled block must not survive a disable.
        draw(p->planet_shader(), cam, l, hdr, &d.u);
        const auto ref = draw(p->opaque_shader(), cam, l, hdr, nullptr);
        const pd::SampleUniforms off{};
        const auto got = draw(p->planet_shader(), cam, l, hdr, &off);
        ASSERT_EQ(ref.size(), got.size());
        std::size_t exact_diffs = 0, over_ulp = 0;
        for (std::size_t i = 0; i < ref.size(); ++i) {
            if (ref[i] == got[i]) continue;
            ++exact_diffs;
            if (std::fabs(ref[i] - got[i]) > fp16_ulp(ref[i])) ++over_ulp;
        }
        EXPECT_EQ(over_ulp, 0u) << exact_diffs << " channel(s) differ, " << over_ulp
                                << " by more than one fp16 ulp";
        EXPECT_EQ(exact_diffs, 0u) << "R6 tolerance in use: record the measured diff";
        EXPECT_GT(lum(ref, kSize / 2, kSize / 2), 0.0f) << "the planet must be in view";
    }
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(PlanetSurfaceDrawTest, EnabledChangesNearNadirOnly) {
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    const glm::vec3 dir = glm::normalize(glm::vec3(0.3f, -0.5f, 0.8f));
    Detail d = bake(dir, 2);
    const auto l = sun_over(dir);
    const pd::SampleUniforms off{};

    const auto near_cam = nadir_cam(dir, 150.0f);
    const auto a = draw(p->planet_shader(), near_cam, l, hdr, &off);
    const auto b = draw(p->planet_shader(), near_cam, l, hdr, &d.u);
    int changed = 0, total = 0;
    for (int y = kSize / 2 - 32; y < kSize / 2 + 32; ++y)
        for (int x = kSize / 2 - 32; x < kSize / 2 + 32; ++x, ++total)
            if (differs(a, b, x, y)) ++changed;
    EXPECT_GT(changed, total / 2) << "only " << changed << "/" << total
                                  << " nadir pixels changed with detail on";

    // 50 R away a BC texel is far below 2 px: detail weight 0, identical.
    // Every level claims a huge valid rect here, so coverage cannot be what
    // holds the far frame at zero (a far pixel lies outside the real rects
    // and would pass vacuously): only the px-per-BC-texel weight can.
    pd::SampleUniforms far_u = d.u;
    far_u.valid[0] = far_u.valid[1] = glm::vec4(-1e7f, -1e7f, 1e7f, 1e7f);
    const auto far_cam = nadir_cam(dir, 49.0f * R());
    const auto fa = draw(p->planet_shader(), far_cam, l, hdr, &off);
    const auto fb = draw(p->planet_shader(), far_cam, l, hdr, &far_u);
    EXPECT_GT(lum(fa, kSize / 2, kSize / 2), 0.0f) << "the far planet must be in view";
    EXPECT_TRUE(fa == fb) << "a far planet changed with detail enabled";
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(PlanetSurfaceDrawTest, FiniteEverywhere) {
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    struct View { const char* name; glm::vec3 dir; scenegraph::Camera cam; };
    const glm::vec3 side = glm::normalize(glm::vec3(0.3f, -0.5f, 0.8f));
    std::vector<View> views;
    views.push_back({"outside", side, nadir_cam(side, 2.0f * R())});
    {   // the limb: 150 GU up, looking along the surface toward the horizon
        auto cam = nadir_cam(side, 150.0f);
        const pd::Anchor a = pd::make_anchor(side, R());
        cam.target = cam.eye + a.E * 1000.0f - a.A * 60.0f;
        cam.up = a.A;
        views.push_back({"limb", side, cam});
    }
    views.push_back({"pole", glm::vec3(0, 0, 1), nadir_cam(glm::vec3(0, 0, 1), 150.0f)});
    // BC's u seam: u = fract(lon/2pi + 0.75) wraps at lon = +90 deg (+Y).
    views.push_back({"u-seam", glm::vec3(0, 1, 0), nadir_cam(glm::vec3(0, 1, 0), 150.0f)});

    renderer::NonfiniteProbe probe;
    for (const auto& v : views) {
        Detail d = bake(v.dir, pd::level_count_for(R(), 0.1f));
        const auto px = draw(p->planet_shader(), v.cam, sun_over(v.dir), hdr, &d.u);
        const auto& r = probe.run(hdr.color_texture(), kSize, kSize);
        EXPECT_FALSE(r.any) << v.name << ": " << r.flagged_cells << " non-finite cell(s)";
        int nonfinite = 0, lit = 0;
        for (float f : px) {
            if (!std::isfinite(f)) ++nonfinite;
            else if (f > 0.0f) ++lit;
        }
        EXPECT_EQ(nonfinite, 0) << v.name;
        EXPECT_GT(lit, 0) << v.name << ": nothing drawn";
        if (std::string(v.name) != "outside") {   // detail must really be on here
            const pd::SampleUniforms off{};
            const auto plain = draw(p->planet_shader(), v.cam, sun_over(v.dir), hdr, &off);
            EXPECT_FALSE(plain == px) << v.name << ": detail never applied";
        }
    }
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

TEST_F(PlanetSurfaceDrawTest, NoSeamAcrossLevelBand) {
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    const glm::vec3 dir = glm::normalize(glm::vec3(0.3f, -0.5f, 0.8f));
    // A smooth field and a DIFFERENT seed per level, so a hard level switch is
    // a visible step. Ice, not Rocky: Rocky is always ridged, and a ridge
    // crest flips the gradient -- a real step in the bump that would read as
    // a seam. With production content (one field, every octave) pixel-scale
    // relief dominates the adjacent-pixel steps and a hard seam is lost in
    // it: MEASURED with the transition band removed, seam 0.147 vs inside
    // 0.375 -- passing. Here, MEASURED: seam 0.0013 vs inside 0.0018 with the
    // band; with it removed, seam 0.0074 vs inside 0.0014 -- failing.
    pd::TypeParams tp = pd::default_params(pd::SurfaceType::Ice);
    tp.base_wavelength_gu = 20.0f;
    tp.max_octaves = 1;
    tp.amplitude = 1.0f;
    tp.bump = 0.35f;
    Detail d = bake(dir, 2, pd::SurfaceType::Ice, tp, {7u, 1234u});
    // Level 0 valid only on a 200-texel square whose LEFT edge (abs x -50,
    // plane x -5 GU) crosses the screen's centre row; level 1 is complete.
    d.u.valid[0] = glm::vec4(-50.0f, -100.0f, 150.0f, 100.0f);
    const auto cam = nadir_cam(dir, 20.0f);   // a nadir pixel ~0.09 GU: level 0
    const auto px = draw(p->planet_shader(), cam, sun_over(dir), hdr, &d.u);

    const pd::Anchor a = pd::make_anchor(dir, R());
    const glm::vec3 edge_ws = centre_ws() + pd::from_plane(a, glm::vec2(-5.0f, 0.0f));
    const glm::vec3 sp = glm::project(edge_ws, cam.view_matrix(), cam.proj_matrix(),
                                      glm::vec4(0, 0, kSize, kSize));
    const int ex = static_cast<int>(std::lround(sp.x));
    const int y = static_cast<int>(std::lround(sp.y));
    ASSERT_GT(ex, 20);
    ASSERT_LT(ex, kSize - 60);

    float seam = 0.0f, inside = 0.0f;
    for (int x = 1; x < kSize - 1; ++x) {
        const float step = std::fabs(lum(px, x + 1, y) - lum(px, x, y));
        if (std::abs(x - ex) <= 4) seam = std::max(seam, step);
        else if (x > ex + 16) inside = std::max(inside, step);
    }
    ASSERT_GT(inside, 0.0f) << "no detail inside level 0";
    EXPECT_LE(seam, 1.5f * inside) << "seam step " << seam << " vs inside " << inside
                                   << " at column " << ex;
}

}  // namespace
