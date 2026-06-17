// native/tools/voxel_inspect/main.cc
//
// Reverse-engineering inspector for BC's NiBinaryVoxelData blocks (the
// per-ship solid-voxel grid stored in *_vox.nif files). Dumps the parsed
// header (3 shorts + 7 floats), the raw payload size, hex of the payload
// head/tail, a byte-value histogram, and the candidate-dimension sanity
// arithmetic (nx*ny*nz, /8, vs payload length).
//
// Optionally takes a HULL nif as a second argument; if given, the tool
// computes the hull's body-frame AABB (by walking the NiNode tree and
// transforming NiTriShapeData vertices) and prints it next to the voxel
// block's 7 floats, so the bounds mapping can be deduced.
//
// Usage:
//   voxel_inspect <path/to/X_vox.nif> [path/to/X.nif]
//   voxel_inspect --dump-hull-obj <hull.nif> <out.obj>
//   voxel_inspect --anchor <X_vox.nif>
//   voxel_inspect --anchor-corpus <models_dir>
//
// GL-free: links only against `nif`, walks NiTriShapeData verts directly.

#include <nif/file.h>
#include <nif/block.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <exception>
#include <filesystem>
#include <fstream>
#include <limits>
#include <string>
#include <unordered_map>
#include <variant>
#include <vector>

namespace fs = std::filesystem;

