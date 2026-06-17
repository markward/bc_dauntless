#include <voxel/dual_contour.h>
#include <glm/glm.hpp>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <vector>

namespace voxel {

glm::vec3 solve_qef(const std::vector<Plane>& planes, glm::vec3 fallback) {
    if (planes.empty()) {
        return fallback;
    }

    // Build the normal-equation system A = Σ n_i n_iᵀ, b = Σ d_i n_i.
    // glm::mat3 is column-major: mat3[col][row].
    // For a symmetric outer-product matrix n·nᵀ, column-major and row-major
    // representations are identical, so we can build it directly.
    glm::mat3 A(0.0f);
    glm::vec3 b(0.0f);

    for (const auto& p : planes) {
        const glm::vec3& n = p.n;
        // Outer product n·nᵀ accumulated into A (column-major: A[col][row])
        A[0][0] += n.x * n.x;  A[1][0] += n.y * n.x;  A[2][0] += n.z * n.x;
        A[0][1] += n.x * n.y;  A[1][1] += n.y * n.y;  A[2][1] += n.z * n.y;
        A[0][2] += n.x * n.z;  A[1][2] += n.y * n.z;  A[2][2] += n.z * n.z;
        b += p.d * n;
    }

    // Tikhonov regularization: (A + λI) v = b + λ·fallback
    // λ = 1e-4: small enough that a well-constrained corner (A = I, b = exact)
    // has error O(λ·d) < 1e-3 for typical cell coordinates, yet large enough
    // to guarantee invertibility and pull under-constrained axes toward the
    // seed (e.g. the two free axes in the single-plane case where only one
    // diagonal element of A is non-zero before regularization).
    constexpr float kLambda = 1e-4f;
    A[0][0] += kLambda;
    A[1][1] += kLambda;
    A[2][2] += kLambda;
    b += kLambda * fallback;

    const float det = glm::determinant(A);
    if (std::abs(det) < 1e-10f) {
        // Should not happen with λ > 0 and a well-formed normal matrix, but
        // defend against degenerate floating-point edge cases.
        return fallback;
    }

    return glm::inverse(A) * b;
}

namespace {

// Voxel-center body-frame position of node (i,j,k).
inline glm::vec3 node_pos(const VoxelVolume& v, int i, int j, int k) {
    return v.origin + (glm::vec3(i, j, k) + 0.5f) * v.cell;
}

// The 8 corners of a dual-contouring cell (lo-corner = node (i,j,k)).
// Corner ordering: bit0 = +x, bit1 = +y, bit2 = +z.
constexpr std::array<glm::ivec3, 8> kCorner = {{
    {0,0,0},{1,0,0},{0,1,0},{1,1,0},{0,0,1},{1,0,1},{0,1,1},{1,1,1}}};

// The 12 edges of a cell as (cornerA, cornerB) index pairs.
constexpr std::array<std::array<int,2>,12> kEdge = {{
    {0,1},{2,3},{4,5},{6,7},   // x-aligned
    {0,2},{1,3},{4,6},{5,7},   // y-aligned
    {0,4},{1,5},{2,6},{3,7}}}; // z-aligned

}  // namespace

Mesh dual_contour(const VoxelVolume& fill, int isovalue,
                  const std::vector<glm::vec4>& palette) {
    Mesh mesh;
    const glm::ivec3 d = fill.dims;
    if (d.x < 2 || d.y < 2 || d.z < 2 || fill.occ.empty()) {
        return mesh;
    }

    const float iso = static_cast<float>(isovalue);
    // Match tolerance: ~1 cell size. A palette plane counts as "the local hull
    // facet through this cell" when the cell's surface point lies within ~1
    // cell of it.
    const float cell_len = std::max({fill.cell.x, fill.cell.y, fill.cell.z});
    const float kMatchTol = 1.0f * cell_len;
    constexpr int kMaxPlanes = 3;

    auto val = [&](int i, int j, int k) -> float {
        return static_cast<float>(fill.occ[fill.index(i, j, k)]);
    };

    // Cell (i,j,k) spans nodes [i..i+1]^3, so cells run [0..d-2] on each axis.
    const glm::ivec3 cdim = d - glm::ivec3(1);
    const std::size_t ncell =
        static_cast<std::size_t>(cdim.x) * cdim.y * cdim.z;
    auto cidx = [&](int i, int j, int k) -> std::size_t {
        return static_cast<std::size_t>(i)
             + static_cast<std::size_t>(cdim.x) * (j + static_cast<std::size_t>(cdim.y) * k);
    };

    // cell -> vertex index (-1 = no vertex for this cell)
    std::vector<std::int64_t> cell_vert(ncell, -1);

    // -------- pass 1: place one vertex per straddling cell --------
    for (int k = 0; k < cdim.z; ++k)
    for (int j = 0; j < cdim.y; ++j)
    for (int i = 0; i < cdim.x; ++i) {
        // gather 8 corner fill values
        std::array<float, 8> cv;
        bool any_below = false, any_above = false;
        for (int c = 0; c < 8; ++c) {
            const glm::ivec3& off = kCorner[c];
            cv[c] = val(i + off.x, j + off.y, k + off.z);
            if (cv[c] < iso) any_below = true; else any_above = true;
        }
        if (!(any_below && any_above)) continue;  // does not straddle

        // surface point p = average of edge crossings (linear interp of fill)
        glm::vec3 psum(0.f);
        int ncross = 0;
        for (const auto& e : kEdge) {
            float va = cv[e[0]], vb = cv[e[1]];
            bool a_in = va >= iso, b_in = vb >= iso;
            if (a_in == b_in) continue;  // no sign change
            float t = (iso - va) / (vb - va);     // va + t(vb-va) = iso
            t = std::clamp(t, 0.f, 1.f);
            glm::vec3 pa = node_pos(fill, i + kCorner[e[0]].x,
                                          j + kCorner[e[0]].y,
                                          k + kCorner[e[0]].z);
            glm::vec3 pb = node_pos(fill, i + kCorner[e[1]].x,
                                          j + kCorner[e[1]].y,
                                          k + kCorner[e[1]].z);
            psum += pa + t * (pb - pa);
            ++ncross;
        }
        glm::vec3 p = (ncross > 0)
            ? psum / static_cast<float>(ncross)
            : node_pos(fill, i, j, k) + 0.5f * fill.cell;  // cell center

        // -------- match palette planes by point-to-plane distance --------
        // Keep up to kMaxPlanes nearest (within tol) with distinct normals.
        std::array<std::pair<float, Plane>, kMaxPlanes> best;
        int nbest = 0;
        for (const auto& pl4 : palette) {
            glm::vec3 n(pl4.x, pl4.y, pl4.z);
            float pd = pl4.w;
            float dist = std::abs(glm::dot(n, p) - pd);
            if (dist > kMatchTol) continue;
            // reject if a near-parallel normal is already kept (same facet);
            // keep whichever is closer.
            bool dup = false;
            for (int b = 0; b < nbest; ++b) {
                if (glm::dot(best[b].second.n, n) > 0.985f) {  // ~10 deg
                    dup = true;
                    if (dist < best[b].first) best[b] = {dist, Plane{n, pd}};
                    break;
                }
            }
            if (dup) continue;
            if (nbest < kMaxPlanes) {
                best[nbest++] = {dist, Plane{n, pd}};
            } else {
                // replace the worst kept if this one is closer
                int worst = 0;
                for (int b = 1; b < nbest; ++b)
                    if (best[b].first > best[worst].first) worst = b;
                if (dist < best[worst].first) best[worst] = {dist, Plane{n, pd}};
            }
        }

        std::vector<Plane> matched;
        for (int b = 0; b < nbest; ++b) matched.push_back(best[b].second);

        // Vertex normal candidate: averaged matched-plane normals.
        glm::vec3 nrm(0.f);
        for (const auto& pl : matched) nrm += pl.n;

        if (matched.empty()) {
            // Fall back to a single plane from the central-difference fill
            // gradient through p, so the mesh stays watertight where no palette
            // plane is close (e.g. interpolation drift on smooth spans).
            auto clampv = [&](int x, int lo, int hi){ return std::clamp(x, lo, hi); };
            float gx = val(clampv(i+1,0,d.x-1), clampv(j,0,d.y-1), clampv(k,0,d.z-1))
                     - val(clampv(i  ,0,d.x-1), clampv(j,0,d.y-1), clampv(k,0,d.z-1));
            float gy = val(clampv(i,0,d.x-1), clampv(j+1,0,d.y-1), clampv(k,0,d.z-1))
                     - val(clampv(i,0,d.x-1), clampv(j  ,0,d.y-1), clampv(k,0,d.z-1));
            float gz = val(clampv(i,0,d.x-1), clampv(j,0,d.y-1), clampv(k+1,0,d.z-1))
                     - val(clampv(i,0,d.x-1), clampv(j,0,d.y-1), clampv(k  ,0,d.z-1));
            // Fill increases toward solid; outward surface normal points toward
            // emptiness, i.e. opposite the gradient.
            glm::vec3 g(gx, gy, gz);
            if (glm::dot(g, g) > 1e-12f) {
                glm::vec3 n = -glm::normalize(g);
                matched.push_back(Plane{n, glm::dot(n, p)});
                nrm = n;
            }
        }

        glm::vec3 vert = solve_qef(matched, /*fallback=*/p);

        if (glm::dot(nrm, nrm) < 1e-12f) nrm = glm::vec3(0, 0, 1);
        else nrm = glm::normalize(nrm);

        cell_vert[cidx(i, j, k)] = static_cast<std::int64_t>(mesh.positions.size());
        mesh.positions.push_back(vert);
        mesh.normals.push_back(nrm);
    }

    // -------- pass 2: emit quads on isovalue-crossing grid edges --------
    // For a grid edge between two adjacent nodes that straddles the isovalue,
    // the 4 cells sharing that edge each (should) own a vertex; connect them.
    auto emit_quad = [&](std::int64_t a, std::int64_t b,
                         std::int64_t c, std::int64_t dd, bool flip) {
        if (a < 0 || b < 0 || c < 0 || dd < 0) return;
        auto A = static_cast<std::uint32_t>(a);
        auto B = static_cast<std::uint32_t>(b);
        auto C = static_cast<std::uint32_t>(c);
        auto D = static_cast<std::uint32_t>(dd);
        if (!flip) {
            mesh.indices.insert(mesh.indices.end(), {A, B, C, A, C, D});
        } else {
            mesh.indices.insert(mesh.indices.end(), {A, C, B, A, D, C});
        }
    };

    // X-edges: node (i,j,k)->(i+1,j,k). Shared by cells differing in (j-1,k-1).
    for (int k = 1; k < d.z - 1; ++k)
    for (int j = 1; j < d.y - 1; ++j)
    for (int i = 0; i < d.x - 1; ++i) {
        float va = val(i, j, k), vb = val(i + 1, j, k);
        if ((va >= iso) == (vb >= iso)) continue;
        // 4 cells around the x-edge, varying y in {j-1,j}, z in {k-1,k}, x = i.
        std::int64_t v00 = cell_vert[cidx(i, j-1, k-1)];
        std::int64_t v10 = cell_vert[cidx(i, j  , k-1)];
        std::int64_t v11 = cell_vert[cidx(i, j  , k  )];
        std::int64_t v01 = cell_vert[cidx(i, j-1, k  )];
        emit_quad(v00, v10, v11, v01, /*flip=*/vb < iso);
    }
    // Y-edges: node (i,j,k)->(i,j+1,k). Shared by cells varying x,z.
    for (int k = 1; k < d.z - 1; ++k)
    for (int j = 0; j < d.y - 1; ++j)
    for (int i = 1; i < d.x - 1; ++i) {
        float va = val(i, j, k), vb = val(i, j + 1, k);
        if ((va >= iso) == (vb >= iso)) continue;
        std::int64_t v00 = cell_vert[cidx(i-1, j, k-1)];
        std::int64_t v10 = cell_vert[cidx(i  , j, k-1)];
        std::int64_t v11 = cell_vert[cidx(i  , j, k  )];
        std::int64_t v01 = cell_vert[cidx(i-1, j, k  )];
        emit_quad(v00, v10, v11, v01, /*flip=*/vb >= iso);
    }
    // Z-edges: node (i,j,k)->(i,j,k+1). Shared by cells varying x,y.
    for (int k = 0; k < d.z - 1; ++k)
    for (int j = 1; j < d.y - 1; ++j)
    for (int i = 1; i < d.x - 1; ++i) {
        float va = val(i, j, k), vb = val(i, j, k + 1);
        if ((va >= iso) == (vb >= iso)) continue;
        std::int64_t v00 = cell_vert[cidx(i-1, j-1, k)];
        std::int64_t v10 = cell_vert[cidx(i  , j-1, k)];
        std::int64_t v11 = cell_vert[cidx(i  , j  , k)];
        std::int64_t v01 = cell_vert[cidx(i-1, j  , k)];
        emit_quad(v00, v10, v11, v01, /*flip=*/vb < iso);
    }

    return mesh;
}

void write_obj(const Mesh& m, const std::string& path) {
    std::FILE* fp = std::fopen(path.c_str(), "w");
    if (!fp) return;
    for (const auto& p : m.positions)
        std::fprintf(fp, "v %.6f %.6f %.6f\n", p.x, p.y, p.z);
    for (const auto& n : m.normals)
        std::fprintf(fp, "vn %.6f %.6f %.6f\n", n.x, n.y, n.z);
    for (std::size_t t = 0; t + 2 < m.indices.size(); t += 3) {
        // OBJ is 1-based; emit v//vn triplets.
        unsigned a = m.indices[t] + 1, b = m.indices[t+1] + 1, c = m.indices[t+2] + 1;
        std::fprintf(fp, "f %u//%u %u//%u %u//%u\n", a, a, b, b, c, c);
    }
    std::fclose(fp);
}

}  // namespace voxel
