// native/src/renderer/part_severance_check.cc -- see part_severance_check.h.
#include "renderer/part_severance_check.h"

#include <algorithm>
#include <cstddef>

namespace renderer {

bool can_structure_sever(const scenegraph::Instance& inst) {
    return inst.node_overrides.empty();
}

std::vector<float> interior_wear_field(const voxel::VoxelVolume& vol,
                                       const plating::DamageList& dmg) {
    const glm::ivec3 d = vol.dims;
    std::vector<float> wear(vol.occ.size(), 0.f);
    for (int k = 0; k < dmg.count; ++k) {
        const float R = dmg.a[k].w;
        if (R <= 0.f) continue;
        const glm::vec3 c(dmg.a[k]);
        const glm::vec3 lo = (c - R - vol.origin) / vol.cell - 0.5f;
        const glm::vec3 hi = (c + R - vol.origin) / vol.cell - 0.5f;
        const glm::vec3 fmax = glm::vec3(d - 1);
        const glm::ivec3 i0 = glm::ivec3(glm::clamp(glm::floor(lo), glm::vec3(0.f), fmax));
        const glm::ivec3 i1 = glm::ivec3(glm::clamp(glm::ceil(hi), glm::vec3(0.f), fmax));
        if (hi.x < 0.f || hi.y < 0.f || hi.z < 0.f || lo.x > fmax.x || lo.y > fmax.y ||
            lo.z > fmax.z)
            continue;
        for (int z = i0.z; z <= i1.z; ++z)
            for (int y = i0.y; y <= i1.y; ++y)
                for (int x = i0.x; x <= i1.x; ++x) {
                    const glm::vec3 p = vol.origin + (glm::vec3(x, y, z) + 0.5f) * vol.cell;
                    const glm::vec3 dv = p - c;
                    const float r2 = glm::dot(dv, dv) / (R * R);
                    if (r2 >= 1.f) continue;
                    const float f = 1.f - r2;
                    wear[vol.index(x, y, z)] += dmg.b[k].w * f * f;
                }
    }
    return wear;
}

std::vector<SeveredPiece> find_severed_parts(const voxel::StructureSegmentation& seg,
                                            const plating::DamageList& dmg, float deck_break,
                                            std::uint32_t already_severed,
                                            std::uint32_t gone) {
    std::vector<SeveredPiece> out;
    const int np = static_cast<int>(seg.parts.size());
    const glm::ivec3 d = seg.vol.dims;
    const std::size_t n = seg.vol.occ.size();
    if (np < 2 || d.x <= 0 || seg.label.size() != n) return out;

    const std::vector<float> wear = interior_wear_field(seg.vol, dmg);

    // Surviving voxels: occupied, labelled, interior wear below deck_break,
    // and not in a part that has left the hull (`gone`): a lost part is
    // neither the main body nor a bridge for the flood.
    std::vector<std::uint8_t> alive(n, 0);
    std::vector<int> alive_count(static_cast<std::size_t>(np), 0);
    for (std::size_t i = 0; i < n; ++i) {
        const int lab = seg.label[i];
        if (!seg.vol.occ[i] || lab < 0 || lab >= np) continue;
        if (lab < 32 && ((gone >> lab) & 1u)) continue;
        if (wear[i] < deck_break) {
            alive[i] = 1;
            ++alive_count[static_cast<std::size_t>(lab)];
        }
    }

    const int mask_parts = std::min(np, 32);
    const int main_part = static_cast<int>(
        std::max_element(alive_count.begin(), alive_count.begin() + mask_parts) -
        alive_count.begin());
    if (alive_count[static_cast<std::size_t>(main_part)] == 0) return out;

    // Flood from every surviving main-body voxel across 6-connected survivors.
    std::vector<std::uint8_t> reached(n, 0);
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

    // Ruling 4: what is cut off leaves in ONE piece. Group the unreached
    // survivors into 6-connected components; a part belongs to a component
    // when the majority of its surviving voxels are unreached and lie in it.
    // A component of at least kMinPartVoxels holding at least one part
    // becomes one piece: those parts, and the component's voxels.
    const std::uint32_t skip = already_severed | gone;
    std::vector<std::uint8_t> seen(n, 0);
    std::vector<std::size_t> comp;
    std::vector<int> comp_count(static_cast<std::size_t>(np), 0);
    for (std::size_t seed = 0; seed < n; ++seed) {
        if (!alive[seed] || reached[seed] || seen[seed]) continue;
        comp.clear();
        seen[seed] = 1;
        stack.push_back(seed);
        while (!stack.empty()) {
            const std::size_t i = stack.back();
            stack.pop_back();
            comp.push_back(i);
            const int x = static_cast<int>(i % sy), y = static_cast<int>((i / sy) % d.y),
                      z = static_cast<int>(i / sz);
            auto visit = [&](bool ok, std::size_t j) {
                if (ok && alive[j] && !reached[j] && !seen[j]) {
                    seen[j] = 1;
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
        if (static_cast<int>(comp.size()) < kMinPartVoxels) continue;

        for (const std::size_t i : comp) ++comp_count[static_cast<std::size_t>(seg.label[i])];
        SeveredPiece piece;
        for (int p = 0; p < np; ++p) {
            const int in_comp = comp_count[static_cast<std::size_t>(p)];
            comp_count[static_cast<std::size_t>(p)] = 0;
            if (p == main_part || p >= 32 || ((skip >> p) & 1u)) continue;
            if (2 * in_comp > alive_count[static_cast<std::size_t>(p)]) piece.parts |= 1u << p;
        }
        if (piece.parts == 0) continue;

        glm::vec3 lo(1e30f), hi(-1e30f);
        glm::dvec3 sum(0.0);
        for (const std::size_t i : comp) {
            const int x = static_cast<int>(i % sy), y = static_cast<int>((i / sy) % d.y),
                      z = static_cast<int>(i / sz);
            const glm::vec3 mn = seg.vol.origin + glm::vec3(x, y, z) * seg.vol.cell;
            lo = glm::min(lo, mn);
            hi = glm::max(hi, mn + seg.vol.cell);
            sum += glm::dvec3(mn + 0.5f * seg.vol.cell);
        }
        piece.voxels = static_cast<int>(comp.size());
        piece.min_body = lo;
        piece.max_body = hi;
        piece.centroid_body = glm::vec3(sum / static_cast<double>(comp.size()));
        out.push_back(piece);
    }
    return out;
}

std::vector<SeveredSplit> split_severed_parts(scenegraph::World& world,
                                              scenegraph::InstanceId parent,
                                              const voxel::StructureSegmentation& seg,
                                              const plating::DamageList& dmg,
                                              float deck_break) {
    std::vector<SeveredSplit> out;
    const scenegraph::Instance* p = world.get(parent);
    // A chunk (shown_parts) is debris: it never severs further.
    if (p == nullptr || p->surface_is_rock || p->shown_parts != 0 || !can_structure_sever(*p))
        return out;
    // Parts the draw cannot hide are never reported, but they still join the
    // hull (an intact pylon past the cap keeps its nacelle on). Parts already
    // lost are gone: out of the main-body choice and the flood.
    const std::uint32_t unhideable = ~((1u << kMaxHideableParts) - 1u);
    const std::vector<SeveredPiece> pieces =
        find_severed_parts(seg, dmg, deck_break, unhideable, p->severed_parts);
    if (pieces.empty()) return out;
    int total = 0;
    for (const std::int16_t lab : seg.label) total += lab >= 0 ? 1 : 0;
    for (const SeveredPiece& sp : pieces) {
        const scenegraph::InstanceId child = world.create_instance(p->model_handle);
        // create_instance may grow the store: re-fetch the parent.
        scenegraph::Instance* pi = world.get(parent);
        scenegraph::Instance* ci = world.get(child);
        if (pi == nullptr || ci == nullptr) continue;
        // All three pose fields: `world` alone would be rebuilt from the
        // child's default pose by the next resolve_render_space.
        ci->world = pi->world;
        ci->world_linear = pi->world_linear;
        ci->world_translation_d = pi->world_translation_d;
        ci->visible = pi->visible;
        ci->pass = pi->pass;
        ci->comm_set_id = pi->comm_set_id;
        ci->rim_eligible = pi->rim_eligible;
        ci->rim_strength = pi->rim_strength;
        ci->emissive_scale = pi->emissive_scale;
        ci->surface_is_rock = pi->surface_is_rock;
        ci->hull_damage = pi->hull_damage;
        ci->shown_parts = sp.parts;
        pi->severed_parts |= sp.parts;
        out.push_back(SeveredSplit{sp, child, total});
    }
    return out;
}

}  // namespace renderer
