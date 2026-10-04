// native/tests/renderer/far_dither_test.cc
//
// Far tier (far-tier spec §1, §3): the screen-door crossfade between a rock's
// mesh and its impostor lives in the SHARED opaque.frag. A mesh fading out
// carries Instance::far_fade = d > 0 (keeps the UPPER 1 - d of the Bayer
// range); an impostor carries -d (keeps the LOWER d). The Bayer cell is
// chosen per 2x2 pixel group (a 4x4 matrix over groups: an 8x8 pixel
// period), never per pixel. Equal |d| must be exact
// complements, far_fade >= 1 must skip the mesh, and far_fade == 0 must leave
// the production hull path byte-identical. u_coverage_cutout discards texels
// whose base alpha is < 0.5 (impostor silhouettes).
//
// The fixture follows minor_pass_test.cc: a hidden renderer::Window,
// GTEST_SKIP only when no GL context exists, a hand-built one-node one-mesh
// assets::Model uploaded through assets::upload_mesh, and pixel readback.

#include <gtest/gtest.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

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

#include <cmath>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <vector>

namespace {

constexpr int kW = 64;
constexpr int kH = 64;

constexpr float kCubeHalf = 0.3f;

// The four-texel base texture minor_pass_test.cc uses: every texel opaque.
assets::Image default_image() {
    assets::Image img;
    img.width = 2;
    img.height = 2;
    img.format = assets::Image::Format::RGBA8;
    img.pixels = {230, 60, 40, 255,   40, 200, 70, 255,
                  50, 80, 220, 255,   240, 230, 90, 255};
    return img;
}

// A cube of half-extent `h` with per-face outward normals, per-face UVs and
// CCW-from-outside winding (front faces under the pipeline's GL_CCW), plus a
// material with a non-white diffuse and the given base texture.
assets::Model make_cube_model(float h, const assets::Image& img = default_image()) {
    assets::MeshCpu cpu;
    struct Face { glm::vec3 n, u, v; };
    const Face faces[6] = {
        {{ 1, 0, 0}, {0, 1, 0}, {0, 0, 1}}, {{-1, 0, 0}, {0, 0, 1}, {0, 1, 0}},
        {{ 0, 1, 0}, {0, 0, 1}, {1, 0, 0}}, {{ 0,-1, 0}, {1, 0, 0}, {0, 0, 1}},
        {{ 0, 0, 1}, {1, 0, 0}, {0, 1, 0}}, {{ 0, 0,-1}, {0, 1, 0}, {1, 0, 0}},
    };
    for (const Face& f : faces) {
        const auto base = static_cast<std::uint32_t>(cpu.vertices.size());
        const glm::vec2 uvs[4] = {{0, 0}, {1, 0}, {1, 1}, {0, 1}};
        const glm::vec3 corners[4] = {
            h * (f.n - f.u - f.v), h * (f.n + f.u - f.v),
            h * (f.n + f.u + f.v), h * (f.n - f.u + f.v),
        };
        for (int k = 0; k < 4; ++k) {
            assets::MeshCpu::Vertex vert;
            vert.position = corners[k];
            vert.normal   = f.n;
            vert.uv       = uvs[k];
            cpu.vertices.push_back(vert);
        }
        for (std::uint32_t i : {0u, 1u, 2u, 0u, 2u, 3u}) cpu.indices.push_back(base + i);
    }
    cpu.material_index = 0;

    assets::Model m;
    m.meshes.push_back(assets::upload_mesh(cpu));
    assets::Node node;
    node.parent_index    = -1;
    node.local_transform = glm::mat4(1.0f);
    node.meshes          = {0};
    m.nodes.push_back(node);
    m.root_node = 0;

    m.textures.push_back(assets::upload_image(img, /*generate_mipmaps=*/false));

    assets::Material mat;
    mat.diffuse  = glm::vec3(0.9f, 0.8f, 0.7f);
    mat.emissive = glm::vec3(0.02f, 0.01f, 0.0f);
    mat.stages[static_cast<std::size_t>(assets::Material::StageSlot::Base)]
        .texture_index = 0;
    m.materials.push_back(mat);
    return m;
}

std::uint64_t handle_of(const assets::Model& m) {
    return static_cast<std::uint64_t>(reinterpret_cast<std::uintptr_t>(&m));
}

const assets::Model* lookup_handle(std::uint64_t h) {
    return reinterpret_cast<const assets::Model*>(static_cast<std::uintptr_t>(h));
}

class FarDitherGLTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   w;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "far-dither-test", false);
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

    static renderer::Lighting test_lighting() {
        renderer::Lighting l;
        l.ambient               = glm::vec3(0.15f, 0.12f, 0.1f);
        l.ambient_dir_ws        = glm::normalize(glm::vec3(0.2f, 1.0f, 0.1f));
        l.ambient_gradient      = 0.4f;
        l.directional_count     = 1;
        l.directional_dir_ws[0] = glm::normalize(glm::vec3(0.6f, 0.8f, 0.5f));
        l.directional_color[0]  = glm::vec3(1.0f, 0.95f, 0.9f);
        return l;
    }

    static scenegraph::Camera test_camera(glm::vec3 target) {
        scenegraph::Camera c;
        c.eye       = target + glm::vec3(1.1f, 0.9f, 1.6f);
        c.target    = target;
        c.up        = glm::vec3(0.0f, 1.0f, 0.0f);
        c.fov_y_rad = glm::radians(45.0f);
        c.aspect    = 1.0f;
        c.near      = 0.1f;
        c.far       = 100.0f;
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
        return (buf[i * 4] + buf[i * 4 + 1] + buf[i * 4 + 2]) > 0;
    }

    static int lit_pixels(const std::vector<unsigned char>& buf) {
        int n = 0;
        for (int i = 0; i < kW * kH; ++i) n += lit(buf, i) ? 1 : 0;
        return n;
    }

    static constexpr glm::vec3 kCentre{0.0f, 0.0f, -3.0f};

    // One instance of `model` at kCentre with Instance::far_fade = fade, drawn
    // through FrameSubmitter::submit_opaque_in_pass(Pass::Space).
    std::vector<unsigned char> draw_instance(const assets::Model& model, float fade) {
        clear_framebuffer();
        scenegraph::World sg;
        const auto iid = sg.create_instance(
            static_cast<scenegraph::ModelHandle>(handle_of(model)));
        sg.set_world_transform(iid, glm::translate(glm::mat4(1.0f), kCentre));
        sg.get(iid)->far_fade = fade;
        renderer::FrameSubmitter submitter;
        submitter.submit_opaque_in_pass(
            sg, test_camera(kCentre), *pipeline,
            [](scenegraph::ModelHandle h) { return lookup_handle(h); },
            test_lighting(), scenegraph::Pass::Space);
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
        return read_frame();
    }

    // Like draw_instance(model, 0) but with u_dither_fade set DIRECTLY on the
    // static program to `d` (as an impostor's vertex shader would supply a
    // negative value). A far_fade-0 instance never touches the uniform, so the
    // raw value is what the draw sees; it is reset to 0 afterwards.
    std::vector<unsigned char> draw_with_raw_dither(const assets::Model& model, float d) {
        auto& s = pipeline->opaque_shader();
        s.use();
        s.set_float("u_dither_fade", d);
        auto px = draw_instance(model, 0.0f);
        s.use();
        s.set_float("u_dither_fade", 0.0f);
        return px;
    }

    // draw_instance(model, 0) with u_coverage_cutout set on the static program.
    std::vector<unsigned char> draw_with_cutout(const assets::Model& model, int cutout) {
        auto& s = pipeline->opaque_shader();
        s.use();
        s.set_int("u_coverage_cutout", cutout);
        auto px = draw_instance(model, 0.0f);
        s.use();
        s.set_int("u_coverage_cutout", 0);
        return px;
    }
};

