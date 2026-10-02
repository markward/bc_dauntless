// native/tests/renderer/far_pass_test.cc
//
// FarPass (far-tier spec §3, "Impostor geometry"): each distant catalogue rock
// is ONE quad per instance, posed in its chosen baked view's plane, drawn by
// impostor.vert LINKED WITH the existing opaque.frag and textured from the
// rock's 16-view impostor atlas. These tests pin:
//   * the atlas's row order against the quad (u_uv_flip_y) -- AtlasOrientation;
//   * the atlas normal's green axis against opaque.frag's derivative tangent
//     frame (u_normal_flip_g) -- LightingSide;
//   * that an impostor of a sphere looks like the sphere's mesh drawn through
//     draw_model from the baked direction -- MatchesTheMeshWithinTolerance;
//   * one instanced draw per non-empty bin that has an atlas.
//
// The atlas is rasterised HERE, on the CPU, from an analytic sphere using the
// bake's own view basis (renderer::far::make_view_basis, a copy of
// native/src/rockgen/src/impostor.cc:make_basis) and the bake's own screen
// mapping (screen.y = (half - sy) / (2 half) * size: y grows DOWN in a cell),
// so the test atlas is laid out exactly as rockgen lays out a real one.
//
// The GL fixture follows minor_pass_test.cc: a hidden renderer::Window,
// GTEST_SKIP only when no GL context exists, pixel readback.

#include <gtest/gtest.h>
#include <array>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <renderer/far_field.h>
#include <renderer/far_pass.h>
#include <renderer/frame.h>
#include <renderer/hdr_target.h>
#include <renderer/pipeline.h>
#include <renderer/scuff_texture.h>
#include <renderer/speck.h>
#include <renderer/window.h>

#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/model.h>
#include <assets/texture.h>

#include <scenegraph/camera.h>
#include <scenegraph/world.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "support/content_root.h"

namespace {

namespace far = renderer::far;

constexpr int kW = 128;
constexpr int kH = 128;

// Every catalogue rock's bound radius at load scale 1 (constraints.md).
constexpr float kBoundMu = 57.142857f;
// The bake's per-view cell size.
constexpr int kViewSize = 128;
// A near-level baked view: dir.y (glTF) = 1 - 2 * 7.5 / 16 = 0.0625.
constexpr int kLevelView = 7;

const glm::vec3 kRed(200.0f, 60.0f, 40.0f);
const glm::vec3 kBlue(40.0f, 70.0f, 200.0f);

// rockgen's impostor_view_dirs(): 16 Fibonacci-sphere directions, glTF frame.
std::vector<glm::vec3> view_dirs() {
    std::vector<glm::vec3> dirs;
    for (int i = 0; i < 16; ++i) {
        const float y = 1.0f - 2.0f * (static_cast<float>(i) + 0.5f) / 16.0f;
        const float r = std::sqrt(std::max(0.0f, 1.0f - y * y));
        const float phi = static_cast<float>(i) * 2.399963229728653f;
        dirs.emplace_back(std::cos(phi) * r, y, std::sin(phi) * r);
    }
    return dirs;
}

struct Atlas {
    assets::Image albedo;
    assets::Image normal;
};

// The 16-view atlas of a sphere of radius kBoundMu (glTF frame) whose upper
// hemisphere (glTF +y == BC +Z) is `upper` and lower is `lower`, laid out as
// rockgen's bake_impostor lays it out: view v in cell (v % 4, v / 4), half
// extent = radius * 1.02, screen y DOWN, normal = (n.right, n.up, n.dir).
Atlas sphere_atlas(glm::vec3 upper, glm::vec3 lower) {
    const int canvas = 4 * kViewSize;
    Atlas a;
    for (assets::Image* img : {&a.albedo, &a.normal}) {
        img->width = img->height = static_cast<std::uint32_t>(canvas);
        img->format = assets::Image::Format::RGBA8;
        img->pixels.assign(static_cast<std::size_t>(canvas) * canvas * 4, 0);
    }
    const float R = kBoundMu;
    const float half = R * 1.02f;
    const auto dirs = view_dirs();
    for (int view = 0; view < 16; ++view) {
        const far::ViewBasis b = far::make_view_basis(dirs[static_cast<std::size_t>(view)]);
        const int ox = (view % 4) * kViewSize;
        const int oy = (view / 4) * kViewSize;
        for (int py = 0; py < kViewSize; ++py) {
            for (int px = 0; px < kViewSize; ++px) {
                // Inverse of the bake's screen mapping at the pixel centre.
                const float sx = ((static_cast<float>(px) + 0.5f) / kViewSize * 2.0f - 1.0f) * half;
                const float sy = (1.0f - (static_cast<float>(py) + 0.5f) / kViewSize * 2.0f) * half;
                const float rr = sx * sx + sy * sy;
                if (rr > R * R) continue;
                const float z = std::sqrt(R * R - rr);
                const glm::vec3 p = sx * b.right + sy * b.up + z * b.dir;
                const glm::vec3 n = p / R;
                const glm::vec3 c = p.y > 0.0f ? upper : lower;
                const std::size_t i =
                    (static_cast<std::size_t>(oy + py) * canvas + static_cast<std::size_t>(ox + px)) * 4;
                a.albedo.pixels[i + 0] = static_cast<std::uint8_t>(c.r);
                a.albedo.pixels[i + 1] = static_cast<std::uint8_t>(c.g);
                a.albedo.pixels[i + 2] = static_cast<std::uint8_t>(c.b);
                a.albedo.pixels[i + 3] = 255;
                const glm::vec3 nv(glm::dot(n, b.right), glm::dot(n, b.up), glm::dot(n, b.dir));
                for (int k = 0; k < 3; ++k)
                    a.normal.pixels[i + static_cast<std::size_t>(k)] = static_cast<std::uint8_t>(
                        glm::clamp(nv[k] * 0.5f + 0.5f, 0.0f, 1.0f) * 255.0f);
                a.normal.pixels[i + 3] = 255;
            }
        }
    }
    return a;
}

// The same sphere as a mesh in BC model axes (glTF positions through
// far::gltf_to_bc()), with a 1x64 base texture: rows 0..31 `upper`, 32..63
// `lower`, and v = stack / stacks from the glTF +y pole, so v < 0.5 is the
// upper hemisphere. An even stack count puts a ring exactly on the equator.
assets::Model make_sphere_model(glm::vec3 upper, glm::vec3 lower) {
    const glm::mat3 M = far::gltf_to_bc();
    const int stacks = 48, slices = 64;
    const float R = kBoundMu;
    assets::MeshCpu cpu;
    for (int i = 0; i <= stacks; ++i) {
        const float th = 3.14159265f * static_cast<float>(i) / stacks;
        for (int j = 0; j <= slices; ++j) {
            const float ph = 2.0f * 3.14159265f * static_cast<float>(j) / slices;
            const glm::vec3 g(std::sin(th) * std::cos(ph), std::cos(th), std::sin(th) * std::sin(ph));
            assets::MeshCpu::Vertex v;
            v.position = M * (g * R);
            v.normal = M * g;
            v.uv = glm::vec2(static_cast<float>(j) / slices, static_cast<float>(i) / stacks);
            cpu.vertices.push_back(v);
        }
    }
    auto idx = [&](int i, int j) { return static_cast<std::uint32_t>(i * (slices + 1) + j); };
    auto tri = [&](std::uint32_t a, std::uint32_t b, std::uint32_t c) {
        const glm::vec3 A = cpu.vertices[a].position, B = cpu.vertices[b].position,
                        C = cpu.vertices[c].position;
        const glm::vec3 n = glm::cross(B - A, C - A);
        if (glm::length(n) < 1e-6f) return;               // pole sliver
        if (glm::dot(n, A + B + C) < 0.0f) std::swap(b, c);   // CCW from outside
        cpu.indices.insert(cpu.indices.end(), {a, b, c});
    };
    for (int i = 0; i < stacks; ++i)
        for (int j = 0; j < slices; ++j) {
            tri(idx(i, j), idx(i + 1, j), idx(i + 1, j + 1));
            tri(idx(i, j), idx(i + 1, j + 1), idx(i, j + 1));
        }
    cpu.material_index = 0;

    assets::Model m;
    m.meshes.push_back(assets::upload_mesh(cpu));
    assets::Node node;
    node.parent_index = -1;
    node.local_transform = glm::mat4(1.0f);
    node.meshes = {0};
    m.nodes.push_back(node);
    m.root_node = 0;

    assets::Image img;
    img.width = 1;
    img.height = 64;
    img.format = assets::Image::Format::RGBA8;
    for (int row = 0; row < 64; ++row) {
        const glm::vec3 c = row < 32 ? upper : lower;
        img.pixels.insert(img.pixels.end(), {static_cast<std::uint8_t>(c.r),
                                             static_cast<std::uint8_t>(c.g),
                                             static_cast<std::uint8_t>(c.b), 255});
    }
    m.textures.push_back(assets::upload_image(img, /*generate_mipmaps=*/false));

    assets::Material mat;
    mat.diffuse = glm::vec3(1.0f);
    mat.emissive = glm::vec3(0.0f);
    mat.stages[static_cast<std::size_t>(assets::Material::StageSlot::Base)].texture_index = 0;
    m.materials.push_back(mat);
    return m;
}

std::uint64_t handle_of(const assets::Model& m) {
    return static_cast<std::uint64_t>(reinterpret_cast<std::uintptr_t>(&m));
}

const assets::Model* lookup_handle(std::uint64_t h) {
    return reinterpret_cast<const assets::Model*>(static_cast<std::uintptr_t>(h));
}

// The baked view `view`'s direction and in-plane axes in BC axes, for a rock
// at the identity rotation -- exactly what FarField::build emits.
struct BcView { glm::vec3 dir, right, up; };
BcView bc_view(int view) {
    const glm::mat3 M = far::gltf_to_bc();
    const far::ViewBasis b = far::make_view_basis(view_dirs()[static_cast<std::size_t>(view)]);
    return {M * b.dir, M * b.right, M * b.up};
}

// One impostor of radius `r` at `centre`, viewed from baked view `view`,
// fully on (dither weight 1).
far::ImpostorBin one_impostor_bin(int rock, int view, glm::vec3 centre, float r) {
    const BcView v = bc_view(view);
    far::ImpostorBin bin;
    bin.rock = rock;
    bin.items.push_back(far::ImpostorGpu{glm::vec4(centre, r * 1.02f),
                                         glm::vec4(v.right, static_cast<float>(view)),
                                         glm::vec4(v.up, -1.0f)});
    return bin;
}

class FarPassGLTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "far-pass-test", false);
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

    // A camera `dist` away along the baked view `view`, BC +Z up (level for a
    // near-horizontal view), framing a rock of radius 1 at `centre`.
    static scenegraph::Camera view_camera(int view, glm::vec3 centre, float dist) {
        scenegraph::Camera c;
        c.eye = centre + bc_view(view).dir * dist;
        c.target = centre;
        c.up = glm::vec3(0.0f, 0.0f, 1.0f);
        c.fov_y_rad = glm::radians(35.0f);
        c.aspect = 1.0f;
        c.near = 0.1f;
        c.far = 100.0f;
        return c;
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

    static bool lit(const std::vector<unsigned char>& buf, int i) {
        return buf[static_cast<std::size_t>(i) * 4] + buf[static_cast<std::size_t>(i) * 4 + 1] +
                   buf[static_cast<std::size_t>(i) * 4 + 2] > 0;
    }

    static int lit_pixels(const std::vector<unsigned char>& buf) {
        int n = 0;
        for (int i = 0; i < kW * kH; ++i) n += lit(buf, i) ? 1 : 0;
        return n;
    }

    std::vector<unsigned char> draw_impostors(renderer::FarPass& pass,
                                              const std::vector<far::ImpostorBin>& bins,
                                              const scenegraph::Camera& cam,
                                              const renderer::Lighting& lighting) {
        clear_framebuffer();
        pass.render_impostors(bins, cam, *pipeline, lighting, /*ambient_scale=*/1.0f,
                              /*rim_strength=*/0.0f);
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
        return read_frame();
    }

    std::vector<unsigned char> draw_major(const assets::Model& model, const glm::mat4& world,
                                          const scenegraph::Camera& cam,
                                          const renderer::Lighting& lighting) {
        clear_framebuffer();
        scenegraph::World sg;
        const auto iid = sg.create_instance(static_cast<scenegraph::ModelHandle>(handle_of(model)));
        sg.set_world_transform(iid, world);
        renderer::FrameSubmitter submitter;
        submitter.submit_opaque_instance(
            sg, iid, cam, *pipeline,
            [](scenegraph::ModelHandle h) { return lookup_handle(h); }, lighting);
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
        return read_frame();
    }
};

}  // namespace

