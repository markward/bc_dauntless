// native/tests/renderer/minor_pass_test.cc
//
// MinorPass (minor-rocks spec §2): the instanced draw of minor rocks through
// minor.vert + the EXISTING opaque.frag. The load-bearing claim is that a
// minor is lit exactly as a major is, so the key test renders one cube twice
// -- once through the ordinary opaque path (FrameSubmitter::
// submit_opaque_instance -> draw_model) and once as a one-minor MinorField
// through MinorPass -- and requires every pixel to match. Same fragment
// shader, same inputs: there is no tolerance to give.
//
// The fixture follows breach_pass_test.cc: a hidden renderer::Window,
// GTEST_SKIP only when no GL context exists, a hand-built one-node one-mesh
// assets::Model uploaded through assets::upload_mesh, and pixel readback.

#include <gtest/gtest.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <renderer/frame.h>
#include <renderer/minor_field.h>
#include <renderer/minor_pass.h>
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

namespace minors = renderer::minors;

constexpr int kW = 64;
constexpr int kH = 64;

// Every catalogue fragment's bound radius at load scale 1 (constraints.md).
constexpr float kBoundMu = 57.142857f;
// A real-sized fragment: a cube whose corner radius is exactly kBoundMu.
const float kCubeHalf = kBoundMu / std::sqrt(3.0f);

