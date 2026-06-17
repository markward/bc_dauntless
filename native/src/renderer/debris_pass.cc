// native/src/renderer/debris_pass.cc
#include <renderer/debris_pass.h>
#include <renderer/pipeline.h>
#include <renderer/carve_field_cache.h>
#include "cube_mesh.h"
#include "debris_chunks.h"

#include <scenegraph/breach_events.h>
#include <scenegraph/camera.h>
#include <scenegraph/world.h>
#include <assets/model.h>
#include <assets/mesh.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/type_ptr.hpp>

namespace dauntless_hull_damage { bool enabled(); }

namespace renderer {

DebrisPass::DebrisPass() = default;

void DebrisPass::ensure_cube() {
    if (cube_mesh_) return;
    cube_mesh_ = std::make_unique<assets::Mesh>(
        assets::upload_mesh(build_unit_cube()));
}

void DebrisPass::render(const scenegraph::World& world,
                        const scenegraph::Camera& camera,
                        Pipeline& pipeline,
                        const ModelLookup& lookup,
                        CarveFieldCache& carve_cache,
                        float now) {
    if (!dauntless_hull_damage::enabled()) return;
    ensure_cube();

    bool any = false;
    auto ensure_state = [&]() {
        if (any) return;
        any = true;
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_FALSE);   // alpha-blended: don't write depth
        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glDisable(GL_CULL_FACE);
    };

    auto& shader = pipeline.debris_shader();

    const glm::vec3 light_dir = glm::normalize(glm::vec3(0.3f, 1.f, 0.2f));

    world.for_each_visible_in_pass(
        scenegraph::Pass::Space,
        [&](const scenegraph::Instance& inst) {
            if (inst.breach_events.count() == 0) return;
            const assets::Model* model = lookup(inst.model_handle);
            if (!model || model->source.empty()) return;
            const CarveFieldCache::Entry* ce = carve_cache.get_for_source(model->source);
            if (!ce) return;
            const voxel::VoxelVolume& vol = ce->fill;
            if (vol.occ.empty()) return;

            for (const auto& ev : inst.breach_events.slots()) {
                if (!ev.active) continue;
                const float age = now - ev.birth_time;
                if (age >= scenegraph::kDebrisLife) continue;

                const auto origins = sample_chunk_origins(
                    vol, ev.center_body, ev.radius, ev.seed, kChunkCount);
                if (origins.empty()) continue;

                ensure_state();

                shader.use();
                shader.set_mat4("u_model", inst.world);
                shader.set_mat4("u_view",  camera.view_matrix());
                shader.set_mat4("u_proj",  camera.proj_matrix());
                shader.set_vec3("u_light_dir", light_dir);
                shader.set_float("u_cell_size", vol.cell.x); // assume isotropic

                glBindVertexArray(cube_mesh_->vao());

                for (int i = 0; i < static_cast<int>(origins.size()); ++i) {
                    const ChunkTransform ct =
                        chunk_transform(origins[static_cast<std::size_t>(i)],
                                        ev.center_body, age, ev.seed, i);
                    if (ct.alpha <= 0.f) continue;

                    // Per-chunk hash color: classic multicolor hull-interior look.
                    const std::uint64_t ch =
                        (ev.seed * 6364136223846793005ull) ^
                        (static_cast<std::uint64_t>(i) * 2654435761ull);
                    const float cr = 0.3f + 0.4f * static_cast<float>((ch >> 40) & 0xFFu) / 255.f;
                    const float cg = 0.2f + 0.3f * static_cast<float>((ch >> 24) & 0xFFu) / 255.f;
                    const float cb = 0.15f + 0.25f * static_cast<float>((ch >> 8) & 0xFFu) / 255.f;

                    shader.set_vec3("u_chunk_pos",   ct.pos_body);
                    shader.set_mat3("u_chunk_rot",   ct.rot);
                    shader.set_vec3("u_chunk_color", glm::vec3(cr, cg, cb));
                    shader.set_float("u_chunk_alpha", ct.alpha);

                    glDrawElements(GL_TRIANGLES,
                                   static_cast<GLsizei>(cube_mesh_->index_count()),
                                   GL_UNSIGNED_INT, nullptr);
                }
                glBindVertexArray(0);
            }
        });

    if (any) {
        glDepthMask(GL_TRUE);
        glDisable(GL_BLEND);
        glEnable(GL_CULL_FACE);
    }
}

} // namespace renderer
