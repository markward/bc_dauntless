// native/src/renderer/breach_pass.cc
#include <renderer/breach_pass.h>

#include <renderer/pipeline.h>
#include <renderer/carve_field_cache.h>
#include <renderer/instance_field_cache.h>
#include <renderer/asset_path.h>

#include <scenegraph/breach_events.h>
#include <scenegraph/camera.h>
#include <scenegraph/instance.h>
#include <scenegraph/world.h>
#include <assets/model.h>
#include <assets/mesh.h>
#include <assets/texture.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/matrix_inverse.hpp>

#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <string>
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
    "data/Damage1.tga",
    "data/Damage2.tga",
    "data/Damage3.tga",
    "data/Damage4.tga",
};
// Animation playback rate (frames/sec). 4 frames at 8 fps = a 0.5s loop —
// a lively damage shimmer on the breach interior. Eyeball-tunable.
constexpr float kDamageAnimFps = 8.0f;

// Triplanar texture scale: 1 period over ~40 model units (body-frame).
// Eyeball-tunable: lower = larger features.
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

// Unit cube ([0,1]^3), one box proxy per damaged instance (raymarched-
// breach-interior Task 3 — supersedes build_uv_sphere's per-carve sphere).
//
// 24 vertices (4 per face, not 8 shared corners): each face needs its own
// flat winding, and duplicating corners is negligible cost for a mesh this
// small (12 triangles total) versus the index bookkeeping of a shared-corner
// cube.
//
// Each face is parameterised as p(u,v) = face_origin + u*U + v*V with U, V
// chosen so cross(U, V) == the face's OUTWARD normal (a right-handed
// tangent basis).
//
// Winding: (p00,p11,p01)/(p00,p10,p11) below is COUNTER-clockwise from
// outside, on every face — the correct, standard convention, and the SAME
// one build_uv_sphere.cc actually uses (see that file's own comment).
//
// This took a real GL render to get right rather than a hand derivation: a
// first version here reproduced sphere_mesh.cc's PRE-fix comment, which
// claimed "clockwise from outside" — a hand signed-area check for the +Z
// face (U=(1,0,0), V=(0,1,0), the standard "looking down -Z from +Z" 2D
// view) taking that claim at face value predicted (p00,p01,p11)/
// (p00,p11,p10) instead. BreachPassGLTest.SolidFillDrawsInterior failed
// against that prediction — cull(FRONT) was keeping the near face instead
// of the far one — and the OPPOSITE triangulation (below) was what actually
// worked. sphere_mesh.cc's "clockwise" comment was independently re-checked
// by hand afterward (a code review caught it) and found to have simply been
// wrong the whole time: build_uv_sphere IS also CCW-from-outside, so the two
// meshes agree after all — see sphere_mesh.cc's corrected comment for that
// derivation. Both meshes are drawn with glCullFace(GL_FRONT) so only the
// back (far, as seen from outside) faces survive rasterisation.
assets::MeshCpu build_unit_box_cpu() {
    using assets::MeshCpu;

    struct Face {
        glm::vec3 origin, u, v, n;
    };
    // Six faces, each with its own right-handed (u, v, n=u×v) tangent basis
    // — see this function's header comment for the winding derivation.
    const Face faces[6] = {
        {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}, {1, 0, 0}},   // +X
        {{0, 0, 0}, {0, 0, 1}, {0, 1, 0}, {-1, 0, 0}},  // -X
        {{0, 1, 0}, {0, 0, 1}, {1, 0, 0}, {0, 1, 0}},   // +Y
        {{0, 0, 0}, {1, 0, 0}, {0, 0, 1}, {0, -1, 0}},  // -Y
        {{0, 0, 1}, {1, 0, 0}, {0, 1, 0}, {0, 0, 1}},   // +Z
        {{0, 0, 0}, {0, 1, 0}, {1, 0, 0}, {0, 0, -1}},  // -Z
    };

    MeshCpu cpu;
    cpu.vertices.reserve(24);
    cpu.indices.reserve(36);

    for (const Face& f : faces) {
        const std::uint32_t base = static_cast<std::uint32_t>(cpu.vertices.size());
        const glm::vec3 p00 = f.origin;
        const glm::vec3 p01 = f.origin + f.v;
        const glm::vec3 p10 = f.origin + f.u;
        const glm::vec3 p11 = f.origin + f.u + f.v;
        for (const glm::vec3& p : {p00, p01, p10, p11}) {
            MeshCpu::Vertex vert;
            vert.position = p;
            vert.normal   = f.n;
            cpu.vertices.push_back(vert);
        }
        // p00=base+0, p01=base+1, p10=base+2, p11=base+3.
        // Empirically-verified triangulation (see this function's header
        // comment): (p00,p11,p01), (p00,p10,p11).
        cpu.indices.push_back(base + 0); cpu.indices.push_back(base + 3); cpu.indices.push_back(base + 1);
        cpu.indices.push_back(base + 0); cpu.indices.push_back(base + 2); cpu.indices.push_back(base + 3);
    }

    return cpu;
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