// A cube of half-extent `h` with per-face outward normals, per-face UVs and
// CCW-from-outside winding (front faces under the pipeline's GL_CCW), plus a
// material with a non-white diffuse and a 2x2 base texture whose four texels
// differ -- so the pixel comparison also covers texture binding and UVs.
assets::Model make_cube_model(float h) {
    assets::MeshCpu cpu;
    struct Face { glm::vec3 n, u, v; };
    const Face faces[6] = {
        {{ 1, 0, 0}, {0, 1, 0}, {0, 0, 1}}, {{-1, 0, 0}, {0, 0, 1}, {0, 1, 0}},
        {{ 0, 1, 0}, {0, 0, 1}, {1, 0, 0}}, {{ 0,-1, 0}, {1, 0, 0}, {0, 0, 1}},
        {{ 0, 0, 1}, {1, 0, 0}, {0, 1, 0}}, {{ 0, 0,-1}, {0, 1, 0}, {1, 0, 0}},
    };
    for (const Face& f : faces) {
        // cross(u, v) == n for every face above, so (0,1,2),(0,2,3) is CCW
        // seen from outside.
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

    assets::Image img;
    img.width = 2;
    img.height = 2;
    img.format = assets::Image::Format::RGBA8;
    img.pixels = {230, 60, 40, 255,   40, 200, 70, 255,
                  50, 80, 220, 255,   240, 230, 90, 255};
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

class MinorPassGLTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   w;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "minor-pass-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        pipeline = std::make_unique<renderer::Pipeline>();
    }

    // Release draw_model's session-scoped GL state while this context is
    // current, exactly as frame_test.cc does.
    void TearDown() override {
        if (!w) return;
        renderer::reset_damage_decal_texture();
        renderer::reset_scuff_normal_texture();
        renderer::reset_decal_mask_sampler();
        renderer::reset_model_radius_cache();
    }

    // One directional key light plus a directional ambient, so the ambient
    // helper's three uniforms all matter to the picture.
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

    // Looking at the cube's centre from up and to the right, so three faces
    // (three different normals) are visible.
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

    static minors::StepInput step_input(const scenegraph::Camera& cam, double t = 0.0) {
        minors::StepInput in;
        in.game_time  = t;
        in.view       = cam.view_matrix();
        in.proj       = cam.proj_matrix();
        in.viewport_h = static_cast<float>(kH);
        return in;
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

    static int lit_pixels(const std::vector<unsigned char>& buf) {
        int n = 0;
        for (int i = 0; i < kW * kH; ++i)
            n += (buf[i * 4] + buf[i * 4 + 1] + buf[i * 4 + 2]) > 0 ? 1 : 0;
        return n;
    }

    // Render `world` (a RENDER-space instance world) through the ordinary
    // opaque path. rim_eligible defaults false, so rim strength is 0.
    std::vector<unsigned char> draw_major(const assets::Model& model, const glm::mat4& world,
                                          const scenegraph::Camera& cam,
                                          const renderer::Lighting& lighting) {
        clear_framebuffer();
        scenegraph::World sg;
        const auto iid = sg.create_instance(
            static_cast<scenegraph::ModelHandle>(handle_of(model)));
        sg.set_world_transform(iid, world);
        renderer::FrameSubmitter submitter;
        submitter.submit_opaque_instance(
            sg, iid, cam, *pipeline,
            [](scenegraph::ModelHandle h) { return lookup_handle(h); }, lighting);
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
        return read_frame();
    }

    std::vector<unsigned char> draw_minors(renderer::MinorPass& pass,
                                           const minors::MinorField& field,
                                           const scenegraph::Camera& cam,
                                           const renderer::Lighting& lighting) {
        clear_framebuffer();
        pass.render(field, cam, *pipeline,
                    [](std::uint64_t h) { return lookup_handle(h); },
                    lighting, /*ambient_scale=*/1.0f, /*rim_strength=*/0.0f);
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
        return read_frame();
    }

    // A field holding ONE fragment family (0) of `n` slots, every slot and LOD
    // resolving to `model`.
    static void set_family(minors::MinorField& field, const assets::Model& model, int n) {
        std::vector<minors::Fragment> frags;
        for (int i = 0; i < n; ++i)
            frags.push_back({handle_of(model), handle_of(model), kBoundMu});
        field.set_fragments(0, frags);
    }

    // One minor of radius r, exactly at `centre` (shell 0), no tumble, no
    // orbit, phase set to `phase`.
    static void one_minor_cloud(minors::MinorField& field, glm::vec3 centre, float r,
                                float phase) {
        minors::Dials d;
        d.tumble_min = 0.0f;
        d.tumble_max = 0.0f;
        field.set_dials(d);
        minors::CloudDesc c;
        c.id = 1;
        c.anchor = minors::Anchor::Point;
        c.point = glm::dvec3(centre);
        c.shell_inner = 0.0f;
        c.shell_outer = 0.0f;
        c.count = 1;
        c.r_min = r;
        c.r_max = r;
        c.family = 0;
        c.seed = 11;
        field.add_cloud(c, 0.0);
        field.debug_set_phase(1, 0, phase);
    }

    static glm::mat4 world_of(const minors::InstanceGpu& g) {
        return glm::transpose(glm::mat4(g.row0, g.row1, g.row2, glm::vec4(0, 0, 0, 1)));
    }
};

}  // namespace

// Same fragment shader, same inputs => identical pixels. The major draws the
// cube at world = translate(p) * scale(s), with s computed exactly as
// MinorField computes a minor's instance scale (r / bound_mu: model units
// straight to GU).
TEST_F(MinorPassGLTest, MatchesDrawModelPixelForPixel) {
    const assets::Model cube = make_cube_model(kCubeHalf);
    const glm::vec3 centre(0.0f, 0.0f, -3.0f);
    const float r = 0.5f;
    const float s = r / kBoundMu;
    const scenegraph::Camera cam = test_camera(centre);
    const renderer::Lighting lighting = test_lighting();

    const glm::mat4 world =
        glm::translate(glm::mat4(1.0f), centre) * glm::scale(glm::mat4(1.0f), glm::vec3(s));
    const auto a = draw_major(cube, world, cam, lighting);

    minors::MinorField field;
    set_family(field, cube, 1);
    one_minor_cloud(field, centre, r, /*phase=*/0.0f);
    field.step(step_input(cam));
    ASSERT_EQ(field.bins().size(), 1u);
    ASSERT_EQ(field.bins()[0].items.size(), 1u);
    // Precondition: the field produced exactly the major's world, so any
    // pixel difference below is MinorPass's.
    ASSERT_EQ(world_of(field.bins()[0].items[0]), world);

    renderer::MinorPass pass;
    const auto b = draw_minors(pass, field, cam, lighting);

    ASSERT_GT(lit_pixels(a), kW * kH / 20) << "the major draw put the cube on screen";
    ASSERT_EQ(a.size(), b.size());
    int differing = 0;
    for (std::size_t i = 0; i < a.size(); ++i) differing += a[i] != b[i] ? 1 : 0;
    EXPECT_EQ(differing, 0) << "minor pixels must equal the major's exactly";
    EXPECT_EQ(pass.last_draw_calls(), 1);
}

