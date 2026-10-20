// native/src/voxel/src/structure_parts.cc -- see structure_parts.h (SPIKE).
#include <voxel/structure_parts.h>

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>

namespace voxel {
namespace {

constexpr double kInf = 1e20;

// Felzenszwalb-Huttenlocher 1D squared distance transform with sample
// spacing s (physical units). f, d: n samples; v, z: scratch (n, n+1).
void dt1d(const double* f, int n, double s, double* d, int* v, double* z) {
    int k = 0;
    v[0] = 0;
    z[0] = -kInf;
    z[1] = kInf;
    for (int q = 1; q < n; ++q) {
        double sq;
        for (;;) {
            const int vk = v[k];
            sq = ((f[q] + (q * s) * (q * s)) - (f[vk] + (vk * s) * (vk * s)))
                 / (2.0 * s * (q - vk));
            if (sq <= z[k]) { --k; continue; }
            break;
        }
        ++k;
        v[k] = q;
        z[k] = sq;
        z[k + 1] = kInf;
    }
    k = 0;
    for (int q = 0; q < n; ++q) {
        while (z[k + 1] < q * s) ++k;
        const double dq = (q - v[k]) * s;
        d[q] = dq * dq + f[v[k]];
    }
}

// Cyclic Jacobi for a symmetric 3x3. Eigenvalues in w, eigenvectors in the
// COLUMNS of V.
void jacobi3(double A[3][3], double w[3], double V[3][3]) {
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j) V[i][j] = (i == j) ? 1.0 : 0.0;
    for (int sweep = 0; sweep < 64; ++sweep) {
        const double off = std::fabs(A[0][1]) + std::fabs(A[0][2]) + std::fabs(A[1][2]);
        if (off < 1e-14) break;
        for (int p = 0; p < 2; ++p) {
            for (int q = p + 1; q < 3; ++q) {
                if (std::fabs(A[p][q]) < 1e-18) continue;
                const double theta = (A[q][q] - A[p][p]) / (2.0 * A[p][q]);
                const double t = (theta >= 0 ? 1.0 : -1.0)
                                 / (std::fabs(theta) + std::sqrt(theta * theta + 1.0));
                const double c = 1.0 / std::sqrt(t * t + 1.0), s = t * c;
                for (int k = 0; k < 3; ++k) {          // A = J^T A J
                    const double akp = A[k][p], akq = A[k][q];
                    A[k][p] = c * akp - s * akq;
                    A[k][q] = s * akp + c * akq;
                }
                for (int k = 0; k < 3; ++k) {
                    const double apk = A[p][k], aqk = A[q][k];
                    A[p][k] = c * apk - s * aqk;
                    A[q][k] = s * apk + c * aqk;
                }
                for (int k = 0; k < 3; ++k) {
                    const double vkp = V[k][p], vkq = V[k][q];
                    V[k][p] = c * vkp - s * vkq;
                    V[k][q] = s * vkp + c * vkq;
                }
            }
        }
    }
    for (int i = 0; i < 3; ++i) w[i] = A[i][i];
}

int find_root(std::vector<int>& parent, int x) {
    while (parent[x] != x) {
        parent[x] = parent[parent[x]];
        x = parent[x];
    }
    return x;
}

glm::vec3 canonical_sign(glm::vec3 v) {
    const glm::vec3 a = glm::abs(v);
    const int i = (a.x >= a.y && a.x >= a.z) ? 0 : (a.y >= a.z ? 1 : 2);
    return v[i] < 0.0f ? -v : v;
}

struct Moments {
    int n = 0;
    glm::dvec3 sum{0.0};
    double m2[9] = {0};
    void add(const glm::dvec3& q) {
        ++n;
        sum += q;
        for (int a = 0; a < 3; ++a)
            for (int b = 0; b < 3; ++b) m2[a * 3 + b] += q[a] * q[b];
    }
    void merge(const Moments& o) {
        n += o.n;
        sum += o.sum;
        for (int i = 0; i < 9; ++i) m2[i] += o.m2[i];
    }
};

StructurePart fit_part(const Moments& M, const StructureParams& p) {
    StructurePart part;
    const glm::dvec3 mu = M.sum / static_cast<double>(M.n);
    double C[3][3];
    for (int a = 0; a < 3; ++a)
        for (int b = 0; b < 3; ++b) C[a][b] = M.m2[a * 3 + b] / M.n - mu[a] * mu[b];
    double w[3], V[3][3];
    jacobi3(C, w, V);
    int ord[3] = {0, 1, 2};
    std::sort(ord, ord + 3, [&](int a, int b) { return w[a] > w[b]; });
    glm::vec3 ev[3];
    float s[3];
    for (int i = 0; i < 3; ++i) {
        ev[i] = canonical_sign(glm::normalize(glm::vec3(
            static_cast<float>(V[0][ord[i]]), static_cast<float>(V[1][ord[i]]),
            static_cast<float>(V[2][ord[i]]))));
        s[i] = static_cast<float>(std::sqrt(std::max(w[ord[i]], 0.0)));
    }
    const float r21 = s[0] > 0 ? s[1] / s[0] : 0.0f;
    const float r32 = s[1] > 0 ? s[2] / s[1] : 0.0f;
    const float k3 = std::sqrt(3.0f);
    if (r32 < p.disc_flat && r21 > p.disc_round) {
        part.kind = PartKind::Disc;
        part.axis[0] = ev[2];
        part.axis[1] = ev[0];
        part.half_extent = glm::vec3(k3 * s[2], 2.0f * s[0], 2.0f * s[1]);
    } else if (r21 < p.cyl_long && r32 > p.cyl_round) {
        part.kind = PartKind::Cylinder;
        part.axis[0] = ev[0];
        part.axis[1] = ev[1];
        part.half_extent = glm::vec3(k3 * s[0], 2.0f * s[1], 2.0f * s[2]);
    } else {
        part.kind = PartKind::Box;
        part.axis[0] = ev[0];
        part.axis[1] = ev[1];
        part.half_extent = k3 * glm::vec3(s[0], s[1], s[2]);
    }
    part.axis[2] = glm::normalize(glm::cross(part.axis[0], part.axis[1]));
    part.centre = glm::vec3(mu);
    part.voxels = M.n;
    part.spread = glm::vec3(s[0], s[1], s[2]);
    return part;
}

}  // namespace

