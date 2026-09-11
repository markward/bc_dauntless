// native/src/voxel/src/hull_connectivity.cc
#include <voxel/hull_connectivity.h>

#include <cassert>
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
    if (baked.dims != damage.dims || baked.dist.size() != damage.dist.size()) {
        assert(false && "hull_connectivity: baked and damage lattices differ");
        return r;
    }

    const std::size_t n = baked.dist.size();
    // 0 = unlabelled. Main body gets a sentinel label that is never a
    // component label; components are numbered 1..N afterwards.
    constexpr std::uint32_t kMainBody = std::numeric_limits<std::uint32_t>::max();
    std::vector<std::uint32_t> labels(n, 0);
    std::vector<std::size_t> stack;
    stack.reserve(4096);

    // Seed: occupied cell nearest the body-frame origin.
    std::size_t seed = n;
    float best = std::numeric_limits<float>::max();
    const glm::ivec3 d = baked.dims;
    for (int z = 0; z < d.z; ++z)
    for (int y = 0; y < d.y; ++y)
    for (int x = 0; x < d.x; ++x) {
        const std::size_t i = baked.index(x, y, z);
        if (!occupied(baked, damage, i)) continue;
        const glm::vec3 c = baked.origin + (glm::vec3(x, y, z) + 0.5f) * baked.cell;
        const float dd = glm::dot(c, c);
        if (dd < best) { best = dd; seed = i; }
    }
    if (seed == n) return r;   // nothing occupied at all

    r.main_body_cells = flood(baked, damage, labels, stack, seed, kMainBody, nullptr);

    std::uint32_t next = 1;
    for (std::size_t i = 0; i < n; ++i) {
        if (labels[i] != 0) continue;
        if (!occupied(baked, damage, i)) continue;
        HullComponent comp;
        comp.label = next;
        flood(baked, damage, labels, stack, i, next, &comp);
        r.detached.push_back(std::move(comp));
        ++next;
    }
    return r;
}

}  // namespace voxel
