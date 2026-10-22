// native/src/renderer/bridge_pass.cc
#include "renderer/bridge_pass.h"
#include "renderer/bridge_lighting_tuning.h"
#include "renderer/bridge_probe_schedule.h"
#include "renderer/frame_timer.h"
#include "renderer/pipeline.h"
#include "renderer/bone_palette.h"
#include "renderer/node_anim.h"

#include <glad/glad.h>

#include <scenegraph/world.h>
#include <scenegraph/camera.h>
#include <scenegraph/instance.h>

#include <assets/file_bytes.h>
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
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <optional>
#include <utility>
#include <vector>

namespace renderer {

int bridge_emissive_texture(const assets::Material& mat, int alert) {
    using S = assets::Material::StageSlot;
    auto slot = [&](S s) { return mat.stages[static_cast<std::size_t>(s)].texture_index; };
    if (alert == kBridgeStateSpecial) {
        if (slot(S::EmissiveSpecial) >= 0) return slot(S::EmissiveSpecial);
        return slot(S::Emissive) >= 0 ? slot(S::Emissive) : -1;
    }
    // Red tries its own map, then the yellow one (spec §11.1: yellow and red
    // share the alert look, §9.4), then the default.
    if (alert == 2 && slot(S::EmissiveRed) >= 0) return slot(S::EmissiveRed);
    if ((alert == 1 || alert == 2) && slot(S::EmissiveYellow) >= 0)
        return slot(S::EmissiveYellow);
    return slot(S::Emissive) >= 0 ? slot(S::Emissive) : -1;
}

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
    const auto bytes = assets::read_binary_file(off_tex_path_);
    if (!bytes) {
        std::fprintf(stderr, "[bridge] viewscreen off texture: open '%s' failed\n",
                     off_tex_path_.c_str());
        return;
    }
    try {
        off_tex_ = assets::upload_image(assets::decode_tga(*bytes),
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
               float metal_override = -1.0f,
               int emissive_alert = 0,
               int glow_src = -1,
               glm::vec3 glow_rgb = glm::vec3(0.0f),
               float glow_level = 0.0f,
               int capture_glow_src = -1,
               glm::vec3 capture_glow_rgb = glm::vec3(0.0f)) {
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
    // Emitter glow (spec §11.2): -1 = none (the texture-level emissive default).
    shader.set_int("u_glow_src", glow_src);
    shader.set_vec3("u_glow_rgb", glow_rgb);
    shader.set_float("u_glow_level", glow_level);
    // A probe face's glow (spec 2026-10-17 §4.1): read only by the capture
    // branch; -1 = none (a base then shows the texture-level default).
    shader.set_int("u_capture_glow_src", capture_glow_src);
    shader.set_vec3("u_capture_glow_rgb", capture_glow_rgb);
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
    // Emissive sibling map (task 17), chosen per alert level; same contract
    // as the maps above (white fallback + flag, set every draw).
    {
        const int ti = bridge_emissive_texture(mat, emissive_alert);
        GLuint id = 0;
        if (ti >= 0 && ti < static_cast<int>(model.textures.size()))
            id = model.textures[static_cast<std::size_t>(ti)].id();
        // Spec §13.1: power offline darkens the texture-level default; a
        // material glow (live, or a probe face's) still samples the map.
        if (glow_src < 0 && capture_glow_src < 0 &&
            emissive_alert == kBridgeStateOffline)
            id = 0;
        shader.set_int("u_has_emissive_map", id != 0 ? 1 : 0);
        glActiveTexture(GL_TEXTURE0 + kBridgeEmissiveUnit);
        glBindTexture(GL_TEXTURE_2D, id != 0 ? id : white_fallback);
    }
    glActiveTexture(GL_TEXTURE0);
    glBindVertexArray(mesh.vao());
    glDrawElements(GL_TRIANGLES, mesh.index_count(), GL_UNSIGNED_INT, nullptr);
}

}  // namespace

namespace {
// TEMPORARY perf experiment (perf/bridge-4k): DAUNTLESS_BRIDGE_EXP bitmask,
// main bridge view only. 1 AO filter off, 2 PBR off, 4 probes off,
// 8 spots + area lights off, 16 depth pre-fill then LEQUAL / no depth write,
// 32 spots off, 64 area lights off.
int bridge_exp() {
    static const int v = [] {
        const char* e = std::getenv("DAUNTLESS_BRIDGE_EXP");
        const int x = e ? std::atoi(e) : 0;
        if (x != 0) std::fprintf(stderr, "[bridge-exp] mask %d\n", x);
        return x;
    }();
    return v;
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
    const int exp_main = (main_bridge && !normal_pass_ && !capture_pass_) ? bridge_exp() : 0;
    // A probe face (spec 2026-10-17 §4.1): which state it shows and which of
    // that state's layers it holds (-1 = the state's base).
    const int cap_layer = (capture_pass_ && capture_probe_ >= kBridgeStates)
        ? capture_probe_ - kBridgeStates : -1;
    const int cap_state = !capture_pass_ ? 0
        : cap_layer >= 0 ? layer_states_[static_cast<std::size_t>(cap_layer)]
                         : capture_probe_;
    // Reflection probes: the box follows the bridge model; this frame's
    // capture steps run here, BEFORE the AO pre-pass, into the probe array
    // (each face re-enters render() with capture_pass_ set). Never inside a
    // nested pass, and never with no bridge drawn: the queue then waits.
    if (main_bridge && !normal_pass_ && !capture_pass_) {
        // The pass reads only `ambient` from Lighting (no directional), and
        // the UNSCALED one: the alert scale never reaches a capture. It is a
        // signature input, so a changed bridge lighting queues every probe.
        capture_ambient_ = lighting.ambient;
        const bool have_bridge = update_box(world, lookup);
        if (capture_requested_ && have_bridge)
            run_capture_steps(world, pipeline, lookup, lighting);
        // A base that just landed with nothing showing snaps in this frame;
        // at dt 0 nothing else moves.
        fade_.update(probe_target_, 0.0f, [this](int s) { return probe_valid(s); });
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
    // draw only -- never a comm set, never a probe capture (draw_probe_face
    // hands each face its probe's ambient).
    const glm::vec3 ambient = lighting.ambient *
        ((main_bridge && !capture_pass_) ? alert_ambient_scale_ : 1.0f);

    // PBR on the main bridge view only: a comm set (another ship's room on
    // the viewscreen) keeps the legacy shading -- the probes would hold the
    // PLAYER's bridge, the wrong room to reflect.
    const int pbr = (pbr_enabled_ && main_bridge && !(exp_main & 2)) ? 1 : 0;
    // Emissive variant by the player's alert level on the main bridge view
    // only; a comm set shows the default. A probe face shows its own state's.
    // (The AO pre-pass returns before the shader reads any emissive.)
    const int emissive_alert = capture_pass_ ? cap_state
                             : main_bridge ? alert_level_ : 0;
    // The reflection (spec §4.2): one weighted list of valid probes -- the
    // bases by their cross-fade weight, the layers by value x their state's
    // base weight. A sampler on a unit with nothing bound must never be
    // sampled, so with no entry the unit stays empty and u_probe_entries = 0
    // keeps the shader off it. The array's texture and each slot's layer move
    // with every reallocation and completed capture: read them now, never
    // cached. Debug view 11 samples the layer entries alone.
    int probe_entries_n = 0;
    int probe_layer[kBridgeMaxProbeEntries] = {};
    float probe_weight[kBridgeMaxProbeEntries] = {};
    if (pbr != 0 && !capture_pass_ && !normal_pass_ && probes_.texture() != 0 &&
        brdf_lut_.texture() != 0 && !(exp_main & 4)) {
        for (const ProbeEntry& e : probe_entries(fade_.w, layer_states_, layer_values_,
                                                 [this](int p) { return probe_valid(p); })) {
            if (debug_view_ == BridgeDebugView::ReflectionLayers && e.probe < kBridgeStates)
                continue;
            probe_layer[probe_entries_n] = probes_.layer_of(e.probe);
            probe_weight[probe_entries_n] = e.weight;
            ++probe_entries_n;
        }
    }
    const bool has_probe = probe_entries_n > 0;
    if (has_probe) {
        glActiveTexture(GL_TEXTURE7);
        glBindTexture(GL_TEXTURE_CUBE_MAP_ARRAY, probes_.texture());
        glActiveTexture(GL_TEXTURE9);
        glBindTexture(GL_TEXTURE_2D, brdf_lut_.texture());
        glActiveTexture(GL_TEXTURE0);
    }

    // A light's radiance in this draw: live outside a capture; in a base, its
    // steady capture colour for the state (live when it has none); in a
    // layer, its at-peak colour if it is a member, else nothing.
    auto capture_light_radiance = [&](const auto& l, int state, int layer) -> glm::vec3 {
        if (!capture_pass_) return l.radiance;
        if (layer >= 0)
            return l.layer[state] == layer ? l.layer_radiance[state] : glm::vec3(0.0f);
        return l.has_capture ? l.capture_radiance[state] : l.radiance;
    };

    // Static spot lights, packed once per render() (both sub-passes share them).
    const int spot_count = (main_bridge && !(exp_main & (8 | 32))) ? static_cast<int>(spots_.size()) : 0;
    if (exp_main != 0) {
        static bool printed = false;
        if (!printed && (!spots_.empty() || !area_lights_.empty())) {
            printed = true;
            std::fprintf(stderr, "[bridge-exp] spots %zu, area rects %zu\n",
                         spots_.size(), area_lights_.size());
        }
    }
    glm::vec3 spot_pos[kBridgeMaxSpots];
    glm::vec3 spot_dir[kBridgeMaxSpots];
    glm::vec3 spot_rad[kBridgeMaxSpots];
    glm::vec4 spot_params[kBridgeMaxSpots];   // x cos_inner, y cos_outer, z range
    for (int i = 0; i < spot_count; ++i) {
        const BridgeSpot& sp = spots_[static_cast<std::size_t>(i)];
        spot_pos[i] = sp.position;
        spot_dir[i] = sp.direction;
        spot_rad[i] = capture_light_radiance(sp, cap_state, cap_layer);
        spot_params[i] = glm::vec4(sp.cos_inner, sp.cos_outer, sp.range, 0.0f);
    }

    // Static area lights (spec §16.3), packed like the spots.
    const int area_count = (main_bridge && !(exp_main & (8 | 64))) ? static_cast<int>(area_lights_.size()) : 0;
    glm::vec4 area_cr[kBridgeMaxAreaLights];   // xyz centre, w range
    glm::vec3 area_u[kBridgeMaxAreaLights];
    glm::vec3 area_v[kBridgeMaxAreaLights];
    glm::vec3 area_rad[kBridgeMaxAreaLights];
    int area_joins[kBridgeMaxAreaLights];
    for (int i = 0; i < area_count; ++i) {
        const BridgeAreaLight& a = area_lights_[static_cast<std::size_t>(i)];
        area_cr[i] = glm::vec4(a.center, a.range);
        area_u[i] = a.half_u;
        area_v[i] = a.half_v;
        area_rad[i] = capture_light_radiance(a, cap_state, cap_layer);
        area_joins[i] = a.joins;
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
        s.set_int("u_ao_on", (ao_on && !(exp_main & 1)) ? 1 : 0);
        s.set_int("u_output_normal", normal_pass_ ? 1 : 0);
        s.set_int("u_debug_view", static_cast<int>(debug_view_));
        // Selection pulse phase: a real clock, once per sub-pass.
        s.set_float("u_highlight_time", pulse_phase);
        // Bridge PBR material maps: own units (draw_mesh binds them per draw).
        s.set_int("u_normal_map", 1);
        s.set_int("u_rough_map", 5);
        s.set_int("u_metal_map", 6);
        s.set_int("u_emissive_map", kBridgeEmissiveUnit);
        s.set_float("u_emissive_scale", kEmissiveScale);
        // Reflection probes + BRDF LUT: units 7/9 assigned on EVERY use,
        // bound or not, so no two sampler types ever share a unit (a cube
        // sampler left on unit 0 beside u_base_color fails every draw).
        s.set_int("u_probes", 7);
        s.set_int("u_probe_entries", probe_entries_n);
        if (probe_entries_n > 0) {
            s.set_int_array("u_probe_layer", probe_layer, probe_entries_n);
            s.set_float_array("u_probe_weight", probe_weight, probe_entries_n);
        }
        s.set_int("u_brdf_lut", 9);
        s.set_vec3("u_probe_pos", probe_origin_);
        s.set_float("u_probe_max_mip", static_cast<float>(kBridgeProbeMips - 1));
        s.set_vec3("u_box_min", box_min_);
        s.set_vec3("u_box_max", box_max_);
        s.set_int("u_capture", capture_pass_ ? 1 : 0);
        s.set_int("u_capture_state", cap_state);
        s.set_int("u_capture_layer", cap_layer);
        s.set_float("u_reflectance", 1.0f);   // the room; sub-pass B sets 0
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
        s.set_int("u_area_count", area_count);
        if (area_count > 0) {
            s.set_vec4_array("u_area_center_range", area_cr, area_count);
            s.set_vec3_array("u_area_u", area_u, area_count);
            s.set_vec3_array("u_area_v", area_v, area_count);
            s.set_vec3_array("u_area_radiance", area_rad, area_count);
            s.set_int_array("u_area_joins", area_joins, area_count);
        }
    };

    // Developer Options debug view 5 (Mesh ID): a per-draw counter, reset
    // every render() call so numbering is stable within a frame.
    int mesh_id_counter = 0;

    // The main view's two sub-passes are timed apart; the AO pre-pass and the
    // probe faces re-enter here inside their own scopes.
    const bool time_main = main_bridge && !normal_pass_ && !capture_pass_;
    std::optional<ScopedFrameTimer> sub_scope;
    if (time_main) sub_scope.emplace(frame_timer(), "bridge.shell");

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
    // A probe face's glow shapes, by mesh (a later entry for a mesh wins).
    std::unordered_map<int, const BridgeGlowCapture*> capture_glow;
    if (capture_pass_ && glow_capture_model_ != 0)
        for (const auto& g : glow_captures_) capture_glow[g.mesh] = &g;
    auto draw_shell = [&](const assets::Model& m, const assets::Mesh& mesh,
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
            // Emitter glow: the main bridge view only, never a probe face.
            int glow_src = -1;
            glm::vec3 glow_rgb(0.0f);
            float glow_level = 0.0f;
            if (main_bridge && !capture_pass_ && glow_model_ != 0 && mh == glow_model_) {
                const int mi = static_cast<int>(&mesh - m.meshes.data());
                if (auto it = glow_.find(mi); it != glow_.end()) {
                    glow_src = it->second.src;
                    glow_rgb = it->second.rgb;
                    glow_level = it->second.level;
                }
            }
            // A probe face's glow (spec 2026-10-17 §4.1): a base shows a glow
            // shape at its steady value; a layer only its members, at peak.
            int cap_glow_src = -1;
            glm::vec3 cap_glow_rgb(0.0f);
            if (!capture_glow.empty() && mh == glow_capture_model_) {
                const int mi = static_cast<int>(&mesh - m.meshes.data());
                if (auto it = capture_glow.find(mi); it != capture_glow.end()) {
                    const BridgeGlowCapture& g = *it->second;
                    if (cap_layer < 0) {
                        cap_glow_src = g.src;
                        cap_glow_rgb = g.base[cap_state];
                    } else if (g.layer[cap_state] == cap_layer) {
                        cap_glow_src = g.src;
                        cap_glow_rgb = g.layer_rgb[cap_state];
                    }
                }
            }
            draw_mesh(m, mesh, mat, base_shader, w, white, t, ov, flip,
                      viewscreen_brightness_, viewscreen_flash_,
                      /*face_blend=*/false, /*face_a=*/0u, /*face_b=*/0u,
                      /*face_mix=*/0.0f, mesh_id_counter++, hl,
                      pbr, rough_ov, metal_ov, emissive_alert,
                      glow_src, glow_rgb, glow_level, cap_glow_src, cap_glow_rgb);
        };
    if (exp_main & 16) {
        // Depth only, through the same program (the normal-output early
        // return), so the shading draw below matches its depth exactly.
        glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE);
        base_shader.set_int("u_output_normal", 1);
        walk_bridge_meshes(world, lookup, pass, comm_set_id, draw_shell);
        base_shader.set_int("u_output_normal", 0);
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        glDepthFunc(GL_LEQUAL);
        glDepthMask(GL_FALSE);
    }
    walk_bridge_meshes(world, lookup, pass, comm_set_id, draw_shell);
    if (exp_main & 16) {
        glDepthFunc(GL_LESS);
        glDepthMask(GL_TRUE);
    }

    // ── Sub-pass B: skinned bridge characters ──────────────────────────────
    sub_scope.reset();
    if (time_main) sub_scope.emplace(frame_timer(), "bridge.crew");
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
        // Characters reflect nothing (bridge.frag u_reflectance).
        skin_shader.set_float("u_reflectance", 0.0f);

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
                                  /*highlight=*/0, pbr,  // officers: no overrides
                                  -1.0f, -1.0f, emissive_alert);
                    }
                }
            });
    }
    sub_scope.reset();

    glBindVertexArray(0);
    // The PBR map units (bound per draw) never leak to the next pass.
    for (GLenum unit : {GLenum{GL_TEXTURE1}, GLenum{GL_TEXTURE5}, GLenum{GL_TEXTURE6},
                        GLenum{GL_TEXTURE9},
                        static_cast<GLenum>(GL_TEXTURE0 + kBridgeEmissiveUnit)}) {
        glActiveTexture(unit);
        glBindTexture(GL_TEXTURE_2D, 0);
    }
    // ...nor the probe array.
    glActiveTexture(GL_TEXTURE7);
    glBindTexture(GL_TEXTURE_CUBE_MAP_ARRAY, 0);
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