namespace {

// ---- link resolution (block link IDs are raw pointer-ish IDs) ----------
std::unordered_map<std::uint32_t, std::size_t> build_link_map(const nif::File& f) {
    std::unordered_map<std::uint32_t, std::size_t> m;
    m.reserve(f.block_ids.size());
    for (std::size_t i = 0; i < f.block_ids.size(); ++i) m[f.block_ids[i]] = i;
    return m;
}

// ---- 4x4 from NiAVObject T,R,S (column-vector v' = M*v) ----------------
struct Mat4 {
    // row-major storage; element(r,c)
    std::array<float, 16> m{};
    float& at(int r, int c) { return m[r * 4 + c]; }
    float at(int r, int c) const { return m[r * 4 + c]; }
    static Mat4 identity() {
        Mat4 o;
        o.at(0, 0) = o.at(1, 1) = o.at(2, 2) = o.at(3, 3) = 1.0f;
        return o;
    }
};

Mat4 mul(const Mat4& a, const Mat4& b) {
    Mat4 o;
    for (int r = 0; r < 4; ++r)
        for (int c = 0; c < 4; ++c) {
            float s = 0;
            for (int k = 0; k < 4; ++k) s += a.at(r, k) * b.at(k, c);
            o.at(r, c) = s;
        }
    return o;
}

// Build T * R * S from the AV base. nif::Mat3x3 is row-major (m[0]=r0c0).
Mat4 av_to_mat4(const nif::AvObjectBase& av) {
    Mat4 o = Mat4::identity();
    const auto& R = av.rotation.m;  // row-major 3x3
    const float s = av.scale;
    // (T * R * S): upper-left 3x3 = R*s, translation column = T.
    o.at(0, 0) = R[0] * s; o.at(0, 1) = R[1] * s; o.at(0, 2) = R[2] * s;
    o.at(1, 0) = R[3] * s; o.at(1, 1) = R[4] * s; o.at(1, 2) = R[5] * s;
    o.at(2, 0) = R[6] * s; o.at(2, 1) = R[7] * s; o.at(2, 2) = R[8] * s;
    o.at(0, 3) = av.translation.x;
    o.at(1, 3) = av.translation.y;
    o.at(2, 3) = av.translation.z;
    return o;
}

struct Vec3 { float x, y, z; };
Vec3 transform_point(const Mat4& M, const nif::Vec3& p) {
    return Vec3{
        M.at(0, 0) * p.x + M.at(0, 1) * p.y + M.at(0, 2) * p.z + M.at(0, 3),
        M.at(1, 0) * p.x + M.at(1, 1) * p.y + M.at(1, 2) * p.z + M.at(1, 3),
        M.at(2, 0) * p.x + M.at(2, 1) * p.y + M.at(2, 2) * p.z + M.at(2, 3),
    };
}

struct Aabb {
    Vec3 lo{ std::numeric_limits<float>::max(),
             std::numeric_limits<float>::max(),
             std::numeric_limits<float>::max() };
    Vec3 hi{ -std::numeric_limits<float>::max(),
             -std::numeric_limits<float>::max(),
             -std::numeric_limits<float>::max() };
    bool valid = false;
    void add(const Vec3& p) {
        valid = true;
        lo.x = std::min(lo.x, p.x); lo.y = std::min(lo.y, p.y); lo.z = std::min(lo.z, p.z);
        hi.x = std::max(hi.x, p.x); hi.y = std::max(hi.y, p.y); hi.z = std::max(hi.z, p.z);
    }
};

void accumulate_aabb(const nif::File& f,
                     const std::unordered_map<std::uint32_t, std::size_t>& links,
                     std::size_t idx, const Mat4& parent,
                     std::vector<bool>& visited, Aabb& box) {
    if (idx >= f.blocks.size() || visited[idx]) return;
    visited[idx] = true;
    const auto& blk = f.blocks[idx];
    if (auto* n = std::get_if<nif::NiNode>(&blk)) {
        Mat4 world = mul(parent, av_to_mat4(n->av));
        for (auto link : n->child_links) {
            auto it = links.find(link);
            if (it != links.end()) accumulate_aabb(f, links, it->second, world, visited, box);
        }
    } else if (auto* sh = std::get_if<nif::NiTriShape>(&blk)) {
        Mat4 world = mul(parent, av_to_mat4(sh->av));
        auto it = links.find(sh->data_link);
        if (it != links.end()) {
            if (auto* d = std::get_if<nif::NiTriShapeData>(&f.blocks[it->second])) {
                for (const auto& v : d->vertices) box.add(transform_point(world, v));
            }
        }
    }
}

Aabb hull_aabb(const nif::File& f) {
    auto links = build_link_map(f);
    Aabb box;
    std::vector<bool> visited(f.blocks.size(), false);
    // Walk from each top-level node (root if present, else every node) so we
    // catch the whole scene even if the root handle isn't set.
    std::size_t start = 0;
    if (f.root.ptr) {
        for (std::size_t i = 0; i < f.blocks.size(); ++i)
            if (&f.blocks[i] == f.root.ptr) { start = i; break; }
        accumulate_aabb(f, links, start, Mat4::identity(), visited, box);
    } else {
        for (std::size_t i = 0; i < f.blocks.size(); ++i)
            accumulate_aabb(f, links, i, Mat4::identity(), visited, box);
    }
    return box;
}

// ---- hex / histogram helpers -------------------------------------------
void hex_dump(const std::uint8_t* p, std::size_t n, std::size_t base_offset) {
    for (std::size_t i = 0; i < n; i += 16) {
        std::printf("    %06zx  ", base_offset + i);
        for (std::size_t j = 0; j < 16; ++j) {
            if (i + j < n) std::printf("%02x ", p[i + j]);
            else std::printf("   ");
            if (j == 7) std::printf(" ");
        }
        std::printf(" |");
        for (std::size_t j = 0; j < 16 && i + j < n; ++j) {
            unsigned char c = p[i + j];
            std::printf("%c", (c >= 32 && c < 127) ? c : '.');
        }
        std::printf("|\n");
    }
}

void print_histogram(const std::vector<std::uint8_t>& payload) {
    std::array<std::uint64_t, 256> hist{};
    for (auto b : payload) hist[b]++;
    std::size_t distinct = 0;
    for (auto c : hist) if (c) distinct++;
    std::printf("  byte-value histogram (distinct values used: %zu/256)\n", distinct);
    // Top 16 most frequent values.
    std::vector<std::pair<int, std::uint64_t>> v;
    for (int i = 0; i < 256; ++i) v.push_back({ i, hist[i] });
    std::sort(v.begin(), v.end(),
              [](auto& a, auto& b) { return a.second > b.second; });
    std::printf("    top values:  ");
    for (int i = 0; i < 16 && v[i].second; ++i) {
        double pct = payload.empty() ? 0.0 : 100.0 * double(v[i].second) / payload.size();
        std::printf("0x%02x=%llu(%.1f%%) ", v[i].first,
                    (unsigned long long)v[i].second, pct);
    }
    std::printf("\n");
    // Explicit counts for 0x00 and 0xff (RLE / bitmask candidates).
    std::printf("    0x00=%llu  0xff=%llu  (payload bytes=%zu)\n",
                (unsigned long long)hist[0x00],
                (unsigned long long)hist[0xff], payload.size());
}

// ---- find the voxel blocks ---------------------------------------------
const nif::NiBinaryVoxelData* find_voxel(const nif::File& f) {
    for (const auto& b : f.blocks)
        if (auto* vd = std::get_if<nif::NiBinaryVoxelData>(&b)) return vd;
    return nullptr;
}
const nif::NiBinaryVoxelExtraData* find_voxel_extra(const nif::File& f) {
    for (const auto& b : f.blocks)
        if (auto* e = std::get_if<nif::NiBinaryVoxelExtraData>(&b)) return e;
    return nullptr;
}

// ---- little-endian readers over the raw payload -------------------------
inline std::uint32_t rd_u32(const std::vector<std::uint8_t>& p, std::size_t off) {
    return (std::uint32_t)p[off] | ((std::uint32_t)p[off + 1] << 8) |
           ((std::uint32_t)p[off + 2] << 16) | ((std::uint32_t)p[off + 3] << 24);
}
inline float rd_f32(const std::vector<std::uint8_t>& p, std::size_t off) {
    std::uint32_t u = rd_u32(p, off);
    float f;
    std::memcpy(&f, &u, 4);
    return f;
}

// ---- two-ended anchoring result ----------------------------------------
struct AnchorResult {
    bool ok = false;
    std::string failure;             // why, if !ok
    std::size_t N = 0;               // payload length
    // tail anchoring
    bool tail_ok = false;
    std::array<std::uint32_t, 5> trailer{};
    std::size_t B0 = 0;              // offset of numBytes2 field
    std::uint32_t numBytes2 = 0;
    // front anchoring
    std::size_t O = 0;              // offset of numVectors field
    std::uint32_t numVectors = 0;
    std::size_t L = 0;              // bitmask length == O
    // vector diagnostics
    double frac_unit = 0.0;         // fraction with sqrt(x^2+y^2+z^2)~1
    double frac_in_aabb = 0.0;      // fraction with (x,y,z) inside aabb
    double w_min = 0.0, w_max = 0.0;
    bool w_all_zero = false, w_all_one = false;
};

// Anchor the TAIL: locate numBytes2 by the both-ends closure on the tail.
// The uint32 at offset Q must satisfy Q + 4 + (u32@Q) == N - 20.
// Enumerate ALL such Q (descending: largest Q first => smallest numBytes2).
// A coincidental u32 can close near the top of the buffer, so a single
// greedy match is unreliable; we return every candidate and let the front
// anchor disambiguate (the both-ends joint closure is the real constraint).
std::vector<std::size_t> tail_candidates(const std::vector<std::uint8_t>& P,
                                         AnchorResult& res) {
    std::vector<std::size_t> out;
    const std::size_t N = P.size();
    if (N < 24) { res.failure = "payload < 24 bytes (no room for trailer)"; return out; }
    for (int i = 0; i < 5; ++i) res.trailer[i] = rd_u32(P, N - 20 + 4 * i);
    const std::size_t tail_start = N - 20;  // trailer begins here
    if (tail_start < 4) { res.failure = "payload too small for numBytes2 field"; return out; }
    for (std::size_t Q = tail_start - 4; ; --Q) {
        std::uint32_t m = rd_u32(P, Q);
        if ((std::uint64_t)Q + 4 + (std::uint64_t)m == (std::uint64_t)tail_start)
            out.push_back(Q);
        if (Q == 0) break;
    }
    if (out.empty()) res.failure = "no Q closes the tail (numBytes2 closure failed)";
    return out;
}

// Candidate front solution for a given B0.
struct FrontFit {
    bool ok = false;
    std::size_t O = 0;
    std::uint32_t numVectors = 0;
    double frac_unit = 0.0, frac_in_aabb = 0.0;
    double w_min = 0.0, w_max = 0.0;
    bool w_all_zero = false, w_all_one = false;
};

// Anchor numVectors from the front for a fixed B0: find the smallest O with
// closure O + 4 + 16*n == B0 AND all-finite, plausible Vector4s. Returns the
// first such O (the bitmask is at the front, so the smallest closing O that
// passes plausibility is the true vector-run start).
FrontFit anchor_front(const std::vector<std::uint8_t>& P, const nif::NiBinaryVoxelData* vd,
                      std::size_t B0) {
    FrontFit fit;
    const float amin[3] = { vd->aabb_min[0], vd->aabb_min[1], vd->aabb_min[2] };
    const float amax[3] = { vd->aabb_max[0], vd->aabb_max[1], vd->aabb_max[2] };
    const float pad = 1.0f;  // grid encloses hull; small slop on the in-aabb test
    if (B0 < 4) return fit;
    for (std::size_t O = 0; O + 4 <= B0; ++O) {
        std::uint32_t n = rd_u32(P, O);
        if ((std::uint64_t)O + 4 + 16ull * n != (std::uint64_t)B0) continue;
        if (n == 0) continue;  // empty run: not a real vector section
        std::size_t base = O + 4;
        bool all_finite = true;
        std::size_t unit = 0, in_aabb = 0;
        double wmin = std::numeric_limits<double>::max();
        double wmax = -std::numeric_limits<double>::max();
        bool w_all_zero = true, w_all_one = true;
        for (std::uint32_t i = 0; i < n; ++i) {
            std::size_t o = base + 16ull * i;
            float x = rd_f32(P, o), y = rd_f32(P, o + 4), z = rd_f32(P, o + 8), w = rd_f32(P, o + 12);
            if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z) || !std::isfinite(w)) {
                all_finite = false; break;
            }
            if (std::fabs(x) > 1e6f || std::fabs(y) > 1e6f || std::fabs(z) > 1e6f) {
                all_finite = false; break;
            }
            double mag = std::sqrt((double)x * x + (double)y * y + (double)z * z);
            if (std::fabs(mag - 1.0) < 1e-2) unit++;
            if (x >= amin[0] - pad && x <= amax[0] + pad &&
                y >= amin[1] - pad && y <= amax[1] + pad &&
                z >= amin[2] - pad && z <= amax[2] + pad) in_aabb++;
            wmin = std::min(wmin, (double)w);
            wmax = std::max(wmax, (double)w);
            if (std::fabs(w) > 1e-6) w_all_zero = false;
            if (std::fabs(w - 1.0) > 1e-6) w_all_one = false;
        }
        if (!all_finite) continue;
        double fu = double(unit) / n;
        double fa = double(in_aabb) / n;
        // Require the (x,y,z) triples to be predominantly UNIT vectors. The
        // in-aabb test is confounded (unit vectors trivially sit inside a
        // large grid AABB), so unit-magnitude is the discriminating signal.
        if (fu < 0.20) continue;
        fit.ok = true;
        fit.O = O;
        fit.numVectors = n;
        fit.frac_unit = fu;
        fit.frac_in_aabb = fa;
        fit.w_min = wmin;
        fit.w_max = wmax;
        fit.w_all_zero = w_all_zero;
        fit.w_all_one = w_all_one;
        return fit;
    }
    return fit;
}