// A rock whose upper half (BC +Z) is red and lower half blue, drawn as an
// impostor with the camera level, shows red in the upper half of the screen
// and blue in the lower. Pins u_uv_flip_y: the wrong value swaps the halves.
TEST_F(FarPassGLTest, AtlasOrientation) {
    const Atlas atlas = sphere_atlas(kRed, kBlue);
    renderer::FarPass pass;
    pass.debug_set_atlas(0, atlas.albedo, atlas.normal);
    ASSERT_TRUE(pass.atlas_loaded(0));

    const glm::vec3 centre(0.0f, 0.0f, 0.0f);
    ASSERT_LT(std::abs(bc_view(kLevelView).dir.z), 0.1f) << "precondition: a near-level view";
    ASSERT_GT(bc_view(kLevelView).up.z, 0.99f) << "precondition: the view's up is BC +Z";
    const scenegraph::Camera cam = view_camera(kLevelView, centre, 8.0f);

    renderer::Lighting l;            // flat ambient only: the colour is the albedo
    l.ambient = glm::vec3(1.0f);
    const auto px = draw_impostors(pass, {one_impostor_bin(0, kLevelView, centre, 1.0f)}, cam, l);
    ASSERT_GT(lit_pixels(px), kW * kH / 10) << "the impostor is on screen";

    int red_up = 0, blue_up = 0, red_down = 0, blue_down = 0;
    for (int y = 0; y < kH; ++y)
        for (int x = 0; x < kW; ++x) {
            const std::size_t i = (static_cast<std::size_t>(y) * kW + x) * 4;
            if (!lit(px, y * kW + x)) continue;
            const bool red = px[i] > px[i + 2] + 40;
            const bool blue = px[i + 2] > px[i] + 40;
            const bool upper = y >= kH / 2;   // readback row 0 is the BOTTOM
            red_up += upper && red;
            blue_up += upper && blue;
            red_down += !upper && red;
            blue_down += !upper && blue;
        }
    EXPECT_GT(red_up, 10 * std::max(1, blue_up)) << "upper half of the screen is red";
    EXPECT_GT(blue_down, 10 * std::max(1, red_down)) << "lower half of the screen is blue";
}

// Lit from BC +Z, the upper rows of the impostor are brighter than the lower
// rows. The quad's geometric normal is the (near-horizontal) view direction,
// so only the atlas normal can make that so. Pins u_normal_flip_g.
TEST_F(FarPassGLTest, LightingSide) {
    const glm::vec3 grey(180.0f, 180.0f, 180.0f);
    const Atlas atlas = sphere_atlas(grey, grey);
    renderer::FarPass pass;
    pass.debug_set_atlas(0, atlas.albedo, atlas.normal);

    const glm::vec3 centre(0.0f, 0.0f, 0.0f);
    const scenegraph::Camera cam = view_camera(kLevelView, centre, 8.0f);
    renderer::Lighting l;
    l.ambient = glm::vec3(0.05f);
    l.directional_count = 1;
    l.directional_dir_ws[0] = glm::vec3(0.0f, 0.0f, 1.0f);   // toward the light
    l.directional_color[0] = glm::vec3(1.0f);
    const auto px = draw_impostors(pass, {one_impostor_bin(0, kLevelView, centre, 1.0f)}, cam, l);
    ASSERT_GT(lit_pixels(px), kW * kH / 10);

    double upper = 0.0, lower = 0.0;
    int n_upper = 0, n_lower = 0;
    for (int y = 0; y < kH; ++y)
        for (int x = 0; x < kW; ++x) {
            if (!lit(px, y * kW + x)) continue;
            const std::size_t i = (static_cast<std::size_t>(y) * kW + x) * 4;
            const double lum = px[i] + px[i + 1] + px[i + 2];
            if (y >= kH / 2) { upper += lum; ++n_upper; } else { lower += lum; ++n_lower; }
        }
    ASSERT_GT(n_upper, 0);
    ASSERT_GT(n_lower, 0);
    EXPECT_GT(upper / n_upper, 2.0 * (lower / n_lower))
        << "upper mean " << upper / n_upper << " lower mean " << lower / n_lower;
}

