// native/src/renderer/breach_pass.cc
#include <renderer/breach_pass.h>

#include <renderer/pipeline.h>
#include <renderer/carve_field_cache.h>
#include "sphere_mesh.h"

#include <scenegraph/breach_events.h>
#include <scenegraph/camera.h>
#include <scenegraph/hull_carve.h>
#include <scenegraph/instance.h>
#include <scenegraph/world.h>
#include <assets/model.h>
#include <assets/mesh.h>
#include <assets/texture.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <unordered_map>
#include <vector>

// Toggle for the hull-breach renderer (carve emission + clip + breach surface).
// Defined in frame.cc (librenderer); forward-declared here so the pass can gate
// itself without a circular dependency. When off, render() does nothing.
namespace dauntless_hull_damage {
    bool enabled();
}

namespace renderer {

namespace {

// Animated interior texture: 4 frames of the same damage texture, cycled by
// the game clock. (BC ships these loose in data/, separate from the static
// Textures/Effects/Damage.tga.) 64x64 24-bit RGB each.
constexpr const char* kDamageFramePaths[4] = {
    "game/data/Damage1.tga",
    "game/data/Damage2.tga",
    "game/data/Damage3.tga",
    "game/data/Damage4.tga",
};
// Animation playback rate (frames/sec). 4 frames at 8 fps = a 0.5s loop —
// a lively damage shimmer on the breach interior. Eyeball-tunable.
constexpr float kDamageAnimFps = 8.0f;

// Target triangle count for the scoop sphere. 16×24 lat/lon segments ≈ 768
// triangles: more than enough resolution for a 1–5 GU breach.
constexpr int kSphereTargetTris = 768;

// Triplanar texture scale: 1 period over ~40 model units (body-frame).
// The carve scoop spans ~50-400 model units (radius 25-200), so this gives
// roughly 1-10 readable Damage.tga features across a breach. The old 1/4
// tiled the 128px texture ~12-50x across a scoop; minified through mipmaps
// that averaged to the texture's mean colour and read as a flat, untextured
// surface. Eyeball-tunable: lower = larger features.
constexpr float kTexScale = 1.0f / 40.0f;

// Returns the uploaded texture (id() == 0 on failure). The CALLER owns the
// returned Texture and must keep it alive for as long as the GL id is used —
// see BreachPass::damage_owned_. Owning the texture on the pass (rather than a
// process-lifetime static) is essential: init()/shutdown() destroy and recreate
// the GL context per session, and a fresh context reuses GL ids from 1. A
// static that outlives the context would leave Texture objects whose ids alias
// a *different* live texture in the next context — and whose eventual deletion
// corrupts that context's state (observed as a stray GL_INVALID_OPERATION
// surfacing at the next check_gl, e.g. in upload_mesh). Tying ownership to the
// pass means shutdown()'s g_breach_pass.reset() releases them in the correct,
// still-current context.
assets::Texture load_damage_tga(const char* path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[breach] failed to open '%s'\n", path);
        return assets::Texture{};
    }
    std::vector<std::uint8_t> bytes((std::istreambuf_iterator<char>(in)),
                                    std::istreambuf_iterator<char>());
    try {
        assets::Image img = assets::decode_tga(bytes);
        return assets::upload_image(img, /*generate_mipmaps=*/true);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[breach] decode/upload '%s' failed: %s\n",
                     path, e.what());
        return assets::Texture{};
    }
}

}  // namespace

BreachPass::BreachPass() = default;

BreachPass::~BreachPass() {
    // Release per-instance fill textures (test/standalone path).
    for (auto& kv : fill_cache_) {
        if (kv.second.tex3d) {
            GLuint t = kv.second.tex3d;
            glDeleteTextures(1, &t);
            kv.second.tex3d = 0;
        }
    }
}

void BreachPass::ensure_sphere() {
    if (sphere_mesh_) return;
    assets::MeshCpu cpu = build_uv_sphere(kSphereTargetTris);
    sphere_mesh_ = std::make_unique<assets::Mesh>(assets::upload_mesh(cpu));
}

