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
                            const pd::SampleUniforms* pd_u, float time = 0.0f) {
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
                             0.0f, decals, glow, time, 1.0f, {}, carve, {}, 0,
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

    // Overwrite every mip of the model's base texture(s) with one solid
    // RGBA8 colour (the cache is per-test, so the next SetUp reloads it).
    void paint_base(unsigned char r, unsigned char g, unsigned char b) {
        for (const auto& mat : geo->materials) {
            const int ti = mat.stages[static_cast<std::size_t>(
                assets::Material::StageSlot::Base)].texture_index;
            if (ti < 0) continue;
            glBindTexture(GL_TEXTURE_2D, geo->textures[static_cast<std::size_t>(ti)].id());
            for (int lvl = 0; lvl < 16; ++lvl) {
                GLint tw = 0, th = 0;
                glGetTexLevelParameteriv(GL_TEXTURE_2D, lvl, GL_TEXTURE_WIDTH, &tw);
                glGetTexLevelParameteriv(GL_TEXTURE_2D, lvl, GL_TEXTURE_HEIGHT, &th);
                if (tw <= 0 || th <= 0) break;
                std::vector<unsigned char> px(static_cast<std::size_t>(tw * th * 4));
                for (std::size_t i = 0; i < px.size(); i += 4) {
                    px[i] = r; px[i + 1] = g; px[i + 2] = b; px[i + 3] = 255;
                }
                glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
                glTexSubImage2D(GL_TEXTURE_2D, lvl, 0, 0, tw, th, GL_RGBA, GL_UNSIGNED_BYTE,
                                px.data());
            }
        }
        glBindTexture(GL_TEXTURE_2D, 0);
    }

    // A clipmap atlas (ClipmapAtlas's format) whose every texel is `texel`.
    static GLuint const_atlas(int levels, glm::vec4 texel) {
        const int h = 1026 * levels;
        std::vector<float> px(static_cast<std::size_t>(1024 * h * 4));
        for (std::size_t i = 0; i < px.size(); i += 4) {
            px[i] = texel.x; px[i + 1] = texel.y; px[i + 2] = texel.z; px[i + 3] = texel.w;
        }
        GLuint t = 0;
        glGenTextures(1, &t);
        glBindTexture(GL_TEXTURE_2D, t);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, 1024, h, 0, GL_RGBA, GL_FLOAT, px.data());
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glBindTexture(GL_TEXTURE_2D, 0);
        return t;
    }

    // The sun straight overhead at dir: with a nadir camera the centre pixel
    // sits exactly in the sun's mirror direction off the geometric normal.
    renderer::Lighting sun_mirror(glm::vec3 dir) const {
        renderer::Lighting l;
        l.ambient = glm::vec3(0.05f);
        l.directional_count = 1;
        l.directional_dir_ws[0] = pd::make_anchor(glm::normalize(dir), R()).A;
        l.directional_color[0] = glm::vec3(1.0f);
        return l;
    }

    // A sun grazing the surface at dir (~8.5 deg above the horizon, from E).
    renderer::Lighting sun_grazing(glm::vec3 dir) const {
        const pd::Anchor a = pd::make_anchor(glm::normalize(dir), R());
        renderer::Lighting l;
        l.ambient = glm::vec3(0.05f);
        l.directional_count = 1;
        l.directional_dir_ws[0] = glm::normalize(0.15f * a.A + a.E);
        l.directional_color[0] = glm::vec3(1.0f);
        return l;
    }

    static std::size_t count_diffs(const std::vector<float>& a, const std::vector<float>& b) {
        std::size_t n = 0;
        for (std::size_t i = 0; i < a.size() && i < b.size(); ++i)
            if (a[i] != b[i]) ++n;
        return n;
    }

    static double mean_lum(const std::vector<float>& px) {
        double s = 0.0;
        for (int y = 0; y < kSize; ++y)
            for (int x = 0; x < kSize; ++x) s += lum(px, x, y);
        return s / double(kSize * kSize);
    }

    // sRGB byte -> linear (engine/planets/atmosphere.py srgb_hex_to_linear).
    static float srgb_lin(unsigned char v) {
        const float c = float(v) / 255.0f;
        return c <= 0.04045f ? c / 12.92f : std::pow((c + 0.055f) / 1.055f, 2.4f);
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
            // R8: at the pole BC's u texel shrinks to nothing on screen while
            // v stays hugely magnified; the weight must follow the COARSER
            // axis, so the nadir (the pole itself) gets relief too.
            if (std::string(v.name) == "pole") {
                EXPECT_TRUE(differs(plain, px, kSize / 2, kSize / 2))
                    << "no relief at the pole nadir";
            }
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

// Spec §6 water: a texel whose BC colour matches the ocean key is water --
// no land bump, and a GGX sun glint (f0 0.02) in the mirror direction.
TEST_F(PlanetSurfaceDrawTest, WaterMaskFollowsOceanKey) {
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    paint_base(0x40, 0x58, 0x70);
    const glm::vec3 dir = glm::normalize(glm::vec3(0.3f, -0.5f, 0.8f));
    Detail d = bake(dir, 2);
    d.u.has_ocean = true;
    d.u.ocean = glm::vec3(srgb_lin(0x40), srgb_lin(0x58), srgb_lin(0x70));
    const auto cam = nadir_cam(dir, 150.0f);

    // Bump suppressed: strength 1 renders exactly as strength 0.
    pd::SampleUniforms flat = d.u;
    flat.strength = 0.0f;
    const auto bumped = draw(p->planet_shader(), cam, sun_over(dir), hdr, &d.u);
    const auto ref = draw(p->planet_shader(), cam, sun_over(dir), hdr, &flat);
    EXPECT_EQ(count_diffs(bumped, ref), 0u) << "water still carries the land bump";
    // ...whereas the same planet without the key IS bumped (non-vacuous).
    pd::SampleUniforms land = d.u, land_flat = flat;
    land.has_ocean = land_flat.has_ocean = false;
    const auto lb = draw(p->planet_shader(), cam, sun_over(dir), hdr, &land);
    const auto lf = draw(p->planet_shader(), cam, sun_over(dir), hdr, &land_flat);
    EXPECT_GT(count_diffs(lb, lf), 0u);

    // Glint: the mirror-direction sun brightens the centre over land.
    const auto water = draw(p->planet_shader(), cam, sun_mirror(dir), hdr, &d.u);
    const auto dry = draw(p->planet_shader(), cam, sun_mirror(dir), hdr, &land);
    const float lw = lum(water, kSize / 2, kSize / 2), ld = lum(dry, kSize / 2, kSize / 2);
    EXPECT_GT(lw, ld * 1.1f) << "no sun glint on water: " << lw << " vs land " << ld;
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// type: ocean is all water whatever the texture -- even over a relief atlas.
TEST_F(PlanetSurfaceDrawTest, OceanTypeIsAllWater) {
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    const glm::vec3 dir = glm::normalize(glm::vec3(0.3f, -0.5f, 0.8f));
    Detail d = bake(dir, 2);   // Rocky relief in the atlas, Rocky roughness
    d.u.type = static_cast<int>(pd::SurfaceType::Ocean);
    const auto cam = nadir_cam(dir, 150.0f);
    pd::SampleUniforms flat = d.u;
    flat.strength = 0.0f;
    const auto a = draw(p->planet_shader(), cam, sun_over(dir), hdr, &d.u);
    const auto b = draw(p->planet_shader(), cam, sun_over(dir), hdr, &flat);
    EXPECT_EQ(count_diffs(a, b), 0u) << "an ocean planet was bumped";
    const pd::SampleUniforms off{};
    const auto water = draw(p->planet_shader(), cam, sun_mirror(dir), hdr, &d.u);
    const auto plain = draw(p->planet_shader(), cam, sun_mirror(dir), hdr, &off);
    const float lw = lum(water, kSize / 2, kSize / 2), lp = lum(plain, kSize / 2, kSize / 2);
    EXPECT_GT(lw, lp * 1.1f) << "no glint on an ocean planet: " << lw << " vs " << lp;
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// Gas: albedo only (no bump, whatever the bump dial), advected by game time;
// rate 0 is static.
TEST_F(PlanetSurfaceDrawTest, GasHasNoBumpAndAnimates) {
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    const glm::vec3 dir = glm::normalize(glm::vec3(0.3f, -0.5f, 0.8f));
    pd::TypeParams tp = pd::default_params(pd::SurfaceType::Gas);
    tp.bump = 0.35f;   // a non-zero bump dial: gas must still not bump
    Detail d = bake(dir, 2, pd::SurfaceType::Gas, tp);
    d.u.seed = 7u;
    const auto cam = nadir_cam(dir, 150.0f);
    const auto l = sun_grazing(dir);

    pd::SampleUniforms strong = d.u, flat = d.u;
    strong.strength = 4.0f;
    flat.strength = 0.0f;
    const auto a = draw(p->planet_shader(), cam, l, hdr, &strong, 2.0f);
    const auto b = draw(p->planet_shader(), cam, l, hdr, &flat, 2.0f);
    EXPECT_EQ(count_diffs(a, b), 0u) << "the gas giant was bumped";

    const auto t0 = draw(p->planet_shader(), cam, l, hdr, &d.u, 0.0f);
    const auto t5 = draw(p->planet_shader(), cam, l, hdr, &d.u, 5.0f);
    EXPECT_GT(count_diffs(t0, t5), 1000u) << "the gas giant does not animate";

    pd::SampleUniforms still = d.u;
    still.params.gas_rate_gups = 0.0f;
    const auto s0 = draw(p->planet_shader(), cam, l, hdr, &still, 0.0f);
    const auto s5 = draw(p->planet_shader(), cam, l, hdr, &still, 5.0f);
    EXPECT_EQ(count_diffs(s0, s5), 0u) << "gas rate 0 must be static";
    const pd::SampleUniforms off{};
    const auto plain = draw(p->planet_shader(), cam, l, hdr, &off, 0.0f);
    EXPECT_GT(count_diffs(s0, plain), 0u) << "static gas detail never applied";
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// Ice: the A channel is the crack mask -- cracks darken (and blue-shift).
TEST_F(PlanetSurfaceDrawTest, IceCracksDarken) {
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    const glm::vec3 dir = glm::normalize(glm::vec3(0.3f, -0.5f, 0.8f));
    Detail d = bake(dir, 1, pd::SurfaceType::Ice, pd::default_params(pd::SurfaceType::Ice));
    const GLuint cracked = const_atlas(1, glm::vec4(0.0f, 0.0f, 0.0f, 1.0f));
    const GLuint whole = const_atlas(1, glm::vec4(0.0f));
    const auto cam = nadir_cam(dir, 150.0f);
    pd::SampleUniforms uc = d.u, uw = d.u;
    uc.atlas = cracked;
    uw.atlas = whole;
    const auto pc = draw(p->planet_shader(), cam, sun_over(dir), hdr, &uc);
    const auto pw = draw(p->planet_shader(), cam, sun_over(dir), hdr, &uw);
    glDeleteTextures(1, &cracked);
    glDeleteTextures(1, &whole);
    // Whole frame: darker on average (the single level covers only the
    // middle of the view, so the frame-wide ratio is diluted).
    EXPECT_LT(mean_lum(pc), mean_lum(pw)) << "cracks did not darken";
    // Centre, where the detail weight is full: the crack tint's luminance is
    // 0.2126*0.80 + 0.7152*0.86 + 0.0722 = 0.857.
    double lc = 0.0, lw = 0.0;
    for (int y = kSize / 2 - 16; y < kSize / 2 + 16; ++y)
        for (int x = kSize / 2 - 16; x < kSize / 2 + 16; ++x) {
            lc += lum(pc, x, y);
            lw += lum(pw, x, y);
        }
    EXPECT_GT(lw, 0.0);
    EXPECT_LT(lc, lw * 0.9) << "cracks did not darken the centre: " << lc << " vs " << lw;
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// Spec §6: the water mask exists only for entries with `ocean`. Without a
// key, a dialled-up coast sharpening must do nothing -- no pull toward the
// (black) default key, no lost bump, no glint -- on land AND ocean types.
TEST_F(PlanetSurfaceDrawTest, CoastSharpeningNeedsAnOceanKey) {
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    const glm::vec3 dir = glm::normalize(glm::vec3(0.3f, -0.5f, 0.8f));
    const auto cam = nadir_cam(dir, 150.0f);
    for (const auto t : {pd::SurfaceType::Rocky, pd::SurfaceType::Ocean}) {
        Detail d = bake(dir, 2);   // Rocky relief in the atlas
        d.u.type = static_cast<int>(t);
        d.u.has_ocean = false;
        pd::SampleUniforms dialled = d.u, plain = d.u;
        dialled.params.coast_k = 0.45f;
        plain.params.coast_k = 0.0f;
        for (const auto& l : {sun_over(dir), sun_mirror(dir)}) {
            const auto a = draw(p->planet_shader(), cam, l, hdr, &dialled);
            const auto b = draw(p->planet_shader(), cam, l, hdr, &plain);
            EXPECT_EQ(count_diffs(a, b), 0u)
                << "type " << int(t) << ": keyless coast sharpening changed the render";
        }
    }
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

// FiniteEverywhere, for every surface type (water on, gas mid-animation).
TEST_F(PlanetSurfaceDrawTest, FiniteEverywhereEveryType) {
    renderer::HdrTarget hdr;
    hdr.resize(kSize, kSize);
    const glm::vec3 side = glm::normalize(glm::vec3(0.3f, -0.5f, 0.8f));
    struct View { const char* name; glm::vec3 dir; scenegraph::Camera cam; };
    std::vector<View> views;
    views.push_back({"outside", side, nadir_cam(side, 2.0f * R())});
    {
        auto cam = nadir_cam(side, 150.0f);
        const pd::Anchor a = pd::make_anchor(side, R());
        cam.target = cam.eye + a.E * 1000.0f - a.A * 60.0f;
        cam.up = a.A;
        views.push_back({"limb", side, cam});
    }
    views.push_back({"pole", glm::vec3(0, 0, 1), nadir_cam(glm::vec3(0, 0, 1), 150.0f)});
    views.push_back({"u-seam", glm::vec3(0, 1, 0), nadir_cam(glm::vec3(0, 1, 0), 150.0f)});
    const pd::SurfaceType types[] = {pd::SurfaceType::Rocky, pd::SurfaceType::Desert,
                                     pd::SurfaceType::Ice, pd::SurfaceType::Gas,
                                     pd::SurfaceType::Ocean};
    renderer::NonfiniteProbe probe;
    for (const auto t : types) {
        for (const auto& v : views) {
            Detail d = bake(v.dir, pd::level_count_for(R(), 0.1f), t, pd::default_params(t));
            d.u.has_ocean = true;   // a key near the IcePlanet's own blues
            d.u.ocean = glm::vec3(srgb_lin(0x90), srgb_lin(0xA8), srgb_lin(0xC0));
            d.u.ocean_tol = 0.3f;
            d.u.seed = 12345u;
            const renderer::Lighting suns[2] = {sun_over(v.dir), sun_mirror(v.dir)};
            for (const auto& l : suns) {
                const auto px = draw(p->planet_shader(), v.cam, l, hdr, &d.u, 13.7f);
                const auto& r = probe.run(hdr.color_texture(), kSize, kSize);
                EXPECT_FALSE(r.any) << int(t) << "/" << v.name << ": " << r.flagged_cells
                                    << " non-finite cell(s)";
                int nonfinite = 0, lit = 0;
                for (float f : px) {
                    if (!std::isfinite(f)) ++nonfinite;
                    else if (f > 0.0f) ++lit;
                }
                EXPECT_EQ(nonfinite, 0) << int(t) << "/" << v.name;
                EXPECT_GT(lit, 0) << int(t) << "/" << v.name << ": nothing drawn";
            }
        }
    }
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}

}  // namespace
