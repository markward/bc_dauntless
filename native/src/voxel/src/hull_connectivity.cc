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

inline bool same_lattice(const DistanceField& a, const DistanceField& b) {
    return a.dims == b.dims && a.origin == b.origin && a.cell == b.cell &&
           a.dist.size() == b.dist.size();
}

// 6-connected flood from `seed`, writing `label` into `labels` for every
// occupied, unlabelled cell reached. Returns the count and, through `out`,
// the component's centroid and bounds -- but NOT its cell list: that is
// collected afterwards, for detached components only, by a single scan
// over `labels` (see hull_connectivity). Iterative -- a recursive fill
// would overflow the stack on a Warbird-sized lattice.
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
    if (!same_lattice(baked, damage)) return r;

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
        comps[k].cell_list.reserve(comps[k].cells);
        r.detached.push_back(std::move(comps[k]));
    }
    if (r.detached.empty()) return r;   // the common case: no list to build

    // Cell lists for the detached components only. Labels are 1..N in
    // discovery order and every detached label is > 0, so a direct
    // label -> slot table avoids a search per cell.
    std::vector<std::size_t> slot_of(next, static_cast<std::size_t>(-1));
    for (std::size_t k = 0; k < r.detached.size(); ++k)
        slot_of[r.detached[k].label] = k;
    const glm::ivec3 d = baked.dims;
    for (std::size_t i = 0; i < n; ++i) {
        const std::uint32_t l = labels[i];
        if (l == 0 || l == r.main_body_label) continue;
        const int x = static_cast<int>(i % static_cast<std::size_t>(d.x));
        const int y = static_cast<int>((i / static_cast<std::size_t>(d.x)) % static_cast<std::size_t>(d.y));
        const int z = static_cast<int>(i / (static_cast<std::size_t>(d.x) * static_cast<std::size_t>(d.y)));
        r.detached[slot_of[l]].cell_list.emplace_back(x, y, z);
    }
    return r;
}

Severance hull_severance_local(const DistanceField& baked,
                               const DistanceField& damage,
                               const CellBox& box,
                               std::size_t visit_cap) {
    if (box.empty() || baked.empty() || damage.empty()) return Severance::kUnknown;
    if (!same_lattice(baked, damage)) return Severance::kUnknown;
    const glm::ivec3 d = baked.dims;
    if (box.lo.x < 0 || box.lo.y < 0 || box.lo.z < 0 ||
        box.hi.x >= d.x || box.hi.y >= d.y || box.hi.z >= d.z) {
        return Severance::kUnknown;
    }

    // The box grown by one cell, clamped: the shell of material around the
    // carve, plus whatever survived inside it.
    CellBox e{glm::max(box.lo - 1, glm::ivec3(0)),
              glm::min(box.hi + 1, d - 1)};
    if (visit_cap == 0) visit_cap = kSeveranceVisitFactor * e.volume();

    // Two bitmaps over the lattice -- targets and visited -- rather than
    // hash sets: one bit per cell is 8 KB on a Galaxy and 210 KB on the
    // largest station, cleared in microseconds, and every membership test
    // is a shift and a mask. (A hash-set version cost 190 ms per check at
    // -O0 on a Galaxy: worse than the full BFS it was meant to avoid.)
    const std::size_t n = baked.dist.size();
    std::vector<std::uint64_t> target_bits((n + 63) / 64, 0);
    std::vector<std::uint64_t> visited_bits((n + 63) / 64, 0);
    auto test = [](const std::vector<std::uint64_t>& b, std::size_t i) {
        return (b[i >> 6] >> (i & 63)) & 1u;
    };
    auto set = [](std::vector<std::uint64_t>& b, std::size_t i) {
        b[i >> 6] |= (std::uint64_t{1} << (i & 63));
    };

    std::size_t remaining = 0;
    std::size_t seed = 0;
    for (int z = e.lo.z; z <= e.hi.z; ++z)
    for (int y = e.lo.y; y <= e.hi.y; ++y)
    for (int x = e.lo.x; x <= e.hi.x; ++x) {
        const std::size_t i = baked.index(x, y, z);
        if (!occupied(baked, damage, i)) continue;
        if (remaining == 0) seed = i;
        set(target_bits, i);
        ++remaining;
    }
    if (remaining == 0) return Severance::kConnected;   // nothing here to sever

    // Breadth-first flood from one target over occupied cells anywhere in
    // the lattice until every target is reached or the budget runs out.
    // Breadth-first, not depth-first, on purpose: the targets sit within a
    // few cells of the seed, and a DFS would happily run down a nacelle
    // before finishing the shell.
    std::vector<std::size_t> queue;
    queue.reserve(visit_cap + 1);
    queue.push_back(seed);
    set(visited_bits, seed);
    std::size_t visited = 1;
    for (std::size_t head = 0; head < queue.size(); ++head) {
        const std::size_t i = queue[head];
        if (test(target_bits, i) && --remaining == 0) return Severance::kConnected;
        if (visited > visit_cap) return Severance::kUnknown;
        const int x = static_cast<int>(i % static_cast<std::size_t>(d.x));
        const int y = static_cast<int>((i / static_cast<std::size_t>(d.x)) % static_cast<std::size_t>(d.y));
        const int z = static_cast<int>(i / (static_cast<std::size_t>(d.x) * static_cast<std::size_t>(d.y)));
        const int nx[6] = {x - 1, x + 1, x, x, x, x};
        const int ny[6] = {y, y, y - 1, y + 1, y, y};
        const int nz[6] = {z, z, z, z, z - 1, z + 1};
        for (int k = 0; k < 6; ++k) {
            if (nx[k] < 0 || ny[k] < 0 || nz[k] < 0 ||
                nx[k] >= d.x || ny[k] >= d.y || nz[k] >= d.z) continue;
            const std::size_t j = baked.index(nx[k], ny[k], nz[k]);
            if (test(visited_bits, j)) continue;
            if (!occupied(baked, damage, j)) continue;
            set(visited_bits, j);
            ++visited;
            queue.push_back(j);
        }
    }
    return Severance::kUnknown;   // the flood died out with targets unreached
}

}  // namespace voxel