// A rotated pose pins the row layout of InstanceGpu through minor.vert: a
// transposed (row/column swapped) read would turn the cube the other way and
// light different faces. The major's world is rebuilt from the minor's rows.
TEST_F(MinorPassGLTest, RotatedMinorMatchesDrawModelPixelForPixel) {
    const assets::Model cube = make_cube_model(kCubeHalf);
    const glm::vec3 centre(0.0f, 0.0f, -3.0f);
    const scenegraph::Camera cam = test_camera(centre);
    const renderer::Lighting lighting = test_lighting();

    minors::MinorField field;
    set_family(field, cube, 1);
    one_minor_cloud(field, centre, 0.5f, /*phase=*/0.7f);
    field.step(step_input(cam));
    ASSERT_EQ(field.bins().size(), 1u);
    const glm::mat4 world = world_of(field.bins()[0].items[0]);
    ASSERT_NE(glm::mat3(world), glm::transpose(glm::mat3(world)))
        << "precondition: the pose is not symmetric, so a transpose would show";

    const auto a = draw_major(cube, world, cam, lighting);
    renderer::MinorPass pass;
    const auto b = draw_minors(pass, field, cam, lighting);

    ASSERT_GT(lit_pixels(a), kW * kH / 20);
    int differing = 0;
    for (std::size_t i = 0; i < a.size(); ++i) differing += a[i] != b[i] ? 1 : 0;
    EXPECT_EQ(differing, 0);
}

TEST_F(MinorPassGLTest, OneInstancedDrawPerNonEmptyBin) {
    const assets::Model cube = make_cube_model(kCubeHalf);
    const glm::vec3 centre(0.0f, 0.0f, -8.0f);
    const scenegraph::Camera cam = test_camera(centre);

    minors::MinorField field;
    set_family(field, cube, 2);
    minors::Dials d;
    d.lod0_pixel_radius = 6.0f;   // both LODs populated at this viewport size
    field.set_dials(d);
    minors::CloudDesc c;
    c.id = 3;
    c.anchor = minors::Anchor::Point;
    c.point = glm::dvec3(centre);
    c.shell_inner = 0.0f;
    c.shell_outer = 1.0f;
    c.count = 300;
    c.r_min = 0.05f;
    c.r_max = 0.6f;
    c.seed = 5;
    field.add_cloud(c, 0.0);
    field.step(step_input(cam));

    // Precondition: 2 slots x 2 LODs, every bin non-empty.
    ASSERT_EQ(field.bins().size(), 4u);
    std::size_t instances = 0;
    for (const auto& b : field.bins()) {
        ASSERT_FALSE(b.items.empty());
        instances += b.items.size();
    }
    ASSERT_GT(instances, field.bins().size()) << "some bin carries several instances";

    renderer::MinorPass pass;
    const auto px = draw_minors(pass, field, cam, renderer::Lighting{});
    EXPECT_EQ(pass.last_draw_calls(), static_cast<int>(field.bins().size()));
    EXPECT_GT(lit_pixels(px), 0);
}

