// native/tests/renderer/impostor_blend_gl_test.cc
//
// Rock impostors blend between baked views (rock-blend, 2026-10-03): a
// tumbling billboard is a SMOOTH, CLOSED loop -- no snap to another baked
// view, and a full turn lands back on the first frame. Plus the mesh <->
// billboard hand-off, measured on a real catalogue rock drawn the way the
// near band draws it (MinorPass mesh, FarPass billboard, same lighting).
//
// The synthetic atlas is a lumpy-coloured ELLIPSOID rasterised analytically
// with the bake's own view basis and screen mapping (as far_pass_test.cc's
// sphere atlas), so its silhouette differs per view: the loop test sees
// both picture and coverage changes.

#include <gtest/gtest.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <renderer/far_field.h>
#include <renderer/far_pass.h>
#include <renderer/frame.h>
#include <renderer/minor_field.h>
#include <renderer/minor_pass.h>
#include <renderer/pipeline.h>
#include <renderer/scuff_texture.h>
#include <renderer/window.h>

#include <assets/cache.h>
#include <assets/model.h>
#include <assets/texture.h>

#include <scenegraph/camera.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include "rock_scenario.h"
#include "support/content_root.h"

namespace {

namespace far = renderer::far;
namespace minors = renderer::minors;

constexpr int kW = 128;
constexpr int kH = 128;

// The bake's view directions and grid, as the catalogue ships them.
int test_grid() { return 8; }
std::vector<glm::vec3> test_dirs() { return rock_scenario::view_dirs64(); }

struct Atlas {
    assets::Image albedo;
    assets::Image normal;
};

// An ellipsoid with semi-axes `axes` (glTF frame, the largest 1, so its bound
// radius is 1) rasterised into a grid x grid atlas of `view_size` cells, laid
// out as rockgen's bake: view v in cell (v % grid, v / grid), half extent
// 1.02, screen y DOWN, normal = (n.right, n.up, n.dir) * 0.5 + 0.5.
Atlas ellipsoid_atlas(const std::vector<glm::vec3>& dirs, int grid, int view_size, glm::vec3 axes) {
    const int canvas = grid * view_size;
    Atlas a;
    for (assets::Image* img : {&a.albedo, &a.normal}) {
        img->width = img->height = static_cast<std::uint32_t>(canvas);
        img->format = assets::Image::Format::RGBA8;
        img->pixels.assign(static_cast<std::size_t>(canvas) * canvas * 4, 0);
    }
    const float half = 1.02f;
    for (int view = 0; view < grid * grid; ++view) {
        const far::ViewBasis b = far::make_view_basis(dirs[static_cast<std::size_t>(view)]);
        const int ox = (view % grid) * view_size, oy = (view / grid) * view_size;
        const glm::vec3 e = b.dir / axes;
        for (int py = 0; py < view_size; ++py)
            for (int px = 0; px < view_size; ++px) {
                const float sx = ((static_cast<float>(px) + 0.5f) / view_size * 2.0f - 1.0f) * half;
                const float sy = (1.0f - (static_cast<float>(py) + 0.5f) / view_size * 2.0f) * half;
                const glm::vec3 o = sx * b.right + sy * b.up;
                const glm::vec3 q = o / axes;
                const float A = glm::dot(e, e), B = glm::dot(q, e), C = glm::dot(q, q) - 1.0f;
                const float disc = B * B - A * C;
                if (disc < 0.0f) continue;
                const float s = (-B + std::sqrt(disc)) / A;   // the hit nearest the camera
                const glm::vec3 p = o + s * b.dir;
                const glm::vec3 n = glm::normalize(p / (axes * axes));
                const glm::vec3 c(128.0f + 100.0f * std::sin(5.0f * p.x + 1.3f * p.y),
                                  128.0f + 100.0f * std::sin(4.0f * p.y - 2.1f * p.z + 0.7f),
                                  128.0f + 100.0f * std::sin(6.0f * p.z + 0.9f * p.x + 2.0f));
                const std::size_t i =
                    (static_cast<std::size_t>(oy + py) * canvas + static_cast<std::size_t>(ox + px)) * 4;
                for (int k = 0; k < 3; ++k)
                    a.albedo.pixels[i + static_cast<std::size_t>(k)] = static_cast<std::uint8_t>(c[k]);
                a.albedo.pixels[i + 3] = 255;
                const glm::vec3 nv(glm::dot(n, b.right), glm::dot(n, b.up), glm::dot(n, b.dir));
                for (int k = 0; k < 3; ++k)
                    a.normal.pixels[i + static_cast<std::size_t>(k)] = static_cast<std::uint8_t>(
                        glm::clamp(nv[k] * 0.5f + 0.5f, 0.0f, 1.0f) * 255.0f);
                a.normal.pixels[i + 3] = 255;
            }
    }
    return a;
}

double mean_abs_diff(const std::vector<unsigned char>& a, const std::vector<unsigned char>& b) {
    double s = 0.0;
    for (std::size_t i = 0; i < a.size(); i += 4)
        for (std::size_t k = 0; k < 3; ++k) s += std::abs(int(a[i + k]) - int(b[i + k]));
    return s / (static_cast<double>(kW) * kH * 3);
}

bool lit(const std::vector<unsigned char>& b, int i) {
    const std::size_t j = static_cast<std::size_t>(i) * 4;
    return b[j] + b[j + 1] + b[j + 2] > 0;
}

class ImpostorBlendGLTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "impostor-blend-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        pipeline = std::make_unique<renderer::Pipeline>();
    }

    void TearDown() override {
        if (!w) return;
        renderer::reset_damage_decal_texture();
        renderer::reset_scuff_normal_texture();
        renderer::reset_decal_mask_sampler();
        renderer::reset_model_radius_cache();
    }

    void clear_framebuffer() {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, kW, kH);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    }

    std::vector<unsigned char> read_frame() const {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        std::vector<unsigned char> buf(static_cast<std::size_t>(kW * kH * 4));
        glReadPixels(0, 0, kW, kH, GL_RGBA, GL_UNSIGNED_BYTE, buf.data());
        return buf;
    }

    std::vector<unsigned char> draw_board(renderer::FarPass& pass, const far::ImpostorGpu& g, int rock,
                                          const scenegraph::Camera& cam, const renderer::Lighting& l,
                                          float ambient_scale = 1.0f, float rim = 0.0f) {
        clear_framebuffer();
        far::ImpostorBin bin;
        bin.rock = rock;
        bin.items.push_back(g);
        pass.render_impostors({bin}, cam, *pipeline, l, ambient_scale, rim);
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
        return read_frame();
    }

