// native/src/voxel/src/hull_connectivity.cc
#include <voxel/hull_connectivity.h>

#include <limits>
#include <vector>

namespace voxel {

namespace {

inline bool occupied(const DistanceField& baked, const DistanceField& damage,
                     std::size_t i) {
    return baked.dist[i] <= 0 && damage.dist[i] <= 0;
}

// 6-connected flood from `seed`, writing `label` into `labels` for every
// occupied, unlabelled cell reached. Returns the count. Iterative -- a
// recursive fill would overflow the stack on a Warbird-sized lattice.
std::size_t flood(const DistanceField& baked, const DistanceField& damage,
                  std::vector<std::uint32_t>& labels, std::vector<std::size_t>& stack,
                  std::size_t seed, std::uint32_t label,
                  HullComponent* out) {
    const glm::ivec3 d = baked.dims;
    std::size_t count = 0;
    glm::vec3 sum(0.0f);
    glm::vec3 mn(std::numeric_limits<float>::max());
    glm::vec3 mx(std::numeric_limits<float>::lowest());

    stack.clear();
    stack.push_back(seed);
    labels[seed] = label;
    while (!stack.empty()) {
        const std::size_t i = stack.back();
        stack.pop_back();
        ++count;
        const int x = static_cast<int>(i % static_cast<std::size_t>(d.x));
        const int y = static_cast<int>((i / static_cast<std::size_t>(d.x)) % static_cast<std::size_t>(d.y));
        const int z = static_cast<int>(i / (static_cast<std::size_t>(d.x) * static_cast<std::size_t>(d.y)));
        if (out != nullptr) {
            const glm::vec3 c = baked.origin + (glm::vec3(x, y, z) + 0.5f) * baked.cell;
            sum += c;
            mn = glm::min(mn, c);
            mx = glm::max(mx, c);
            out->cell_list.emplace_back(x, y, z);
        }
        const int nx[6] = {x - 1, x + 1, x, x, x, x};
        const int ny[6] = {y, y, y - 1, y + 1, y, y};
        const int nz[6] = {z, z, z, z, z - 1, z + 1};
        for (int k = 0; k < 6; ++k) {
            if (nx[k] < 0 || ny[k] < 0 || nz[k] < 0 ||
                nx[k] >= d.x || ny[k] >= d.y || nz[k] >= d.z) continue;
            const std::size_t j = baked.index(nx[k], ny[k], nz[k]);
            if (labels[j] != 0) continue;
            if (!occupied(baked, damage, j)) continue;
            labels[j] = label;
            stack.push_back(j);
        }
    }
    if (out != nullptr && count > 0) {
        out->cells = count;
        out->centroid_body = sum / static_cast<float>(count);
        out->bounds_min_body = mn;
        out->bounds_max_body = mx;
    }
    return count;
}

}  // namespace

ConnectivityResult hull_connectivity(const DistanceField& baked,
                                     const DistanceField& damage) {
    ConnectivityResult r;
    if (baked.empty() || damage.empty()) return r;
    // The instance field copies the baked lattice by construction
    // (renderer/instance_field_cache.cc), so any difference here is a
    // caller bug, not rounding -- exact equality is correct. Return
    // gracefully rather than reading out of bounds; do NOT assert, since
    // an assert compiles away under NDEBUG and this contract must hold in
    // every build, not just Debug.
    if (baked.dims != damage.dims ||
        baked.origin != damage.origin ||
        baked.cell != damage.cell ||
        baked.dist.size() != damage.dist.size()) {
        return r;
    }

    const std::size_t n = baked.dist.size();
    // 0 = unlabelled; components are numbered 1..N in lattice scan order.
    // Every component is labelled first, with no privileged seed -- the
    // main body is chosen AFTERWARDS as the largest one. A seed at the cell
    // nearest the origin made a small central fragment the "main body" when
    // a cascade capsule hollowed the centre, and spawned the whole remaining
    // hull as a chunk of it.
    std::vector<std::uint32_t> labels(n, 0);
    std::vector<std::size_t> stack;
    stack.reserve(4096);

    std::vector<HullComponent> comps;
    std::uint32_t next = 1;
    for (std::size_t i = 0; i < n; ++i) {
        if (labels[i] != 0) continue;
        if (!occupied(baked, damage, i)) continue;
        HullComponent comp;
        comp.label = next;
        flood(baked, damage, labels, stack, i, next, &comp);
        comps.push_back(std::move(comp));
        ++next;
    }
    if (comps.empty()) return r;   // nothing occupied at all

    // Largest wins; strict '>' keeps the lowest label on a tie, which is
    // deterministic (scan order) and what the dumbbell test pins.
    std::size_t main = 0;
    for (std::size_t k = 1; k < comps.size(); ++k) {
        if (comps[k].cells > comps[main].cells) main = k;
    }
    r.main_body_cells = comps[main].cells;
    r.main_body_label = comps[main].label;
    r.detached.reserve(comps.size() - 1);
    for (std::size_t k = 0; k < comps.size(); ++k) {
        if (k == main) continue;
        r.detached.push_back(std::move(comps[k]));
    }
    return r;
}

}  // namespace voxel