// The same sphere drawn through draw_model from the exact baked direction and
// through render_impostors: the mean RGB over the silhouette agrees within 10%
// per channel, and the silhouettes agree on >= 90% of their union.
TEST_F(FarPassGLTest, MatchesTheMeshWithinTolerance) {
    const int view = 5;   // an oblique view: dir.y (glTF) = 0.3125
    const Atlas atlas = sphere_atlas(kRed, kBlue);
    const assets::Model sphere = make_sphere_model(kRed, kBlue);
    const glm::vec3 centre(0.0f, 0.0f, 0.0f);
    const float r = 1.0f;
    const scenegraph::Camera cam = view_camera(view, centre, 8.0f);

    const BcView v = bc_view(view);
    renderer::Lighting l;
    l.ambient = glm::vec3(0.15f);
    l.directional_count = 1;
    l.directional_dir_ws[0] = glm::normalize(v.dir + 0.8f * v.up + 0.4f * v.right);
    l.directional_color[0] = glm::vec3(1.0f, 0.95f, 0.9f);

    const glm::mat4 world = glm::scale(glm::mat4(1.0f), glm::vec3(r / kBoundMu));
    const auto a = draw_major(sphere, world, cam, l);

    renderer::FarPass pass;
    pass.debug_set_atlas(0, atlas.albedo, atlas.normal);
    const auto b = draw_impostors(pass, {one_impostor_bin(0, view, centre, r)}, cam, l);
    ASSERT_EQ(pass.last_draw_calls(), 1);

    int both = 0, either = 0;
    double sum_a[3] = {0, 0, 0}, sum_b[3] = {0, 0, 0};
    int n_a = 0, n_b = 0;
    for (int i = 0; i < kW * kH; ++i) {
        const bool la = lit(a, i), lb = lit(b, i);
        both += la && lb;
        either += la || lb;
        for (int k = 0; k < 3; ++k) {
            if (la) sum_a[k] += a[static_cast<std::size_t>(i) * 4 + static_cast<std::size_t>(k)];
            if (lb) sum_b[k] += b[static_cast<std::size_t>(i) * 4 + static_cast<std::size_t>(k)];
        }
        n_a += la;
        n_b += lb;
    }
    ASSERT_GT(n_a, kW * kH / 10) << "the mesh is on screen";
    ASSERT_GT(n_b, 0) << "the impostor is on screen";
    const double agree = static_cast<double>(both) / either;
    std::printf("[far_pass_test] silhouette IoU %.4f; mean RGB mesh (%.1f %.1f %.1f) "
                "impostor (%.1f %.1f %.1f)\n",
                agree, sum_a[0] / n_a, sum_a[1] / n_a, sum_a[2] / n_a, sum_b[0] / std::max(1, n_b),
                sum_b[1] / std::max(1, n_b), sum_b[2] / std::max(1, n_b));
    EXPECT_GE(agree, 0.90) << "silhouette IoU " << agree;
    for (int k = 0; k < 3; ++k) {
        const double ma = sum_a[k] / n_a, mb = sum_b[k] / n_b;
        EXPECT_LE(std::abs(ma - mb), 0.10 * ma)
            << "channel " << k << ": mesh mean " << ma << ", impostor mean " << mb;
    }
}

// One draw per non-empty bin with an atlas. An empty bin draws nothing; a bin
// whose atlas file is missing is skipped (and its index stays unloaded). The
// count accumulates until reset_counts().
TEST_F(FarPassGLTest, DrawCountIsOnePerBinWithAnAtlas) {
    const Atlas atlas = sphere_atlas(kRed, kBlue);
    renderer::FarPass pass;
    pass.set_atlas_paths({{"/nonexistent/far_pass_test/a0.png", "/nonexistent/far_pass_test/n0.png"},
                          {"/nonexistent/far_pass_test/a1.png", "/nonexistent/far_pass_test/n1.png"},
                          {"/nonexistent/far_pass_test/a2.png", "/nonexistent/far_pass_test/n2.png"},
                          {"/nonexistent/far_pass_test/a3.png", "/nonexistent/far_pass_test/n3.png"}});
    pass.debug_set_atlas(0, atlas.albedo, atlas.normal);
    pass.debug_set_atlas(1, atlas.albedo, atlas.normal);
    pass.debug_set_atlas(3, atlas.albedo, atlas.normal);

    const glm::vec3 centre(0.0f, 0.0f, 0.0f);
    const scenegraph::Camera cam = view_camera(kLevelView, centre, 8.0f);
    renderer::Lighting l;
    l.ambient = glm::vec3(1.0f);

    std::vector<far::ImpostorBin> bins;
    bins.push_back(one_impostor_bin(0, kLevelView, centre + glm::vec3(0.0f, -1.5f, 0.0f), 0.5f));
    bins.push_back(far::ImpostorBin{1, {}});                                     // empty
    bins.push_back(one_impostor_bin(2, kLevelView, centre, 0.5f));               // no atlas
    bins.push_back(one_impostor_bin(3, kLevelView, centre + glm::vec3(0.0f, 1.5f, 0.0f), 0.5f));

    pass.reset_counts();
    const auto px = draw_impostors(pass, bins, cam, l);
    EXPECT_EQ(pass.last_draw_calls(), 2);
    EXPECT_GT(lit_pixels(px), 0);
    EXPECT_FALSE(pass.atlas_loaded(2)) << "a missing file leaves the index unloaded";
    EXPECT_TRUE(pass.atlas_loaded(3));

    draw_impostors(pass, bins, cam, l);
    EXPECT_EQ(pass.last_draw_calls(), 4) << "counts accumulate until reset_counts()";
    pass.reset_counts();
    EXPECT_EQ(pass.last_draw_calls(), 0);

    // Nothing but an empty bin and an atlas-less bin: no draw, no pixels.
    const auto none = draw_impostors(pass, {bins[1], bins[2]}, cam, l);
    EXPECT_EQ(pass.last_draw_calls(), 0);
    EXPECT_EQ(lit_pixels(none), 0);
}

// A failed atlas is not remembered across set_atlas_paths: paths that failed
// once are retried after a new path list arrives (here, a real committed atlas).
TEST_F(FarPassGLTest, SetAtlasPathsForgetsFailures) {
    const std::string dir =
        (test_support::project_root() / "native" / "assets" / "rocks" / "majors" /
         "carbonaceous_01").string();
    renderer::FarPass pass;
    pass.set_atlas_paths({{"/nonexistent/far_pass_test/a0.png", "/nonexistent/far_pass_test/n0.png"}});
    const glm::vec3 centre(0.0f, 0.0f, 0.0f);
    const scenegraph::Camera cam = view_camera(kLevelView, centre, 8.0f);
    renderer::Lighting l;
    l.ambient = glm::vec3(1.0f);
    const std::vector<far::ImpostorBin> bins = {one_impostor_bin(0, kLevelView, centre, 0.5f)};

    pass.reset_counts();
    draw_impostors(pass, bins, cam, l);
    ASSERT_EQ(pass.last_draw_calls(), 0) << "precondition: the missing atlas failed";

    pass.set_atlas_paths({{dir + "/impostor_base.png", dir + "/impostor_normal.png"}});
    pass.reset_counts();
    draw_impostors(pass, bins, cam, l);
    EXPECT_EQ(pass.last_draw_calls(), 1) << "new paths are tried, not the remembered failure";
    EXPECT_TRUE(pass.atlas_loaded(0));
}

// has_atlas loads lazily and reports a missing file as false.
TEST_F(FarPassGLTest, HasAtlasReportsAMissingFile) {
    renderer::FarPass pass;
    pass.set_atlas_paths({{"/nonexistent/far_pass_test/a0.png", "/nonexistent/far_pass_test/n0.png"}});
    EXPECT_FALSE(pass.has_atlas(0));
    EXPECT_FALSE(pass.has_atlas(5)) << "no path at all";
    const Atlas atlas = sphere_atlas(kRed, kBlue);
    pass.debug_set_atlas(0, atlas.albedo, atlas.normal);
    EXPECT_TRUE(pass.has_atlas(0));
}

// dilate_coverage spreads colour into alpha-0 texels and never changes alpha.
TEST(FarPassCpu, DilateCoverage) {
    assets::Image img;
    img.width = 3;
    img.height = 1;
    img.format = assets::Image::Format::RGBA8;
    img.pixels = {0, 0, 0, 0, 100, 150, 200, 255, 0, 0, 0, 0};
    renderer::dilate_coverage(img, 1);
    EXPECT_EQ(img.pixels[0], 100);
    EXPECT_EQ(img.pixels[3], 0);
    EXPECT_EQ(img.pixels[8], 100);
    EXPECT_EQ(img.pixels[11], 0);
    EXPECT_EQ(img.pixels[7], 255);
}

// Rings: a texel two steps from the coverage is filled only by a second pass.
TEST(FarPassCpu, DilateCoverageGrowsOneRingPerPass) {
    assets::Image img;
    img.width = 3;
    img.height = 1;
    img.format = assets::Image::Format::RGBA8;
    img.pixels = {90, 30, 10, 255, 0, 0, 0, 0, 0, 0, 0, 0};
    assets::Image one = img;
    renderer::dilate_coverage(one, 1);
    EXPECT_EQ(one.pixels[4], 90);
    EXPECT_EQ(one.pixels[8], 0) << "two rings away: not reached by one pass";
    renderer::dilate_coverage(img, 2);
    EXPECT_EQ(img.pixels[8], 90);
    EXPECT_EQ(img.pixels[9], 30);
    EXPECT_EQ(img.pixels[11], 0);
}

// ---- Specks (far-tier Task 6) --------------------------------------------