public:
    void clear_framebuffer_public() { clear_framebuffer(); }
    std::vector<unsigned char> read_frame_public() const { return read_frame(); }
    std::vector<unsigned char> draw_board_public(renderer::FarPass& pass, const far::ImpostorGpu& g, int rock,
                                                 const scenegraph::Camera& cam, const renderer::Lighting& l) {
        return draw_board(pass, g, rock, cam, l);
    }
};

scenegraph::Camera camera(glm::vec3 eye, float fov_deg) {
    scenegraph::Camera c;
    c.eye = eye;
    c.target = glm::vec3(0.0f);
    c.up = glm::vec3(0.0f, 0.0f, 1.0f);
    c.fov_y_rad = glm::radians(fov_deg);
    c.aspect = 1.0f;
    c.near = 0.1f;
    c.far = 1000.0f;
    return c;
}

renderer::Lighting test_lighting() {
    renderer::Lighting l;
    l.ambient = glm::vec3(0.25f);
    l.directional_count = 1;
    l.directional_dir_ws[0] = glm::normalize(glm::vec3(0.5f, -0.6f, 0.62f));
    l.directional_color[0] = glm::vec3(1.0f, 0.97f, 0.92f);
    return l;
}

}  // namespace

// A billboard tumbling a full turn about a fixed axis in N steps: every step
// changes the picture by about the same amount (no snap to another view
// spikes the sequence), and frame N is frame 0 (the loop closes).
TEST_F(ImpostorBlendGLTest, AFullTurnIsASmoothClosedLoop) {
    const int grid = test_grid();
    const auto dirs = test_dirs();
    const Atlas atlas = ellipsoid_atlas(dirs, grid, 64, glm::vec3(1.0f, 0.7f, 0.55f));
    renderer::FarPass pass;
    pass.debug_set_atlas(0, atlas.albedo, atlas.normal);
    const far::ImpostorViews views = far::make_impostor_views(dirs);

    const scenegraph::Camera cam = camera(glm::vec3(0.0f, -4.0f, 0.8f), 35.0f);
    const renderer::Lighting l = test_lighting();
    const glm::vec3 axis = glm::normalize(glm::vec3(0.3f, 0.4f, 0.87f));
    const int N = 72;
    std::vector<std::vector<unsigned char>> frames;
    for (int k = 0; k <= N; ++k) {
        const float a = 6.2831853f * static_cast<float>(k) / N;
        const glm::mat3 R(glm::rotate(glm::mat4(1.0f), a, axis));
        frames.push_back(draw_board(pass, far::make_impostor(views, cam.eye, glm::vec3(0.0f), R, 1.0f, 0.0f),
                                    0, cam, l));
    }
    int on = 0;
    for (int i = 0; i < kW * kH; ++i) on += lit(frames[0], i);
    ASSERT_GT(on, kW * kH / 8) << "the rock is on screen";

    std::vector<double> d;
    for (int k = 0; k < N; ++k) d.push_back(mean_abs_diff(frames[static_cast<std::size_t>(k)],
                                                          frames[static_cast<std::size_t>(k) + 1]));
    std::vector<double> sorted = d;
    std::sort(sorted.begin(), sorted.end());
    const double median = sorted[sorted.size() / 2], worst = sorted.back();
    const double close = mean_abs_diff(frames.front(), frames.back());
    std::printf("[impostor blend] %d steps: step diff median %.3f max %.3f (x%.2f); frame N vs 0 %.4f\n",
                N, median, worst, worst / median, close);
    EXPECT_LE(worst, 2.0 * median) << "a step spikes: the picture snapped";
    EXPECT_LE(close, 0.02 * median) << "frame N is not frame 0: the loop does not close";
}