TEST_F(MinorPassGLTest, ModelVaoIsNotModified) {
    const assets::Model cube = make_cube_model(kCubeHalf);
    const glm::vec3 centre(0.0f, 0.0f, -3.0f);
    const scenegraph::Camera cam = test_camera(centre);

    auto attrib7_enabled = [&] {
        glBindVertexArray(cube.meshes[0].vao());
        GLint enabled = -1;
        glGetVertexAttribiv(7, GL_VERTEX_ATTRIB_ARRAY_ENABLED, &enabled);
        GLint divisor = -1;
        glGetVertexAttribiv(7, GL_VERTEX_ATTRIB_ARRAY_DIVISOR, &divisor);
        glBindVertexArray(0);
        return std::pair<GLint, GLint>{enabled, divisor};
    };
    const auto before = attrib7_enabled();
    EXPECT_EQ(before.first, GL_FALSE);

    minors::MinorField field;
    set_family(field, cube, 1);
    one_minor_cloud(field, centre, 0.5f, 0.0f);
    field.step(step_input(cam));
    ASSERT_FALSE(field.bins().empty());
    renderer::MinorPass pass;
    draw_minors(pass, field, cam, renderer::Lighting{});
    ASSERT_EQ(pass.last_draw_calls(), 1);

    const auto after = attrib7_enabled();
    EXPECT_EQ(after.first, GL_FALSE);
    EXPECT_EQ(after.second, 0);
}

TEST_F(MinorPassGLTest, EmptyFieldIssuesNoDraws) {
    const assets::Model cube = make_cube_model(kCubeHalf);
    const glm::vec3 centre(0.0f, 0.0f, -3.0f);
    const scenegraph::Camera cam = test_camera(centre);

    minors::MinorField field;
    set_family(field, cube, 1);
    one_minor_cloud(field, centre, 0.5f, 0.0f);
    field.step(step_input(cam));
    renderer::MinorPass pass;
    draw_minors(pass, field, cam, renderer::Lighting{});
    ASSERT_EQ(pass.last_draw_calls(), 1);

    // Clouds gone: the next render resets the count and draws nothing.
    field.clear();
    field.step(step_input(cam));
    ASSERT_TRUE(field.bins().empty());
    const auto px = draw_minors(pass, field, cam, renderer::Lighting{});
    EXPECT_EQ(pass.last_draw_calls(), 0);
    EXPECT_EQ(lit_pixels(px), 0);
}

TEST_F(MinorPassGLTest, NullModelSkipsTheBin) {
    const assets::Model cube = make_cube_model(kCubeHalf);
    const glm::vec3 centre(0.0f, 0.0f, -3.0f);
    const scenegraph::Camera cam = test_camera(centre);

    minors::MinorField field;
    set_family(field, cube, 1);
    one_minor_cloud(field, centre, 0.5f, 0.0f);
    field.step(step_input(cam));
    ASSERT_EQ(field.bins().size(), 1u);

    renderer::MinorPass pass;
    clear_framebuffer();
    pass.render(field, cam, *pipeline,
                [](std::uint64_t) -> const assets::Model* { return nullptr; },
                renderer::Lighting{}, 1.0f, 0.0f);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    EXPECT_EQ(pass.last_draw_calls(), 0);
    EXPECT_EQ(lit_pixels(read_frame()), 0);
}