namespace {

/// A light pushed without capture colours captures, in every state, with the
/// radiance it was pushed with -- never the live colour set_*_radiance
/// writes later, which must neither reach a probe nor move a signature
/// (spec §11.4: a pulse never recaptures).
template <class L>
void freeze_capture_colour(L& l) {
    if (l.has_capture) return;
    for (auto& c : l.capture_radiance) c = l.radiance;
    l.has_capture = true;
}

/// FNV-1a, 64 bit, over raw bytes.
class Fnv1a {
public:
    template <class T>
    void add(const T& v) {
        unsigned char b[sizeof(T)];
        std::memcpy(b, &v, sizeof(T));
        for (unsigned char c : b) { h_ ^= c; h_ *= 1099511628211ull; }
    }
    void add(const glm::vec3& v) { add(v.x); add(v.y); add(v.z); }
    std::uint64_t value() const { return h_; }
private:
    std::uint64_t h_ = 14695981039346656037ull;
};

}  // namespace

std::uint64_t BridgePass::probe_signature(int probe) const {
    if (probe < 0 || probe >= probe_count()) return 0;
    const bool layer = probe >= kBridgeStates;
    const int k = probe - kBridgeStates;
    const int s = layer ? layer_states_[static_cast<std::size_t>(k)] : probe;
    Fnv1a h;
    h.add(layer ? 1 : 0);
    h.add(s);
    // Inputs every probe reads.
    h.add(overrides_model_);
    std::vector<std::pair<int, std::pair<float, float>>> ov(overrides_.begin(),
                                                            overrides_.end());
    std::sort(ov.begin(), ov.end());       // unordered_map: hash in a stable order
    for (const auto& o : ov) { h.add(o.first); h.add(o.second.first); h.add(o.second.second); }
    h.add(probe_origin_);
    h.add(box_handle_);
    h.add(capture_ambient_);
    for (const auto& sp : spots_) {
        h.add(sp.position); h.add(sp.direction);
        h.add(sp.cos_inner); h.add(sp.cos_outer); h.add(sp.range);
    }
    for (const auto& al : area_lights_) {
        h.add(al.center); h.add(al.half_u); h.add(al.half_v); h.add(al.range);
    }
    h.add(glow_capture_model_);
    for (const auto& g : glow_captures_) { h.add(g.mesh); h.add(g.src); }
    // Inputs only this probe reads.
    if (!layer) {
        h.add(scales_[static_cast<std::size_t>(s)]);
        auto light = [&](const auto& l) {
            h.add(l.has_capture);
            h.add(l.has_capture ? l.capture_radiance[s] : l.radiance);
        };
        for (const auto& sp : spots_) light(sp);
        for (const auto& al : area_lights_) light(al);
        for (const auto& g : glow_captures_) h.add(g.base[s]);
    } else {
        auto member = [&](const auto& l, int idx) {
            if (l.layer[s] != k) return;
            h.add(idx);
            h.add(l.layer_radiance[s]);
        };
        int i = 0;
        for (const auto& sp : spots_) member(sp, i++);
        i = 0;
        for (const auto& al : area_lights_) member(al, i++);
        i = 0;
        for (const auto& g : glow_captures_) {
            if (g.layer[s] == k) { h.add(i); h.add(g.layer_rgb[s]); }
            ++i;
        }
    }
    return h.value();
}