AnchorResult run_anchor(const nif::NiBinaryVoxelData* vd) {
    AnchorResult res;
    const auto& P = vd->raw_voxel_payload;
    res.N = P.size();
    auto cands = tail_candidates(P, res);
    if (cands.empty()) return res;  // res.failure set
    res.tail_ok = true;
    // Try each tail candidate (largest Q / smallest numBytes2 first). Accept
    // the first one whose front anchor closes with high-confidence unit
    // normals — the joint both-ends closure uniquely fixes (L, B0).
    FrontFit best;
    std::size_t best_B0 = 0;
    for (std::size_t Q : cands) {
        FrontFit fit = anchor_front(P, vd, Q);
        if (fit.ok) {
            // Prefer the fit with the highest unit-normal fraction; a true
            // section is essentially all unit normals (frac ~ 1.0).
            if (!best.ok || fit.frac_unit > best.frac_unit) { best = fit; best_B0 = Q; }
            // A ~1.0 unit fraction is unambiguous; stop early.
            if (fit.frac_unit > 0.95) break;
        }
    }
    // Record the chosen tail boundary for reporting.
    res.B0 = best.ok ? best_B0 : cands.front();
    res.numBytes2 = rd_u32(P, res.B0);
    if (!best.ok) {
        res.failure = "tail closes but no front anchor passes (vector-run plausibility failed for all tail candidates)";
        return res;
    }
    res.O = best.O;
    res.L = best.O;
    res.numVectors = best.numVectors;
    res.frac_unit = best.frac_unit;
    res.frac_in_aabb = best.frac_in_aabb;
    res.w_min = best.w_min;
    res.w_max = best.w_max;
    res.w_all_zero = best.w_all_zero;
    res.w_all_one = best.w_all_one;
    res.ok = true;
    return res;
}

