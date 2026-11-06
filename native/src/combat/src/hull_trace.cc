// The CPU hull trace -- see hull_trace.h. A port of engine/appc/
// damage_point.py's _Bvh.first_hit; each line names the Python it stands for.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/hull_trace.h"

#include <cmath>
#include <stdexcept>
#include <utility>

namespace dauntless::combat {

namespace {

std::vector<HullMesh>& meshes() {
    static std::vector<HullMesh> m;
    return m;
}

}  // namespace

int64_t hull_trace_register(HullMesh mesh) {
    meshes().push_back(std::move(mesh));
    return static_cast<int64_t>(meshes().size()) - 1;
}

void hull_trace_clear() { meshes().clear(); }

std::optional<double> hull_trace_first_hit(int64_t h, const double o[3],
                                           const double d[3]) {
    if (h < 0 || h >= static_cast<int64_t>(meshes().size()))
        throw std::out_of_range("hull_trace: no such mesh");
    const HullMesh& m = meshes()[static_cast<size_t>(h)];
    if (m.nodes.empty()) return std::nullopt;
    // inv = [1.0 / d[k] if abs(d[k]) > 1e-12 else 1e30 for k in range(3)]
    double inv[3];
    for (int k = 0; k < 3; ++k)
        inv[k] = std::fabs(d[k]) > 1e-12 ? 1.0 / d[k] : 1e30;
    bool found = false;
    double best = 0.0;
    std::vector<int64_t> stack{0};
    while (!stack.empty()) {
        const HullBvhNode& n = m.nodes[static_cast<size_t>(stack.back())];
        stack.pop_back();
        double tmin = 0.0, tmax = 1e30;
        bool ok = true;
        for (int k = 0; k < 3; ++k) {
            double t1 = (n.lo[k] - o[k]) * inv[k];
            double t2 = (n.hi[k] - o[k]) * inv[k];
            if (t1 > t2) std::swap(t1, t2);
            if (t1 > tmin) tmin = t1;
            if (t2 < tmax) tmax = t2;
            if (tmin > tmax) {
                ok = false;
                break;
            }
        }
        if (!ok) continue;
        if (n.left != -1) {   // `idx is None`: an inner node
            stack.push_back(n.left);
            stack.push_back(n.right);
            continue;
        }
        for (const int64_t i : n.tris) {
            const double* t = &m.tris[static_cast<size_t>(i) * 9];
            const double *v0 = t, *e1 = t + 3, *e2 = t + 6;
            const double px = d[1] * e2[2] - d[2] * e2[1];
            const double py = d[2] * e2[0] - d[0] * e2[2];
            const double pz = d[0] * e2[1] - d[1] * e2[0];
            const double det = e1[0] * px + e1[1] * py + e1[2] * pz;
            if (-1e-12 < det && det < 1e-12) continue;
            const double f = 1.0 / det;
            const double sx = o[0] - v0[0], sy = o[1] - v0[1], sz = o[2] - v0[2];
            const double u = (sx * px + sy * py + sz * pz) * f;
            if (u < 0.0 || u > 1.0) continue;
            const double qx = sy * e1[2] - sz * e1[1];
            const double qy = sz * e1[0] - sx * e1[2];
            const double qz = sx * e1[1] - sy * e1[0];
            const double v = (d[0] * qx + d[1] * qy + d[2] * qz) * f;
            if (v < 0.0 || u + v > 1.0) continue;
            const double tt = (e2[0] * qx + e2[1] * qy + e2[2] * qz) * f;
            if (tt > 1e-6 && (!found || tt < best)) {
                best = tt;
                found = true;
            }
        }
    }
    if (!found) return std::nullopt;
    return best;
}

}  // namespace dauntless::combat
