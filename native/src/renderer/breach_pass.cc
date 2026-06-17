// native/src/renderer/breach_pass.cc
#include <renderer/breach_pass.h>

#include <renderer/pipeline.h>
#include <scenegraph/camera.h>
#include <scenegraph/hull_carve.h>
#include <scenegraph/instance.h>
#include <scenegraph/world.h>
#include <assets/model.h>
#include <assets/texture.h>

#include <voxel/dual_contour.h>
#include <voxel/voxelize.h>  // carve_sphere

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <vector>

// Toggle for the hull-breach renderer (carve emission + clip + breach surface).
// Defined in frame.cc (librenderer); forward-declared here so the pass can gate
// itself without a circular dependency. When off, render() does nothing.
namespace dauntless_hull_damage {
    bool enabled();
}

namespace renderer {

namespace {

constexpr const char* kDamageTgaPath =
    "game/data/Textures/Effects/Damage.tga";

// Inflate each DC-mesh vertex along its outward normal by this many cell
// widths before applying u_model. The dual-contour isosurface sits ~1 cell
// inset from the real hull surface (lattice nodes live at cell centres, one
// step inside the AABB), so without inflation the cavity rim is recessed
// behind the clip hole and leaves a see-through gap near the breach edge.
// 1.0 is the baseline; dial up/down visually if a thicker or thinner rim
// is needed.
static constexpr float kInflateCells = 1.0f;

unsigned int load_damage_tga() {
    std::ifstream in(kDamageTgaPath, std::ios::binary);
    if (!in) {
        std::fprintf(stderr, "[breach] failed to open '%s'\n", kDamageTgaPath);
        return 0;
    }
    std::vector<std::uint8_t> bytes((std::istreambuf_iterator<char>(in)),
                                    std::istreambuf_iterator<char>());
    try {
        assets::Image img = assets::decode_tga(bytes);
        assets::Texture tex = assets::upload_image(img, /*generate_mipmaps=*/true);
        // assets::Texture has no id-release; keep the owner alive in a
        // process-lifetime static so the GL id we hand back stays valid (this
        // lazy fallback path runs at most once — GL tests / no host wiring).
        static std::vector<assets::Texture> s_owned;
        unsigned int id = tex.id();
        s_owned.emplace_back(std::move(tex));
        return id;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[breach] decode/upload '%s' failed: %s\n",
                     kDamageTgaPath, e.what());
        return 0;
    }
}

}  // namespace

BreachPass::BreachPass() = default;

BreachPass::~BreachPass() {
    if (ebo_) glDeleteBuffers(1, &ebo_);
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void BreachPass::ensure_mesh_buffers() {
    if (vao_ != 0) return;
    glGenVertexArrays(1, &vao_);
    glBindVertexArray(vao_);

    glGenBuffers(1, &vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    // Interleaved: location 0 = body-frame position, location 1 = body normal.
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 6 * sizeof(float),
                          reinterpret_cast<void*>(0));
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 6 * sizeof(float),
                          reinterpret_cast<void*>(3 * sizeof(float)));

    glGenBuffers(1, &ebo_);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo_);

    glBindVertexArray(0);
}

void BreachPass::ensure_damage_texture() {
    if (damage_tex_ != 0 || damage_tex_tried_) return;
    damage_tex_tried_ = true;
    damage_tex_ = load_damage_tga();
}

voxel::VoxelVolume BreachPass::build_carved_fill(
        const voxel::VoxelVolume& fill,
        const scenegraph::HullCarveField& carve) {
    voxel::VoxelVolume carved = fill;  // copy the intact source fill
    for (const auto& s : carve.slots()) {
        if (!s.active) continue;
        voxel::carve_sphere(carved, s.center_body, s.radius);
    }
    return carved;
}