// ---- OBJ hull-mesh export -----------------------------------------------
// Walks the same NiNode tree as accumulate_aabb using the same world
// transform (T*R*S accumulated top-down, column-vector v_world = M * v_body).
// For each NiTriShapeData encountered the transformed vertices are written
// as OBJ "v x y z" lines and the triangles as 1-based global "f a b c" lines.
// vbase tracks the running global vertex offset so faces are always globally
// indexed as required by the OBJ spec.

struct ObjStats {
    std::size_t total_verts = 0;
    std::size_t total_tris  = 0;
    Aabb        vert_aabb;   // recomputed from emitted verts for verification
};

void accumulate_obj(const nif::File& f,
                    const std::unordered_map<std::uint32_t, std::size_t>& links,
                    std::size_t idx, const Mat4& parent,
                    std::vector<bool>& visited,
                    std::ofstream& out,
                    std::size_t& vbase,
                    ObjStats& stats) {
    if (idx >= f.blocks.size() || visited[idx]) return;
    visited[idx] = true;
    const auto& blk = f.blocks[idx];
    if (auto* n = std::get_if<nif::NiNode>(&blk)) {
        Mat4 world = mul(parent, av_to_mat4(n->av));
        for (auto link : n->child_links) {
            auto it = links.find(link);
            if (it != links.end())
                accumulate_obj(f, links, it->second, world, visited, out, vbase, stats);
        }
    } else if (auto* sh = std::get_if<nif::NiTriShape>(&blk)) {
        Mat4 world = mul(parent, av_to_mat4(sh->av));
        auto it = links.find(sh->data_link);
        if (it == links.end()) return;
        const auto* d = std::get_if<nif::NiTriShapeData>(&f.blocks[it->second]);
        if (!d) return;

        // Emit transformed vertices.
        for (const auto& v : d->vertices) {
            Vec3 w = transform_point(world, v);
            out << "v " << w.x << ' ' << w.y << ' ' << w.z << '\n';
            stats.vert_aabb.add(w);
        }
        // Emit 1-based global faces.
        for (const auto& tri : d->triangles) {
            out << "f "
                << (vbase + tri[0] + 1) << ' '
                << (vbase + tri[1] + 1) << ' '
                << (vbase + tri[2] + 1) << '\n';
        }
        stats.total_verts += d->vertices.size();
        stats.total_tris  += d->triangles.size();
        vbase += d->vertices.size();
    }
}

