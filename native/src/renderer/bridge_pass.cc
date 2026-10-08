// native/src/renderer/bridge_pass.cc
#include "renderer/bridge_pass.h"
#include "renderer/bridge_lighting_tuning.h"
#include "renderer/pipeline.h"
#include "renderer/bone_palette.h"
#include "renderer/node_anim.h"

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

#include <cstdio>
#include <fstream>
#include <iterator>
#include <utility>
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

void BridgePass::ensure_off_texture() {
    if (off_tex_path_ == off_tex_loaded_) return;
    off_tex_loaded_ = off_tex_path_;
    off_tex_ = {};
    if (off_tex_path_.empty()) return;
    std::ifstream in(off_tex_path_, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[bridge] viewscreen off texture: open '%s' failed\n",
                     off_tex_path_.c_str());
        return;
    }
    std::vector<std::uint8_t> bytes((std::istreambuf_iterator<char>(in)),
                                    std::istreambuf_iterator<char>());
    try {
        off_tex_ = assets::upload_image(assets::decode_tga(bytes),
                                        /*generate_mipmaps=*/false);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[bridge] viewscreen off texture: decode '%s': %s\n",
                     off_tex_path_.c_str(), e.what());
    }
}

namespace {

/// Walk every visible bridge-tagged instance's meshes; for each mesh,
/// compute its world-space transform and issue a draw via `draw_one`.
template <typename DrawOne>
void walk_bridge_meshes(const scenegraph::World& world,
                        const BridgePass::ModelLookup& lookup,
                        scenegraph::Pass pass,
                        std::uint32_t comm_set_id,
                        const DrawOne& draw_one) {
    world.for_each_visible_in_pass(pass,
        [&](const scenegraph::Instance& inst) {
            // comm_set_id == 0 means "no set filter" (bridge default).
            if (comm_set_id != 0 && inst.comm_set_id != comm_set_id) return;
            const assets::Model* m = lookup(inst.model_handle);
            if (!m) return;
            // Skinned models are drawn by the skinned sub-pass only; the static
            // base shader would draw them undeformed and double-draw them.
            if (!m->skeleton.bones.empty()) return;
            std::vector<glm::mat4> world_per_node =
                renderer::compose_node_worlds(*m, inst.world, inst.node_overrides);
            for (std::size_t i = 0; i < m->nodes.size(); ++i) {
                const auto& node = m->nodes[i];
                for (int mesh_idx : node.meshes) {
                    const auto& mesh = m->meshes[mesh_idx];
                    const auto& mat = (mesh.material_index() >= 0
                        ? m->materials[mesh.material_index()]
                        : assets::Material{});
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
               GLuint base_override,
               bool override_flip_v = true,
               float vs_brightness = 1.0f,
               float vs_flash = 0.0f,
               bool face_blend = false,
               GLuint face_a = 0,
               GLuint face_b = 0,
               float face_mix = 0.0f,
               int mesh_id = 0) {
    shader.set_mat4("u_model", world);
    // Debug view 5 (Mesh ID): a stable per-draw counter, reset each render().
    shader.set_int("u_mesh_id", mesh_id);
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
    // NiFlipController-driven animation (EBridge's LCARS): the current
    // frame's texture, or the static Base when the material has none.
    int base_tex = assets::animated_base_texture(model, mat, wall_time);
    // Flip V only for the viewscreen RTT feed: its FBO colour attachment is
    // bottom-up, the NIF screen UVs are top-down (see bridge.frag). The other
    // override — the SDK off texture — is a .tga and must NOT be flipped. Set
    // every draw so it never sticks on for the surrounding bridge geometry.
    shader.set_int("u_flip_v",
                   (base_override != 0 && override_flip_v) ? 1 : 0);
    // Brightness multiplier: only the viewscreen override path receives the
    // per-frame fade value; all other geometry gets 1.0 (byte-identical).
    shader.set_float("u_viewscreen_brightness",
                     base_override != 0 ? vs_brightness : 1.0f);
    // Warp flash only on the viewscreen feed; 0 everywhere else.
    shader.set_float("u_viewscreen_flash",
                     base_override != 0 ? vs_flash : 0.0f);
    // Unlit only for the viewscreen override (set every draw so it never
    // sticks): the feed / off texture draws full bright, unaffected by the
    // bridge ambient or the downlight.
    shader.set_int("u_unlit", (!face_blend && base_override != 0) ? 1 : 0);
    // Officer lip-sync face blend (set every draw so it never sticks).
    shader.set_int("u_face_blend", face_blend ? 1 : 0);
    if (face_blend) shader.set_float("u_face_mix", face_mix);
    glActiveTexture(GL_TEXTURE0);
    if (face_blend) {
        // unit0 = face_tex_a (or the head's own base texture when 0 = neutral);
        // unit2 = face_tex_b (or the same as unit0). The frag lerps by u_face_mix.
        const GLuint a = face_a ? face_a
            : (base_tex >= 0 ? model.textures[base_tex].id() : white_fallback);
        const GLuint b = face_b ? face_b : a;
        glBindTexture(GL_TEXTURE_2D, a);
        glActiveTexture(GL_TEXTURE2);
        glBindTexture(GL_TEXTURE_2D, b);
    } else if (base_override != 0) {
        // Viewscreen RTT feed: ignore the NIF base texture and draw the
        // offscreen scene full-bright (u_unlit above -> FragColor = feed,
        // unaffected by bridge ambient).
        glBindTexture(GL_TEXTURE_2D, base_override);
    } else if (base_tex >= 0) {
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
                        const Lighting& lighting,
                        scenegraph::Pass pass,
                        std::uint32_t comm_set_id) {
    // Screen-space AO for the main bridge view only -- never the comm-set RTT
    // (a different camera into a different room), and not while this call is
    // the AO's own normal pre-pass.
    GLint view_vp[4] = {0, 0, 0, 0};
    glGetIntegerv(GL_VIEWPORT, view_vp);
    const bool main_bridge = pass == scenegraph::Pass::Bridge && comm_set_id == 0;
    bool ao_on = false;
    if (main_bridge && !normal_pass_ && ao_enabled_) {
        ao_on = ao_.render(camera, view_vp[2], view_vp[3], ao_settings_, [&] {
            normal_pass_ = true;
            render(world, camera, pipeline, lookup, lighting,
                   scenegraph::Pass::Bridge, 0);
            normal_pass_ = false;
        });
    }
    if (ao_on) {
        glActiveTexture(GL_TEXTURE3);
        glBindTexture(GL_TEXTURE_2D, ao_.ao_texture());
        glActiveTexture(GL_TEXTURE4);   // pre-pass depth, for the depth-aware filter
        glBindTexture(GL_TEXTURE_2D, ao_.depth_texture());
        glBindSampler(4, ao_.raw_sampler());
        glActiveTexture(GL_TEXTURE0);
    }
    const glm::mat4 inv_proj = glm::inverse(camera.proj_matrix());

    // Uniforms common to both sub-passes: camera, the bridge ambient and the
    // ceiling downlight (kBridgeLighting, bridge_lighting_tuning.h).
    auto set_frame_uniforms = [&](Shader& s) {
        s.set_mat4("u_view", camera.view_matrix());
        s.set_mat4("u_proj", camera.proj_matrix());
        s.set_vec3("u_ambient", lighting.ambient);
        s.set_vec3("u_eye", camera.eye);
        s.set_vec3("u_up", kBridgeUp);
        s.set_float("u_down_top", kBridgeLighting.down_top);
        s.set_float("u_down_bottom", kBridgeLighting.down_bottom);
        s.set_float("u_diffuse_max", kBridgeLighting.diffuse_max);
        s.set_int("u_base_color", 0);
        s.set_int("u_face_b", 2);  // lip-sync second face texture
        s.set_float("u_alpha_test_threshold", 0.5f);
        // AO: own units (an unset sampler shares unit 0). The AO may be
        // smaller than the view; the filter maps each fragment through the
        // view size.
        s.set_int("u_ao", 3);
        s.set_int("u_ao_depth", 4);
        s.set_mat4("u_ao_inv_proj", inv_proj);
        s.set_vec2("u_ao_screen", glm::vec2(static_cast<float>(view_vp[2]),
                                            static_cast<float>(view_vp[3])));
        s.set_int("u_ao_on", ao_on ? 1 : 0);
        s.set_int("u_output_normal", normal_pass_ ? 1 : 0);
        s.set_int("u_debug_view", static_cast<int>(debug_view_));
    };

    // Developer Options debug view 5 (Mesh ID): a per-draw counter, reset
    // every render() call so numbering is stable within a frame.
    int mesh_id_counter = 0;

    // ── Sub-pass A: base geometry, opaque, downlit, alpha-test ─────────────
    auto& base_shader = pipeline.bridge_shader();
    base_shader.use();
    set_frame_uniforms(base_shader);
    // Generated set normals follow their triangle's winding.
    base_shader.set_int("u_face_by_winding", 1);

    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);

    // DBridge.NIF has mixed face winding; no single glFrontFace catches
    // both. Disable back-face culling for the bridge pass — interior is
    // enclosed with ~145 small meshes, fillrate impact is negligible.
    glDisable(GL_CULL_FACE);

    // Render every bridge shape opaque with its Base texture, lit by the
    // ceiling downlight. BC's baked lightmaps (the Dark slot) are not drawn.
    const GLuint white = ensure_white_texture();
    const double t = wall_time_;
    ensure_off_texture();
    // The viewscreen override: the live RTT feed when it is on, otherwise the
    // SDK's off texture (the loading screen). Only the feed needs the V flip —
    // it is an FBO colour attachment (bottom-up); the off texture is a .tga,
    // authored top-down like every other NIF texture.
    const GLuint off_tex = off_tex_.id();
    auto viewscreen_override = [&](unsigned long long mh)
        -> std::pair<GLuint, bool> {
        if (viewscreen_model_handle_ == 0 || mh != viewscreen_model_handle_)
            return {0u, false};
        if (viewscreen_tex_ != 0) return {viewscreen_tex_, true};
        return {off_tex, false};
    };
    walk_bridge_meshes(world, lookup, pass, comm_set_id,
        [&](const assets::Model& m, const assets::Mesh& mesh,
            const assets::Material& mat, const glm::mat4& w,
            unsigned long long mh) {
            const auto [ov, flip] = viewscreen_override(mh);
            draw_mesh(m, mesh, mat, base_shader, w, white, t, ov, flip,
                      viewscreen_brightness_, viewscreen_flash_,
                      /*face_blend=*/false, /*face_a=*/0u, /*face_b=*/0u,
                      /*face_mix=*/0.0f, mesh_id_counter++);
        });

    // ── Sub-pass B: skinned bridge characters ──────────────────────────────
    // Any Pass::Bridge instance carrying a skeleton is drawn here, lit by the
    // same downlight as the geometry (bridge.frag). The
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
    set_frame_uniforms(skin_shader);
    // Officers carry authored normals: light the side that faces the eye.
    skin_shader.set_int("u_face_by_winding", 0);

    world.for_each_visible_in_pass(pass,
        [&](const scenegraph::Instance& inst) {
            if (comm_set_id != 0 && inst.comm_set_id != comm_set_id) return;
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
                    // Lip-sync: blend the head meshes' face texture when this
                    // officer has an active face override. Body meshes and
                    // non-speaking officers take the byte-identical normal path.
                    const bool is_head = m->head_mesh_begin >= 0
                                         && mesh_idx >= m->head_mesh_begin;
                    const bool face = inst.face_active && is_head;
                    draw_mesh(*m, mesh, mat, skin_shader, inst.world, white, t, 0u,
                              /*override_flip_v=*/true, 1.0f, 0.0f,
                              face, inst.face_tex_a, inst.face_tex_b,
                              inst.face_mix, mesh_id_counter++);
                }
            }
        });

    glBindVertexArray(0);
    if (ao_on) glBindSampler(4, 0);   // don't leak the raw sampler to other passes
}

}  // namespace renderer
