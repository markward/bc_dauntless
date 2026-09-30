// native/src/voxel/src/dvox.cc
#include <voxel/dvox.h>

#include <assets/gltf.h>

#include <cstring>
#include <fstream>
#include <system_error>
#include <vector>

namespace voxel {

namespace {

constexpr char kMagic[4] = {'D', 'V', 'X', '1'};
constexpr std::uint16_t kVersion = 1;
// A hull occupancy grid is small (a rock catalogue mesh, not a full fleet).
// A header claiming more than this is corrupt, not ambitious -- mirrors
// dhv.cc's kMaxCells reasoning.
constexpr std::uint64_t kMaxCells = 64ull * 1024 * 1024;

template <typename T>
void put(std::ostream& s, const T& v) {
    s.write(reinterpret_cast<const char*>(&v), sizeof(T));
}
template <typename T>
bool get(std::istream& s, T& v) {
    s.read(reinterpret_cast<char*>(&v), sizeof(T));
    return static_cast<bool>(s);
}

}  // namespace

bool write_dvox(const std::filesystem::path& p, const VoxelVolume& v) {
    if (v.dims.x <= 0 || v.dims.y <= 0 || v.dims.z <= 0) return false;
    const std::int64_t n = static_cast<std::int64_t>(v.dims.x) *
                            static_cast<std::int64_t>(v.dims.y) *
                            static_cast<std::int64_t>(v.dims.z);
    if (static_cast<std::int64_t>(v.occ.size()) != n) return false;

    std::error_code ec;
    if (p.has_parent_path()) std::filesystem::create_directories(p.parent_path(), ec);

    const std::filesystem::path tmp = p.string() + ".tmp";
    bool write_ok = false;
    {
        std::ofstream s(tmp, std::ios::binary | std::ios::trunc);
        if (!s) return false;

        s.write(kMagic, 4);
        put(s, kVersion);
        put(s, v.dims.x); put(s, v.dims.y); put(s, v.dims.z);
        put(s, v.origin.x); put(s, v.origin.y); put(s, v.origin.z);
        put(s, v.cell.x); put(s, v.cell.y); put(s, v.cell.z);

        const std::size_t nbytes = static_cast<std::size_t>((n + 7) / 8);
        std::vector<std::uint8_t> bits(nbytes, 0);
        for (std::int64_t i = 0; i < n; ++i)
            if (v.occ[static_cast<std::size_t>(i)] != 0)
                bits[static_cast<std::size_t>(i >> 3)] |=
                    static_cast<std::uint8_t>(1u << (i & 7));
        s.write(reinterpret_cast<const char*>(bits.data()),
                static_cast<std::streamsize>(bits.size()));

        // Explicitly close and check BEFORE deciding write_ok -- see dhv.cc's
        // identical reasoning: our whole payload may fit inside the filebuf's
        // internal buffer, so a late failure (e.g. ENOSPC) can only surface here.
        s.close();
        write_ok = !s.fail();
    }
    if (!write_ok) {
        std::error_code rm_ec;
        std::filesystem::remove(tmp, rm_ec);
        return false;
    }
    std::filesystem::rename(tmp, p, ec);
    if (ec) { std::filesystem::remove(tmp, ec); return false; }
    return true;
}

bool read_dvox(const std::filesystem::path& p, VoxelVolume& out) {
    std::ifstream s(p, std::ios::binary);
    if (!s) return false;

    char magic[4] = {};
    s.read(magic, 4);
    if (!s || std::memcmp(magic, kMagic, 4) != 0) return false;

    std::uint16_t version = 0;
    if (!get(s, version) || version != kVersion) return false;

    VoxelVolume v;
    if (!get(s, v.dims.x) || !get(s, v.dims.y) || !get(s, v.dims.z)) return false;
    if (v.dims.x <= 0 || v.dims.y <= 0 || v.dims.z <= 0) return false;
    if (!get(s, v.origin.x) || !get(s, v.origin.y) || !get(s, v.origin.z)) return false;
    if (!get(s, v.cell.x) || !get(s, v.cell.y) || !get(s, v.cell.z)) return false;

    // Multiply and bounds-check in two steps (mirrors dhv.cc): each dim is
    // untrusted i32, so the full triple product could overflow uint64 and
    // wrap back under kMaxCells before a single check at the end would catch it.
    std::uint64_t cells = static_cast<std::uint64_t>(v.dims.x) *
                          static_cast<std::uint64_t>(v.dims.y);
    if (cells > kMaxCells) return false;
    cells *= static_cast<std::uint64_t>(v.dims.z);
    if (cells > kMaxCells) return false;

    const std::size_t nbytes = static_cast<std::size_t>((cells + 7) / 8);
    std::vector<std::uint8_t> bits(nbytes);
    s.read(reinterpret_cast<char*>(bits.data()), static_cast<std::streamsize>(nbytes));
    // gcount, not the stream state: a payload shorter than the header claims
    // is the crash-mid-write case and must be rejected rather than padded.
    if (static_cast<std::uint64_t>(s.gcount()) != nbytes) return false;

    v.occ.assign(static_cast<std::size_t>(cells), 0);
    for (std::uint64_t i = 0; i < cells; ++i)
        if (bits[static_cast<std::size_t>(i >> 3)] & (1u << (i & 7)))
            v.occ[static_cast<std::size_t>(i)] = 1;

    out = std::move(v);
    return true;
}

VoxelVolume remap_gltf_volume_to_bc(const VoxelVolume& g, float scale) {
    const float k = assets::gltf::kMetresToModelUnits * scale;

    VoxelVolume out;
    out.dims = glm::ivec3(g.dims.x, g.dims.z, g.dims.y);
    out.cell = glm::vec3(g.cell.x, g.cell.z, g.cell.y) * k;
    out.origin = glm::vec3(-(g.origin.x + g.dims.x * g.cell.x), g.origin.z, g.origin.y) * k;
    out.occ.assign(static_cast<std::size_t>(out.dims.x) *
                       static_cast<std::size_t>(out.dims.y) *
                       static_cast<std::size_t>(out.dims.z),
                   0);

    for (int z = 0; z < g.dims.z; ++z)
    for (int y = 0; y < g.dims.y; ++y)
    for (int x = 0; x < g.dims.x; ++x)
        if (g.solid(x, y, z))
            out.set(g.dims.x - 1 - x, z, y, true);

    return out;
}

}  // namespace voxel