constexpr glm::vec3 FarDitherGLTest::kCentre;

}  // namespace

// 1. Byte-identity: an instance with far_fade 0 renders exactly as before.
//    "Before" = the same draw with u_dither_fade never touched; compare to a
//    draw after a previous instance used far_fade 0.5 (the reset must hold).
TEST_F(FarDitherGLTest, ZeroFadeIsByteIdentical) {
    const assets::Model cube = make_cube_model(kCubeHalf);
    const auto a = draw_instance(cube, /*fade=*/0.0f);
    (void)draw_instance(cube, 0.5f);
    const auto b = draw_instance(cube, 0.0f);
    ASSERT_GT(lit_pixels(a), kW * kH / 20);
    EXPECT_EQ(a, b);
}

// 2. far_fade >= 1 draws nothing.
TEST_F(FarDitherGLTest, FullFadeSkipsTheInstance) {
    const assets::Model cube = make_cube_model(kCubeHalf);
    ASSERT_GT(lit_pixels(draw_instance(cube, 0.0f)), kW * kH / 20);
    EXPECT_EQ(lit_pixels(draw_instance(cube, 1.0f)), 0);
}

// 3. Complement: a fade-d draw plus a -d draw of the same geometry (through
//    u_dither_fade = -d set directly) cover every pixel the undithered draw
//    covers, exactly once, for d in {0.25, 0.5, 0.75}.
TEST_F(FarDitherGLTest, OppositeSignsAreExactComplements) {
    const assets::Model cube = make_cube_model(kCubeHalf);
    const auto full = draw_instance(cube, 0.0f);
    ASSERT_GT(lit_pixels(full), kW * kH / 20);
    for (float d : {0.25f, 0.5f, 0.75f}) {
        const auto pos = draw_instance(cube, d);
        const auto neg = draw_with_raw_dither(cube, -d);
        int mismatches = 0;
        for (int i = 0; i < kW * kH; ++i) {
            const bool f = lit(full, i), p = lit(pos, i), n = lit(neg, i);
            if (f != (p || n) || (p && n)) ++mismatches;
        }
        EXPECT_EQ(mismatches, 0) << "d=" << d;
        // And the kept fraction is close to 1 - d.
        EXPECT_NEAR(lit_pixels(pos) / static_cast<float>(lit_pixels(full)), 1.0f - d, 0.08f)
            << "d=" << d;
    }
}

