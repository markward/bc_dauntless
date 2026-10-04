// native/tests/renderer/rock_fade_merge.h
// Rock fade (2026-10-03, .superpowers/sdd/rock-fade/brief.md): NearField
// builds now split their impostors into a solid/dithered list
// (NearOutput::billboards) and a translucent list (billboards_fading)
// without changing a byte of any item.
// merge() reassembles the ONE list the builds emitted before the split --
// bins by ascending catalogue/atlas index, items nearest first by (distance,
// centre) -- so tests and digests recorded before the split still pin every
// item. `dist` must compute an item's eye distance exactly as the build did
// (it decides the order). Assumes no catalogue index is shared by the near
// band's two classes (true of every test catalogue).
#pragma once
#include <algorithm>
#include <functional>
#include <map>
#include <tuple>
#include <vector>
#include <renderer/far_field.h>

namespace rock_fade_merge {

using Dist = std::function<float(const glm::vec3& centre)>;

inline std::vector<renderer::far::ImpostorBin> merge(
    const std::vector<renderer::far::ImpostorBin>& solid,
    const std::vector<renderer::far::ImpostorBin>& fading, const Dist& dist) {
    std::map<int, std::vector<renderer::far::ImpostorGpu>> bins;
    for (const auto* list : {&solid, &fading})
        for (const auto& b : *list)
            bins[b.rock].insert(bins[b.rock].end(), b.items.begin(), b.items.end());
    std::vector<renderer::far::ImpostorBin> out;
    for (auto& [rock, items] : bins) {
        std::vector<std::pair<float, renderer::far::ImpostorGpu>> keyed;
        keyed.reserve(items.size());
        for (const auto& it : items) keyed.emplace_back(dist(glm::vec3(it.centre_half)), it);
        std::stable_sort(keyed.begin(), keyed.end(), [](const auto& a, const auto& b) {
            if (a.first != b.first) return a.first < b.first;
            const glm::vec4& p = a.second.centre_half;
            const glm::vec4& q = b.second.centre_half;
            return std::tie(p.x, p.y, p.z) < std::tie(q.x, q.y, q.z);
        });
        renderer::far::ImpostorBin bin{rock, {}};
        for (const auto& k : keyed) bin.items.push_back(k.second);
        out.push_back(std::move(bin));
    }
    return out;
}

}  // namespace rock_fade_merge
