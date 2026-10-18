// native/src/voxel/src/field_brush.cc
#include <voxel/field_brush.h>

#include <algorithm>
#include <cmath>
#include <cstring>

namespace voxel {

namespace {

// Both brushes compute g(p) = -d_brush(p) + offset at a cell centre and write
// q(max(d_old, g)), q = round(d / scale) clamped to +-127. Two facts make most
// of a big carve free without changing a single result:
//
//  * +127 is the ceiling of a monotonic max: a cell already there cannot
//    change, so it is skipped before g is evaluated (a whole row at a time
//    when the row is already full).
//  * d_brush is convex for both shapes (a norm of an affine map for the
//    oblate, distance-to-a-segment for the capsule), so g is concave and its
//    minimum over any box of cells is at one of that box's 8 corner cells.
//    The reach box is walked in kBlock^3 blocks; when every corner of a block
//    has g >= 127 * scale -- half a quantum above where rounding reaches 127,
//    far more than float error -- every cell in the block becomes +127, and
//    the block is a fill. Only blocks the brush's surface passes through pay
//    for g per cell.
//
// The returned box is the tight box of cells that CHANGED, so a carve that
// lands on fully carved material reports nothing, and the upload and the
// severance check skip it. Measured (perf-register P-4): a dead station's
// wreck took 35 GU carves whose reach box was its whole 13.4 M-cell lattice,
// 0.75 s each in Debug, repeated after every cell was already +127.
constexpr std::int8_t kFull = 127;
constexpr int kBlock = 8;

struct Bounds {
    int x0 = 0, y0 = 0, z0 = 0, x1 = -1, y1 = -1, z1 = -1;
    void add_row(int xa, int xb, int y, int z) {
        if (x1 < x0) { x0 = xa; x1 = xb; y0 = y1 = y; z0 = z1 = z; return; }
        x0 = std::min(x0, xa); x1 = std::max(x1, xb);
        y0 = std::min(y0, y);  y1 = std::max(y1, y);
        z0 = std::min(z0, z);  z1 = std::max(z1, z);
    }
    CellBox box() const {
        if (x1 < x0) return {};
        return CellBox{glm::ivec3(x0, y0, z0), glm::ivec3(x1, y1, z1)};
    }
};

template <class G>
CellBox apply_brush(DistanceField& f, glm::ivec3 c0, glm::ivec3 c1, G g) {
    auto centre = [&](int x, int y, int z) {
        return f.origin + (glm::vec3(x, y, z) + 0.5f) * f.cell;
    };
    const float full_at = 127.0f * f.scale;
    std::int8_t full_row[kBlock];
    std::memset(full_row, kFull, sizeof(full_row));
    Bounds changed;

    for (int bz = c0.z; bz <= c1.z; bz += kBlock)
    for (int by = c0.y; by <= c1.y; by += kBlock)
    for (int bx = c0.x; bx <= c1.x; bx += kBlock) {
        const glm::ivec3 b0(bx, by, bz);
        const glm::ivec3 b1 = glm::min(b0 + (kBlock - 1), c1);
        const int row = b1.x - b0.x + 1;
        const std::size_t row_bytes = static_cast<std::size_t>(row);

        bool fill = true;
        for (int k = 0; k < 8 && fill; ++k) {
            fill = g(centre((k & 1) ? b1.x : b0.x, (k & 2) ? b1.y : b0.y,
                            (k & 4) ? b1.z : b0.z)) >= full_at;
        }

        for (int z = b0.z; z <= b1.z; ++z)
        for (int y = b0.y; y <= b1.y; ++y) {
            std::int8_t* r = f.dist.data() + f.index(b0.x, y, z);
            if (std::memcmp(r, full_row, row_bytes) == 0) continue;
            int a = -1, b = -1;
            if (fill) {
                a = 0;
                while (r[a] == kFull) ++a;
                b = row - 1;
                while (r[b] == kFull) --b;
                std::memset(r + a, kFull, static_cast<std::size_t>(b - a + 1));
            } else {
                for (int i = 0; i < row; ++i) {
                    const std::int8_t old = r[i];
                    if (old == kFull) continue;
                    const float d_new = std::max(static_cast<float>(old) * f.scale,
                                                 g(centre(b0.x + i, y, z)));
                    float q = std::round(d_new / f.scale);
                    q = std::max(-127.0f, std::min(127.0f, q));
                    const auto q8 = static_cast<std::int8_t>(q);
                    if (q8 == old) continue;
                    r[i] = q8;
                    if (a < 0) a = i;
                    b = i;
                }
            }
            if (a >= 0) changed.add_row(b0.x + a, b0.x + b, y, z);
        }
    }
    return changed.box();
}

}  // namespace

CellBox field_carve_oblate(DistanceField& f,
                        const glm::vec3& center_body,
                        const glm::vec3& normal_body,
                        float radius) {
    if (f.empty()) return {};
    if (!(radius > 0.0f)) return {};
    if (!(f.scale > 0.0f)) return {};

    // Reject non-finite inputs. Infinity or NaN in center_body, normal_body, or
    // radius would lead to undefined behaviour in floor() and int casts below.
    if (!std::isfinite(center_body.x) || !std::isfinite(center_body.y) ||
        !std::isfinite(center_body.z) || !std::isfinite(radius) ||
        !std::isfinite(normal_body.x) || !std::isfinite(normal_body.y) ||
        !std::isfinite(normal_body.z)) {
        return {};
    }

    glm::vec3 n = normal_body;
    const float nl = glm::length(n);
    n = (nl > 1e-4f) ? n / nl : glm::vec3(0.0f, 0.0f, 1.0f);

    // Smallest cell axis: the field may be anisotropic, and every
    // representability floor below has to hold on the WORST axis.
    const float min_cell = std::min(f.cell.x, std::min(f.cell.y, f.cell.z));

    // Lateral half-extent covers the shader's OUTWARD rim perturbation, not
    // just the nominal radius -- see kCarveRimAmp.
    const float lat    = radius * (1.0f + kCarveRimAmp);
    const float depth  = std::max(kCarveDepthFactor * radius,
                                  kCarveDepthFloorCells * min_cell);
    const float offset = kCarveFieldOffsetCells * min_cell;

    // Only cells within the brush's AABB can change. The oblate is oriented
    // along `n`, which is arbitrary in body frame, so the axis-aligned box
    // must use the LARGEST half-extent on every axis. The offset dilates the
    // brush's zero crossing outward by offset/|grad|, and the shallowest
    // gradient is min(lat, depth)/max(lat, depth) -- so bound the reach by
    // scaling the largest extent by the same dilation factor the shader
    // computes. Under-sizing this box would silently truncate the carve at
    // the box edge.
    const float dil   = 1.0f + offset / std::min(lat, depth);
    const float reach = std::max(lat, depth) * dil;
    const glm::vec3 lo = center_body - glm::vec3(reach);
    const glm::vec3 hi = center_body + glm::vec3(reach);
    auto to_cell = [&](const glm::vec3& p) {
        const glm::vec3 g = (p - f.origin) / f.cell;
        return glm::ivec3(int(std::floor(g.x)), int(std::floor(g.y)),
                          int(std::floor(g.z)));
    };
    glm::ivec3 c0 = to_cell(lo);
    glm::ivec3 c1 = to_cell(hi);
    c0 = glm::max(c0, glm::ivec3(0));
    c1 = glm::min(c1, f.dims - 1);
    if (c0.x > c1.x || c0.y > c1.y || c0.z > c1.z) return {};   // wholly off-grid

    return apply_brush(f, c0, c1, [&](const glm::vec3& p) {
        const glm::vec3 v = p - center_body;
        const float along   = glm::dot(v, n);
        // NB: `lat_vec`, not `lat` -- `lat` is the brush's lateral half-extent
        // above, and shadowing it here silently reverted the rim dilation.
        const glm::vec3 lat_vec = v - along * n;
        const float ld          = glm::length(lat_vec);

        // Signed distance to the oblate, scaled back to model units. Dividing
        // each axis by its own half-extent turns the ellipsoid into a unit
        // sphere; multiplying the result by the SMALLEST half-extent ensures
        // the correct sign at the ellipsoid boundary (shape fidelity). Monotonicity
        // is unconditional given the max() in apply_brush: the scaling never
        // looks at d_old, only at -d_brush, so the max() cannot restore material.
        const float u = ld / lat;
        const float w = along / depth;
        const float unit = std::sqrt(u * u + w * w);
        const float d_brush = (unit - 1.0f) * std::min(lat, depth);
        // `+ offset` dilates the carve by a constant in the brush's own
        // distance units. It is added to the BRUSH only, never to d_old, so
        // the max() still cannot restore material: monotonicity holds.
        return -d_brush + offset;
    });
}

CellBox field_carve_capsule(DistanceField& f,
                         const glm::vec3& p0_body,
                         const glm::vec3& p1_body,
                         float radius) {
    if (f.empty()) return {};
    if (!(radius > 0.0f) || !std::isfinite(radius)) return {};
    if (!(f.scale > 0.0f)) return {};
    for (int k = 0; k < 3; ++k) {
        if (!std::isfinite(p0_body[k]) || !std::isfinite(p1_body[k])) return {};
    }

    const float min_cell = std::min(f.cell.x, std::min(f.cell.y, f.cell.z));
    const float r      = std::max(radius, kCarveDepthFloorCells * min_cell);
    const float offset = kCarveFieldOffsetCells * min_cell;
    const float reach  = r + offset;

    const glm::vec3 lo = glm::min(p0_body, p1_body) - glm::vec3(reach);
    const glm::vec3 hi = glm::max(p0_body, p1_body) + glm::vec3(reach);
    auto to_cell = [&](const glm::vec3& p) {
        const glm::vec3 g = (p - f.origin) / f.cell;
        return glm::ivec3(int(std::floor(g.x)), int(std::floor(g.y)),
                          int(std::floor(g.z)));
    };
    glm::ivec3 c0 = glm::max(to_cell(lo), glm::ivec3(0));
    glm::ivec3 c1 = glm::min(to_cell(hi), f.dims - 1);
    if (c0.x > c1.x || c0.y > c1.y || c0.z > c1.z) return {};

    const glm::vec3 ab = p1_body - p0_body;
    const float ab2 = glm::dot(ab, ab);

    return apply_brush(f, c0, c1, [&](const glm::vec3& p) {
        // Closest point on the segment.
        const float t = (ab2 > 0.0f)
            ? std::max(0.0f, std::min(1.0f, glm::dot(p - p0_body, ab) / ab2))
            : 0.0f;
        const glm::vec3 q = p0_body + ab * t;
        const float d_brush = glm::length(p - q) - r;   // signed: <0 inside
        return -d_brush + offset;
    });
}

}  // namespace voxel
