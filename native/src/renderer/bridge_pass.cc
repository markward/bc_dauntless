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

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <limits>
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
                    const auto& mat =
                        assets::material_or_default(*m, mesh.material_index());
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
               int mesh_id = 0,
               int highlight = 0,
               int pbr = 0,
               float rough_override = -1.0f,
               float metal_override = -1.0f) {
    shader.set_mat4("u_model", world);
    // Debug view 5 (Mesh ID): a stable per-draw counter, reset each render().
    shader.set_int("u_mesh_id", mesh_id);
    // Developer-only bridge editor selection tint (spec
    // 2026-10-08-bridge-emitters §4): 0 none, 1 hover, 2 selected.
    shader.set_int("u_highlight", highlight);
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
    // Bridge PBR (spec 2026-10-08-bridge-emitters §9.2): per channel the first
    // hit wins -- map, then the per-shape override (< 0 = none), then the
    // default. Units 1 (normal / Bump), 5 (roughness), 6 (metalness) are bound
    // on EVERY draw, the white fallback when the material has no map, so no
    // declared sampler is ever left on a stale or unbound unit. Set every draw
    // so a flag never sticks to the next mesh.
    shader.set_int("u_pbr", pbr);
    shader.set_float("u_rough_override", rough_override);
    shader.set_float("u_metal_override", metal_override);
    auto bind_map = [&](GLenum unit, assets::Material::StageSlot slot,
                        const char* has_name) {
        const int ti = mat.stages[static_cast<std::size_t>(slot)].texture_index;
        GLuint id = 0;
        if (ti >= 0 && ti < static_cast<int>(model.textures.size()))
            id = model.textures[static_cast<std::size_t>(ti)].id();
        shader.set_int(has_name, id != 0 ? 1 : 0);
        glActiveTexture(unit);
        glBindTexture(GL_TEXTURE_2D, id != 0 ? id : white_fallback);
    };
    bind_map(GL_TEXTURE1, assets::Material::StageSlot::Bump, "u_has_normal_map");
    bind_map(GL_TEXTURE5, assets::Material::StageSlot::Roughness, "u_has_rough_map");
    bind_map(GL_TEXTURE6, assets::Material::StageSlot::Metalness, "u_has_metal_map");
    glActiveTexture(GL_TEXTURE0);
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
    const bool main_bridge = pass == scenegraph::Pass::Bridge && comm_set_id == 0;
    // Reflection probes: the box follows the bridge model; a pending capture
    // runs here, BEFORE the AO pre-pass, into the probes' own FBOs (each face
    // re-enters render() with capture_pass_ set). Never inside a nested pass,
    // and never with no bridge drawn: the request then waits for one.
    if (main_bridge && !normal_pass_ && !capture_pass_) {
        const bool have_bridge = update_box(world, lookup);
        // A changed bridge lighting re-lights the room the probes hold. The
        // pass reads only `ambient` from Lighting (no directional), and the
        // UNSCALED one: the alert scale never reaches a capture. Only once a
        // first capture exists -- the bridge load requests that one.
        if (probes_captured_ && lighting.ambient != capture_ambient_)
            probe_dirty_ = true;
        if (probe_dirty_ && have_bridge)
            capture_probes(world, pipeline, lookup, lighting);
    }
    // Screen-space AO for the main bridge view only -- never the comm-set RTT
    // (a different camera into a different room), and not while this call is
    // the AO's own normal pre-pass or a probe face.
    GLint view_vp[4] = {0, 0, 0, 0};
    glGetIntegerv(GL_VIEWPORT, view_vp);
    bool ao_on = false;
    if (main_bridge && !normal_pass_ && !capture_pass_ && ao_enabled_) {
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
    // `lighting` is UNSCALED: the alert scale applies to the normal main-bridge
    // draw only -- never a comm set, never a probe capture (capture_probes
    // hands each face ambient x probe scale).
    const glm::vec3 ambient = lighting.ambient *
        ((main_bridge && !capture_pass_) ? alert_ambient_scale_ : 1.0f);

    // PBR on the main bridge view only: a comm set (another ship's room on
    // the viewscreen) keeps the legacy shading -- the probes would hold the
    // PLAYER's bridge, the wrong room to reflect.
    const int pbr = (pbr_enabled_ && main_bridge) ? 1 : 0;
    // The probes are sampled only once BOTH hold a capture: a samplerCube on
    // a unit with no cube bound must never be sampled, so with no probe the
    // units stay empty and u_has_probe = 0 keeps the shader off them.
    const bool has_probe = pbr != 0 && !capture_pass_ && !normal_pass_ && probes_valid();
    if (has_probe) {
        glActiveTexture(GL_TEXTURE7);
        glBindTexture(GL_TEXTURE_CUBE_MAP, probe_green_.texture());
        glActiveTexture(GL_TEXTURE8);
        glBindTexture(GL_TEXTURE_CUBE_MAP, probe_yr_.texture());
        glActiveTexture(GL_TEXTURE9);
        glBindTexture(GL_TEXTURE_2D, brdf_lut_.texture());
        glActiveTexture(GL_TEXTURE0);
    }

    // Static spot lights, packed once per render() (both sub-passes share them).
    const int spot_count = main_bridge ? static_cast<int>(spots_.size()) : 0;
    glm::vec3 spot_pos[kBridgeMaxSpots];
    glm::vec3 spot_dir[kBridgeMaxSpots];
    glm::vec3 spot_rad[kBridgeMaxSpots];
    glm::vec4 spot_params[kBridgeMaxSpots];   // x cos_inner, y cos_outer, z range
    for (int i = 0; i < spot_count; ++i) {
        const BridgeSpot& sp = spots_[static_cast<std::size_t>(i)];
        spot_pos[i] = sp.position;
        spot_dir[i] = sp.direction;
        spot_rad[i] = sp.radiance;
        spot_params[i] = glm::vec4(sp.cos_inner, sp.cos_outer, sp.range, 0.0f);
    }

    // Uniforms common to both sub-passes: camera, the bridge ambient and the
    // ceiling downlight (kBridgeLighting, bridge_lighting_tuning.h).
    const float pulse_phase = highlight_phase();
    auto set_frame_uniforms = [&](Shader& s) {
        s.set_mat4("u_view", camera.view_matrix());
        s.set_mat4("u_proj", camera.proj_matrix());
        s.set_vec3("u_ambient", ambient);
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
        // Selection pulse phase: a real clock, once per sub-pass.
        s.set_float("u_highlight_time", pulse_phase);
        // Bridge PBR material maps: own units (draw_mesh binds them per draw).
        s.set_int("u_normal_map", 1);
        s.set_int("u_rough_map", 5);
        s.set_int("u_metal_map", 6);
        // Reflection probes + BRDF LUT: units 7/8/9 assigned on EVERY use,
        // bound or not, so no two sampler types ever share a unit (a
        // samplerCube left on unit 0 beside u_base_color fails every draw).
        s.set_int("u_probe_a", 7);
        s.set_int("u_probe_b", 8);
        s.set_int("u_brdf_lut", 9);
        s.set_int("u_has_probe", has_probe ? 1 : 0);
        s.set_float("u_probe_mix", probe_mix_);
        s.set_vec3("u_probe_pos", probe_origin_);
        s.set_float("u_probe_max_mip", static_cast<float>(kBridgeProbeMips - 1));
        s.set_vec3("u_box_min", box_min_);
        s.set_vec3("u_box_max", box_max_);
        s.set_int("u_capture", capture_pass_ ? 1 : 0);
        // Static spots: main bridge view only (its probe captures included;
        // they light the capture's diffuse). Comm sets get 0. Only the count
        // in use is uploaded; the shader never reads past u_spot_count.
        s.set_int("u_spot_count", spot_count);
        if (spot_count > 0) {
            s.set_vec3_array("u_spot_pos", spot_pos, spot_count);
            s.set_vec3_array("u_spot_dir", spot_dir, spot_count);
            s.set_vec3_array("u_spot_radiance", spot_rad, spot_count);
            s.set_vec4_array("u_spot_params", spot_params, spot_count);
        }
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
            int hl = 0;
            if (highlight_model_ != 0 && mh == highlight_model_) {
                const int mi = static_cast<int>(&mesh - m.meshes.data());
                if (mi == highlight_selected_) hl = 2;
                else if (mi == highlight_hover_) hl = 1;
            }
            // Per-shape material override, only for the overrides' model.
            float rough_ov = -1.0f, metal_ov = -1.0f;
            if (overrides_model_ != 0 && mh == overrides_model_) {
                const int mi = static_cast<int>(&mesh - m.meshes.data());
                if (auto it = overrides_.find(mi); it != overrides_.end()) {
                    rough_ov = it->second.first;
                    metal_ov = it->second.second;
                }
            }
            draw_mesh(m, mesh, mat, base_shader, w, white, t, ov, flip,
                      viewscreen_brightness_, viewscreen_flash_,
                      /*face_blend=*/false, /*face_a=*/0u, /*face_b=*/0u,
                      /*face_mix=*/0.0f, mesh_id_counter++, hl,
                      pbr, rough_ov, metal_ov);
        });

    // ── Sub-pass B: skinned bridge characters ──────────────────────────────
    // A probe capture is sub-pass A only: officers are never in the probes.
    if (!capture_pass_) {
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
                        const auto& mat =
                            assets::material_or_default(*m, mesh.material_index());
                        // Lip-sync: blend the head meshes' face texture when this
                        // officer has an active face override. Body meshes and
                        // non-speaking officers take the byte-identical normal path.
                        const bool is_head = m->head_mesh_begin >= 0
                                             && mesh_idx >= m->head_mesh_begin;
                        const bool face = inst.face_active && is_head;
                        draw_mesh(*m, mesh, mat, skin_shader, inst.world, white, t, 0u,
                                  /*override_flip_v=*/true, 1.0f, 0.0f,
                                  face, inst.face_tex_a, inst.face_tex_b,
                                  inst.face_mix, mesh_id_counter++,
                                  /*highlight=*/0, pbr);  // officers: no overrides
                    }
                }
            });
    }

    glBindVertexArray(0);
    // The PBR map units (bound per draw) never leak to the next pass.
    for (GLenum unit : {GL_TEXTURE1, GL_TEXTURE5, GL_TEXTURE6, GL_TEXTURE9}) {
        glActiveTexture(unit);
        glBindTexture(GL_TEXTURE_2D, 0);
    }
    // ...nor the probe cubes.
    for (GLenum unit : {GL_TEXTURE7, GL_TEXTURE8}) {
        glActiveTexture(unit);
        glBindTexture(GL_TEXTURE_CUBE_MAP, 0);
    }
    glActiveTexture(GL_TEXTURE0);
    if (ao_on) {
        // Don't leak the raw sampler or the AO textures to other passes: next
        // frame's nested normal pre-pass renders INTO the depth texture's FBO
        // with a program that declares u_ao_depth on unit 4 -- a rendering
        // feedback loop (GL 4.1 section 9.3.1) if that texture is still bound.
        glBindSampler(4, 0);
        glActiveTexture(GL_TEXTURE3);
        glBindTexture(GL_TEXTURE_2D, 0);
        glActiveTexture(GL_TEXTURE4);
        glBindTexture(GL_TEXTURE_2D, 0);
        glActiveTexture(GL_TEXTURE0);
    }
}