// Returns 0 on success, 1 on error.
int dump_hull_obj(const fs::path& hull_path, const fs::path& obj_path) {
    nif::File hf;
    try { hf = nif::load(hull_path); }
    catch (const std::exception& e) {
        std::fprintf(stderr, "hull load failed: %s\n", e.what());
        return 1;
    }

    std::ofstream out(obj_path);
    if (!out) {
        std::fprintf(stderr, "cannot open output: %s\n", obj_path.string().c_str());
        return 1;
    }

    // Write header comment; placeholders replaced after walk.
    // (We write counts in a second pass by reopening; just flush counts to
    // stdout after the walk — the OBJ spec doesn't require them in the file.)
    out << "# voxel_inspect --dump-hull-obj\n";
    out << "# source: " << hull_path.string() << '\n';
    out << "# transform: column-vector v_world = (T*R*S)_accumulated * v_body\n";

    auto link_map = build_link_map(hf);
    ObjStats stats;
    std::vector<bool> visited(hf.blocks.size(), false);
    std::size_t vbase = 0;

    if (hf.root.ptr) {
        std::size_t start = 0;
        for (std::size_t i = 0; i < hf.blocks.size(); ++i)
            if (&hf.blocks[i] == hf.root.ptr) { start = i; break; }
        accumulate_obj(hf, link_map, start, Mat4::identity(), visited, out, vbase, stats);
    } else {
        for (std::size_t i = 0; i < hf.blocks.size(); ++i)
            accumulate_obj(hf, link_map, i, Mat4::identity(), visited, out, vbase, stats);
    }

    out.flush();
    out.close();

    // Rewrite the file prepending a stats comment. Re-open and prepend isn't
    // trivial in C++; instead write a brief summary to stdout so the caller
    // can capture it in headers.txt.
    std::printf("OBJ: %s\n", obj_path.string().c_str());
    std::printf("  source: %s\n", hull_path.string().c_str());
    std::printf("  verts=%zu  tris=%zu\n", stats.total_verts, stats.total_tris);
    if (stats.vert_aabb.valid) {
        std::printf("  vert_aabb min=(%.4f, %.4f, %.4f)\n",
                    stats.vert_aabb.lo.x, stats.vert_aabb.lo.y, stats.vert_aabb.lo.z);
        std::printf("  vert_aabb max=(%.4f, %.4f, %.4f)\n",
                    stats.vert_aabb.hi.x, stats.vert_aabb.hi.y, stats.vert_aabb.hi.z);
    }
    return 0;
}

}  // namespace

