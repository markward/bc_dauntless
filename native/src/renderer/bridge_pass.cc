// native/src/renderer/bridge_pass.cc
#include "renderer/bridge_pass.h"
#include "renderer/pipeline.h"

#include <glad/glad.h>

#include <scenegraph/world.h>
#include <scenegraph/camera.h>
#include <scenegraph/instance.h>

#include <assets/model.h>
#include <assets/mesh.h>
#include <assets/texture.h>
#include <assets/material.h>

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <vector>

namespace renderer {

BridgePass::~BridgePass() {
    if (white_texture_ != 0) {
        GLuint t = white_texture_;
        glDeleteTextures(1, &t);
        white_texture_ = 0;
    }
}

std::uint32_t BridgePass::ensure_white_texture() {
    if (white_texture_ != 0) return white_texture_;
    GLuint t = 0;
    glGenTextures(1, &t);
    glBindTexture(GL_TEXTURE_2D, t);
    const std::uint8_t white[4] = {255, 255, 255, 255};
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, white);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glBindTexture(GL_TEXTURE_2D, 0);
    white_texture_ = t;
    return white_texture_;
}

namespace {

/// Walk every visible bridge-tagged instance's meshes; for each mesh
/// whose Material::lightmap_pass == `want_lightmap_pass`, compute its
/// world-space transform and issue a draw via `draw_one`.
template <typename DrawOne>
void walk_bridge_meshes(const scenegraph::World& world,
                        const BridgePass::ModelLookup& lookup,
                        bool want_lightmap_pass,
                        const DrawOne& draw_one) {
    world.for_each_visible_in_pass(scenegraph::Pass::Bridge,
        [&](const scenegraph::Instance& inst) {
            const assets::Model* m = lookup(inst.model_handle);
            if (!m) return;
            std::vector<glm::mat4> world_per_node(m->nodes.size(), glm::mat4(1.0f));
            if (!m->nodes.empty()) {
                world_per_node[m->root_node] =
                    inst.world * m->nodes[m->root_node].local_transform;
            }
            for (std::size_t i = 0; i < m->nodes.size(); ++i) {
                const auto& node = m->nodes[i];
                if (node.parent_index >= 0) {
                    world_per_node[i] =
                        world_per_node[node.parent_index] * node.local_transform;
                }
                for (int mesh_idx : node.meshes) {
                    const auto& mesh = m->meshes[mesh_idx];
                    const auto& mat = (mesh.material_index() >= 0
                        ? m->materials[mesh.material_index()]
                        : assets::Material{});
                    if (mat.lightmap_pass != want_lightmap_pass) continue;
                    draw_one(*m, mesh, mat, world_per_node[i]);
                }
            }
        });
}

void draw_mesh(const assets::Model& model,
               const assets::Mesh& mesh,
               const assets::Material& mat,
               Shader& shader,
               const glm::mat4& world,
               GLuint white_fallback) {
    shader.set_mat4("u_model", world);
    const int base_tex = mat.stages[
        static_cast<std::size_t>(assets::Material::StageSlot::Base)
    ].texture_index;
    glActiveTexture(GL_TEXTURE0);
    if (base_tex >= 0) {
        glBindTexture(GL_TEXTURE_2D, model.textures[base_tex].id());
    } else {
        glBindTexture(GL_TEXTURE_2D, white_fallback);
    }
    glBindVertexArray(mesh.vao());
    glDrawElements(GL_TRIANGLES, mesh.index_count(), GL_UNSIGNED_INT, nullptr);
}

}  // namespace

void BridgePass::render(const scenegraph::World& world,
                        const scenegraph::Camera& camera,
                        Pipeline& pipeline,
                        const ModelLookup& lookup,
                        const Lighting& lighting) {
    // ── Sub-pass A: base geometry, opaque, base × ambient, alpha-test ──
    auto& base_shader = pipeline.bridge_shader();
    base_shader.use();
    base_shader.set_mat4("u_view", camera.view_matrix());
    base_shader.set_mat4("u_proj", camera.proj_matrix());
    base_shader.set_vec3("u_ambient", lighting.ambient);
    base_shader.set_int("u_base_color", 0);
    base_shader.set_float("u_alpha_test_threshold", 0.5f);

    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);

    // BC's NIFs are Gamebryo CW-wound, and pipeline.cc sets
    // glFrontFace(GL_CW) globally on the assumption that the world
    // matrix has det < 0 (which holds for ships via
    // _ship_world_matrix's X-axis flip — see host_loop.py). The bridge
    // instance is set with identity transform (det = +1), so under
    // GL_CW the bridge would render with its front faces culled and
    // back faces visible. Flip the front-face mode for the bridge pass
    // only, restoring at the end.
    glFrontFace(GL_CCW);

    const GLuint white = ensure_white_texture();
    walk_bridge_meshes(world, lookup, /*want_lightmap_pass=*/false,
        [&](const assets::Model& m, const assets::Mesh& mesh,
            const assets::Material& mat, const glm::mat4& w) {
            draw_mesh(m, mesh, mat, base_shader, w, white);
        });

    // ── Sub-pass B: lightmap geometry, multiply blend over framebuffer ──
    // GL state for fixed-function-style multiply lightmaps:
    //   LEQUAL  — lightmap mesh is coplanar with the base mesh under it
    //             in most stock content; LESS would reject every fragment
    //             on exact-coplanar duplicates.
    //   depth-write OFF — sub-pass B does not contribute to the depth
    //             buffer; only A's opaque pass owns depth.
    //   blend DST_COLOR/ZERO — `framebuffer *= lightmap`, the canonical
    //             multiply-blend lightmap composite.
    //   polygon offset (-1, -1) — handles floating-point drift between
    //             the base and lightmap copies even when nominally
    //             coplanar; cheap and standard for this pattern.
    auto& lm_shader = pipeline.lightmap_shader();
    lm_shader.use();
    lm_shader.set_mat4("u_view", camera.view_matrix());
    lm_shader.set_mat4("u_proj", camera.proj_matrix());
    lm_shader.set_int("u_lightmap", 0);

    glDepthFunc(GL_LEQUAL);
    glDepthMask(GL_FALSE);
    glEnable(GL_BLEND);
    glBlendFunc(GL_DST_COLOR, GL_ZERO);
    glEnable(GL_POLYGON_OFFSET_FILL);
    glPolygonOffset(-1.0f, -1.0f);

    walk_bridge_meshes(world, lookup, /*want_lightmap_pass=*/true,
        [&](const assets::Model& m, const assets::Mesh& mesh,
            const assets::Material& mat, const glm::mat4& w) {
            draw_mesh(m, mesh, mat, lm_shader, w, white);
        });

    // Restore GL state so subsequent passes don't inherit our changes.
    glDisable(GL_POLYGON_OFFSET_FILL);
    glPolygonOffset(0.0f, 0.0f);
    glDisable(GL_BLEND);
    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glFrontFace(GL_CW);  // restore pipeline-wide default

    glBindVertexArray(0);
}

}  // namespace renderer