std::size_t BridgePass::set_probe_layers(std::vector<int> layer_states,
                                         std::vector<std::uint64_t> identities) {
    std::vector<int> states;
    std::vector<std::uint64_t> ids;
    for (std::size_t k = 0; k < layer_states.size(); ++k) {
        const int st = layer_states[k];
        if (st < 0 || st >= kBridgeStates) continue;
        states.push_back(st);
        ids.push_back(k < identities.size() ? identities[k]
                                            : static_cast<std::uint64_t>(st));
    }
    // A slot whose layer changed holds another layer's capture (or one freed
    // with the old count): never sample it before its own lands.
    for (std::size_t k = 0; k < ids.size(); ++k) {
        if (k < layer_ids_.size() && layer_ids_[k] == ids[k]) continue;
        const int probe = kBridgeStates + static_cast<int>(k);
        probes_.invalidate(probe);
        if (static_cast<std::size_t>(probe) < captured_sigs_.size())
            captured_sigs_[static_cast<std::size_t>(probe)] = 0;
    }
    const std::size_t dropped = layer_states.size() - states.size();
    layer_states_ = std::move(states);
    layer_ids_ = std::move(ids);
    return dropped;
}

void BridgePass::set_glow_captures(unsigned long long model_handle,
                                   std::vector<BridgeGlowCapture> captures) {
    glow_captures_ = std::move(captures);
    glow_capture_model_ = glow_captures_.empty() ? 0 : model_handle;
}