std::vector<float> solid_depth(const VoxelVolume& vol) {
    const int nx = vol.dims.x, ny = vol.dims.y, nz = vol.dims.z;
    const std::size_t n = static_cast<std::size_t>(nx) * ny * nz;
    std::vector<double> g(n);
    for (std::size_t i = 0; i < n; ++i) g[i] = vol.occ[i] ? kInf : 0.0;

    const int nmax = std::max({nx, ny, nz});
    std::vector<double> f(nmax), d(nmax), z(nmax + 1);
    std::vector<int> v(nmax);
    auto pass = [&](int len, double s, auto idx_of) {
        for (int i = 0; i < len; ++i) f[i] = g[idx_of(i)];
        dt1d(f.data(), len, s, d.data(), v.data(), z.data());
        for (int i = 0; i < len; ++i) g[idx_of(i)] = d[i];
    };
    for (int zz = 0; zz < nz; ++zz)
        for (int yy = 0; yy < ny; ++yy)
            pass(nx, vol.cell.x, [&](int i) { return vol.index(i, yy, zz); });
    for (int zz = 0; zz < nz; ++zz)
        for (int xx = 0; xx < nx; ++xx)
            pass(ny, vol.cell.y, [&](int i) { return vol.index(xx, i, zz); });
    for (int yy = 0; yy < ny; ++yy)
        for (int xx = 0; xx < nx; ++xx)
            pass(nz, vol.cell.z, [&](int i) { return vol.index(xx, yy, i); });

    // Physical units -> cells (mean cell), as documented.
    const double mean_cell = (vol.cell.x + vol.cell.y + vol.cell.z) / 3.0;
    std::vector<float> out(n, 0.0f);
    for (std::size_t i = 0; i < n; ++i)
        if (vol.occ[i]) out[i] = static_cast<float>(std::sqrt(g[i]) / mean_cell);
    return out;
}