namespace {

constexpr int kFluxSize = 256;

// A camera `dist` away from `centre` along baked view `view`, BC +Z up, 35
// degree fov, square: the flux test's view for a rock at p = 2 px.
scenegraph::Camera flux_camera(int view, glm::vec3 centre, float dist) {
    scenegraph::Camera c;
    c.eye = centre + bc_view(view).dir * dist;
    c.target = centre;
    c.up = glm::vec3(0.0f, 0.0f, 1.0f);
    c.fov_y_rad = glm::radians(35.0f);
    c.aspect = 1.0f;
    c.near = 1.0f;
    c.far = 2000.0f;
    return c;
}

// Clear `t` to black, run `draw`, and return sum(r + g + b) over every pixel
// of the RGBA16F colour target, read back as floats.
template <class F>
double hdr_flux(renderer::HdrTarget& t, F&& draw) {
    t.bind();
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    draw();
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    std::vector<float> px(static_cast<std::size_t>(t.width()) * t.height() * 4);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, t.fbo());
    glReadPixels(0, 0, t.width(), t.height(), GL_RGBA, GL_FLOAT, px.data());
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    double sum = 0.0;
    for (std::size_t i = 0; i < px.size(); i += 4) sum += px[i] + px[i + 1] + px[i + 2];
    return sum;
}

}  // namespace

// Flux continuity (spec §5): the same rock at p = 2 px drawn as a mesh, as an
// impostor and as a speck: summed linear radiance within 25% of each other.
TEST_F(FarPassGLTest, FluxContinuityAtTwoPixels) {
    // The target first: HdrTarget::resize binds on the ACTIVE unit.
    renderer::HdrTarget target;
    target.resize(kFluxSize, kFluxSize);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, 0);

    const glm::vec3 grey8(150.0f, 150.0f, 150.0f);
    const glm::vec3 avg_albedo = grey8 / 255.0f;
    const Atlas atlas = sphere_atlas(grey8, grey8);
    const assets::Model sphere = make_sphere_model(grey8, grey8);

    const int view = kLevelView;
    const glm::vec3 centre(0.0f, 0.0f, 0.0f);
    const float r = 1.0f;
    const float p = 2.0f;
    scenegraph::Camera cam = flux_camera(view, centre, 1.0f);
    const float k = far::pixels_per_gu(cam.proj_matrix(), static_cast<float>(kFluxSize));
    cam = flux_camera(view, centre, r * k / p);

    const BcView v = bc_view(view);
    renderer::Lighting l;
    l.ambient = glm::vec3(0.05f);
    l.directional_count = 1;
    l.directional_dir_ws[0] = glm::normalize(v.dir + 0.8f * v.up + 0.4f * v.right);
    l.directional_color[0] = glm::vec3(1.0f, 0.95f, 0.9f);

    const glm::mat4 world = glm::scale(glm::mat4(1.0f), glm::vec3(r / kBoundMu));
    const double mesh = hdr_flux(target, [&] {
        scenegraph::World sg;
        const auto iid = sg.create_instance(static_cast<scenegraph::ModelHandle>(handle_of(sphere)));
        sg.set_world_transform(iid, world);
        renderer::FrameSubmitter submitter;
        submitter.submit_opaque_instance(
            sg, iid, cam, *pipeline,
            [](scenegraph::ModelHandle h) { return lookup_handle(h); }, l);
    });

    renderer::FarPass pass;
    pass.debug_set_atlas(0, atlas.albedo, atlas.normal);
    const double impostor = hdr_flux(target, [&] {
        pass.render_impostors({one_impostor_bin(0, view, centre, r)}, cam, *pipeline, l,
                              /*ambient_scale=*/1.0f, /*rim_strength=*/0.0f);
    });
    const double speck = hdr_flux(target, [&] {
        pass.render_specks({renderer::SpeckGpu{centre, p, avg_albedo, 1.0f}}, cam, *pipeline, l,
                           /*ambient_scale=*/1.0f, /*speck_gain=*/1.0f, kFluxSize, kFluxSize);
    });

    std::printf("[far_pass_test] flux at p = 2 px: mesh %.4f impostor %.4f speck %.4f\n", mesh,
                impostor, speck);
    ASSERT_GT(mesh, 0.0);
    EXPECT_NEAR(impostor, mesh, 0.25 * mesh);
    EXPECT_NEAR(speck, mesh, 0.25 * mesh);
    EXPECT_NEAR(speck, impostor, 0.25 * impostor);
}

// Premultiplied output, exactly: a lit speck with p < 1 (so a < 1 per texel)
// over white reads c*a + (1 - a). Straight alpha would read c*a*a + (1 - a).
// The ambient is scaled by ambient_scale as set_ambient_uniforms scales it.
// A non-empty list is one draw; GL state, including the blend function, is
// restored.
TEST_F(FarPassGLTest, SpeckOccludesABrightBackground) {
    renderer::HdrTarget target;            // first: resize binds on the ACTIVE unit
    target.resize(kW, kH);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, 0);

    const glm::vec3 centre(0.0f, 0.0f, 0.0f);
    const scenegraph::Camera cam = view_camera(kLevelView, centre, 8.0f);
    renderer::Lighting l;                  // ambient only: c = albedo * ambient * scale
    l.ambient = glm::vec3(1.0f);
    l.directional_count = 0;               // Lighting defaults to one sun
    const float ambient_scale = 0.5f;
    const glm::vec3 albedo(0.6f, 0.4f, 0.2f);
    const float p = 0.8f;
    const float a = 3.14159265f * p * p / 4.0f;
    const glm::vec3 expect = albedo * ambient_scale * a + glm::vec3(1.0f - a);

    target.bind();
    glClearColor(1.0f, 1.0f, 1.0f, 1.0f);
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);     // a caller's blend function, to be kept

    renderer::FarPass pass;
    pass.reset_counts();
    pass.render_specks({}, cam, *pipeline, l, ambient_scale, 1.0f, kW, kH);
    EXPECT_EQ(pass.last_draw_calls(), 0) << "an empty list draws nothing";
    pass.render_specks({renderer::SpeckGpu{centre, p, albedo, 1.0f}}, cam, *pipeline, l,
                       ambient_scale, 1.0f, kW, kH);
    EXPECT_EQ(pass.last_draw_calls(), 1);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));

    std::vector<float> px(static_cast<std::size_t>(kW) * kH * 4);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, target.fbo());
    glReadPixels(0, 0, kW, kH, GL_RGBA, GL_FLOAT, px.data());
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    int touched = 0;
    for (std::size_t i = 0; i < px.size(); i += 4) {
        if (px[i] == 1.0f && px[i + 1] == 1.0f && px[i + 2] == 1.0f) continue;
        ++touched;
        for (int k = 0; k < 3; ++k)
            EXPECT_NEAR(px[i + static_cast<std::size_t>(k)], expect[k], 2.0f / 255.0f)
                << "texel " << i / 4 << " channel " << k;
    }
    EXPECT_EQ(touched, 4) << "p < 1: exactly the 2x2 block";

    // State is restored: blending off, depth writes on, the blend function kept.
    EXPECT_FALSE(glIsEnabled(GL_BLEND));
    GLboolean depth_write = GL_FALSE;
    glGetBooleanv(GL_DEPTH_WRITEMASK, &depth_write);
    EXPECT_TRUE(depth_write);
    GLint src = 0, dst = 0;
    glGetIntegerv(GL_BLEND_SRC_RGB, &src);
    glGetIntegerv(GL_BLEND_DST_RGB, &dst);
    EXPECT_EQ(src, GL_SRC_ALPHA);
    EXPECT_EQ(dst, GL_ONE);
    glBlendFunc(GL_ONE, GL_ZERO);
}

namespace {

// Speck-only flux (sum r+g+b over a float readback) of one ambient-lit speck
// of radius `p` px, its centre shifted by (ox, oy) framebuffer pixels from a
// pixel corner (the 256x256 target's centre).
struct SpeckFluxRig {
    renderer::Pipeline& pipeline;
    renderer::HdrTarget& target;
    renderer::FarPass pass;
    scenegraph::Camera cam = flux_camera(kLevelView, glm::vec3(0.0f), 100.0f);
    renderer::Lighting light;
    glm::vec3 albedo{0.5f, 0.4f, 0.3f};

    explicit SpeckFluxRig(renderer::Pipeline& p, renderer::HdrTarget& t) : pipeline(p), target(t) {
        light.ambient = glm::vec3(1.0f);
        light.directional_count = 0;       // Lighting defaults to one sun
    }

    double flux(float p, float ox, float oy) {
        const float k = far::pixels_per_gu(cam.proj_matrix(), static_cast<float>(kFluxSize));
        const float gu_per_px = glm::length(cam.eye - cam.target) / k;
        const glm::vec3 fwd = glm::normalize(cam.target - cam.eye);
        const glm::vec3 right = glm::normalize(glm::cross(fwd, cam.up));
        const glm::vec3 up = glm::cross(right, fwd);
        const glm::vec3 pos = cam.target + (ox * right + oy * up) * gu_per_px;
        return hdr_flux(target, [&] {
            pass.render_specks({renderer::SpeckGpu{pos, p, albedo, 1.0f}}, cam, pipeline, light,
                               1.0f, 1.0f, kFluxSize, kFluxSize);
        });
    }

    // pi p^2 * sum(albedo * ambient): the flux an area-weighted speck owes.
    double expected(float p) const {
        return 3.14159265 * p * p * (albedo.r + albedo.g + albedo.b);
    }
};

}  // namespace