// Run the two-ended anchoring and print a per-file report. Returns the
// AnchorResult so a batch caller can tabulate.
AnchorResult anchor_report(const nif::File& f, const fs::path& vox_path, bool verbose) {
    AnchorResult res;
    const auto* vd = find_voxel(f);
    if (!vd) {
        if (verbose) std::printf("  no NiBinaryVoxelData block found!\n");
        res.failure = "no voxel block";
        return res;
    }
    res = run_anchor(vd);
    const std::uint64_t nx = vd->dim_x, ny = vd->dim_y,
                        nz = vd->dim_z;
    const std::uint64_t cells = nx * ny * nz;
    const std::uint64_t cells8 = (cells + 7) / 8;
    const float cellsize = vd->cell_size;

    if (!verbose) return res;

    std::printf("=========================================================\n");
    std::printf("ANCHOR: %s\n", vox_path.filename().string().c_str());
    std::printf("  dims=(%llu,%llu,%llu) cellsize=%.3f  N(payload)=%zu\n",
                (unsigned long long)nx, (unsigned long long)ny,
                (unsigned long long)nz, cellsize, res.N);
    if (res.tail_ok) {
        std::printf("  TAIL: B0(numBytes2 field)=%zu  numBytes2=%u  bytes2=[%zu,%zu)\n",
                    res.B0, res.numBytes2, res.B0 + 4, res.N - 20);
        std::printf("        trailer u32[5] = %u %u %u %u %u  (0x%08x 0x%08x 0x%08x 0x%08x 0x%08x)\n",
                    res.trailer[0], res.trailer[1], res.trailer[2], res.trailer[3], res.trailer[4],
                    res.trailer[0], res.trailer[1], res.trailer[2], res.trailer[3], res.trailer[4]);
    } else {
        std::printf("  TAIL: FAILED (%s)\n", res.failure.c_str());
        return res;
    }
    if (res.ok) {
        std::printf("  FRONT: O(numVectors field)=%zu  numVectors=%u  vectors=[%zu,%zu)\n",
                    res.O, res.numVectors, res.O + 4, res.B0);
        std::printf("         closure: O+4+16*n = %llu  == B0 = %zu  %s\n",
                    (unsigned long long)(res.O + 4 + 16ull * res.numVectors), res.B0,
                    (res.O + 4 + 16ull * res.numVectors == res.B0) ? "EXACT" : "MISMATCH");
        std::printf("  L (bitmask length) = %zu\n", res.L);
        std::printf("  vectors: frac_unit_mag=%.3f  frac_in_aabb=%.3f  w in [%.4f,%.4f] %s\n",
                    res.frac_unit, res.frac_in_aabb, res.w_min, res.w_max,
                    res.w_all_zero ? "(w==0 all)" : res.w_all_one ? "(w==1 all)" : "");
    } else {
        std::printf("  FRONT: FAILED (%s)\n", res.failure.c_str());
    }
    std::printf("  resolution sanity: nx*ny*nz=%llu  ceil(/8)=%llu  L=%zu",
                (unsigned long long)cells, (unsigned long long)cells8, res.L);
    if (res.ok && cells8) std::printf("  L/ceil(cells/8)=%.3f", double(res.L) / cells8);
    std::printf("\n");
    return res;
}

