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