// Ruling R12: speck flux is pi p^2 * colour on both sides of the p = 1 seam
// between the square and the disc, and through the band.
TEST_F(FarPassGLTest, SpeckFluxScalesAsPSquaredAcrossTheSeam) {
    renderer::HdrTarget target;
    target.resize(kFluxSize, kFluxSize);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, 0);
    SpeckFluxRig rig(*pipeline, target);
    for (float p : {0.99f, 1.0f, 1.01f, 1.5f, 2.0f}) {
        const double got = rig.flux(p, 0.0f, 0.0f);
        std::printf("[far_pass_test] speck flux p %.2f: %.4f (expected %.4f, ratio %.4f)\n", p,
                    got, rig.expected(p), got / rig.expected(p));
        EXPECT_NEAR(got / rig.expected(p), 1.0, 0.05) << "p = " << p;
    }
}

// Ruling R12: sub-pixel motion does not make a speck shimmer. 16 offsets (a
// 4x4 grid of quarter pixels, including the exact half-pixel alignments) at
// p = 1.0 and 1.5 (the ruling), and at 1.25, 1.75 and 1.9, where the disc
// carries most of the square -> disc cross-fade: max/min flux <= 1.10.
TEST_F(FarPassGLTest, SpeckFluxIsSteadyUnderSubPixelMotion) {
    renderer::HdrTarget target;
    target.resize(kFluxSize, kFluxSize);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, 0);
    SpeckFluxRig rig(*pipeline, target);
    for (float p : {1.0f, 1.25f, 1.5f, 1.75f, 1.9f}) {
        double lo = 1e30, hi = 0.0;
        for (int i = 0; i < 4; ++i)
            for (int j = 0; j < 4; ++j) {
                const double f = rig.flux(p, 0.25f * i, 0.25f * j);
                lo = std::min(lo, f);
                hi = std::max(hi, f);
            }
        std::printf("[far_pass_test] speck shimmer p %.2f: min %.4f max %.4f max/min %.4f\n", p,
                    lo, hi, hi / lo);
        ASSERT_GT(lo, 0.0);
        EXPECT_LE(hi / lo, 1.10) << "p = " << p;
    }
}

// ---- Haze (far-tier Task 7) ----------------------------------------------

namespace {

constexpr int kHazeSize = 64;

// Vesuvi's band (far_field_test.cc's vesuvi_like), minors only.
far::DiscSource haze_source(glm::dvec3 centre = glm::dvec3(0.0)) {
    far::DiscSource s;
    s.id = 1; s.frame = "Vesuvi"; s.seed = 7;
    s.centre = centre;
    s.table = {{0.0f, 0.05f}, {215000.0f, 0.05f}, {226000.0f, 0.5f},
               {330000.0f, 0.5f}, {340000.0f, 0.05f}};
    far::Population minors;
    minors.kind = 0; minors.density_at_1 = 9.67e-8f; minors.a_lo = 0.0f; minors.a_hi = 1.0f;
    minors.size = {0.05f, 0.7f, 2.5f};
    minors.albedo = glm::vec3(0.5f, 0.4f, 0.3f);
    s.pops = {minors};
    return s;
}

// The haze test's camera: render-space eye off the origin (so u_centre's
// system -> render offset is exercised), looking roughly along +y.
scenegraph::Camera haze_camera() {
    scenegraph::Camera c;
    c.eye = glm::vec3(10.0f, 20.0f, 5.0f);
    c.target = c.eye + glm::vec3(0.1f, 1.0f, 0.02f);
    c.up = glm::vec3(0.0f, 0.0f, 1.0f);
    c.fov_y_rad = glm::radians(60.0f);
    c.aspect = 1.0f;
    c.near = 10.0f;
    c.far = 1.0e6f;
    return c;
}

glm::dvec3 unproject(const glm::dmat4& inv_vp, double u, double v, double d) {
    const glm::dvec4 w = inv_vp * glm::dvec4(u * 2.0 - 1.0, v * 2.0 - 1.0, d * 2.0 - 1.0, 1.0);
    return glm::dvec3(w) / w.w;
}

}  // namespace

namespace {
// Draws `src` with far_haze.frag at 5 pixels of a 64x64 render, twice -- a far
// depth (cleared to 1.0) and a near occluder (a plane near_gu ahead) -- and
// asserts alpha and premultiplied colour agree with haze_column within 0.001.
// centre_alpha[pass] = the CPU alpha at the centre pixel.
// `pixels` (default: the centre and four corners) are the pixels compared.
// Returns the max |alpha| difference.
using HazePixels = std::vector<std::array<int, 2>>;
const HazePixels kHazeDefaultPixels = {{32, 32}, {6, 6}, {57, 6}, {6, 57}, {57, 57}};
// The exact pixel-compare path (rock-fields Task 12): full resolution and no
// start ramp, so far_haze.frag draws straight into the target as before.
far::FarDials exact_haze_dials() {
    far::FarDials d;
    d.haze_res_divisor = 1;
    d.haze_start_gu = 0.0f;
    d.haze_start_ramp_gu = 0.0f;
    return d;
}
float haze_matches_cpu(renderer::Pipeline& pipeline, const far::DiscSource& src,
                       const glm::dvec3& origin_sys, float near_gu, float centre_alpha[2],
                       const HazePixels& pix = kHazeDefaultPixels,
                       const far::FarDials& dials = exact_haze_dials()) {
    // Targets first: HdrTarget::resize binds on the ACTIVE unit.
    renderer::HdrTarget scene, out;
    scene.resize(kHazeSize, kHazeSize);
    out.resize(kHazeSize, kHazeSize);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, 0);

    const std::vector<far::DiscSource> sources = {src};
    const scenegraph::Camera cam = haze_camera();
    const glm::mat4 vp = cam.proj_matrix() * cam.view_matrix();
    const glm::mat4 inv_vp = glm::inverse(vp);
    const glm::dmat4 inv_vp_d = glm::inverse(glm::dmat4(cam.proj_matrix()) * glm::dmat4(cam.view_matrix()));
    renderer::Lighting l;
    l.ambient = glm::vec3(0.1f, 0.12f, 0.15f);
    l.directional_count = 1;
    l.directional_dir_ws[0] = glm::normalize(glm::vec3(1.0f, 0.3f, 0.5f));
    l.directional_color[0] = glm::vec3(1.0f, 0.9f, 0.8f);
    const float ambient_scale = 0.7f;

    // Depth of a plane near_gu ahead.
    const glm::vec4 clip = cam.proj_matrix() * glm::vec4(0.0f, 0.0f, -near_gu, 1.0f);
    const float near_depth = clip.z / clip.w * 0.5f + 0.5f;

    float max_diff = 0.0f;
    for (int pass_i = 0; pass_i < 2; ++pass_i) {
        scene.bind();
        glViewport(0, 0, kHazeSize, kHazeSize);
        glDepthMask(GL_TRUE);
        glClearDepth(pass_i == 0 ? 1.0 : static_cast<double>(near_depth));
        glClear(GL_DEPTH_BUFFER_BIT);
        glClearDepth(1.0);
        std::vector<float> depth(static_cast<std::size_t>(kHazeSize) * kHazeSize);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, scene.fbo());
        glReadPixels(0, 0, kHazeSize, kHazeSize, GL_DEPTH_COMPONENT, GL_FLOAT, depth.data());

        out.bind();
        glViewport(0, 0, kHazeSize, kHazeSize);
        glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        renderer::FarPass pass;
        pass.render_haze(sources, origin_sys, cam, pipeline, l, ambient_scale,
                         scene.depth_texture(), inv_vp, dials);
        EXPECT_EQ(pass.last_draw_calls(), 1);
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
        std::vector<float> px(static_cast<std::size_t>(kHazeSize) * kHazeSize * 4);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, out.fbo());
        glReadPixels(0, 0, kHazeSize, kHazeSize, GL_RGBA, GL_FLOAT, px.data());
        glBindFramebuffer(GL_FRAMEBUFFER, 0);

        for (const auto& p : pix) {
            const double u = (p[0] + 0.5) / kHazeSize, v = (p[1] + 0.5) / kHazeSize;
            const std::size_t idx = static_cast<std::size_t>(p[1]) * kHazeSize + p[0];
            const double d = depth[idx];
            const glm::dvec3 eye(cam.eye);
            const glm::vec3 dir = glm::vec3(glm::normalize(unproject(inv_vp_d, u, v, 0.5) - eye));
            const float t_max = d >= 1.0 ? 1.0e30f
                                         : static_cast<float>(glm::length(unproject(inv_vp_d, u, v, d) - eye));
            glm::vec3 light = l.ambient * ambient_scale;
            light += l.directional_color[0] *
                     far::lambert_sphere_phase(glm::dot(l.directional_dir_ws[0], -dir));
            const auto h = far::haze_column(sources[0], origin_sys, dir, t_max, dials.slab_sigmas, dials.haze_steps, dials.haze_gain, light,
                                          dials.haze_start_gu, dials.haze_start_ramp_gu);
            const float* g = &px[idx * 4];
            std::printf("[far_pass_test] haze %s px (%d,%d): gpu a %.4f rgb (%.4f %.4f %.4f) | "
                        "cpu a %.4f rgb (%.4f %.4f %.4f)\n", pass_i == 0 ? "far " : "near",
                        p[0], p[1], g[3], g[0], g[1], g[2], h.alpha, h.rgb.r, h.rgb.g, h.rgb.b);
            // The brief's bound is 0.01; measured agreement is ~4e-5, and a
            // left-endpoint (not midpoint) march differs by only ~0.003, so
            // 0.001 is what actually pins "the same midpoint rule".
            EXPECT_NEAR(g[3], h.alpha, 0.001f) << "pixel " << p[0] << "," << p[1];
            for (int c = 0; c < 3; ++c) EXPECT_NEAR(g[c], h.rgb[c], 0.001f);
            max_diff = std::max(max_diff, std::fabs(g[3] - h.alpha));
            if (p[0] == 32 && p[1] == 32) centre_alpha[pass_i] = h.alpha;
        }
    }
    std::printf("[far_pass_test] haze shader-vs-CPU max alpha diff %.5f\n", max_diff);
    return max_diff;
}
}  // namespace