void BridgePass::set_material_overrides(
        unsigned long long model_handle,
        std::vector<BridgeMaterialOverride> overrides) {
    std::unordered_map<int, std::pair<float, float>> next;
    for (const auto& o : overrides)
        next[o.mesh] = {o.roughness, o.metalness};
    // A signature input of every probe: a CHANGED set queues them, an
    // identical re-push (the editor re-pushes after every action, no-ops
    // included) does not. With no entries the model is moot, so it is not
    // kept (none over none hashes the same whatever handle came with it).
    overrides_ = std::move(next);
    overrides_model_ = overrides_.empty() ? 0 : model_handle;
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
        freeze_capture_colour(sp);
    }
    // The probes hold the room lit by the spots' diffuse; the SANITISED list
    // is what probe_signature reads, so an alert change that re-pushes the
    // same list queues nothing.
    spots_ = std::move(spots);
    return dropped;
}

void BridgePass::set_spot_radiance(const std::vector<glm::vec3>& radiance) {
    const std::size_t n = std::min(radiance.size(), spots_.size());
    for (std::size_t i = 0; i < n; ++i) {
        const glm::vec3& r = radiance[i];
        spots_[i].radiance = (std::isfinite(r.x) && std::isfinite(r.y) && std::isfinite(r.z))
            ? r : glm::vec3(0.0f);
    }
}