int run_anchor_corpus(const fs::path& root) {
    std::vector<fs::path> files;
    for (auto& e : fs::recursive_directory_iterator(root)) {
        if (!e.is_regular_file()) continue;
        auto name = e.path().filename().string();
        std::string lower = name;
        std::transform(lower.begin(), lower.end(), lower.begin(),
                       [](unsigned char c) { return (char)std::tolower(c); });
        if (lower.size() > 8 &&
            lower.compare(lower.size() - 8, 8, "_vox.nif") == 0)
            files.push_back(e.path());
    }
    std::sort(files.begin(), files.end());
    std::printf("CORPUS ANCHOR: %zu *_vox.nif files under %s\n\n",
                files.size(), root.string().c_str());
    std::printf("%-28s %-14s %8s %6s %8s %8s %8s %7s %7s\n",
                "file", "dims", "cell", "N", "L", "nVec", "nB2", "fUnit", "fAabb");
    std::size_t n_closed = 0, n_tail_only = 0, n_fail = 0;
    struct Row { std::uint64_t cells, cells8, L; bool ok; };
    std::vector<Row> rows;
    for (auto& p : files) {
        nif::File f;
        try { f = nif::load(p); }
        catch (const std::exception& e) {
            std::printf("%-28s LOAD FAILED: %s\n", p.filename().string().c_str(), e.what());
            n_fail++; continue;
        }
        const auto* vd = find_voxel(f);
        if (!vd) { std::printf("%-28s (no voxel block)\n", p.filename().string().c_str()); n_fail++; continue; }
        AnchorResult res = run_anchor(vd);
        const std::uint64_t nx = vd->dim_x, ny = vd->dim_y, nz = vd->dim_z;
        char dims[32];
        std::snprintf(dims, sizeof dims, "%llux%llux%llu",
                      (unsigned long long)nx, (unsigned long long)ny, (unsigned long long)nz);
        std::printf("%-28s %-14s %8.2f %6zu ",
                    p.filename().string().c_str(), dims, vd->cell_size, res.N);
        if (res.ok) {
            std::printf("%8zu %8u %8u %7.3f %7.3f\n",
                        res.L, res.numVectors, res.numBytes2, res.frac_unit, res.frac_in_aabb);
            n_closed++;
            std::uint64_t cells = nx * ny * nz;
            rows.push_back({ cells, (cells + 7) / 8, res.L, true });
        } else if (res.tail_ok) {
            std::printf("%8s %8s %8u  TAIL-ONLY: %s\n", "-", "-", res.numBytes2, res.failure.c_str());
            n_tail_only++;
        } else {
            std::printf("%8s %8s %8s  FAIL: %s\n", "-", "-", "-", res.failure.c_str());
            n_fail++;
        }
    }
    std::printf("\nSUMMARY: %zu closed (front+tail), %zu tail-only, %zu failed, of %zu total\n",
                n_closed, n_tail_only, n_fail, files.size());
    // L vs resolution relationship probe
    std::printf("\nL vs resolution probe (closed files only):\n");
    std::printf("  %12s %12s %12s %10s\n", "nx*ny*nz", "ceil(/8)", "L", "L/ceil8");
    for (auto& r : rows)
        std::printf("  %12llu %12llu %12llu %10.4f\n",
                    (unsigned long long)r.cells, (unsigned long long)r.cells8,
                    (unsigned long long)r.L, r.cells8 ? double(r.L) / r.cells8 : 0.0);
    return 0;
}

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr,
            "usage: %s <X_vox.nif> [X.nif (hull, for AABB compare)]\n"
            "       %s --dump-hull-obj <hull.nif> <out.obj>  # export body-frame hull mesh\n"
            "       %s --anchor <X_vox.nif>                  # two-ended payload anchoring\n"
            "       %s --anchor-corpus <models_dir>          # anchor every *_vox.nif\n",
            argv[0], argv[0], argv[0], argv[0]);
        return 2;
    }

    // --dump-hull-obj mode
    if (std::strcmp(argv[1], "--dump-hull-obj") == 0) {
        if (argc < 4) {
            std::fprintf(stderr, "--dump-hull-obj needs <hull.nif> <out.obj>\n");
            return 2;
        }
        return dump_hull_obj(fs::path(argv[2]), fs::path(argv[3]));
    }

    // --anchor / --anchor-corpus modes
    if (std::strcmp(argv[1], "--anchor") == 0) {
        if (argc < 3) { std::fprintf(stderr, "--anchor needs a vox file\n"); return 2; }
        fs::path p = argv[2];
        nif::File f;
        try { f = nif::load(p); }
        catch (const std::exception& e) { std::fprintf(stderr, "load failed: %s\n", e.what()); return 1; }
        AnchorResult res = anchor_report(f, p, /*verbose=*/true);
        return res.ok ? 0 : 1;
    }
    if (std::strcmp(argv[1], "--anchor-corpus") == 0) {
        if (argc < 3) { std::fprintf(stderr, "--anchor-corpus needs a directory\n"); return 2; }
        return run_anchor_corpus(argv[2]);
    }

    fs::path vox_path = argv[1];

    nif::File f;
    try {
        f = nif::load(vox_path);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "load failed: %s\n", e.what());
        return 1;
    }

    std::printf("=========================================================\n");
    std::printf("FILE: %s\n", vox_path.string().c_str());
    std::printf("  file size on disk: %ju bytes\n",
                (std::uintmax_t)fs::file_size(vox_path));
    std::printf("  blocks parsed: %zu   eof_reached=%d  stopped_at='%s'\n",
                f.blocks.size(), (int)f.eof_reached,
                f.stopped_at_block_type.c_str());

    const auto* extra = find_voxel_extra(f);
    if (extra) {
        std::printf("\n  NiBinaryVoxelExtraData:\n");
        std::printf("    next_extra_data_link = 0x%08x\n", extra->next_extra_data_link);
        std::printf("    unknown_int          = %u (0x%08x)\n",
                    extra->unknown_int, extra->unknown_int);
        std::printf("    data_link            = 0x%08x\n", extra->data_link);
    } else {
        std::printf("\n  (no NiBinaryVoxelExtraData found)\n");
    }

    const auto* vd = find_voxel(f);
    if (!vd) {
        std::fprintf(stderr, "  no NiBinaryVoxelData block found!\n");
        return 1;
    }

    const std::uint16_t s1 = vd->dim_x;
    const std::uint16_t s2 = vd->dim_y;
    const std::uint16_t s3 = vd->dim_z;

    std::printf("\n  NiBinaryVoxelData header (34 bytes confirmed):\n");
    std::printf("    dim_x     = %u\n", s1);
    std::printf("    dim_y     = %u\n", s2);
    std::printf("    dim_z     = %u\n", s3);
    std::printf("    cell_size = % .6f\n", vd->cell_size);
    std::printf("    aabb_min  = [ % .6f, % .6f, % .6f ]\n",
                vd->aabb_min[0], vd->aabb_min[1], vd->aabb_min[2]);
    std::printf("    aabb_max  = [ % .6f, % .6f, % .6f ]\n",
                vd->aabb_max[0], vd->aabb_max[1], vd->aabb_max[2]);

    const auto& payload = vd->raw_voxel_payload;
    std::printf("\n  raw_voxel_payload.size() = %zu bytes\n", payload.size());

    // ---- sanity arithmetic for candidate dims (s1,s2,s3) ----
    const std::uint64_t nx = s1, ny = s2, nz = s3;
    const std::uint64_t cells = nx * ny * nz;
    const std::uint64_t bytes_bitpacked = (cells + 7) / 8;
    std::printf("\n  candidate dims (nx,ny,nz) = (%llu,%llu,%llu)\n",
                (unsigned long long)nx, (unsigned long long)ny,
                (unsigned long long)nz);
    std::printf("    nx*ny*nz                  = %llu cells\n",
                (unsigned long long)cells);
    std::printf("    cells (1 byte/cell)       = %llu bytes  ratio payload/that = %.4f\n",
                (unsigned long long)cells,
                cells ? double(payload.size()) / double(cells) : 0.0);
    std::printf("    ceil(cells/8) bit-packed  = %llu bytes  ratio payload/that = %.4f\n",
                (unsigned long long)bytes_bitpacked,
                bytes_bitpacked ? double(payload.size()) / double(bytes_bitpacked) : 0.0);
    // per-plane row padding to multiple of bytes? compute padded variants.
    auto pad8 = [](std::uint64_t bits) { return (bits + 7) / 8; };
    std::uint64_t row_padded = pad8(nx) * ny * nz;     // pad each row (x) to byte
    std::uint64_t plane_padded = pad8(nx * ny) * nz;   // pad each plane to byte
    std::printf("    row-byte-padded (pad x)   = %llu bytes  ratio = %.4f\n",
                (unsigned long long)row_padded,
                row_padded ? double(payload.size()) / double(row_padded) : 0.0);
    std::printf("    plane-byte-padded         = %llu bytes  ratio = %.4f\n",
                (unsigned long long)plane_padded,
                plane_padded ? double(payload.size()) / double(plane_padded) : 0.0);

    // ---- hex head/tail ----
    std::printf("\n  payload head (first 96 bytes):\n");
    hex_dump(payload.data(), std::min<std::size_t>(96, payload.size()), 0);
    std::printf("  payload tail (last 64 bytes):\n");
    if (payload.size() > 64)
        hex_dump(payload.data() + payload.size() - 64, 64, payload.size() - 64);
    else
        hex_dump(payload.data(), payload.size(), 0);

    std::printf("\n");
    print_histogram(payload);

    // ---- optional hull AABB compare ----
    if (argc >= 3) {
        fs::path hull_path = argv[2];
        try {
            nif::File hf = nif::load(hull_path);
            Aabb box = hull_aabb(hf);
            std::printf("\n  HULL AABB from %s\n", hull_path.string().c_str());
            if (box.valid) {
                std::printf("    min = (% .4f, % .4f, % .4f)\n", box.lo.x, box.lo.y, box.lo.z);
                std::printf("    max = (% .4f, % .4f, % .4f)\n", box.hi.x, box.hi.y, box.hi.z);
                std::printf("    size= (% .4f, % .4f, % .4f)\n",
                            box.hi.x - box.lo.x, box.hi.y - box.lo.y, box.hi.z - box.lo.z);
                std::printf("    center=(% .4f, % .4f, % .4f)\n",
                            0.5f * (box.lo.x + box.hi.x),
                            0.5f * (box.lo.y + box.hi.y),
                            0.5f * (box.lo.z + box.hi.z));
                // If floats encode origin+cellsize, derive what cellsize would
                // need to be to span this AABB over (nx,ny,nz):
                if (nx && ny && nz) {
                    std::printf("    implied cellsize if grid spans AABB: (% .5f, % .5f, % .5f)\n",
                                (box.hi.x - box.lo.x) / nx,
                                (box.hi.y - box.lo.y) / ny,
                                (box.hi.z - box.lo.z) / nz);
                }
            } else {
                std::printf("    (no vertices found)\n");
            }
        } catch (const std::exception& e) {
            std::printf("\n  hull load failed: %s\n", e.what());
        }
    }

    std::printf("\n");
    return 0;
}