StructureSegmentation detect_structure_parts(const std::vector<Tri>& tris,
                                             const StructureParams& p) {
    StructureSegmentation seg;
    if (tris.empty()) return seg;

    // Near-isotropic grid: the longest hull side gets long_axis_cells.
    glm::vec3 lo(std::numeric_limits<float>::max()), hi(-std::numeric_limits<float>::max());
    for (const Tri& t : tris) {
        for (const glm::vec3& q : {t.a, t.b, t.c}) {
            lo = glm::min(lo, q);
            hi = glm::max(hi, q);
        }
    }
    const glm::vec3 ext = hi - lo;
    const float L = std::max({ext.x, ext.y, ext.z});
    const float c = L / static_cast<float>(std::max(p.long_axis_cells - 2, 1));
    glm::ivec3 dims;
    for (int a = 0; a < 3; ++a)
        dims[a] = std::max(3, static_cast<int>(std::ceil(ext[a] / c)) + 2);
    seg.vol = voxelize_tris(tris, dims);
    const VoxelVolume& vol = seg.vol;
    const std::size_t n = vol.occ.size();
    seg.depth = solid_depth(vol);
    const std::vector<float>& depth = seg.depth;
    const float mean_cell = (vol.cell.x + vol.cell.y + vol.cell.z) / 3.0f;

    std::vector<int> order;                      // solid voxels, deepest first
    order.reserve(n);
    for (std::size_t i = 0; i < n; ++i)
        if (vol.occ[i]) order.push_back(static_cast<int>(i));
    std::stable_sort(order.begin(), order.end(),
                     [&](int a, int b) { return depth[a] > depth[b]; });
    const int nx = vol.dims.x, ny = vol.dims.y, nz = vol.dims.z;
    auto inside = [&](int x, int y, int z) {
        return x >= 0 && y >= 0 && z >= 0 && x < nx && y < ny && z < nz;
    };
    auto dep = [&](int x, int y, int z) -> float {
        return inside(x, y, z) ? depth[vol.index(x, y, z)] : 0.0f;
    };

    // 1. Medial core: voxels that are a depth ridge along some direction
    //    (>= both neighbours, > at least one), ignoring the skin.
    static const int kDirs[13][3] = {
        {1, 0, 0}, {0, 1, 0}, {0, 0, 1}, {1, 1, 0}, {1, -1, 0}, {1, 0, 1}, {1, 0, -1},
        {0, 1, 1}, {0, 1, -1}, {1, 1, 1}, {1, 1, -1}, {1, -1, 1}, {-1, 1, 1}};
    std::vector<std::uint8_t> medial(n, 0);
    std::vector<int> medial_ids;
    for (int idx : order) {
        const float d = depth[idx];
        if (d < p.medial_min_depth) continue;
        const int x = idx % nx, y = (idx / nx) % ny, zc = idx / (nx * ny);
        for (const auto& o : kDirs) {
            const float da = dep(x + o[0], y + o[1], zc + o[2]);
            const float db = dep(x - o[0], y - o[1], zc - o[2]);
            if (d >= da && d >= db && (d > da || d > db)) {
                medial[idx] = 1;
                medial_ids.push_back(idx);
                break;
            }
        }
    }

    // 2. Local shape of the core around each medial voxel: principal axes of
    //    the medial points in a box scaled to the local depth, via summed
    //    volume tables of the point moments. Sheet (saucer, neck) / line
    //    (nacelle) / blob, with its normal or axis.
    const int sx = nx + 1, sy = ny + 1, sz = nz + 1;
    const std::size_t sn = static_cast<std::size_t>(sx) * sy * sz;
    std::vector<double> sat(sn * 10, 0.0);
    auto sidx = [&](int x, int y, int z) {
        return (static_cast<std::size_t>(x) + static_cast<std::size_t>(sx) * (y + static_cast<std::size_t>(sy) * z)) * 10;
    };
    for (int z = 1; z < sz; ++z)
        for (int y = 1; y < sy; ++y)
            for (int x = 1; x < sx; ++x) {
                double m[10] = {0};
                if (medial[vol.index(x - 1, y - 1, z - 1)]) {
                    const double X = x - 1, Y = y - 1, Z = z - 1;
                    const double vals[10] = {1, X, Y, Z, X * X, X * Y, X * Z, Y * Y, Y * Z, Z * Z};
                    for (int c = 0; c < 10; ++c) m[c] = vals[c];
                }
                double* out = &sat[sidx(x, y, z)];
                for (int c = 0; c < 10; ++c) {
                    out[c] = m[c]
                        + sat[sidx(x - 1, y, z) + c] + sat[sidx(x, y - 1, z) + c] + sat[sidx(x, y, z - 1) + c]
                        - sat[sidx(x - 1, y - 1, z) + c] - sat[sidx(x - 1, y, z - 1) + c] - sat[sidx(x, y - 1, z - 1) + c]
                        + sat[sidx(x - 1, y - 1, z - 1) + c];
                }
            }
    auto box = [&](int x0, int y0, int z0, int x1, int y1, int z1, double* m) {  // [x0, x1) etc.
        x0 = std::clamp(x0, 0, nx); y0 = std::clamp(y0, 0, ny); z0 = std::clamp(z0, 0, nz);
        x1 = std::clamp(x1, 0, nx); y1 = std::clamp(y1, 0, ny); z1 = std::clamp(z1, 0, nz);
        for (int c = 0; c < 10; ++c)
            m[c] = sat[sidx(x1, y1, z1) + c] - sat[sidx(x0, y1, z1) + c] - sat[sidx(x1, y0, z1) + c]
                 - sat[sidx(x1, y1, z0) + c] + sat[sidx(x0, y0, z1) + c] + sat[sidx(x0, y1, z0) + c]
                 + sat[sidx(x1, y0, z0) + c] - sat[sidx(x0, y0, z0) + c];
    };
    enum : std::uint8_t { kNone = 0, kSheet = 1, kLine = 2, kBlob = 3 };
    std::vector<std::uint8_t> cls(n, kNone);
    std::vector<glm::vec3> dir(n, glm::vec3(0.0f));
    for (int idx : medial_ids) {
        const int x = idx % nx, y = (idx / nx) % ny, zc = idx / (nx * ny);
        const int R = std::clamp(static_cast<int>(std::lround(p.shape_radius_k * depth[idx] + 2.0f)),
                                 3, p.shape_radius_max);
        double m[10];
        box(x - R, y - R, zc - R, x + R + 1, y + R + 1, zc + R + 1, m);
        if (m[0] < 6.0) { cls[idx] = kBlob; continue; }
        const double mx = m[1] / m[0], my = m[2] / m[0], mz = m[3] / m[0];
        double C[3][3] = {
            {m[4] / m[0] - mx * mx, m[5] / m[0] - mx * my, m[6] / m[0] - mx * mz},
            {0, m[7] / m[0] - my * my, m[8] / m[0] - my * mz},
            {0, 0, m[9] / m[0] - mz * mz}};
        C[1][0] = C[0][1]; C[2][0] = C[0][2]; C[2][1] = C[1][2];
        double w[3], V[3][3];
        jacobi3(C, w, V);
        int o3[3] = {0, 1, 2};
        std::sort(o3, o3 + 3, [&](int a, int b) { return w[a] > w[b]; });
        const double l1 = std::max(w[o3[0]], 1e-9), l2 = std::max(w[o3[1]], 0.0),
                     l3 = std::max(w[o3[2]], 0.0);
        auto col = [&](int k) {
            return glm::vec3(static_cast<float>(V[0][k]), static_cast<float>(V[1][k]),
                             static_cast<float>(V[2][k]));
        };
        if (l2 / l1 < p.line_ratio) { cls[idx] = kLine; dir[idx] = col(o3[0]); }
        else if (l3 / std::max(l2, 1e-9) < p.sheet_ratio) { cls[idx] = kSheet; dir[idx] = col(o3[2]); }
        else cls[idx] = kBlob;
    }

    // 3. Grow regions over the core: neighbours join when they are the same
    //    kind and (sheets / lines) face the same way.
    std::vector<int> parent(n);
    std::iota(parent.begin(), parent.end(), 0);
    const float cos_tol = std::cos(glm::radians(p.orient_tol_deg));
    for (int idx : medial_ids) {
        const int x = idx % nx, y = (idx / nx) % ny, zc = idx / (nx * ny);
        for (int dz = -1; dz <= 1; ++dz)
            for (int dy = -1; dy <= 1; ++dy)
                for (int dx = -1; dx <= 1; ++dx) {
                    if (!dx && !dy && !dz) continue;
                    if (!inside(x + dx, y + dy, zc + dz)) continue;
                    const int j = static_cast<int>(vol.index(x + dx, y + dy, zc + dz));
                    if (!medial[j] || cls[j] != cls[idx]) continue;
                    if (cls[idx] != kBlob && std::fabs(glm::dot(dir[idx], dir[j])) < cos_tol) continue;
                    const int ra = find_root(parent, idx), rb = find_root(parent, j);
                    if (ra != rb) parent[std::max(ra, rb)] = std::min(ra, rb);
                }
    }

    // 4. Every solid voxel takes the region of its nearest core voxel
    //    (multi-source BFS through the solid). Solid with no core at all
    //    (one-voxel-thin bits) becomes its own region per connected piece.
    seg.label.assign(n, -1);
    std::vector<int> root_to_label(n, -1);
    int nlabels = 0;
    std::vector<int> queue;
    queue.reserve(order.size());
    for (int idx : medial_ids) {
        const int r = find_root(parent, idx);
        if (root_to_label[r] < 0) root_to_label[r] = nlabels++;
        seg.label[idx] = static_cast<std::int16_t>(root_to_label[r]);
        queue.push_back(idx);
    }
    static const int kN6[6][3] = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}};
    auto bfs = [&](std::size_t head) {
        for (; head < queue.size(); ++head) {
            const int idx = queue[head];
            const int x = idx % nx, y = (idx / nx) % ny, zc = idx / (nx * ny);
            for (const auto& o : kN6) {
                if (!inside(x + o[0], y + o[1], zc + o[2])) continue;
                const int j = static_cast<int>(vol.index(x + o[0], y + o[1], zc + o[2]));
                if (!vol.occ[j] || seg.label[j] >= 0) continue;
                seg.label[j] = seg.label[idx];
                queue.push_back(j);
            }
        }
    };
    bfs(0);
    for (int idx : order) {
        if (seg.label[idx] >= 0) continue;
        seg.label[idx] = static_cast<std::int16_t>(nlabels++);
        const std::size_t head = queue.size();
        queue.push_back(idx);
        bfs(head);
    }

    // Merge lobes below min_fraction into the neighbour they touch most.
    const int min_vox = static_cast<int>(p.min_fraction * static_cast<float>(order.size()));
    std::vector<bool> keep(nlabels, false);   // isolated islands stay parts
    for (;;) {
        std::vector<int> count(nlabels, 0);
        for (int idx : order) ++count[seg.label[idx]];
        int small = -1;
        for (int l = 0; l < nlabels; ++l)
            if (!keep[l] && count[l] > 0 && count[l] < min_vox
                && (small < 0 || count[l] < count[small]))
                small = l;
        if (small < 0) break;
        std::vector<int> contact(nlabels, 0);
        for (int idx : order) {
            if (seg.label[idx] != small) continue;
            const int x = idx % nx, y = (idx / nx) % ny, zc = idx / (nx * ny);
            const int nb[6][3] = {{1,0,0},{-1,0,0},{0,1,0},{0,-1,0},{0,0,1},{0,0,-1}};
            for (const auto& o : nb) {
                const int xx = x + o[0], yy = y + o[1], zz = zc + o[2];
                if (xx < 0 || yy < 0 || zz < 0 || xx >= nx || yy >= ny || zz >= nz) continue;
                const int l = seg.label[vol.index(xx, yy, zz)];
                if (l >= 0 && l != small) ++contact[l];
            }
        }
        const int into = static_cast<int>(std::max_element(contact.begin(), contact.end())
                                          - contact.begin());
        if (contact[into] == 0) { keep[small] = true; continue; }
        for (int idx : order) if (seg.label[idx] == small) seg.label[idx] = static_cast<std::int16_t>(into);
    }
    // Re-compact after merges.
    {
        std::vector<int> remap(nlabels, -1);
        int k = 0;
        for (int idx : order) {
            const int l = seg.label[idx];
            if (remap[l] < 0) remap[l] = k++;
            seg.label[idx] = static_cast<std::int16_t>(remap[l]);
        }
        nlabels = k;
    }

    // Moments per region (additive, so a merge is a sum).
    std::vector<Moments> mom(nlabels);
    std::vector<float> pk(nlabels, 0.0f);
    for (int idx : order) {
        const int l = seg.label[idx];
        const int x = idx % nx, y = (idx / nx) % ny, zc = idx / (nx * ny);
        mom[l].add(glm::dvec3(vol.origin) + (glm::dvec3(x, y, zc) + 0.5) * glm::dvec3(vol.cell));
        pk[l] = std::max(pk[l], depth[idx]);
    }

    // 5. Merge neighbouring regions that are pieces of ONE shape: the merged
    //    fit must keep the larger piece's kind and main axis (a nacelle cut in
    //    three, a saucer in two). A saucer and an engineering hull never pass:
    //    together they are neither a disc nor a cylinder.
    const float cos_merge = std::cos(glm::radians(p.merge_axis_tol_deg));
    for (;;) {
        std::vector<std::pair<int, std::pair<int, int>>> pairs;   // contact, (a, b)
        {
            std::vector<int> contact(static_cast<std::size_t>(nlabels) * nlabels, 0);
            for (int idx : order) {
                const int la = seg.label[idx];
                const int x = idx % nx, y = (idx / nx) % ny, zc = idx / (nx * ny);
                for (int k = 0; k < 6; k += 2) {               // +x, +y, +z only
                    const auto& o = kN6[k];
                    if (!inside(x + o[0], y + o[1], zc + o[2])) continue;
                    const int lb = seg.label[vol.index(x + o[0], y + o[1], zc + o[2])];
                    if (lb >= 0 && lb != la) ++contact[std::min(la, lb) * nlabels + std::max(la, lb)];
                }
            }
            for (int i = 0; i < nlabels; ++i)
                for (int j = i + 1; j < nlabels; ++j)
                    if (contact[i * nlabels + j] > 0)
                        pairs.push_back({contact[i * nlabels + j], {i, j}});
        }
        std::sort(pairs.begin(), pairs.end(), [](auto& u, auto& v) { return u.first > v.first; });
        bool merged = false;
        for (const auto& pr : pairs) {
            int big = pr.second.first, small = pr.second.second;
            if (mom[small].n > mom[big].n) std::swap(big, small);
            if (mom[big].n == 0 || mom[small].n == 0) continue;
            const StructurePart fb = fit_part(mom[big], p);
            Moments mm = mom[big];
            mm.merge(mom[small]);
            const StructurePart fm = fit_part(mm, p);
            // Same kind, or both elongated (box <-> cylinder flips on a
            // flattish cross-section, e.g. the Akira's nacelles).
            const bool elongated = fm.kind != PartKind::Disc && fb.kind != PartKind::Disc
                && fm.spread.y < p.cyl_long * fm.spread.x;
            if (fm.kind != fb.kind && !elongated) continue;
            // ...and the two pieces must already BE the same kind of shape. A
            // flat hull (the LC Intrepid) still fits as one disc once saucer,
            // engineering hull and nacelles are glued together.
            const StructurePart fs = fit_part(mom[small], p);
            const bool both_elongated = fs.kind != PartKind::Disc && fb.kind != PartKind::Disc;
            if (fs.kind != fb.kind && !both_elongated) continue;
            // ...pointing the same way (an aft section lying ACROSS the hull
            // must not join it, then let the fattened hull swallow nacelles).
            if (std::fabs(glm::dot(fs.axis[0], fb.axis[0])) < cos_merge) continue;
            if (std::fabs(glm::dot(fm.axis[0], fb.axis[0])) < cos_merge) continue;
            // ...and joining them must not fatten the shape: a nacelle cut in
            // two keeps its cross-section, a saucer cut in two its thickness,
            // but a nacelle glued to a hull (or a saucer to the hull below it)
            // does not.
            const float g = p.merge_spread_growth;
            if (fb.kind == PartKind::Disc) {
                if (fm.spread.z > g * std::max(fb.spread.z, fs.spread.z)) continue;
            } else {
                if (fm.spread.y > g * std::max(fb.spread.y, fs.spread.y)) continue;
                if (fm.spread.z > g * std::max(fb.spread.z, fs.spread.z)) continue;
            }
            mom[big] = mm;
            mom[small] = Moments{};
            pk[big] = std::max(pk[big], pk[small]);
            for (int idx : order) if (seg.label[idx] == small) seg.label[idx] = static_cast<std::int16_t>(big);
            merged = true;
            break;
        }
        if (!merged) break;
    }

    // 6. A disc claims every voxel inside its own slab: the thick middle of
    //    a saucer, where the neck joins, otherwise goes to the neck's region.
    {
        std::vector<StructurePart> fits(nlabels);
        for (int l = 0; l < nlabels; ++l) if (mom[l].n > 0) fits[l] = fit_part(mom[l], p);
        for (int l = 0; l < nlabels; ++l) {
            if (mom[l].n == 0 || fits[l].kind != PartKind::Disc) continue;
            const StructurePart& d = fits[l];
            const float R = std::max(d.half_extent.y, d.half_extent.z);
            for (int idx : order) {
                const int cur = seg.label[idx];
                if (cur == l || fits[cur].kind == PartKind::Disc) continue;
                const int x = idx % nx, y = (idx / nx) % ny, zc = idx / (nx * ny);
                const glm::dvec3 q = glm::dvec3(vol.origin)
                                     + (glm::dvec3(x, y, zc) + 0.5) * glm::dvec3(vol.cell);
                const glm::vec3 off = glm::vec3(q) - d.centre;
                const float h = glm::dot(off, d.axis[0]);
                if (std::fabs(h) > p.disc_claim_k * d.half_extent.x) continue;
                if (glm::length(off - d.axis[0] * h) > R) continue;
                seg.label[idx] = static_cast<std::int16_t>(l);
            }
        }
        for (auto& m : mom) m = Moments{};
        for (int idx : order) {
            const int x = idx % nx, y = (idx / nx) % ny, zc = idx / (nx * ny);
            mom[seg.label[idx]].add(glm::dvec3(vol.origin)
                                    + (glm::dvec3(x, y, zc) + 0.5) * glm::dvec3(vol.cell));
        }
    }

    // Final parts (compact the emptied slots away).
    std::vector<int> remap(nlabels, -1);
    for (int l = 0; l < nlabels; ++l) {
        if (mom[l].n == 0) continue;
        StructurePart part = fit_part(mom[l], p);
        part.peak_depth = pk[l] * mean_cell;
        remap[l] = static_cast<int>(seg.parts.size());
        seg.parts.push_back(part);
    }
    for (int idx : order) seg.label[idx] = static_cast<std::int16_t>(remap[seg.label[idx]]);
    return seg;
}

}  // namespace voxel