std::size_t BridgePass::set_area_lights(std::vector<BridgeAreaLight> lights) {
    const std::size_t cap = static_cast<std::size_t>(kBridgeMaxAreaLights);
    const std::size_t dropped = lights.size() > cap ? lights.size() - cap : 0;
    if (dropped > 0) lights.resize(cap);
    for (auto& l : lights) freeze_capture_colour(l);
    area_lights_ = std::move(lights);   // a signature input (probe_signature)
    return dropped;
}

void BridgePass::set_area_radiance(const std::vector<glm::vec3>& radiance) {
    const std::size_t n = std::min(radiance.size(), area_lights_.size());
    for (std::size_t i = 0; i < n; ++i) {
        const glm::vec3& r = radiance[i];
        area_lights_[i].radiance = (std::isfinite(r.x) && std::isfinite(r.y) && std::isfinite(r.z))
            ? r : glm::vec3(0.0f);
    }
}

void BridgePass::set_glow(unsigned long long model_handle, std::vector<BridgeGlow> glow) {
    glow_.clear();
    for (const auto& g : glow) glow_[g.mesh] = g;
    glow_model_ = glow_.empty() ? 0 : model_handle;
}

void BridgePass::set_probe_state(int state, float dt) {
    probe_target_ = (state >= 0 && state < kBridgeStates) ? state : -1;
    fade_.update(probe_target_, dt, [this](int s) { return probe_valid(s); });
}