std::vector<std::uint32_t> BreachPass::filter_to_carves(
        const std::vector<glm::vec3>& positions,
        const std::vector<std::uint32_t>& indices,
        const scenegraph::HullCarveField& carve,
        float margin) {
    std::vector<std::uint32_t> kept;
    kept.reserve(indices.size());

    const std::size_t tri_count = indices.size() / 3;
    for (std::size_t t = 0; t < tri_count; ++t) {
        const std::uint32_t i0 = indices[t * 3 + 0];
        const std::uint32_t i1 = indices[t * 3 + 1];
        const std::uint32_t i2 = indices[t * 3 + 2];

        // Guard against degenerate index buffers.
        if (i0 >= positions.size() ||
            i1 >= positions.size() ||
            i2 >= positions.size()) continue;

        const glm::vec3 centroid =
            (positions[i0] + positions[i1] + positions[i2]) * (1.0f / 3.0f);

        bool near_carve = false;
        for (const auto& s : carve.slots()) {
            if (!s.active) continue;
            const float threshold = s.radius + margin;
            if (glm::length(centroid - s.center_body) <= threshold) {
                near_carve = true;
                break;
            }
        }
        if (!near_carve) continue;

        kept.push_back(i0);
        kept.push_back(i1);
        kept.push_back(i2);
    }
    return kept;
}

std::uint64_t BreachPass::carve_version(
        const scenegraph::HullCarveField& carve) const {
    // Max active carve seq strictly increases on every add/grow (hull_carve.cc),
    // so it is a monotone version key; 0 means no active carves.
    std::uint64_t v = 0;
    for (const auto& s : carve.slots()) {
        if (s.active && s.seq > v) v = s.seq;
    }
    return v;
}

const BreachPass::CachedMesh& BreachPass::mesh_for(
        std::uintptr_t instance_key,
        const voxel::VoxelVolume& fill,
        const std::vector<glm::vec4>& palette,
        const scenegraph::HullCarveField& carve) {
    CachedMesh& slot = mesh_cache_[instance_key];
    const std::uint64_t version = carve_version(carve);
    if (slot.carve_version == version && version != 0) {
        return slot;  // unchanged carves -> reuse the extracted mesh
    }

    // Re-extract: carve the fill, dual-contour it, then restrict to
    // triangles whose centroids fall within the active carve spheres.
    // The DC isosurface of the (mostly-uncarved) fill coincides with the hull
    // shell everywhere outside the craters; drawing the full mesh causes a
    // whole-hull "frosting" overlay.  Keeping only crater-region triangles
    // restricts the rendered surface to the actual breach cavity walls.
    voxel::VoxelVolume carved = build_carved_fill(fill, carve);
    voxel::Mesh m = voxel::dual_contour(carved, kIsovalue, palette);

    // Margin = one cell diagonal so that cavity-wall triangles just outside a
    // carve sphere radius are not clipped.
    const float margin = glm::length(fill.cell);
    m.indices = filter_to_carves(m.positions, m.indices, carve, margin);

    slot.carve_version = version;
    slot.indices = std::move(m.indices);
    slot.index_count = static_cast<int>(slot.indices.size());
    slot.interleaved.clear();
    slot.interleaved.reserve(m.positions.size() * 6);
    for (std::size_t i = 0; i < m.positions.size(); ++i) {
        const glm::vec3& p = m.positions[i];
        const glm::vec3  n = (i < m.normals.size()) ? m.normals[i]
                                                     : glm::vec3(0, 1, 0);
        slot.interleaved.push_back(p.x);
        slot.interleaved.push_back(p.y);
        slot.interleaved.push_back(p.z);
        slot.interleaved.push_back(n.x);
        slot.interleaved.push_back(n.y);
        slot.interleaved.push_back(n.z);
    }
    return slot;
}