// 4. Coverage cutout: a texture whose left texel has alpha 0 draws only the
//    texels with alpha >= 0.5. Without the cutout every face pixel is lit
//    (lighting alone lights the transparent half); with it some are discarded
//    and none appear that the plain draw did not light.
TEST_F(FarDitherGLTest, CoverageCutoutDiscardsTransparentTexels) {
    assets::Image img;
    img.width = 2;
    img.height = 1;
    img.format = assets::Image::Format::RGBA8;
    img.pixels = {0, 0, 0, 0,   200, 200, 200, 255};
    const assets::Model cube = make_cube_model(kCubeHalf, img);

    const auto plain = draw_with_cutout(cube, 0);
    const auto cut   = draw_with_cutout(cube, 1);
    ASSERT_GT(lit_pixels(plain), kW * kH / 20);
    EXPECT_LT(lit_pixels(cut), lit_pixels(plain));
    EXPECT_GT(lit_pixels(cut), 0) << "the opaque half must still draw";
    int stray = 0;
    for (int i = 0; i < kW * kH; ++i)
        if (lit(cut, i) && !lit(plain, i)) ++stray;
    EXPECT_EQ(stray, 0);

    // And the default (0) is restored: a later plain draw matches the first.
    EXPECT_EQ(draw_with_cutout(cube, 0), plain);
}