float BridgePass::base_weight(int state) const {
    return (state >= 0 && state < kBridgeStates) ? fade_.w[state] : 0.0f;
}

void BridgePass::set_layer_values(std::vector<float> values) {
    for (float& v : values)
        if (!std::isfinite(v)) v = 0.0f;
    layer_values_ = std::move(values);
}

int BridgePass::shown_state() const {
    return probe_target_ >= 0 ? probe_target_ : 0;
}

bool BridgePass::probe_valid(int probe) const {
    return probe >= 0 && probe < probe_count() && probes_.valid(probe);
}

bool BridgePass::probes_valid() const {
    return probe_valid(shown_state()) && brdf_lut_.texture() != 0;
}

int BridgePass::probe_captures_completed(int probe) const {
    return (probe >= 0 && probe < static_cast<int>(captures_completed_.size()))
        ? captures_completed_[static_cast<std::size_t>(probe)] : 0;
}

bool BridgePass::probe_needs_capture(int probe) const {
    if (!probe_valid(probe)) return true;
    const auto i = static_cast<std::size_t>(probe);
    return i >= captured_sigs_.size() || captured_sigs_[i] == 0 ||
           captured_sigs_[i] != probe_signature(probe);
}

bool BridgePass::probes_settled() const {
    if (!capture_requested_) return true;
    if (probes_.in_flight()) return false;
    return next_probe(shown_state(), layer_states_,
                      [this](int p) { return probe_needs_capture(p); }) < 0;
}