void BreachPass::draw_instance(std::uintptr_t instance_key,
                               const voxel::VoxelVolume& fill,
                               const std::vector<glm::vec4>& palette,
                               const scenegraph::HullCarveField& carve,
                               const glm::mat4& world_xf,
                               const scenegraph::Camera& camera,
                               Pipeline& pipeline) {
    if (carve.count() == 0) return;

    const CachedMesh& mesh = mesh_for(instance_key, fill, palette, carve);
    if (mesh.index_count == 0) return;

    ensure_mesh_buffers();
    ensure_damage_texture();

    auto& shader = pipeline.breach_shader();
    shader.use();
    shader.set_mat4("u_model", world_xf);
    shader.set_mat4("u_view",  camera.view_matrix());
    shader.set_mat4("u_proj",  camera.proj_matrix());
    shader.set_int("u_damage_tex", 0);
    // Triplanar projection scale: 1 sample period over a few cells so the
    // texture reads as panel detail, not a single stretched splat.
    const glm::vec3 c = fill.cell;
    const float cell_avg = (c.x + c.y + c.z) / 3.0f;
    shader.set_float("u_tex_scale", cell_avg > 0.0f ? 1.0f / (cell_avg * 4.0f)
                                                     : 0.25f);

    // Inflate the DC cavity outward by ~1 cell so its rim reaches the hull
    // surface / clip-hole edge (plugs the ~1-cell see-through gap at the rim).
    // The source fill has cubic cells, so any component gives the same size;
    // fall back to cell_avg if a degenerate zero cell is encountered.
    const float cell_size = (c.x > 0.0f) ? c.x : cell_avg;
    shader.set_float("u_inflate", cell_size * kInflateCells);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, damage_tex_);

    glBindVertexArray(vao_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(mesh.interleaved.size() * sizeof(float)),
                 mesh.interleaved.data(), GL_DYNAMIC_DRAW);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo_);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(mesh.indices.size() * sizeof(std::uint32_t)),
                 mesh.indices.data(), GL_DYNAMIC_DRAW);

    glDrawElements(GL_TRIANGLES, mesh.index_count, GL_UNSIGNED_INT, nullptr);
    glBindVertexArray(0);
    glBindTexture(GL_TEXTURE_2D, 0);
}

void BreachPass::render(const scenegraph::World& world,
                        const scenegraph::Camera& camera,
                        Pipeline& pipeline,
                        const ModelLookup& lookup) {
    if (!dauntless_hull_damage::enabled()) return;

    // Depth-test ON, depth-write ON, no blend, CULL OFF (double-sided): the DC
    // mesh winds inward with outward normals, so we must not backface-cull.
    // Drawn after the opaque hull pass: surface behind intact hull depth-fails
    // (hidden); behind a hole (no depth written there) passes (visible).
    bool any_state_changed = false;
    auto ensure_state = [&]() {
        if (any_state_changed) return;
        any_state_changed = true;
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);
        glDisable(GL_BLEND);
        glDisable(GL_CULL_FACE);
    };

    world.for_each_visible_in_pass(
        scenegraph::Pass::Space,
        [&](const scenegraph::Instance& inst) {
            if (inst.carve.count() == 0) return;
            const assets::Model* model = lookup(inst.model_handle);
            if (!model) return;
            if (model->source.empty()) return;
            const voxel::VoxelVolume& fill =
                source_cache_.get_for_hull(model->source);
            if (fill.occ.empty()) return;
            const std::vector<glm::vec4>& palette =
                source_cache_.planes_for_hull(model->source);
            ensure_state();
            // Per-instance cache key: the instance's stable storage address.
            // (A slot recycled to a different ship just re-extracts once.)
            const std::uintptr_t key =
                reinterpret_cast<std::uintptr_t>(&inst);
            draw_instance(key, fill, palette, inst.carve, inst.world, camera,
                          pipeline);
        });

    // Restore default opaque-pass GL state only if we touched it. We re-assert
    // GL_DEPTH_TEST explicitly (not just leave it as ensure_state() set it) so
    // the post-opaque contract holds regardless of future frame reordering.
    if (any_state_changed) {
        glEnable(GL_DEPTH_TEST);
        glEnable(GL_CULL_FACE);
        glDepthMask(GL_TRUE);
        glDisable(GL_BLEND);
    }
}

}  // namespace renderer