// far_haze.frag implements haze_column exactly: at 5 pixels of a 64x64
// render, alpha agrees within 0.01 (asserted: 0.001) with a far depth (cleared to 1.0) and with
// a near occluder (depth cleared to a plane 60,000 GU ahead), and the
// premultiplied colour agrees too.
TEST_F(FarPassGLTest, HazeShaderMatchesTheCpuReference) {
    float centre_alpha[2] = {0.0f, 0.0f};
    far::DiscSource s = haze_source();
    s.brightness = 8.0f;   // colour only: the shader must scale rgb, not alpha
    haze_matches_cpu(*pipeline, s, glm::dvec3(278000.0, 0.0, 0.0), 60000.0f, centre_alpha);
    EXPECT_GT(centre_alpha[0], 0.05f) << "the far view sees real haze";
    EXPECT_LT(centre_alpha[1], centre_alpha[0] - 0.03f) << "the occluder stops the march";
}

// Tile-field haze (2026-10-02): a Sphere source -- Beol 4's field at the
// derived tile gain and brightness, 2,500 GU ahead -- matches haze_column
// within 0.001 too, including gain_scale, brightness, pixels that miss the
// sphere, and an occluder inside it.
TEST_F(FarPassGLTest, SphereHazeShaderMatchesTheCpuReference) {
    const glm::dvec3 origin_sys(278000.0, 0.0, 0.0);
    far::DiscSource s;
    s.id = 2; s.shape = far::DiscSource::Shape::Sphere; s.procedural = false;
    s.centre = origin_sys + glm::dvec3(0.0, 2500.0, 0.0);
    s.sphere_radius_gu = 1000.0f; s.sphere_edge_frac = 0.2f;
    s.gain_scale = 14140.0f / 270.0f;
    s.brightness = 9.1f;
    far::Population minors;
    minors.kind = 0; minors.a_lo = 0.0f; minors.a_hi = 1.0f;
    minors.density_at_1 = 405.0f / (4.0f / 3.0f * 3.14159265f * 1.0e9f);
    minors.size = {0.05f, 0.7f, 2.5f};
    minors.albedo = glm::vec3(0.5f, 0.4f, 0.3f);
    s.pops = {minors};
    float centre_alpha[2] = {0.0f, 0.0f};
    haze_matches_cpu(*pipeline, s, origin_sys, 2600.0f, centre_alpha);
    EXPECT_GT(centre_alpha[0], 0.05f) << "the far view sees the field";
    EXPECT_LT(centre_alpha[1], centre_alpha[0] - 0.03f) << "the occluder stops the march";
}

// Rock-fields Task 12: the start ramp in the shader is haze_column's. The
// sphere scene above (chord 1,500 .. 3,500 GU) with the ramp over 2,000 ..
// 3,000 GU -- inside the field, with the occluder (2,600 GU) inside the ramp --
// matches within 0.001, at divisor 1 (the exact pixel compare path).
TEST_F(FarPassGLTest, StartRampHazeShaderMatchesTheCpuReference) {
    const glm::dvec3 origin_sys(278000.0, 0.0, 0.0);
    far::DiscSource s;
    s.id = 2; s.shape = far::DiscSource::Shape::Sphere; s.procedural = false;
    s.centre = origin_sys + glm::dvec3(0.0, 2500.0, 0.0);
    s.sphere_radius_gu = 1000.0f; s.sphere_edge_frac = 0.2f;
    s.gain_scale = 14140.0f / 270.0f;
    s.brightness = 9.1f;
    far::Population minors;
    minors.kind = 0; minors.a_lo = 0.0f; minors.a_hi = 1.0f;
    minors.density_at_1 = 405.0f / (4.0f / 3.0f * 3.14159265f * 1.0e9f);
    minors.size = {0.05f, 0.7f, 2.5f};
    minors.albedo = glm::vec3(0.5f, 0.4f, 0.3f);
    s.pops = {minors};
    far::FarDials d = exact_haze_dials();
    d.haze_start_gu = 2000.0f;
    d.haze_start_ramp_gu = 1000.0f;
    float ramped[2] = {0.0f, 0.0f}, unramped[2] = {0.0f, 0.0f};
    haze_matches_cpu(*pipeline, s, origin_sys, 2600.0f, ramped, kHazeDefaultPixels, d);
    haze_matches_cpu(*pipeline, s, origin_sys, 2600.0f, unramped);
    EXPECT_GT(ramped[0], 0.02f) << "the far part of the field still hazes";
    EXPECT_LT(ramped[0], unramped[0] - 0.01f) << "the ramp removes the near part";
    EXPECT_LT(ramped[1], ramped[0] - 0.02f) << "the occluder stops the march";
}

// Fix round 1: the shader clips the march to begin at the start, as
// haze_column does. Sensitive setup: 4 steps, the production tile noise and a
// hard step mid-chord (2,500 GU), where an unclipped march would spend half
// its steps before the start and sample different noise.
TEST_F(FarPassGLTest, StartClipHazeShaderMatchesTheCpuReference) {
    const glm::dvec3 origin_sys(278000.0, 0.0, 0.0);
    far::DiscSource s;
    s.id = 3; s.shape = far::DiscSource::Shape::Sphere; s.procedural = false;
    s.centre = origin_sys + glm::dvec3(0.0, 2500.0, 0.0);
    s.sphere_radius_gu = 1000.0f; s.sphere_edge_frac = 0.2f;
    s.gain_scale = 14140.0f / 270.0f;
    s.brightness = 9.1f;
    s.seed = 0xdeadbeefu;
    s.noise_scale_gu = 250.0f; s.noise_contrast = 0.8f; s.noise_octaves = 3;
    s.steps = 4;
    far::Population minors;
    minors.kind = 0; minors.a_lo = 0.0f; minors.a_hi = 1.0f;
    minors.density_at_1 = 405.0f / (4.0f / 3.0f * 3.14159265f * 1.0e9f);
    minors.size = {0.05f, 0.7f, 2.5f};
    minors.albedo = glm::vec3(0.5f, 0.4f, 0.3f);
    s.pops = {minors};
    far::FarDials d = exact_haze_dials();
    d.haze_start_gu = 2500.0f;
    d.haze_start_ramp_gu = 0.0f;
    HazePixels pix;
    for (int y = 20; y <= 44; y += 4)
        for (int x = 20; x <= 44; x += 4) pix.push_back({x, y});
    float centre_alpha[2] = {0.0f, 0.0f};
    haze_matches_cpu(*pipeline, s, origin_sys, 3000.0f, centre_alpha, pix, d);
    EXPECT_GT(centre_alpha[0], 0.02f) << "the far half of the field hazes";
}

namespace {
// Renders `src` at (w, h) with `dials` into a cleared target over a far
// (depth-free) scene, using `pass`; returns the RGBA floats.
// `occluder_gu` > 0: the left `split_x` columns of the scene depth are a
// plane that far ahead (a near occluder), the rest open space.
std::vector<float> render_haze_image(renderer::Pipeline& pipeline, renderer::FarPass& pass,
                                     const far::DiscSource& src, const glm::dvec3& origin_sys,
                                     int w, int h, const far::FarDials& dials,
                                     float occluder_gu = 0.0f, int split_x = 0) {
    renderer::HdrTarget scene, out;   // HdrTarget::resize binds on the ACTIVE unit
    scene.resize(w, h);
    out.resize(w, h);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, 0);
    scenegraph::Camera cam = haze_camera();
    cam.aspect = static_cast<float>(w) / static_cast<float>(h);
    const glm::mat4 inv_vp = glm::inverse(cam.proj_matrix() * cam.view_matrix());
    renderer::Lighting l;
    l.ambient = glm::vec3(0.1f, 0.12f, 0.15f);
    l.directional_count = 1;
    l.directional_dir_ws[0] = glm::normalize(glm::vec3(1.0f, 0.3f, 0.5f));
    l.directional_color[0] = glm::vec3(1.0f, 0.9f, 0.8f);
    scene.bind();
    glViewport(0, 0, w, h);
    glDepthMask(GL_TRUE);
    glClearDepth(1.0);
    glClear(GL_DEPTH_BUFFER_BIT);
    if (occluder_gu > 0.0f) {
        const glm::vec4 clip = cam.proj_matrix() * glm::vec4(0.0f, 0.0f, -occluder_gu, 1.0f);
        glEnable(GL_SCISSOR_TEST);
        glScissor(0, 0, split_x, h);
        glClearDepth(static_cast<double>(clip.z / clip.w * 0.5f + 0.5f));
        glClear(GL_DEPTH_BUFFER_BIT);
        glClearDepth(1.0);
        glDisable(GL_SCISSOR_TEST);
    }
    out.bind();
    glViewport(0, 0, w, h);
    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    pass.render_haze({src}, origin_sys, cam, pipeline, l, 0.7f, scene.depth_texture(), inv_vp,
                     dials);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    std::vector<float> px(static_cast<std::size_t>(w) * h * 4);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, out.fbo());
    glReadPixels(0, 0, w, h, GL_RGBA, GL_FLOAT, px.data());
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    return px;
}
}  // namespace