void BridgePass::set_material_overrides(
        unsigned long long model_handle,
        std::vector<BridgeMaterialOverride> overrides) {
    std::unordered_map<int, std::pair<float, float>> next;
    for (const auto& o : overrides)
        next[o.mesh] = {o.roughness, o.metalness};
    // The probe capture reads the per-shape metalness, so a CHANGED set
    // recaptures. An identical re-push (the editor re-pushes after every
    // action, no-ops included) does not; with no entries the model is moot.
    const bool same = next == overrides_ &&
        (next.empty() || model_handle == overrides_model_);
    overrides_ = std::move(next);
    overrides_model_ = model_handle;
    if (!same) request_probe_capture();
}

void BridgePass::clear_material_overrides() {
    overrides_.clear();
    overrides_model_ = 0;
}

std::size_t BridgePass::set_spots(std::vector<BridgeSpot> spots) {
    const std::size_t cap = static_cast<std::size_t>(kBridgeMaxSpots);
    const std::size_t dropped = spots.size() > cap ? spots.size() - cap : 0;
    if (dropped > 0) spots.resize(cap);
    for (auto& sp : spots) {
        const float len = glm::length(sp.direction);
        sp.direction = (std::isfinite(len) && len > 1e-6f)
            ? sp.direction / len : glm::vec3(0.0f, 0.0f, -1.0f);
        sp.cos_outer = std::min(sp.cos_outer, sp.cos_inner);
    }
    // The probes hold the room lit by the spots' diffuse: recapture -- but
    // only when the SANITISED list changed. An alert change re-pushes the
    // same list (an empty one over an empty one with no lighting file), and
    // a capture of both probes costs ~14 ms for no visible change.
    auto same_spot = [](const BridgeSpot& a, const BridgeSpot& b) {
        return a.position == b.position && a.direction == b.direction &&
               a.cos_inner == b.cos_inner && a.cos_outer == b.cos_outer &&
               a.range == b.range && a.radiance == b.radiance;
    };
    const bool same = spots.size() == spots_.size() &&
        std::equal(spots.begin(), spots.end(), spots_.begin(), same_spot);
    spots_ = std::move(spots);
    if (!same) request_probe_capture();
    return dropped;
}