namespace {

struct HandoffStats {
    double diff = 0.0;   // mean |mesh - billboard| per channel over the union of silhouettes
    double iou = 0.0;    // silhouette intersection over union
};

// One catalogue rock (`id`, e.g. "majors/silicate_01") of radius `r` GU at the
// origin, seen from `dist` GU, drawn as the near band draws it at the
// mesh <-> billboard swap: a MinorPass mesh (lod0) and a FarPass billboard,
// same pose, same lighting. Averaged over `orientations` random poses.
HandoffStats measure_handoff(ImpostorBlendGLTest& t, renderer::Pipeline& pipeline, const std::string& id,
                             float r, float dist, int orientations) {
    namespace fs = std::filesystem;
    const fs::path dir = test_support::project_root() / "native" / "assets" / "rocks" / id;
    assets::AssetCache cache;
    const assets::ModelHandle lod0 = cache.load(dir / "lod0.gltf", dir);
    const auto handle = static_cast<std::uint64_t>(reinterpret_cast<std::uintptr_t>(lod0.get()));
    const minors::Fragment frag{handle, handle, 57.142857f};

    renderer::FarPass board;
    board.set_atlas_paths({{(dir / "impostor_base.png").string(), (dir / "impostor_normal.png").string()}});
    const far::ImpostorViews views = far::make_impostor_views(test_dirs());
    renderer::MinorPass mesh;

    const scenegraph::Camera cam = camera(glm::vec3(0.0f, -dist, 0.0f), 8.0f);
    const renderer::Lighting l = test_lighting();
    HandoffStats out;
    std::uint32_t seed = 977u;
    auto u = [&]() { seed = seed * 1664525u + 1013904223u; return (seed >> 8) / 16777216.0f; };
    for (int n = 0; n < orientations; ++n) {
        glm::vec3 axis(u() * 2 - 1, u() * 2 - 1, u() * 2 - 1);
        if (glm::length(axis) < 1e-3f) axis = glm::vec3(0, 0, 1);
        const glm::mat3 R(glm::rotate(glm::mat4(1.0f), u() * 6.2831853f, glm::normalize(axis)));

        const glm::mat3 rs = R * (r / frag.bound_radius_mu);
        minors::Bin bin;
        bin.family = 1001; bin.slot = 0; bin.lod = 0;
        minors::InstanceGpu g;   // rows of [R*s | t] (rock_near.cc)
        g.row0 = {rs[0][0], rs[1][0], rs[2][0], 0.0f};
        g.row1 = {rs[0][1], rs[1][1], rs[2][1], 0.0f};
        g.row2 = {rs[0][2], rs[1][2], rs[2][2], 0.0f};
        bin.items.push_back(g);
        t.clear_framebuffer_public();
        mesh.render([&](int, int) { return &frag; }, {bin}, cam, pipeline,
                    [](std::uint64_t h) { return reinterpret_cast<const assets::Model*>(static_cast<std::uintptr_t>(h)); },
                    l, 1.0f, 0.0f);
        const auto a = t.read_frame_public();
        const auto b = t.draw_board_public(board, far::make_impostor(views, cam.eye, glm::vec3(0.0f), R, r, 0.0f),
                                           0, cam, l);
        double s = 0.0;
        int uni = 0, both = 0;
        for (int i = 0; i < kW * kH; ++i) {
            const bool la = lit(a, i), lb = lit(b, i);
            if (!(la || lb)) continue;
            ++uni;
            both += la && lb;
            for (std::size_t k = 0; k < 3; ++k)
                s += std::abs(int(a[static_cast<std::size_t>(i) * 4 + k]) - int(b[static_cast<std::size_t>(i) * 4 + k]));
        }
        out.diff += s / (3.0 * std::max(1, uni));
        out.iou += static_cast<double>(both) / std::max(1, uni);
    }
    out.diff /= orientations;
    out.iou /= orientations;
    return out;
}

}  // namespace

