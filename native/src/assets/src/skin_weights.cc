// native/src/assets/src/skin_weights.cc
#include "skin_weights.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

namespace assets::detail {

void fill_skin_weights(MeshCpu& cpu,
                       const nif::NiTriShapeSkinController& skin,
                       const std::vector<int>& skin_bone_to_skeleton) {
    struct Influence { int bone; float weight; };
    std::vector<std::vector<Influence>> per_vertex(cpu.vertices.size());

    for (std::size_t b = 0; b < skin.bone_weights.size(); ++b) {
        if (b >= skin_bone_to_skeleton.size()) continue;
        int skel_bone = skin_bone_to_skeleton[b];
        if (skel_bone < 0) continue;
        for (const auto& w : skin.bone_weights[b]) {
            if (w.vertex_index >= per_vertex.size()) continue;
            if (w.weight <= 0.0f) continue;
            per_vertex[w.vertex_index].push_back({skel_bone, w.weight});
        }
    }

    for (std::size_t v = 0; v < cpu.vertices.size(); ++v) {
        auto& infl = per_vertex[v];
        std::sort(infl.begin(), infl.end(),
                  [](const Influence& a, const Influence& b) { return a.weight > b.weight; });
        if (infl.size() > 4) infl.resize(4);

        std::array<int, 4>   idx{0, 0, 0, 0};
        std::array<float, 4> wt{0, 0, 0, 0};
        float total = 0.0f;
        for (std::size_t k = 0; k < infl.size(); ++k) {
            idx[k] = infl[k].bone;
            wt[k]  = infl[k].weight;
            total += infl[k].weight;
        }
        if (total <= 0.0f) {           // unweighted vertex -> bone 0 full
            wt[0] = 1.0f; total = 1.0f;
        }
        for (auto& w : wt) w /= total;  // renormalize so the four sum to 1

        auto to_u8 = [](float f) {
            int q = static_cast<int>(std::lround(f * 255.0f));
            return static_cast<std::uint8_t>(std::clamp(q, 0, 255));
        };
        cpu.vertices[v].bone_indices = glm::u8vec4(
            static_cast<std::uint8_t>(std::clamp(idx[0], 0, 255)),
            static_cast<std::uint8_t>(std::clamp(idx[1], 0, 255)),
            static_cast<std::uint8_t>(std::clamp(idx[2], 0, 255)),
            static_cast<std::uint8_t>(std::clamp(idx[3], 0, 255)));
        cpu.vertices[v].bone_weights = glm::u8vec4(
            to_u8(wt[0]), to_u8(wt[1]), to_u8(wt[2]), to_u8(wt[3]));
    }
}

}  // namespace assets::detail