void BridgePass::set_probe_mix(float t) {
    probe_mix_ = std::isfinite(t) ? std::clamp(t, 0.0f, 1.0f) : 0.0f;
}

bool BridgePass::probes_valid() const {
    return probes_captured_ && probe_green_.valid() && probe_yr_.valid() &&
           brdf_lut_.texture() != 0;
}

void BridgePass::reset_probes() {
    probes_captured_ = false;
    probe_dirty_ = false;
    probe_mix_ = 0.0f;
    model_boxes_.clear();
    box_handle_ = 0;
    box_min_ = glm::vec3(-1.0f);
    box_max_ = glm::vec3(1.0f);
}

void BridgePass::capture_probes(const scenegraph::World& world,
                                Pipeline& pipeline,
                                const ModelLookup& lookup,
                                const Lighting& lighting) {
    // One attempt per request: without a context (or with an incomplete
    // target) the probes stay invalid and u_has_probe stays 0 rather than
    // retrying every frame.
    probe_dirty_ = false;
    if (!brdf_lut_.ensure() || !probe_green_.ensure() || !probe_yr_.ensure()) {
        std::fprintf(stderr, "[bridge] reflection probes: GL targets unavailable; "
                             "no capture\n");
        return;
    }
    struct CaptureFlag {
        bool& f;
        explicit CaptureFlag(bool& flag) : f(flag) { f = true; }
        ~CaptureFlag() { f = false; }
    };
    auto capture_one = [&](BridgeProbe& probe, float scale) {
        Lighting scaled = lighting;
        scaled.ambient *= scale;
        probe.capture(probe_origin_, [&](const scenegraph::Camera& face_cam) {
            CaptureFlag flag(capture_pass_);
            // render() sets the bridge state itself (depth LESS + write,
            // blend off, cull off) before sub-pass A; the probe has bound and
            // cleared the face.
            render(world, face_cam, pipeline, lookup, scaled,
                   scenegraph::Pass::Bridge, 0);
        });
    };
    capture_one(probe_green_, scale_green_);
    capture_one(probe_yr_, scale_yr_);
    probes_captured_ = probe_green_.valid() && probe_yr_.valid();
    capture_ambient_ = lighting.ambient;
}

