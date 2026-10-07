// native/src/renderer/atmosphere_pass.cc
#include "renderer/atmosphere_pass.h"

#include "renderer/atmosphere_math.h"
#include "renderer/pipeline.h"
#include "renderer/shader.h"

#include <assets/geosphere.h>
#include <assets/model.h>

#include <scenegraph/camera.h>
#include <scenegraph/world.h>

#include <glad/glad.h>

#include <glm/glm.hpp>

namespace renderer {

namespace {

// Subdivision level of the shell mesh: 5,120 triangles. Its chord sagitta at
// this level is ~6e-4 of the radius, far under a pixel at any planet's
// on-screen size -- the shader does the shape, the mesh only covers pixels.
constexpr int kShellLevel = 4;

struct Candidate {
    glm::vec3 center;
    float r_planet;
    float r_top;
    const scenegraph::Instance::Atmosphere* atmo;
};

}  // namespace

AtmospherePass::~AtmospherePass() = default;

void AtmospherePass::render(const scenegraph::World& world, const scenegraph::Camera& cam,
                            Pipeline& pipeline, const ModelLookup& lookup,
                            const Lighting& lighting, const std::vector<SunDescriptor>& suns,
                            std::uint32_t scene_depth, int viewport_w, int viewport_h) {
    last_draw_count_ = 0;

    // Gather first: with nothing to draw the pass must leave GL untouched,
    // so the default (no enabled atmosphere) frame is byte-identical.
    std::vector<Candidate> todo;
    world.for_each_visible_in_pass(scenegraph::Pass::Space,
                                   [&](const scenegraph::Instance& inst) {
        if (!inst.atmosphere.enabled || !lookup) return;
        const assets::Model* model = lookup(inst.model_handle);
        if (model == nullptr || !model->sphere_map) return;
        const auto& sm = *model->sphere_map;
        const glm::vec3 center = glm::vec3(inst.world * glm::vec4(sm.center_body, 1.0f));
        const float scale = glm::length(glm::vec3(inst.world[0]));
        const float r_planet = sm.radius * scale;
        const float r_top = r_planet * (1.0f + inst.atmosphere.thickness);
        if (!(r_top > r_planet)) return;   // zero/negative/NaN thickness: no shell
        todo.push_back({center, r_planet, r_top, &inst.atmosphere});
    });
    if (todo.empty()) return;

    if (!shell_) shell_.emplace(assets::upload_mesh(assets::build_geosphere(kShellLevel, 1.0f)));

    const glm::mat4 view = cam.view_matrix();
    const glm::mat4 proj = cam.proj_matrix();
    const glm::vec3 eye = glm::vec3(glm::inverse(view)[3]);

    Shader& shader = pipeline.atmosphere_shader();
    shader.use();
    shader.set_mat4("u_view", view);
    shader.set_mat4("u_proj", proj);
    // scene_t() linearises depth from the camera's own planes (see
    // atmosphere.frag); depth_tolerance() scales with the near plane.
    shader.set_float("u_near", cam.near);
    shader.set_float("u_far", cam.far);
    shader.set_vec3("u_camera_pos", eye);
    shader.set_vec2("u_viewport", glm::vec2(static_cast<float>(viewport_w),
                                            static_cast<float>(viewport_h)));
    shader.set_int("u_scene_depth", 0);
    shader.set_vec3("u_sun_color", lighting.directional_count > 0
                                       ? lighting.directional_color[0] : glm::vec3(1.0f));

    // Sampling the depth texture while it is attached to the bound draw
    // framebuffer is a feedback loop (undefined per the GL spec even with
    // depth writes off). Depth test is off for this pass, so detach it for
    // the draw and re-attach after.
    GLint draw_fbo = 0;
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &draw_fbo);
    GLenum detached_at = GL_NONE;
    if (draw_fbo != 0) {
        const GLenum points[] = {GL_DEPTH_STENCIL_ATTACHMENT, GL_DEPTH_ATTACHMENT};
        for (GLenum at : points) {
            GLint type = GL_NONE, name = 0;
            glGetFramebufferAttachmentParameteriv(
                GL_DRAW_FRAMEBUFFER, at, GL_FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE, &type);
            if (type != GL_TEXTURE) continue;
            glGetFramebufferAttachmentParameteriv(
                GL_DRAW_FRAMEBUFFER, at, GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME, &name);
            if (static_cast<std::uint32_t>(name) != scene_depth) continue;
            detached_at = at;
            glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, at, GL_TEXTURE_2D, 0, 0);
            break;
        }
    }

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, scene_depth);

    glDisable(GL_DEPTH_TEST);
    glDepthMask(GL_FALSE);
    glEnable(GL_BLEND);
    glBlendFunc(GL_ONE, GL_ONE);
    glEnable(GL_CULL_FACE);

    const glm::vec3 fallback_sun = lighting.directional_count > 0
        ? lighting.directional_dir_ws[0] : glm::vec3(0.0f, 0.0f, 1.0f);

    glBindVertexArray(shell_->vao());
    for (const Candidate& c : todo) {
        const glm::vec3 sun_dir = planet_atmo::sun_dir_for(c.center, suns, fallback_sun);
        // Outside the shell: draw its front faces (one fragment per covered
        // pixel). Inside: its back faces, which surround the eye.
        const bool inside = glm::length(eye - c.center) < c.r_top;
        glCullFace(inside ? GL_FRONT : GL_BACK);

        shader.set_vec3("u_center", c.center);
        shader.set_float("u_r_planet", c.r_planet);
        shader.set_float("u_r_top", c.r_top);
        shader.set_vec3("u_color", c.atmo->color);
        shader.set_float("u_density", c.atmo->density);
        shader.set_vec3("u_sun_dir", sun_dir);
        glDrawElements(GL_TRIANGLES, static_cast<GLsizei>(shell_->index_count()),
                       GL_UNSIGNED_INT, nullptr);
        ++last_draw_count_;
    }

    // Restore what render_space_vfx's following passes expect (the dust
    // pass's epilogue convention): depth test + writes on, blend off with the
    // standard func, back-face culling.
    glBindVertexArray(0);
    glBindTexture(GL_TEXTURE_2D, 0);
    if (detached_at != GL_NONE) {
        glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, detached_at, GL_TEXTURE_2D,
                               scene_depth, 0);
    }
    glCullFace(GL_BACK);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glDisable(GL_BLEND);
    glDepthMask(GL_TRUE);
    glEnable(GL_DEPTH_TEST);
}

}  // namespace renderer