void BreachPass::ensure_damage_frames() {
    if (damage_frames_tried_) return;
    damage_frames_tried_ = true;
    for (int i = 0; i < 4; ++i) {
        assets::Texture tex = load_damage_tga(kDamageFramePaths[i]);
        damage_frames_[i] = tex.id();
        damage_owned_.emplace_back(std::move(tex));  // keep the id alive on the pass
    }
}

/*static*/
unsigned int BreachPass::upload_fill_tex(const voxel::VoxelVolume& fill) {
    if (fill.occ.empty() || fill.dims.x <= 0 || fill.dims.y <= 0 ||
        fill.dims.z <= 0) {
        return 0;
    }
    GLuint t = 0;
    glGenTextures(1, &t);
    glBindTexture(GL_TEXTURE_3D, t);

    GLint prev = 0;
    glGetIntegerv(GL_UNPACK_ALIGNMENT, &prev);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);

    glTexImage3D(GL_TEXTURE_3D, 0, GL_R8,
                 fill.dims.x, fill.dims.y, fill.dims.z, 0,
                 GL_RED, GL_UNSIGNED_BYTE, fill.occ.data());
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_R, GL_CLAMP_TO_EDGE);
    glBindTexture(GL_TEXTURE_3D, 0);
    glPixelStorei(GL_UNPACK_ALIGNMENT, prev);
    return t;
}

void BreachPass::draw_scoop(const glm::vec3& center_body,
                             float radius,
                             const glm::vec3& surface_normal,
                             unsigned int fill_tex,
                             const glm::vec3& fill_origin,
                             const glm::vec3& fill_cell,
                             const glm::ivec3& fill_dims,
                             const glm::mat4& world_xf,
                             const scenegraph::Camera& camera,
                             Pipeline& pipeline,
                             float breach_age,
                             unsigned int damage_tex) {
    // Camera world position: inverse of view matrix column 3, computed once
    // CPU-side per draw (not per fragment). Matches how the opaque pass derives
    // u_camera_pos_ws in submit_opaque / submit_opaque_in_pass.
    const glm::vec3 cam_pos_ws =
        glm::vec3(glm::inverse(camera.view_matrix())[3]);

    auto& shader = pipeline.breach_shader();
    shader.use();
    shader.set_mat4("u_model",           world_xf);
    shader.set_mat4("u_view",            camera.view_matrix());
    shader.set_mat4("u_proj",            camera.proj_matrix());
    shader.set_vec3("u_camera_pos_ws",   cam_pos_ws);
    shader.set_vec3("u_carve_center",    center_body);
    shader.set_float("u_carve_radius",   radius);
    shader.set_vec3("u_carve_normal",    surface_normal);

    // Fill mask (original uncarved fill).
    shader.set_int("u_fill",    0);
    shader.set_vec3("u_fill_origin", fill_origin);
    shader.set_vec3("u_fill_cell",   fill_cell);
    shader.set_ivec3("u_fill_dims",  fill_dims);
    shader.set_float("u_fill_iso",
                     static_cast<float>(CarveFieldCache::kIsovalue) / 255.0f);

    // Triplanar Damage.tga on unit 1.
    shader.set_int("u_damage_tex", 1);
    shader.set_float("u_tex_scale", kTexScale);

    // Molten-rim emissive: age of the nearest active breach event.
    // breach_age >= kRimLife → heat = 0 → no emissive (cold hole).
    shader.set_float("u_breach_age", breach_age);
    shader.set_float("u_rim_life",   scenegraph::kRimLife);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_3D, fill_tex);

    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, damage_tex);

    glBindVertexArray(sphere_mesh_->vao());
    glDrawElements(GL_TRIANGLES,
                   static_cast<GLsizei>(sphere_mesh_->index_count()),
                   GL_UNSIGNED_INT, nullptr);
    glBindVertexArray(0);
}