// The hard mesh <-> billboard swap: at the swap
// distance the billboard should look like the mesh it replaces. Measured on
// two catalogue rocks at their class's default swap (large: mesh_gu 60, small:
// mesh_gu 15) at the on-screen size a 1080p 60-degree view gives them.
TEST_F(ImpostorBlendGLTest, HandoffBillboardLooksLikeTheMesh) {
    const HandoffStats large = measure_handoff(*this, *pipeline, "majors/silicate_01", 3.0f, 60.0f, 12);
    const HandoffStats small = measure_handoff(*this, *pipeline, "fragments/silicate_01", 0.3f, 15.0f, 12);
    std::printf("[impostor blend] hand-off mesh vs billboard: large diff %.2f IoU %.3f; small diff %.2f IoU %.3f\n",
                large.diff, large.iou, small.diff, small.iou);
    // Measured with this test before rock-blend (nearest of 16 Fibonacci
    // views, 128 px cells, the quad posed in that view's plane): large diff
    // 20.94 IoU 0.923, small diff 21.51 IoU 0.853. The blend must not do worse.
    EXPECT_LT(large.diff, 20.94);
    EXPECT_LT(small.diff, 21.51);
    EXPECT_GT(large.iou, 0.923);
    EXPECT_GT(small.iou, 0.853);
}
