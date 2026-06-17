// native/src/renderer/breach_pass.cc
#include <renderer/breach_pass.h>

#include <renderer/pipeline.h>
#include <scenegraph/camera.h>
#include <scenegraph/hull_carve.h>
#include <scenegraph/instance.h>
#include <scenegraph/world.h>
#include <assets/model.h>

#include <voxel/voxelize.h>  // select_breach_voxels

#include <glad/glad.h>
#include <glm/glm.hpp>

#include <cstdint>
#include <vector>

// Toggle for the hull-breach renderer (carve emission + clip + breach splat).
// Defined in frame.cc (librenderer); forward-declared here so the pass can gate
// itself without a circular dependency. When off, render() does nothing.
namespace dauntless_hull_damage {
    bool enabled();
}

namespace renderer {

namespace {

// Unit cube centred at the origin, corners in [-0.5, 0.5]. 8 verts, 36 indices
// (12 triangles). Winding is CW for front faces to match the pipeline's
// glFrontFace(GL_CW); but the pass disables culling anyway (interior voxels are
// viewed from arbitrary angles through holes), so winding is cosmetic here.
constexpr float kCubeVerts[] = {
    -0.5f, -0.5f, -0.5f,
     0.5f, -0.5f, -0.5f,
     0.5f,  0.5f, -0.5f,
    -0.5f,  0.5f, -0.5f,
    -0.5f, -0.5f,  0.5f,
     0.5f, -0.5f,  0.5f,
     0.5f,  0.5f,  0.5f,
    -0.5f,  0.5f,  0.5f,
};

constexpr std::uint32_t kCubeIndices[] = {
    0, 1, 2, 0, 2, 3,   // -Z
    4, 6, 5, 4, 7, 6,   // +Z
    0, 4, 5, 0, 5, 1,   // -Y
    3, 2, 6, 3, 6, 7,   // +Y
    0, 3, 7, 0, 7, 4,   // -X
    1, 5, 6, 1, 6, 2,   // +X
};

}  // namespace

BreachPass::BreachPass() = default;

BreachPass::~BreachPass() {
    if (instance_vbo_) glDeleteBuffers(1, &instance_vbo_);
    if (cube_ebo_)     glDeleteBuffers(1, &cube_ebo_);
    if (cube_vbo_)     glDeleteBuffers(1, &cube_vbo_);
    if (cube_vao_)     glDeleteVertexArrays(1, &cube_vao_);
}

void BreachPass::ensure_cube_mesh() {
    if (cube_vao_ != 0) return;
    glGenVertexArrays(1, &cube_vao_);
    glBindVertexArray(cube_vao_);

    // Static unit-cube geometry: location 0 = corner position.
    glGenBuffers(1, &cube_vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, cube_vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(kCubeVerts), kCubeVerts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float),
                          reinterpret_cast<void*>(0));

    glGenBuffers(1, &cube_ebo_);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, cube_ebo_);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, sizeof(kCubeIndices), kCubeIndices,
                 GL_STATIC_DRAW);
    index_count_ = static_cast<int>(sizeof(kCubeIndices) / sizeof(kCubeIndices[0]));

    // Per-instance attribute: location 1 = vec4(center.xyz, seed), one per cube.
    // Filled per draw via glBufferData (orphaned each time).
    glGenBuffers(1, &instance_vbo_);
    glBindBuffer(GL_ARRAY_BUFFER, instance_vbo_);
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 4, GL_FLOAT, GL_FALSE, sizeof(glm::vec4),
                          reinterpret_cast<void*>(0));
    glVertexAttribDivisor(1, 1);  // advance once per instance

    glBindVertexArray(0);
}

void BreachPass::draw_instance(const voxel::VoxelVolume& volume,
                               const scenegraph::HullCarveField& carve,
                               const glm::mat4& world_xf,
                               const scenegraph::Camera& camera,
                               Pipeline& pipeline) {
    ensure_cube_mesh();

    // Accumulate every solid interior voxel inside every active carve sphere.
    scratch_.clear();
    for (const auto& s : carve.slots()) {
        if (!s.active) continue;
        auto sel = voxel::select_breach_voxels(volume, s.center_body, s.radius);
        scratch_.insert(scratch_.end(), sel.begin(), sel.end());
    }
    if (scratch_.empty()) return;

    auto& shader = pipeline.breach_shader();
    shader.use();
    shader.set_mat4("u_model", world_xf);
    shader.set_mat4("u_view",  camera.view_matrix());
    shader.set_mat4("u_proj",  camera.proj_matrix());
    shader.set_vec3("u_cell_half", 0.5f * volume.cell);

    glBindVertexArray(cube_vao_);
    glBindBuffer(GL_ARRAY_BUFFER, instance_vbo_);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(scratch_.size() * sizeof(glm::vec4)),
                 scratch_.data(), GL_DYNAMIC_DRAW);

    glDrawElementsInstanced(GL_TRIANGLES, index_count_, GL_UNSIGNED_INT,
                            nullptr, static_cast<GLsizei>(scratch_.size()));
    glBindVertexArray(0);
}

void BreachPass::render(const scenegraph::World& world,
                        const scenegraph::Camera& camera,
                        Pipeline& pipeline,
                        const ModelLookup& lookup) {
    if (!dauntless_hull_damage::enabled()) return;

    // Depth-test ON, depth-write ON, no blend, no cull. Drawn after the opaque
    // hull pass: cubes behind intact hull depth-fail (hidden); cubes behind a
    // hole (no depth written there) pass (visible through the breach).
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
            const voxel::VoxelVolume& volume =
                source_cache_.get_for_hull(model->source);
            if (volume.occ.empty()) return;
            ensure_state();
            draw_instance(volume, inst.carve, inst.world, camera, pipeline);
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