// Pins the per-bin instance offset: bin 0 (family 0, its model unresolvable)
// and bin 1 (family 1) each hold one minor at a different place. Bin 1 must
// draw at ITS OWN item's world -- pixel-for-pixel what draw_model draws there.
// A pass reading every bin's rows from offset 0 would draw bin 1 at bin 0's
// item instead.
TEST_F(MinorPassGLTest, EachBinDrawsItsOwnInstances) {
    const assets::Model hidden = make_cube_model(kCubeHalf);
    const assets::Model shown  = make_cube_model(kCubeHalf);
    const glm::vec3 centre(0.0f, 0.0f, -3.0f);
    const scenegraph::Camera cam = test_camera(centre);
    const renderer::Lighting lighting = test_lighting();

    minors::MinorField field;
    field.set_fragments(0, {{handle_of(hidden), handle_of(hidden), kBoundMu}});
    field.set_fragments(1, {{handle_of(shown), handle_of(shown), kBoundMu}});
    minors::Dials d;
    d.tumble_min = 0.0f;
    d.tumble_max = 0.0f;
    field.set_dials(d);
    const glm::vec3 at[2] = {centre + glm::vec3(-0.7f, 0.0f, 0.0f),
                             centre + glm::vec3( 0.7f, 0.0f, 0.0f)};
    for (int fam = 0; fam < 2; ++fam) {
        minors::CloudDesc c;
        c.id = static_cast<std::uint32_t>(10 + fam);
        c.anchor = minors::Anchor::Point;
        c.point = glm::dvec3(at[fam]);
        c.shell_inner = 0.0f;
        c.shell_outer = 0.0f;
        c.count = 1;
        c.r_min = c.r_max = 0.3f;
        c.family = fam;
        c.seed = 21u + static_cast<std::uint32_t>(fam);
        field.add_cloud(c, 0.0);
        field.debug_set_phase(c.id, 0, 0.0f);
    }
    field.step(step_input(cam));
    ASSERT_EQ(field.bins().size(), 2u);
    ASSERT_EQ(field.bins()[0].family, 0);
    ASSERT_EQ(field.bins()[1].family, 1);
    const glm::mat4 world1 = world_of(field.bins()[1].items[0]);
    ASSERT_NE(world_of(field.bins()[0].items[0]), world1);

    const auto a = draw_major(shown, world1, cam, lighting);

    renderer::MinorPass pass;
    clear_framebuffer();
    const std::uint64_t hidden_h = handle_of(hidden);
    pass.render(field, cam, *pipeline,
                [hidden_h](std::uint64_t h) {
                    return h == hidden_h ? nullptr : lookup_handle(h);
                },
                lighting, 1.0f, 0.0f);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    const auto b = read_frame();

    EXPECT_EQ(pass.last_draw_calls(), 1);
    ASSERT_GT(lit_pixels(a), kW * kH / 50);
    int differing = 0;
    for (std::size_t i = 0; i < a.size(); ++i) differing += a[i] != b[i] ? 1 : 0;
    EXPECT_EQ(differing, 0) << "bin 1 must draw at its own instance, not bin 0's";
}

// The VAO cache is keyed on (model handle, mesh index); a handle whose mesh
// was re-uploaded (new vbo/ebo) must not keep drawing the old geometry. The
// replacement is uploaded while the old mesh is alive, so its buffer ids
// differ from the old ones.
TEST_F(MinorPassGLTest, ReuploadedMeshUnderTheSameHandleDrawsTheNewGeometry) {
    assets::Model cube = make_cube_model(kCubeHalf);
    const glm::vec3 centre(0.0f, 0.0f, -3.0f);
    const scenegraph::Camera cam = test_camera(centre);
    const renderer::Lighting lighting = test_lighting();

    minors::MinorField field;
    set_family(field, cube, 1);
    one_minor_cloud(field, centre, 0.5f, 0.0f);
    field.step(step_input(cam));
    ASSERT_EQ(field.bins().size(), 1u);
    renderer::MinorPass pass;
    draw_minors(pass, field, cam, lighting);         // caches the VAO
    ASSERT_EQ(pass.last_draw_calls(), 1);

    assets::Model smaller = make_cube_model(0.5f * kCubeHalf);
    ASSERT_NE(smaller.meshes[0].vbo(), cube.meshes[0].vbo());
    cube.meshes[0] = std::move(smaller.meshes[0]);

    const auto a = draw_major(cube, world_of(field.bins()[0].items[0]), cam, lighting);
    const auto b = draw_minors(pass, field, cam, lighting);
    ASSERT_GT(lit_pixels(a), kW * kH / 50);
    int differing = 0;
    for (std::size_t i = 0; i < a.size(); ++i) differing += a[i] != b[i] ? 1 : 0;
    EXPECT_EQ(differing, 0) << "a stale VAO drew the old mesh";
}