void BridgePass::request_probe_capture() {
    capture_requested_ = true;
    storage_failed_ = false;
    std::fill(captured_sigs_.begin(), captured_sigs_.end(), std::uint64_t{0});
    probes_.abandon();
}

void BridgePass::reset_probes() {
    capture_requested_ = false;
    storage_failed_ = false;
    captured_sigs_.clear();
    probes_.shrink_to(0);   // frees every probe (and drops the one in flight)
    probes_.abandon();      // ...even with nothing allocated to free
    fade_ = ProbeFade{};
    model_boxes_.clear();
    box_handle_ = 0;
    box_min_ = glm::vec3(-1.0f);
    box_max_ = glm::vec3(1.0f);
}

bool BridgePass::sync_probe_storage() {
    const int n = probe_count();
    // Never with the array bound on unit 0: a reallocation restores the
    // caller's unit-0 binding, which would then name a deleted texture. The
    // capture block runs before render() binds anything.
    if (probes_.capacity() > n) probes_.shrink_to(n);
    if (!probes_.ensure(n)) return false;
    captured_sigs_.resize(static_cast<std::size_t>(n), 0);
    if (captures_completed_.size() < static_cast<std::size_t>(n))
        captures_completed_.resize(static_cast<std::size_t>(n), 0);
    return true;
}

void BridgePass::swap_inputs(ProbeInputs& in) {
    std::swap(spots_, in.spots);
    std::swap(area_lights_, in.areas);
    std::swap(glow_capture_model_, in.glow_capture_model);
    std::swap(glow_captures_, in.glow_captures);
    std::swap(overrides_model_, in.overrides_model);
    std::swap(overrides_, in.overrides);
    std::swap(scales_, in.scales);
    std::swap(layer_states_, in.layer_states);
    std::swap(probe_origin_, in.origin);
    std::swap(capture_ambient_, in.ambient);
}

void BridgePass::begin_probe(int probe) {
    snapshot_ = ProbeInputs{spots_, area_lights_, glow_capture_model_, glow_captures_,
                            overrides_model_, overrides_, scales_, layer_states_,
                            probe_origin_, capture_ambient_};
    snapshot_sig_ = probe_signature(probe);
    probes_.begin(probe);
}

void BridgePass::step_probe(const scenegraph::World& world, Pipeline& pipeline,
                            const ModelLookup& lookup, const Lighting& lighting) {
    const int probe = probes_.in_flight_slot();
    if (probe < 0) return;
    // The snapshot is the live input set for the duration of the step, so
    // the re-entered render() (and probe_scale) read it; swapped back out
    // on every exit.
    struct Swapped {
        BridgePass& p;
        explicit Swapped(BridgePass& pass) : p(pass) { p.swap_inputs(p.snapshot_); }
        ~Swapped() { p.swap_inputs(p.snapshot_); }
    };
    bool done = false;
    {
        Swapped swapped(*this);
        Lighting snap = lighting;
        snap.ambient = capture_ambient_;
        done = probes_.step(probe_origin_, [&](const scenegraph::Camera& face_cam) {
            draw_probe_face(probe, face_cam, world, pipeline, lookup, snap);
        });
    }
    if (!done) return;
    const auto i = static_cast<std::size_t>(probe);
    if (i < captured_sigs_.size()) captured_sigs_[i] = snapshot_sig_;
    if (i < captures_completed_.size()) ++captures_completed_[i];
}