const BridgePass::Aabb& BridgePass::model_box(unsigned long long handle,
                                              const assets::Model& m) {
    if (auto it = model_boxes_.find(handle); it != model_boxes_.end())
        return it->second;
    Aabb box;
    box.min = glm::vec3(std::numeric_limits<float>::max());
    box.max = glm::vec3(std::numeric_limits<float>::lowest());
    // Rest pose: the node worlds with an identity instance world and no
    // animated overrides.
    const std::vector<glm::mat4> node_worlds =
        compose_node_worlds(m, glm::mat4(1.0f), {});
    for (std::size_t i = 0; i < m.nodes.size() && i < node_worlds.size(); ++i) {
        for (int mesh_idx : m.nodes[i].meshes) {
            if (mesh_idx < 0 || mesh_idx >= static_cast<int>(m.meshes.size())) continue;
            const auto& cpu = m.meshes[static_cast<std::size_t>(mesh_idx)].cpu_data();
            if (!cpu) continue;
            for (const auto& v : cpu->vertices) {
                const glm::vec3 p = glm::vec3(node_worlds[i] * glm::vec4(v.position, 1.0f));
                box.min = glm::min(box.min, p);
                box.max = glm::max(box.max, p);
                box.valid = true;
            }
        }
    }
    return model_boxes_.emplace(handle, box).first->second;
}