// ---- rock-fields Task 3: the fragment-table overload and per-instance
// dither (InstanceGpu::extra.x -> minor.vert a_extra -> v_dither).
namespace {
// One instance of the cube at `centre`, corner radius `r`, no rotation.
minors::InstanceGpu cube_instance(glm::vec3 centre, float r, float dither) {
    const float s = r / kBoundMu;
    minors::InstanceGpu g;
    g.row0 = {s, 0, 0, centre.x};
    g.row1 = {0, s, 0, centre.y};
    g.row2 = {0, 0, s, centre.z};
    g.extra = {dither, 0, 0, 0};
    return g;
}
}  // namespace

TEST_F(MinorPassGLTest, InstanceDitherDiscardsAboutHalf) {
    const assets::Model cube = make_cube_model(kCubeHalf);
    const glm::vec3 centre(0.0f, 0.0f, -3.0f);
    const scenegraph::Camera cam = test_camera(centre);
    const renderer::Lighting lighting = test_lighting();
    const minors::Fragment frag{handle_of(cube), handle_of(cube), kBoundMu};
    const renderer::FragmentLookup frags =
        [&](int family, int slot) -> const minors::Fragment* {
            return family == 0 && slot == 0 ? &frag : nullptr;
        };
    auto draw = [&](renderer::MinorPass& pass, float dither) {
        std::vector<minors::Bin> bins(1);
        bins[0].items.push_back(cube_instance(centre, 2.0f, dither));
        clear_framebuffer();
        pass.render(frags, bins, cam, *pipeline,
                    [](std::uint64_t h) { return lookup_handle(h); },
                    lighting, 1.0f, 0.0f);
        EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
        EXPECT_EQ(pass.last_draw_calls(), 1);
        return read_frame();
    };
    renderer::MinorPass pass;
    const int solid = lit_pixels(draw(pass, 0.0f));
    const int half = lit_pixels(draw(pass, 0.5f));
    ASSERT_GT(solid, kW * kH / 2) << "the cube should fill most of the view";
    EXPECT_GE(half, solid * 4 / 10);
    EXPECT_LE(half, solid * 6 / 10);
}

// The fragment-table overload with extra == 0 draws exactly what the
// field overload draws (which MatchesDrawModelPixelForPixel ties to
// draw_model): the dither attribute changes nothing at 0.
TEST_F(MinorPassGLTest, ZeroDitherIsByteIdentical) {
    const assets::Model cube = make_cube_model(kCubeHalf);
    const glm::vec3 centre(0.0f, 0.0f, -3.0f);
    const scenegraph::Camera cam = test_camera(centre);
    const renderer::Lighting lighting = test_lighting();

    minors::MinorField field;
    set_family(field, cube, 1);
    one_minor_cloud(field, centre, 0.5f, /*phase=*/0.7f);
    field.step(step_input(cam));
    ASSERT_EQ(field.bins().size(), 1u);
    ASSERT_EQ(field.bins()[0].items[0].extra, glm::vec4(0.0f));

    renderer::MinorPass pass;
    const auto a = draw_minors(pass, field, cam, lighting);

    clear_framebuffer();
    pass.render(
        [&](int family, int slot) -> const minors::Fragment* {
            const auto& f = field.fragments(family);
            return slot >= 0 && static_cast<std::size_t>(slot) < f.size() ? &f[slot] : nullptr;
        },
        field.bins(), cam, *pipeline, [](std::uint64_t h) { return lookup_handle(h); },
        lighting, 1.0f, 0.0f);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    const auto b = read_frame();

    ASSERT_GT(lit_pixels(a), kW * kH / 20);
    int differing = 0;
    for (std::size_t i = 0; i < a.size(); ++i) differing += a[i] != b[i] ? 1 : 0;
    EXPECT_EQ(differing, 0);
}
