// native/src/nif/src/scene_camera.cc
#include <nif/scene_camera.h>

#include <nif/block.h>

#include <array>
#include <unordered_map>
#include <vector>

namespace nif {
namespace {

// 3x3 row-major multiply: c = a * b.
std::array<float, 9> mat_mul(const std::array<float, 9>& a,
                             const std::array<float, 9>& b) {
    std::array<float, 9> c{};
    for (int r = 0; r < 3; ++r)
        for (int col = 0; col < 3; ++col)
            c[r * 3 + col] = a[r * 3 + 0] * b[0 * 3 + col]
                           + a[r * 3 + 1] * b[1 * 3 + col]
                           + a[r * 3 + 2] * b[2 * 3 + col];
    return c;
}

// world = parent_world applied to local: rotation composes, translation is
// parent_pos + parent_rot * (scale * local_translation).
struct Xform {
    std::array<float, 9> rot{1, 0, 0, 0, 1, 0, 0, 0, 1};
    std::array<float, 3> pos{0, 0, 0};
    float scale = 1.0f;
};

Xform local_of(const AvObjectBase& av) {
    Xform x;
    x.rot = av.rotation.m;
    x.pos = {av.translation.x, av.translation.y, av.translation.z};
    x.scale = av.scale;
    return x;
}

Xform compose(const Xform& parent, const Xform& local) {
    Xform w;
    w.rot = mat_mul(parent.rot, local.rot);
    std::array<float, 3> sl = {local.pos[0] * parent.scale,
                               local.pos[1] * parent.scale,
                               local.pos[2] * parent.scale};
    // parent.rot * sl
    for (int r = 0; r < 3; ++r) {
        w.pos[r] = parent.pos[r]
                 + parent.rot[r * 3 + 0] * sl[0]
                 + parent.rot[r * 3 + 1] * sl[1]
                 + parent.rot[r * 3 + 2] * sl[2];
    }
    w.scale = parent.scale * local.scale;
    return w;
}

std::unordered_map<std::uint32_t, std::size_t> link_map(const File& f) {
    std::unordered_map<std::uint32_t, std::size_t> m;
    m.reserve(f.block_ids.size());
    for (std::size_t i = 0; i < f.block_ids.size(); ++i) m[f.block_ids[i]] = i;
    return m;
}

// DFS from `idx` accumulating world transform; when a NiCamera is reached,
// fill `out` and return true. NiCamera carries an AvObjectBase (c.av) so its
// own local transform composes on top of the chain.
bool walk(const File& f,
          const std::unordered_map<std::uint32_t, std::size_t>& links,
          std::size_t idx, const Xform& parent,
          std::vector<bool>& seen, SetCamera& out) {
    if (idx >= f.blocks.size() || seen[idx]) return false;
    seen[idx] = true;
    const Block& blk = f.blocks[idx];

    if (auto* cam = std::get_if<NiCamera>(&blk)) {
        Xform w = compose(parent, local_of(cam->av));
        out.rotation = w.rot;
        out.position = w.pos;
        out.frustum = {cam->frustum_left, cam->frustum_right,
                       cam->frustum_top, cam->frustum_bottom};
        out.near_distance = cam->frustum_near;
        out.far_distance = cam->frustum_far;
        return true;
    }
    if (auto* node = std::get_if<NiNode>(&blk)) {
        Xform w = compose(parent, local_of(node->av));
        for (auto link : node->child_links) {
            auto it = links.find(link);
            if (it != links.end() && walk(f, links, it->second, w, seen, out))
                return true;
        }
    }
    return false;
}

// Find the index of the root block via pointer comparison (BlockHandle::ptr
// points into f.blocks). Returns f.blocks.size() (an invalid index) when
// root is null or not found, so callers can detect the unresolved case.
std::size_t root_index(const File& f) {
    if (f.root.ptr) {
        for (std::size_t i = 0; i < f.blocks.size(); ++i) {
            if (&f.blocks[i] == f.root.ptr) return i;
        }
    }
    return f.blocks.size();  // sentinel: root did not resolve
}

}  // namespace

std::optional<SetCamera> find_first_camera(const File& f) {
    if (f.blocks.empty()) return std::nullopt;
    auto links = link_map(f);
    std::vector<bool> seen(f.blocks.size(), false);
    SetCamera out;
    // Only do the root-anchored walk when the root actually resolves.
    std::size_t root = root_index(f);
    if (root < f.blocks.size()) {
        if (walk(f, links, root, Xform{}, seen, out)) return out;
    }
    // Root walk may miss cameras not under the declared root (or the root
    // did not resolve). Sweep remaining unvisited blocks, sharing `seen`
    // so each block is visited at most once total.
    for (std::size_t i = 0; i < f.blocks.size(); ++i) {
        if (!seen[i]) {
            if (walk(f, links, i, Xform{}, seen, out)) return out;
        }
    }
    return std::nullopt;
}

}  // namespace nif