// Rock-fields Task 12: the haze marches at quarter resolution and is
// depth-aware upsampled. Over open space (no depth edges) the result is the
// full-resolution haze to within 2/255 on average, in every channel -- at the
// main view's size and again, through the SAME pass, at a different
// (viewscreen-RTT-like) size, so the low-res target follows the target size.
TEST_F(FarPassGLTest, QuarterResHazeMatchesFullResInOpenSpace) {
    const glm::dvec3 origin_sys(278000.0, 0.0, 0.0);
    far::DiscSource s = haze_source(origin_sys);
    s.table = {{0.0f, 1.0f}, {20000.0f, 1.0f}};
    s.gain_scale = 4.0f;
    s.brightness = 8.0f;
    s.seed = 0xdeadbeefu;
    s.noise_scale_gu = 4000.0f; s.noise_contrast = 0.8f; s.noise_octaves = 3;
    far::FarDials full = exact_haze_dials();
    far::FarDials quarter = full;
    quarter.haze_res_divisor = 4;
    renderer::FarPass pass;
    for (const auto& [w, h] : {std::pair<int, int>{64, 64}, std::pair<int, int>{96, 40},
                               std::pair<int, int>{64, 64}}) {
        const std::vector<float> a = render_haze_image(*pipeline, pass, s, origin_sys, w, h, full);
        const std::vector<float> b = render_haze_image(*pipeline, pass, s, origin_sys, w, h, quarter);
        double sum = 0.0, mean_alpha = 0.0;
        for (std::size_t i = 0; i < a.size(); ++i) sum += std::fabs(a[i] - b[i]);
        for (std::size_t i = 3; i < a.size(); i += 4) mean_alpha += a[i];
        const double mad = sum / static_cast<double>(a.size());
        mean_alpha /= static_cast<double>(a.size() / 4);
        std::printf("[far_pass_test] quarter-res haze %dx%d: mean |full - quarter| %.5f "
                    "(%.3f/255), mean full alpha %.4f\n", w, h, mad, mad * 255.0, mean_alpha);
        EXPECT_GT(mean_alpha, 0.03) << "a real haze to compare";
        EXPECT_LT(mad, 2.0 / 255.0) << w << "x" << h;
    }
}

// The march resolution follows the TARGET each call (the viewscreen RTT is a
// different size from the main view) at (w / d, h / d), at least 1x1; divisor
// 1 marches at full size, and a divisor below 1 is floored to 1.
TEST_F(FarPassGLTest, HazeMarchesAtTheTargetSizeOverTheDivisor) {
    const glm::dvec3 origin_sys(278000.0, 0.0, 0.0);
    const far::DiscSource s = haze_source(origin_sys);
    renderer::FarPass pass;
    far::FarDials d = exact_haze_dials();
    d.haze_res_divisor = 4;
    render_haze_image(*pipeline, pass, s, origin_sys, 64, 64, d);
    EXPECT_EQ(pass.last_haze_march_size(), glm::ivec2(16, 16));
    render_haze_image(*pipeline, pass, s, origin_sys, 96, 40, d);
    EXPECT_EQ(pass.last_haze_march_size(), glm::ivec2(24, 10));
    d.haze_res_divisor = 1;
    render_haze_image(*pipeline, pass, s, origin_sys, 96, 40, d);
    EXPECT_EQ(pass.last_haze_march_size(), glm::ivec2(96, 40));
    d.haze_res_divisor = 0;
    render_haze_image(*pipeline, pass, s, origin_sys, 64, 64, d);
    EXPECT_EQ(pass.last_haze_march_size(), glm::ivec2(64, 64));
    d.haze_res_divisor = 200;
    render_haze_image(*pipeline, pass, s, origin_sys, 64, 64, d);
    EXPECT_EQ(pass.last_haze_march_size(), glm::ivec2(1, 1));
}

// Fix round 1: depth edges. A near occluder (3,000 GU, before the default
// 6,000 GU haze start, so it carries NO haze at full resolution) covers the
// left half; open space with haze behind it on the right. At quarter
// resolution the depth-aware upsample must not bleed haze onto the occluder:
// occluder pixels >= 3 px from the edge get < 2/255 in every channel. And
// next to the edge (8 px either side) full vs quarter stays bounded.
TEST_F(FarPassGLTest, QuarterResHazeDoesNotBleedOntoANearOccluder) {
    constexpr int W = 128, H = 64;
    const glm::dvec3 origin_sys(278000.0, 0.0, 0.0);
    far::DiscSource s = haze_source(origin_sys);
    s.table = {{0.0f, 1.0f}, {20000.0f, 1.0f}};
    s.gain_scale = 8.0f;
    s.brightness = 8.0f;
    s.seed = 0xdeadbeefu;
    s.noise_scale_gu = 4000.0f; s.noise_contrast = 0.8f; s.noise_octaves = 3;
    far::FarDials full;   // default start 6,000 / ramp 2,000
    full.haze_res_divisor = 1;
    far::FarDials quarter = full;
    quarter.haze_res_divisor = 4;
    renderer::FarPass pass;
    // Every edge phase against the 4 px low-res grid: 64 is aligned; 66 (and
    // 62) put a low-res texel's centre on the open side of an occluder pixel,
    // which leaked 7.5/255 with the non-linear depth weight.
    for (const int kSplit : {64, 65, 66, 67, 62}) {
    const auto a = render_haze_image(*pipeline, pass, s, origin_sys, W, H, full, 3000.0f, kSplit);
    const auto b = render_haze_image(*pipeline, pass, s, origin_sys, W, H, quarter, 3000.0f, kSplit);
    float occ_full = 0.0f, occ_quarter = 0.0f, open_alpha = 0.0f;
    double edge_sum = 0.0, edge_max = 0.0;
    int edge_n = 0;
    for (int y = 0; y < H; ++y)
        for (int x = 0; x < W; ++x)
            for (int c = 0; c < 4; ++c) {
                const std::size_t i = (static_cast<std::size_t>(y) * W + x) * 4 + c;
                if (x <= kSplit - 4) {   // >= 3 px from the edge (edge between 63 and 64)
                    occ_full = std::max(occ_full, a[i]);
                    occ_quarter = std::max(occ_quarter, b[i]);
                }
                if (x >= kSplit + 3 && c == 3) open_alpha = std::max(open_alpha, a[i]);
                if (x >= kSplit - 8 && x < kSplit + 8) {
                    const double d = std::fabs(a[i] - b[i]);
                    edge_sum += d; edge_max = std::max(edge_max, d); ++edge_n;
                }
            }
    const double edge_mean = edge_sum / edge_n;
    std::printf("[far_pass_test] depth edge at %d: occluder max full %.5f quarter %.5f "
                "(%.2f/255); open max alpha %.4f; edge band |full - quarter| mean %.5f "
                "(%.2f/255) max %.5f\n", kSplit, occ_full, occ_quarter, occ_quarter * 255.0f,
                open_alpha, edge_mean, edge_mean * 255.0, edge_max);
    EXPECT_EQ(occ_full, 0.0f) << "the occluder sits before the haze start";
    EXPECT_GT(open_alpha, 0.05f) << "real haze behind the edge";
    EXPECT_LT(occ_quarter, 2.0f / 255.0f) << "haze bleeds onto the occluder, edge " << kSplit;
    EXPECT_LT(edge_mean, 2.0 / 255.0) << "edge " << kSplit;
    }
}

