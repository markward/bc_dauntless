// native/src/renderer/head_center.cc
//
// Built -O2 in every configuration and -ffp-contract=off (CMakeLists.txt),
// plus the pragma below: the same IEEE operations in the same order as the
// -O0 binding this came from, never fused, so the head centre keeps its bits
// (perf-register SIG-183: at -O0 each call cost ~0.19 ms in glm call chains).
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "renderer/head_center.h"

#include <assets/model.h>

#include <cstring>

namespace renderer {

std::optional<glm::vec3> skinned_head_center(const assets::Model& model,
                                             const std::vector<glm::mat4>& palette) {
    const bool use_mesh_range = model.head_mesh_begin >= 0;

    int head_bi = -1;
    if (!use_mesh_range) {
        for (std::size_t i = 0; i < model.skeleton.bones.size(); ++i) {
            if (model.skeleton.bones[i].name == "Bip01 Head") {
                head_bi = static_cast<int>(i);
                break;
            }
        }
    }

    glm::vec3 head_lo(1e30f), head_hi(-1e30f);
    glm::vec3 body_lo(1e30f), body_hi(-1e30f);
    bool any_head = false, any_body = false;
    // With a mesh-range head only the head meshes are skinned; the whole body
    // is skinned only for the fallback centre when the head range has no
    // skinned vertex (perf-register SIG-136).
    auto scan = [&](std::size_t first_mesh) {
        for (std::size_t mesh_idx = first_mesh; mesh_idx < model.meshes.size();
             ++mesh_idx) {
            const auto& mesh = model.meshes[mesh_idx];
            const bool mesh_is_head =
                use_mesh_range &&
                static_cast<int>(mesh_idx) >= model.head_mesh_begin;
            const auto& cd = mesh.cpu_data();
            if (!cd) continue;
            for (const auto& v : cd->vertices) {
                const glm::vec4 p(v.position, 1.0f);
                glm::vec4 skinned(0.0f);
                float wsum = 0.0f;
                bool on_head = mesh_is_head;
                for (int k = 0; k < 4; ++k) {
                    const float w = static_cast<float>(v.bone_weights[k]) / 255.0f;
                    if (w <= 0.0f) continue;
                    const std::size_t bi =
                        static_cast<std::size_t>(v.bone_indices[k]);
                    if (bi >= palette.size()) continue;   // GPU-safe guard
                    skinned += w * (palette[bi] * p);
                    wsum += w;
                    if (!use_mesh_range && static_cast<int>(bi) == head_bi) {
                        on_head = true;
                    }
                }
                if (wsum <= 0.0f) continue;
                const glm::vec3 s(skinned);
                body_lo = glm::min(body_lo, s);
                body_hi = glm::max(body_hi, s);
                any_body = true;
                if (on_head) {
                    head_lo = glm::min(head_lo, s);
                    head_hi = glm::max(head_hi, s);
                    any_head = true;
                }
            }
        }
    };
    if (use_mesh_range)
        scan(static_cast<std::size_t>(model.head_mesh_begin));
    if (!any_head) {
        body_lo = glm::vec3(1e30f);
        body_hi = glm::vec3(-1e30f);
        any_body = false;
        scan(0);
    }
    if (any_head)      return 0.5f * (head_lo + head_hi);
    else if (any_body) return 0.5f * (body_lo + body_hi);
    return std::nullopt;
}

std::optional<glm::vec3> HeadCenterCache::get(scenegraph::InstanceId id,
                                              std::uint64_t model_handle,
                                              const assets::Model& model,
                                              const std::vector<glm::mat4>& palette) {
    const std::uint64_t key =
        (static_cast<std::uint64_t>(id.generation) << 32) | id.index;
    auto it = entries_.find(key);
    if (it != entries_.end()) {
        const Entry& e = it->second;
        // Bytes, not float ==: -0 and +0 compare equal but can round apart.
        if (e.model_handle == model_handle && e.model == &model &&
            e.palette.size() == palette.size() &&
            (palette.empty() || std::memcmp(e.palette.data(), palette.data(),
                        palette.size() * sizeof(glm::mat4)) == 0))
            return e.center;
    } else if (entries_.size() >= kMaxEntries) {
        entries_.clear();
    }
    ++computes_;
    Entry& e = entries_[key];
    e.model_handle = model_handle;
    e.model = &model;
    e.palette = palette;
    e.center = skinned_head_center(model, palette);
    return e.center;
}

}  // namespace renderer