void BreachPass::draw_instance(std::uintptr_t instance_key,
                               const voxel::VoxelVolume& fill,
                               const scenegraph::HullCarveField& carve,
                               const glm::mat4& world_xf,
                               const scenegraph::Camera& camera,
                               Pipeline& pipeline,
                               float breach_age) {
    if (carve.count() == 0) return;

    ensure_sphere();
    ensure_damage_frames();

    // Build + upload the fill 3D texture. In the test/standalone path there is
    // no shared CarveFieldCache, so we own the texture in fill_cache_ (member).
    // Repeated calls with the same instance_key reuse the cached texture.
    auto& fe = fill_cache_[instance_key];
    if (fe.tex3d == 0) {
        fe.tex3d = upload_fill_tex(fill);
    }
    if (fe.tex3d == 0) return;

    // GL state: depth ON, cull FRONT (inner/far sphere wall → recessed).
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_FRONT);

    for (const auto& s : carve.slots()) {
        if (!s.active) continue;
        if (s.radius <= 0.0f) continue;   // sub-iso accumulation: invisible
        draw_scoop(s.center_body, s.radius, s.surface_normal,
                   fe.tex3d, fill.origin, fill.cell, fill.dims,
                   world_xf, camera, pipeline,
                   breach_age, damage_frames_[0]);
    }

    // Restore cull state.
    glCullFace(GL_BACK);

    // Restore texture bindings.
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, 0);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_3D, 0);
}

void BreachPass::render(const scenegraph::World& world,
                        const scenegraph::Camera& camera,
                        Pipeline& pipeline,
                        const ModelLookup& lookup,
                        CarveFieldCache& carve_cache,
                        float now) {
    if (!dauntless_hull_damage::enabled()) return;

    ensure_sphere();
    ensure_damage_frames();

    // Current animation frame, cycled by the game clock. All scoops drawn this
    // frame share it. frame_tex may be 0 (asset missing) → shader grey base.
    int frame = 0;
    if (now > 0.f) {
        frame = static_cast<int>(now * kDamageAnimFps) & 3;  // % 4, now >= 0
    }
    const unsigned int frame_tex = damage_frames_[frame];

    bool any_state_changed = false;
    auto ensure_state = [&]() {
        if (any_state_changed) return;
        any_state_changed = true;
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);
        glDisable(GL_BLEND);
        glEnable(GL_CULL_FACE);
        glCullFace(GL_FRONT);
    };

    world.for_each_visible_in_pass(
        scenegraph::Pass::Space,
        [&](const scenegraph::Instance& inst) {
            if (inst.carve.count() == 0) return;
            const assets::Model* model = lookup(inst.model_handle);
            if (!model) return;
            if (model->source.empty()) return;

            const CarveFieldCache::Entry* ce =
                carve_cache.get_for_source(model->source);
            if (ce == nullptr) return;

            ensure_state();

            for (const auto& s : inst.carve.slots()) {
                if (!s.active) continue;
                if (s.radius <= 0.0f) continue;   // sub-iso accumulation: invisible

                // Find the nearest active breach event for this carve slot.
                float breach_age = scenegraph::kRimLife + 1.f;  // default: cold
                float best_dist  = 1e30f;
                for (const auto& ev : inst.breach_events.slots()) {
                    if (!ev.active) continue;
                    const float d = glm::length(ev.center_body - s.center_body);
                    if (d < best_dist) {
                        best_dist   = d;
                        breach_age  = now - ev.birth_time;
                    }
                }

                draw_scoop(s.center_body, s.radius, s.surface_normal,
                           ce->tex3d, ce->origin, ce->cell, ce->dims,
                           inst.world, camera, pipeline, breach_age, frame_tex);
            }
        });

    if (any_state_changed) {
        glCullFace(GL_BACK);
        glEnable(GL_DEPTH_TEST);
        glEnable(GL_CULL_FACE);
        glDepthMask(GL_TRUE);
        glDisable(GL_BLEND);
        // Restore texture bindings.
        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_2D, 0);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_3D, 0);
    }
}

}  // namespace renderer
