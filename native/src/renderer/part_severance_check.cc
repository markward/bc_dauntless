// native/src/renderer/part_severance_check.cc -- see part_severance_check.h.
#include "renderer/part_severance_check.h"

#include <algorithm>
#include <cstddef>

namespace renderer {

bool can_structure_sever(const scenegraph::Instance& inst) {
    return inst.node_overrides.empty();
}

std::vector<SeveredPart> find_severed_parts(const voxel::StructureSegmentation& seg,
                                            const plating::DamageList& dmg, float deck_break,
                                            std::uint32_t already_severed) {
    std::vector<SeveredPart> out;
    const int np = static_cast<int>(seg.parts.size());
    const glm::ivec3 d = seg.vol.dims;
    const std::size_t n = seg.vol.occ.size();
    if (np < 2 || d.x <= 0 || seg.label.size() != n) return out;

    // Surviving voxels: occupied, labelled, interior wear below deck_break.
    std::vector<std::uint8_t> alive(n, 0);
    std::vector<int> alive_count(static_cast<std::size_t>(np), 0);
    for (int z = 0; z < d.z; ++z)
        for (int y = 0; y < d.y; ++y)
            for (int x = 0; x < d.x; ++x) {
                const std::size_t i = seg.vol.index(x, y, z);
                const int lab = seg.label[i];
                if (!seg.vol.occ[i] || lab < 0 || lab >= np) continue;
                const glm::vec3 p =
                    seg.vol.origin + (glm::vec3(x, y, z) + 0.5f) * seg.vol.cell;
                float w = 0.f;
                for (int k = 0; k < dmg.count; ++k) {
                    const float R = dmg.a[k].w;
                    if (R <= 0.f) continue;
                    const glm::vec3 dv = p - glm::vec3(dmg.a[k]);
                    const float r2 = glm::dot(dv, dv) / (R * R);
                    if (r2 >= 1.f) continue;
                    const float f = 1.f - r2;
                    w += dmg.b[k].w * f * f;
                }
                if (w < deck_break) {
                    alive[i] = 1;
                    ++alive_count[static_cast<std::size_t>(lab)];
                }
            }

    const int main_part = static_cast<int>(
        std::max_element(alive_count.begin(), alive_count.end()) - alive_count.begin());
    if (alive_count[static_cast<std::size_t>(main_part)] == 0) return out;

    // Flood from every surviving main-body voxel across 6-connected survivors.
    std::vector<std::uint8_t> reached(n, 0);
    std::vector<int> reached_count(static_cast<std::size_t>(np), 0);
    std::vector<std::size_t> stack;
    for (std::size_t i = 0; i < n; ++i)
        if (alive[i] && seg.label[i] == main_part) {
            reached[i] = 1;
            stack.push_back(i);
        }
    const std::size_t sx = 1, sy = static_cast<std::size_t>(d.x),
                      sz = static_cast<std::size_t>(d.x) * static_cast<std::size_t>(d.y);
    while (!stack.empty()) {
        const std::size_t i = stack.back();
        stack.pop_back();
        ++reached_count[static_cast<std::size_t>(seg.label[i])];
        const int x = static_cast<int>(i % sy), y = static_cast<int>((i / sy) % d.y),
                  z = static_cast<int>(i / sz);
        auto visit = [&](bool ok, std::size_t j) {
            if (ok && alive[j] && !reached[j]) {
                reached[j] = 1;
                stack.push_back(j);
            }
        };
        visit(x > 0, i - sx);
        visit(x + 1 < d.x, i + sx);
        visit(y > 0, i - sy);
        visit(y + 1 < d.y, i + sy);
        visit(z > 0, i - sz);
        visit(z + 1 < d.z, i + sz);
    }

    for (int p = 0; p < np; ++p) {
        if (p == main_part || (p < 32 && (already_severed >> p) & 1u)) continue;
        const int alive_n = alive_count[static_cast<std::size_t>(p)];
        if (alive_n < kMinPartVoxels) continue;
        if (reached_count[static_cast<std::size_t>(p)] >= kReachedFraction * alive_n) continue;
        SeveredPart s;
        s.part = p;
        s.voxels = alive_n;
        glm::vec3 lo(1e30f), hi(-1e30f);
        glm::dvec3 sum(0.0);
        for (int z = 0; z < d.z; ++z)
            for (int y = 0; y < d.y; ++y)
                for (int x = 0; x < d.x; ++x) {
                    const std::size_t i = seg.vol.index(x, y, z);
                    if (!alive[i] || seg.label[i] != p) continue;
                    const glm::vec3 mn = seg.vol.origin + glm::vec3(x, y, z) * seg.vol.cell;
                    lo = glm::min(lo, mn);
                    hi = glm::max(hi, mn + seg.vol.cell);
                    sum += glm::dvec3(mn + 0.5f * seg.vol.cell);
                }
        s.min_body = lo;
        s.max_body = hi;
        s.centroid_body = glm::vec3(sum / static_cast<double>(alive_n));
        out.push_back(s);
    }
    return out;
}

}  // namespace renderer