void BreachPass::ensure_box() {
    if (box_mesh_) return;
    assets::MeshCpu cpu = build_unit_box_cpu();
    box_mesh_ = std::make_unique<assets::Mesh>(assets::upload_mesh(cpu));
}

void BreachPass::ensure_damage_frames() {
    if (damage_frames_tried_) return;
    damage_frames_tried_ = true;
    for (int i = 0; i < 4; ++i) {
        const std::string resolved = resolve_asset_path(kDamageFramePaths[i]);
        assets::Texture tex = load_damage_tga(resolved.c_str());
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

namespace {
// The proxy's GL state, in ONE place so render() and draw_instance() cannot
// diverge. Depth ON, cull FRONT (the recessed inner wall), and — the part that
// must not be forgotten by either caller — the stencil test that keeps the
// proxy out of open space.
//
// `discard` writes no depth, so a hole in the hull and empty space look
// identical from here, and BC's fill mask reaches up to ~3 cells past the hull
// (39-55% of mask volume lies outside the hull mesh, measured). Stencil 1 is
// stamped by FrameSubmitter::submit_carve_stencil and means "hull was actually
// cut away at this pixel". Callers MUST have stamped it, or nothing draws.
void begin_scoop_state() {
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glDisable(GL_BLEND);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_FRONT);
    glEnable(GL_STENCIL_TEST);
    glStencilFunc(GL_EQUAL, 1, 0xFF);
    glStencilMask(0x00);            // test only; never write
}

void end_scoop_state() {
    glDisable(GL_STENCIL_TEST);
    // Back to the GL default. glClear(GL_STENCIL_BUFFER_BIT) is MASKED by
    // glStencilMask, so leaving it closed silently turns the next stencil clear
    // into a no-op and lets marks accumulate across frames.
    glStencilMask(0xFF);
    glCullFace(GL_BACK);
}
}  // namespace

void BreachPass::draw_box_proxy(const InstanceFieldCache::Entry& field,
                                unsigned int fill_tex,
                                const glm::vec3& fill_origin,
                                const glm::vec3& fill_cell,
                                const glm::ivec3& fill_dims,
                                const glm::mat4& world_xf,
                                const scenegraph::Camera& camera,
                                Pipeline& pipeline,
                                float breach_age,
                                const glm::vec3& breach_center,
                                float breach_radius,
                                unsigned int damage_tex) {
    // Camera world position: inverse of view matrix column 3, computed once
    // CPU-side per draw (not per fragment). Matches how the opaque pass derives
    // u_camera_pos_ws in submit_opaque / submit_opaque_in_pass.
    const glm::mat4 view_inv = glm::inverse(camera.view_matrix());
    const glm::vec3 cam_pos_ws = glm::vec3(view_inv[3]);

    // Camera position in THIS instance's body frame — the ray origin every
    // fragment marches from (breach.frag's u_camera_pos_body). One matrix
    // inverse per draw, not per fragment.
    const glm::mat4 world_inv = glm::inverse(world_xf);
    const glm::vec3 cam_pos_body =
        glm::vec3(world_inv * glm::vec4(cam_pos_ws, 1.0f));

    auto& shader = pipeline.breach_shader();
    shader.use();
    shader.set_mat4("u_model",           world_xf);
    shader.set_mat4("u_view",            camera.view_matrix());
    shader.set_mat4("u_proj",            camera.proj_matrix());
    shader.set_vec3("u_camera_pos_ws",   cam_pos_ws);
    shader.set_vec3("u_camera_pos_body", cam_pos_body);

    // Fill mask (original uncarved fill).
    shader.set_int("u_fill",    0);
    shader.set_vec3("u_fill_origin", fill_origin);
    shader.set_vec3("u_fill_cell",   fill_cell);
    shader.set_ivec3("u_fill_dims",  fill_dims);
    shader.set_float("u_fill_iso",
                     static_cast<float>(CarveFieldCache::kIsovalue) / 255.0f);
    // Must equal opaque.frag's u_carve_fill_iso — same threshold, same shape.
    shader.set_float("u_fill_backing",
                     static_cast<float>(CarveFieldCache::kBackingIsovalue) / 255.0f);

    // Triplanar Damage.tga on unit 1.
    shader.set_int("u_damage_tex", 1);
    shader.set_float("u_tex_scale", kTexScale);

    // Molten-rim emissive: age of the nearest active breach event.
    // breach_age >= kRimLife → heat = 0 → no emissive (cold hole).
    // breach_center/breach_radius: that SAME event's own position, so
    // breach.frag can gate the emissive by DISTANCE from it too -- see
    // breach_pass.h's draw_instance doc and breach.frag's own comment at
    // its u_breach_center declaration for why age alone (a single scalar
    // for the whole instance) is not enough once there is more than one
    // hole on a hull.
    shader.set_float("u_breach_age",    breach_age);
    shader.set_float("u_rim_life",      scenegraph::kRimLife);
    shader.set_vec3("u_breach_center",  breach_center);
    shader.set_float("u_breach_radius", breach_radius);

    // Per-instance damage-field atlas — unit 2 (0=u_fill sampler3D,
    // 1=u_damage_tex). MUST be set on EVERY draw through this function: an
    // unset sampler uniform defaults to unit 0 in GLSL and would collide
    // with u_fill's bound sampler3D there (GL_INVALID_OPERATION on every
    // draw — measured elsewhere in this project, see this pass's header
    // comment and opaque.frag's own unit-6 binding in frame.cc).
    shader.set_int("u_hull_field", 2);
    shader.set_vec3("u_hull_field_origin", field.origin);
    shader.set_vec3("u_hull_field_cell",   field.cell);
    shader.set_vec3("u_hull_field_dims",   glm::vec3(field.dims));
    shader.set_vec2("u_hull_field_tiles",
                    glm::vec2(static_cast<float>(field.layout.tiles_x),
                              static_cast<float>(field.layout.tiles_y)));
    shader.set_vec2("u_hull_field_texel",
                    glm::vec2(1.0f / static_cast<float>(field.layout.width),
                              1.0f / static_cast<float>(field.layout.height)));

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_3D, fill_tex);

    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, damage_tex);

    glActiveTexture(GL_TEXTURE2);
    glBindTexture(GL_TEXTURE_2D, field.tex2d);

    glActiveTexture(GL_TEXTURE0);  // restore default active unit

    glBindVertexArray(box_mesh_->vao());
    glDrawElements(GL_TRIANGLES,
                   static_cast<GLsizei>(box_mesh_->index_count()),
                   GL_UNSIGNED_INT, nullptr);
    glBindVertexArray(0);
    ++draw_calls_;
}

