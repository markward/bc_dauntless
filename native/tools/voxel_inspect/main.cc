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
#include <limits>
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

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr,
            "usage: %s <X_vox.nif> [X.nif (hull, for AABB compare)]\n", argv[0]);
        return 2;
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

    const std::uint16_t s1 = vd->unknown_short1;
    const std::uint16_t s2 = vd->unknown_short2;
    const std::uint16_t s3 = vd->unknown_short3;

    std::printf("\n  NiBinaryVoxelData header:\n");
    std::printf("    short1 = %u\n", s1);
    std::printf("    short2 = %u\n", s2);
    std::printf("    short3 = %u\n", s3);
    std::printf("    7 floats:\n");
    for (int i = 0; i < 7; ++i)
        std::printf("      [%d] = % .6f\n", i, vd->unknown_7_floats[i]);

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