bool BridgePass::update_box(const scenegraph::World& world,
                            const ModelLookup& lookup) {
    // The bridge model: the static main-bridge instance with the most meshes
    // (the shell, ~145 shapes, never the one-mesh viewscreen or a prop).
    const scenegraph::Instance* best = nullptr;
    const assets::Model* best_model = nullptr;
    world.for_each_visible_in_pass(scenegraph::Pass::Bridge,
        [&](const scenegraph::Instance& inst) {
            const assets::Model* m = lookup(inst.model_handle);
            if (!m || !m->skeleton.bones.empty()) return;
            if (!best_model || m->meshes.size() > best_model->meshes.size()) {
                best = &inst;
                best_model = m;
            }
        });
    if (!best) return false;   // nothing drawn: keep the last box
    if (best->model_handle != box_handle_) {
        // A different bridge: captured probes hold the old room.
        if (box_handle_ != 0 && probes_captured_) probe_dirty_ = true;
        box_handle_ = best->model_handle;
    }
    const Aabb& local = model_box(best->model_handle, *best_model);
    if (!local.valid) {
        // No CPU geometry to bound: a box far beyond the room, so the
        // projection degenerates to the plain reflection direction.
        box_min_ = probe_origin_ - glm::vec3(1.0e5f);
        box_max_ = probe_origin_ + glm::vec3(1.0e5f);
        return true;
    }
    glm::vec3 mn(std::numeric_limits<float>::max());
    glm::vec3 mx(std::numeric_limits<float>::lowest());
    for (int c = 0; c < 8; ++c) {
        const glm::vec3 corner((c & 1) ? local.max.x : local.min.x,
                               (c & 2) ? local.max.y : local.min.y,
                               (c & 4) ? local.max.z : local.min.z);
        const glm::vec3 p = glm::vec3(best->world * glm::vec4(corner, 1.0f));
        mn = glm::min(mn, p);
        mx = glm::max(mx, p);
    }
    box_min_ = mn;
    box_max_ = mx;
    return true;
}

float BridgePass::highlight_phase() const {
    // Phase in [0, 1) of the 1 Hz selection pulse. Wrapped in double before
    // the narrowing so a long-running steady_clock never loses float
    // precision in the shader's sin().
    double t = highlight_time_override_;
    if (t < 0.0) {
        t = std::chrono::duration<double>(
                std::chrono::steady_clock::now().time_since_epoch()).count();
    }
    return static_cast<float>(t - std::floor(t));
}

}  // namespace renderer
