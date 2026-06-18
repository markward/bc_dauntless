// native/src/renderer/bridge_pass.cc
#include "renderer/bridge_pass.h"
#include "renderer/pipeline.h"
#include "renderer/bone_palette.h"

#include <glad/glad.h>

#include <scenegraph/world.h>
#include <scenegraph/camera.h>
#include <scenegraph/instance.h>

#include <assets/flip_frame.h>
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
            // Skinned models are drawn by the skinned sub-pass only; the static
            // base shader would draw them undeformed and double-draw them.
            if (!m->skeleton.bones.empty()) return;
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
                    draw_one(*m, mesh, mat, world_per_node[i], inst.model_handle);
                }
            }
        });
}

void draw_mesh(const assets::Model& model,
               const assets::Mesh& mesh,
               const assets::Material& mat,
               Shader& shader,
               const glm::mat4& world,
               GLuint white_fallback,
               double wall_time,
               GLuint base_override) {
    shader.set_mat4("u_model", world);
    shader.set_vec3("u_emissive", mat.emissive);
    // Alpha test only fires when the material carries an NiAlphaProperty;
    // otherwise the shape is fully opaque regardless of the base
    // texture's alpha channel. EBridge's floorlight.tga (and similar
    // glow-mask textures) store alpha as a brightness mask, not as
    // transparency — without this we'd carve the dark fixture body out
    // of every wall-light shape. Sentinel threshold -1 disables the
    // discard in the shader.
    const float thresh = mat.alpha_test_enabled
        ? static_cast<float>(mat.alpha_test_threshold) / 255.0f
        : -1.0f;
    shader.set_float("u_alpha_test_threshold", thresh);
    int base_tex = mat.stages[
        static_cast<std::size_t>(assets::Material::StageSlot::Base)
    ].texture_index;
    // NiFlipController-driven animation: replace base_tex with the
    // current frame's texture index. Falls through to the static
    // base_tex if the animation index is missing or its frame list
    // failed to resolve.
    if (mat.animation_index >= 0 &&
        mat.animation_index < static_cast<int>(model.texture_animations.size()))
    {
        const auto& anim = model.texture_animations[mat.animation_index];
        if (!anim.texture_indices.empty()) {
            const int frame = assets::compute_flip_frame_index(
                wall_time, anim.start_time, anim.frequency, anim.phase,
                anim.delta, static_cast<int>(anim.texture_indices.size()));
            base_tex = anim.texture_indices[frame];
        }
    }
    // Flip V only for the viewscreen RTT feed: its FBO colour attachment is
    // bottom-up, the NIF screen UVs are top-down (see bridge.frag). Set every
    // draw so it never sticks on for the surrounding bridge geometry.
    shader.set_int("u_flip_v", base_override != 0 ? 1 : 0);
    glActiveTexture(GL_TEXTURE0);
    if (base_override != 0) {
        // Viewscreen RTT feed: ignore the NIF base texture and draw the
        // offscreen scene full-bright (BC's emissive=(1,1,1) screen
        // convention -> FragColor = feed, unaffected by bridge ambient).
        glBindTexture(GL_TEXTURE_2D, base_override);
        shader.set_vec3("u_emissive", glm::vec3(1.0f));
    } else if (base_tex >= 0) {
        glBindTexture(GL_TEXTURE_2D, model.textures[base_tex].id());
    } else {
        glBindTexture(GL_TEXTURE_2D, white_fallback);
    }
    // Dark-slot lightmap (BC bridge floor/door/inset lm.tga). When
    // absent, the white fallback returns (1,1,1) so the multiply in
    // the fragment shader has no visual effect.
    const int dark_tex = mat.stages[
        static_cast<std::size_t>(assets::Material::StageSlot::Dark)
    ].texture_index;
    glActiveTexture(GL_TEXTURE1);
    if (dark_tex >= 0) {
        glBindTexture(GL_TEXTURE_2D, model.textures[dark_tex].id());
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
    base_shader.set_int("u_dark_map", 1);
    base_shader.set_float("u_alpha_test_threshold", 0.5f);

    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);

    // DBridge.NIF has mixed face winding; no single glFrontFace catches
    // both. Disable back-face culling for the bridge pass — interior is
    // enclosed with ~145 small meshes, fillrate impact is negligible.
    glDisable(GL_CULL_FACE);

    // Diffuse pass: render all 145 bridge shapes opaque with their Base
    // texture. The Material::lightmap_pass tag is no longer consulted —
    // it controlled a legacy multiply pass and an asset-pipeline UV swap
    // for shapes whose Base texture is an lm.tga, both of which proved
    // to be the wrong model. Per the user's clarification: BC's floor
    // surfaces inherit BOTH a NiTextureProperty (carpet diffuse, UV0)
    // AND a NiMultiTextureProperty (lightmap, UV1). With the material-
    // build fix that stops the multi-tex from overwriting Base, all
    // shapes now have their correct diffuse in Base.
    const GLuint white = ensure_white_texture();
    const double t = wall_time_;
    walk_bridge_meshes(world, lookup, /*want_lightmap_pass=*/false,
        [&](const assets::Model& m, const assets::Mesh& mesh,
            const assets::Material& mat, const glm::mat4& w,
            unsigned long long mh) {
            const GLuint ov = (viewscreen_model_handle_ != 0
                               && mh == viewscreen_model_handle_)
                              ? viewscreen_tex_ : 0u;
            draw_mesh(m, mesh, mat, base_shader, w, white, t, ov);
        });
    walk_bridge_meshes(world, lookup, /*want_lightmap_pass=*/true,
        [&](const assets::Model& m, const assets::Mesh& mesh,
            const assets::Material& mat, const glm::mat4& w,
            unsigned long long mh) {
            const GLuint ov = (viewscreen_model_handle_ != 0
                               && mh == viewscreen_model_handle_)
                              ? viewscreen_tex_ : 0u;
            draw_mesh(m, mesh, mat, base_shader, w, white, t, ov);
        });

    // ── Sub-pass C: skinned bridge characters ──────────────────────────────
    // Any Pass::Bridge instance carrying a skeleton is drawn here, lit by the
    // same bridge ambient as the geometry (bridge.frag, white dark-map). The
    // per-instance bone palette (SP2) poses the body.
    //
    // Culling stays DISABLED (as for the bridge shell). The officer skin
    // matrix (world_pose · inverse_bind) and the instance world compose to a
    // winding that isn't worth tracking per-frame, and characters are small —
    // double-siding is cheaper. This stayed correct across the 2026-06-18
    // right-handed un-mirror precisely because culling is off (the pass is
    // winding-insensitive); the instance world is no longer reflected.
    glDisable(GL_CULL_FACE);
    auto& skin_shader = pipeline.skinned_bridge_shader();
    skin_shader.use();
    skin_shader.set_mat4("u_view", camera.view_matrix());
    skin_shader.set_mat4("u_proj", camera.proj_matrix());
    skin_shader.set_vec3("u_ambient", lighting.ambient);
    skin_shader.set_int("u_base_color", 0);
    skin_shader.set_int("u_dark_map", 1);
    skin_shader.set_float("u_alpha_test_threshold", 0.5f);

    world.for_each_visible_in_pass(scenegraph::Pass::Bridge,
        [&](const scenegraph::Instance& inst) {
            const assets::Model* m = lookup(inst.model_handle);
            if (!m || m->skeleton.bones.empty()) return;
            std::vector<glm::mat4> palette = inst.bone_palette.empty()
                ? build_bone_palette(m->skeleton, nullptr)
                : inst.bone_palette;
            skin_shader.set_mat4_array("u_bones", palette.data(),
                                       static_cast<int>(palette.size()));
            // SP2: bind-model verts + palette => u_model is the instance world.
            // The node loop now only enumerates meshes; the palette does all
            // per-bone placement, so the per-node walk is no longer composed.
            for (std::size_t i = 0; i < m->nodes.size(); ++i) {
                const auto& node = m->nodes[i];
                for (int mesh_idx : node.meshes) {
                    const auto& mesh = m->meshes[mesh_idx];
                    const auto& mat = (mesh.material_index() >= 0
                        ? m->materials[mesh.material_index()] : assets::Material{});
                    draw_mesh(*m, mesh, mat, skin_shader, inst.world, white, t, 0u);
                }
            }
        });

    glBindVertexArray(0);
}

}  // namespace renderer
