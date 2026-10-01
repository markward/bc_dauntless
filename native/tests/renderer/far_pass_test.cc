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

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <renderer/far_field.h>
#include <renderer/far_pass.h>
#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/scuff_texture.h>
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