void BreachPass::draw_instance(std::uintptr_t instance_key,
                               const voxel::VoxelVolume& fill,
                               const InstanceFieldCache::Entry& field,
                               const glm::mat4& world_xf,
                               const scenegraph::Camera& camera,
                               Pipeline& pipeline,
                               float breach_age,
                               const glm::vec3& breach_center,
                               float breach_radius) {
    if (field.tex2d == 0) return;   // no damage field: nothing to raymarch

    ensure_box();
    ensure_damage_frames();

    // Build + upload the fill 3D texture. In the test/standalone path there is
    // no shared CarveFieldCache, so we own the texture in fill_cache_ (member).
    // Repeated calls with the same instance_key reuse the cached texture.
    auto& fe = fill_cache_[instance_key];
    if (fe.tex3d == 0) {
        fe.tex3d = upload_fill_tex(fill);
    }
    if (fe.tex3d == 0) return;

    begin_scoop_state();
    draw_box_proxy(field, fe.tex3d, fill.origin, fill.cell, fill.dims,
                   world_xf, camera, pipeline, breach_age,
                   breach_center, breach_radius, damage_frames_[0]);
    end_scoop_state();

    // Restore texture bindings.
    glActiveTexture(GL_TEXTURE2);
    glBindTexture(GL_TEXTURE_2D, 0);
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
                        InstanceFieldCache* field_cache,
                        float now) {
    if (!dauntless_hull_damage::enabled()) return;
    if (field_cache == nullptr) return;   // feature unavailable: nothing to draw

    ensure_box();
    ensure_damage_frames();

    // Current animation frame, cycled by the game clock. All proxies drawn
    // this frame share it. frame_tex may be 0 (asset missing) → shader grey base.
    int frame = 0;
    if (now > 0.f) {
        frame = static_cast<int>(now * kDamageAnimFps) & 3;  // % 4, now >= 0
    }
    const unsigned int frame_tex = damage_frames_[frame];

    bool any_state_changed = false;
    auto ensure_state = [&]() {
        if (any_state_changed) return;
        any_state_changed = true;
        begin_scoop_state();
    };

    world.for_each_visible_in_pass(
        scenegraph::Pass::Space,
        [&](const scenegraph::Instance& inst) {
            // Checked FIRST, before any model/fill lookup: an instance that
            // was never carved (or whose hull has no baked field at all) has
            // no InstanceFieldCache entry — see that header's class comment
            // — so this is the exact "undamaged instance" gate, and the
            // cheapest possible one (one map lookup, no model/asset touch).
            const InstanceFieldCache::Entry* field = field_cache->get(inst.id);
            if (field == nullptr) return;
            if (field->tex2d == 0) return;   // defensive: entry exists but upload failed

            const assets::Model* model = lookup(inst.model_handle);
            if (!model) return;
            if (model->source.empty()) return;

            const CarveFieldCache::Entry* ce =
                carve_cache.get_for_source(model->source);
            if (ce == nullptr) return;   // no original-fill volume: can't gate the interior
            // ce->{origin,cell,dims} already describe the same fill volume
            // the shader's own backing check samples (CarveFieldCache::get_
            // for_source built ce->tex3d from it) — no separate
            // volume_for_source() lookup needed here.

            ensure_state();

            // Molten-rim age + position: with one draw per instance (not
            // per carve) there is no single carve slot to draw from any
            // more, so this passes the MOST RECENT (smallest age) active
            // breach event's own age AND centre/radius through to the
            // shader, which gates the emissive by distance from that centre
            // as well as by age (breach.frag's u_breach_center comment) —
            // an OLD, cooled hole elsewhere on the same hull must not
            // re-ignite just because a DIFFERENT, fresh hit landed anywhere
            // else on the instance.
            float breach_age = scenegraph::kRimLife + 1.f;  // default: cold
            glm::vec3 breach_center(0.0f);
            float breach_radius = 0.0f;
            for (const auto& ev : inst.breach_events.slots()) {
                if (!ev.active) continue;
                const float age = now - ev.birth_time;
                if (age < breach_age) {
                    breach_age    = age;
                    breach_center = ev.center_body;
                    breach_radius = ev.radius;
                }
            }

            draw_box_proxy(*field, ce->tex3d, ce->origin, ce->cell, ce->dims,
                           inst.world, camera, pipeline, breach_age,
                           breach_center, breach_radius, frame_tex);
        });

    if (any_state_changed) {
        end_scoop_state();
        glEnable(GL_DEPTH_TEST);
        glEnable(GL_CULL_FACE);
        glDepthMask(GL_TRUE);
        glDisable(GL_BLEND);
        // Restore texture bindings.
        glActiveTexture(GL_TEXTURE2);
        glBindTexture(GL_TEXTURE_2D, 0);
        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_2D, 0);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_3D, 0);
    }
}

}  // namespace renderer