void BridgePass::run_capture_steps(const scenegraph::World& world, Pipeline& pipeline,
                                   const ModelLookup& lookup, const Lighting& lighting) {
    if (storage_failed_) return;
    if (!brdf_lut_.ensure() || !sync_probe_storage()) {
        // One report per request: without a context (or with an incomplete
        // target) the probes stay invalid and u_probe_entries stays 0 rather
        // than retrying every frame.
        storage_failed_ = true;
        std::fprintf(stderr, "[bridge] reflection probes: GL targets unavailable; "
                             "no capture\n");
        return;
    }
    // 0 = unlimited (test seam), bounded anyway: inside one render() the
    // inputs cannot change, so the queue drains in at most the rest of the
    // probe in flight plus one capture of every probe.
    const int budget = steps_per_frame_ > 0
        ? steps_per_frame_ : (probe_count() + 1) * probes_.steps_per_probe();
    auto needs = [this](int p) { return probe_needs_capture(p); };
    for (int i = 0; i < budget; ++i) {
        if (!probes_.in_flight()) {
            const int next = next_probe(shown_state(), layer_states_, needs);
            if (next < 0) break;
            begin_probe(next);
            if (!probes_.in_flight()) break;   // never: storage is synced
        }
        DAUNTLESS_FRAME_SCOPE("bridge.probe_capture");
        step_probe(world, pipeline, lookup, lighting);
    }
}

void BridgePass::draw_probe_face(int probe, const scenegraph::Camera& face_cam,
                                 const scenegraph::World& world, Pipeline& pipeline,
                                 const ModelLookup& lookup, const Lighting& lighting) {
    struct CaptureFlag {
        bool& f;
        explicit CaptureFlag(bool& flag) : f(flag) { f = true; }
        ~CaptureFlag() { f = false; }
    };
    // A base is lit by the state's ambient (the unscaled bridge ambient x its
    // probe scale); a layer by its members alone.
    Lighting scaled = lighting;
    scaled.ambient = probe >= kBridgeStates ? glm::vec3(0.0f)
                                            : lighting.ambient * probe_scale(probe);
    capture_probe_ = probe;
    CaptureFlag flag(capture_pass_);
    render(world, face_cam, pipeline, lookup, scaled, scenegraph::Pass::Bridge, 0);
}

void BridgePass::capture_probe_now(int probe, const scenegraph::World& world,
                                   Pipeline& pipeline, const ModelLookup& lookup,
                                   const Lighting& lighting) {
    if (probe < 0 || probe >= probe_count()) return;
    if (!sync_probe_storage()) {
        std::fprintf(stderr, "[bridge] reflection probe array: GL targets unavailable; "
                             "no capture\n");
        return;
    }
    capture_ambient_ = lighting.ambient;
    begin_probe(probe);
    for (int i = 0; i < probes_.steps_per_probe() && probes_.in_flight(); ++i)
        step_probe(world, pipeline, lookup, lighting);
}

bool BridgePass::read_probe(int probe, int mip, std::vector<glm::vec3>& rgb) const {
    rgb.clear();
    if (probe < 0 || probe >= probes_.capacity() || !probes_.valid(probe) ||
        mip < 0 || mip >= kBridgeProbeMips || probes_.texture() == 0)
        return false;
    const int n = std::max(1, kBridgeProbeFace >> mip);
    GLint prev_read = 0, prev_pack = 4;
    glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &prev_read);
    glGetIntegerv(GL_PACK_ALIGNMENT, &prev_pack);
    GLuint fbo = 0;
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, fbo);
    glPixelStorei(GL_PACK_ALIGNMENT, 4);
    std::vector<float> px(static_cast<std::size_t>(n) * n * 4);
    rgb.reserve(static_cast<std::size_t>(6) * n * n);
    bool ok = true;
    for (int face = 0; face < 6 && ok; ++face) {
        glFramebufferTextureLayer(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                  probes_.texture(), mip,
                                  probes_.layer_of(probe) * 6 + face);
        glReadBuffer(GL_COLOR_ATTACHMENT0);
        ok = glCheckFramebufferStatus(GL_READ_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
        if (!ok) break;
        glReadPixels(0, 0, n, n, GL_RGBA, GL_FLOAT, px.data());
        for (std::size_t i = 0; i < static_cast<std::size_t>(n) * n; ++i)
            rgb.emplace_back(px[i * 4], px[i * 4 + 1], px[i * 4 + 2]);
    }
    glBindFramebuffer(GL_READ_FRAMEBUFFER, static_cast<GLuint>(prev_read));
    glDeleteFramebuffers(1, &fbo);
    glPixelStorei(GL_PACK_ALIGNMENT, prev_pack);
    if (!ok) rgb.clear();
    return ok;
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
        // A different bridge: every probe (and the one in flight) holds the
        // old room. Free them all and zero the base weights, so nothing is
        // reflected until the new room's shown base lands (then it snaps).
        // Nothing is bound yet: this runs before render() binds a unit.
        if (box_handle_ != 0) {
            probes_.shrink_to(0);
            probes_.abandon();
            fade_ = ProbeFade{};
        }
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