// The low-res path puts back what it changes: the caller's framebuffer,
// viewport and blend function, active texture unit 0 -- and the documented
// frame defaults (blend off, depth test and writes on).
TEST_F(FarPassGLTest, QuarterResHazeRestoresTheCallersState) {
    renderer::HdrTarget scene, out;
    scene.resize(kHazeSize, kHazeSize);
    out.resize(kHazeSize, kHazeSize);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, 0);
    const scenegraph::Camera cam = haze_camera();
    const glm::mat4 inv_vp = glm::inverse(cam.proj_matrix() * cam.view_matrix());
    renderer::Lighting l;
    far::FarDials dials;
    ASSERT_EQ(dials.haze_res_divisor, 4);
    out.bind();
    glViewport(3, 5, kHazeSize - 7, kHazeSize - 9);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);
    glClearColor(0.25f, 0.5f, 0.75f, 1.0f);   // the caller's clear colour, to be kept
    renderer::FarPass pass;
    pass.render_haze({haze_source()}, glm::dvec3(278000.0, 0.0, 0.0), cam, *pipeline, l, 1.0f,
                     scene.depth_texture(), inv_vp, dials);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    GLint fbo = 0, vp[4] = {0, 0, 0, 0}, unit = 0, src = 0, dst = 0;
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fbo);
    glGetIntegerv(GL_VIEWPORT, vp);
    glGetIntegerv(GL_ACTIVE_TEXTURE, &unit);
    glGetIntegerv(GL_BLEND_SRC_RGB, &src);
    glGetIntegerv(GL_BLEND_DST_RGB, &dst);
    EXPECT_EQ(static_cast<GLuint>(fbo), out.fbo());
    EXPECT_EQ(vp[0], 3); EXPECT_EQ(vp[1], 5);
    EXPECT_EQ(vp[2], kHazeSize - 7); EXPECT_EQ(vp[3], kHazeSize - 9);
    EXPECT_EQ(unit, GL_TEXTURE0);
    EXPECT_EQ(src, GL_SRC_ALPHA);
    EXPECT_EQ(dst, GL_ONE);
    EXPECT_FALSE(glIsEnabled(GL_BLEND));
    EXPECT_TRUE(glIsEnabled(GL_DEPTH_TEST));
    GLboolean depth_write = GL_FALSE;
    glGetBooleanv(GL_DEPTH_WRITEMASK, &depth_write);
    EXPECT_TRUE(depth_write);
    GLfloat clear[4] = {0, 0, 0, 0};
    glGetFloatv(GL_COLOR_CLEAR_VALUE, clear);
    EXPECT_EQ(glm::vec4(clear[0], clear[1], clear[2], clear[3]),
              glm::vec4(0.25f, 0.5f, 0.75f, 1.0f));
    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    glBlendFunc(GL_ONE, GL_ZERO);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}

// Tile-field haze noise (2026-10-02): the same sphere with the production
// noise (250 GU, contrast 0.8, 3 octaves), its own 48 steps and a seed above
// INT_MAX (the uint hash path) matches haze_column within 0.001 over a 7x7
// grid of pixels across the field -- the GLSL value noise is the CPU's twin.
TEST_F(FarPassGLTest, NoisySphereHazeShaderMatchesTheCpuReference) {
    const glm::dvec3 origin_sys(278000.0, 0.0, 0.0);
    far::DiscSource s;
    s.id = 3; s.shape = far::DiscSource::Shape::Sphere; s.procedural = false;
    s.centre = origin_sys + glm::dvec3(0.0, 2500.0, 0.0);
    s.sphere_radius_gu = 1000.0f; s.sphere_edge_frac = 0.2f;
    s.gain_scale = 14140.0f / 270.0f;
    s.brightness = 9.1f;
    s.seed = 0xdeadbeefu;
    s.noise_scale_gu = 250.0f; s.noise_contrast = 0.8f; s.noise_octaves = 3;
    s.steps = 48;
    far::Population minors;
    minors.kind = 0; minors.a_lo = 0.0f; minors.a_hi = 1.0f;
    minors.density_at_1 = 405.0f / (4.0f / 3.0f * 3.14159265f * 1.0e9f);
    minors.size = {0.05f, 0.7f, 2.5f};
    minors.albedo = glm::vec3(0.5f, 0.4f, 0.3f);
    s.pops = {minors};
    HazePixels pix;
    for (int y = 20; y <= 44; y += 4)
        for (int x = 20; x <= 44; x += 4) pix.push_back({x, y});
    float centre_alpha[2] = {0.0f, 0.0f};
    const float max_diff = haze_matches_cpu(*pipeline, s, origin_sys, 2600.0f, centre_alpha, pix);
    std::printf("[far_pass_test] noisy sphere shader-vs-CPU max alpha diff %.6f\n", max_diff);
    EXPECT_GT(centre_alpha[0], 0.05f) << "the far view sees the field";
}

// Rock-fields R1 (2026-10-02): belts carry the noise too. A noisy Disc source
// (the production belt noise: 4,000 GU, contrast 0.8, 3 octaves) centred on
// the eye matches haze_column within 0.001, with and without an occluder.
TEST_F(FarPassGLTest, NoisyDiscHazeShaderMatchesTheCpuReference) {
    const glm::dvec3 origin_sys(278000.0, 0.0, 0.0);
    far::DiscSource s = haze_source(origin_sys);
    s.table = {{0.0f, 1.0f}, {20000.0f, 1.0f}};
    s.gain_scale = 4.0f;    // a visible column over the shorter chord
    s.brightness = 8.0f;
    s.seed = 0xdeadbeefu;
    s.noise_scale_gu = 4000.0f; s.noise_contrast = 0.8f; s.noise_octaves = 3;
    HazePixels pix;
    for (int y = 20; y <= 44; y += 4)
        for (int x = 20; x <= 44; x += 4) pix.push_back({x, y});
    float centre_alpha[2] = {0.0f, 0.0f};
    const float max_diff = haze_matches_cpu(*pipeline, s, origin_sys, 10000.0f, centre_alpha, pix);
    std::printf("[far_pass_test] noisy disc shader-vs-CPU max alpha diff %.6f\n", max_diff);
    EXPECT_GT(centre_alpha[0], 0.05f) << "the far view sees the belt";
}

// One fullscreen draw per active source, at most 4; none for no sources. GL
// state is restored: blend off, depth test and depth writes on, the caller's
// blend function kept.
TEST_F(FarPassGLTest, HazeDrawsOncePerSourceAndCapsAtFour) {
    renderer::HdrTarget scene, out;
    scene.resize(kHazeSize, kHazeSize);
    out.resize(kHazeSize, kHazeSize);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, 0);
    const scenegraph::Camera cam = haze_camera();
    const glm::mat4 inv_vp = glm::inverse(cam.proj_matrix() * cam.view_matrix());
    renderer::Lighting l;
    const far::FarDials dials;

    out.bind();
    glViewport(0, 0, kHazeSize, kHazeSize);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE);     // a caller's blend function, to be kept
    renderer::FarPass pass;
    for (int n : {0, 1, 2, 4, 6}) {
        std::vector<far::DiscSource> srcs;
        for (int i = 0; i < n; ++i) srcs.push_back(haze_source(glm::dvec3(1000.0 * i, 0.0, 0.0)));
        pass.reset_counts();
        pass.render_haze(srcs, glm::dvec3(278000.0, 0.0, 0.0), cam, *pipeline, l, 1.0f,
                         scene.depth_texture(), inv_vp, dials);
        EXPECT_EQ(pass.last_draw_calls(), std::min(n, 4)) << n << " sources";
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    }
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    EXPECT_FALSE(glIsEnabled(GL_BLEND));
    EXPECT_TRUE(glIsEnabled(GL_DEPTH_TEST));
    GLboolean depth_write = GL_FALSE;
    glGetBooleanv(GL_DEPTH_WRITEMASK, &depth_write);
    EXPECT_TRUE(depth_write);
    GLint src = 0, dst = 0;
    glGetIntegerv(GL_BLEND_SRC_RGB, &src);
    glGetIntegerv(GL_BLEND_DST_RGB, &dst);
    EXPECT_EQ(src, GL_SRC_ALPHA);
    EXPECT_EQ(dst, GL_ONE);
    glBlendFunc(GL_ONE, GL_ZERO);
}

// A source with no populations (its catalogue family missing) has nothing to
// march: no fullscreen draw for it, while a populated source still draws.
TEST_F(FarPassGLTest, HazeSkipsASourceWithNoPopulations) {
    renderer::HdrTarget scene, out;
    scene.resize(kHazeSize, kHazeSize);
    out.resize(kHazeSize, kHazeSize);
    const scenegraph::Camera cam = haze_camera();
    const glm::mat4 inv_vp = glm::inverse(cam.proj_matrix() * cam.view_matrix());
    renderer::Lighting l;
    const far::FarDials dials;
    far::DiscSource empty = haze_source();
    empty.pops.clear();

    out.bind();
    glViewport(0, 0, kHazeSize, kHazeSize);
    renderer::FarPass pass;
    pass.reset_counts();
    pass.render_haze({empty}, glm::dvec3(278000.0, 0.0, 0.0), cam, *pipeline, l, 1.0f,
                     scene.depth_texture(), inv_vp, dials);
    EXPECT_EQ(pass.last_draw_calls(), 0);
    pass.reset_counts();
    pass.render_haze({empty, haze_source()}, glm::dvec3(278000.0, 0.0, 0.0), cam, *pipeline, l,
                     1.0f, scene.depth_texture(), inv_vp, dials);
    EXPECT_EQ(pass.last_draw_calls(), 1);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
}
