// native/src/voxel/src/structure_parts_io.cc -- see structure_parts_io.h.
#include <voxel/structure_parts_io.h>

#include <algorithm>
#include <atomic>
#include <bit>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <mutex>
#include <set>
#include <string>
#include <system_error>

#include <assets/file_bytes.h>

#if defined(_WIN32)
#include <process.h>
#else
#include <unistd.h>
#endif

namespace voxel {

namespace {

constexpr char kMagic[4] = {'S', 'P', 'S', '1'};
// A structure grid is ~128 cells on the long side (~370k cells). A header
// claiming more than this is corrupt, not ambitious (mirrors dvox.cc).
constexpr std::uint64_t kMaxCells = 64ull * 1024 * 1024;
constexpr std::int16_t kEmpty = -1;        // occ 0
constexpr std::int16_t kSolidNoPart = -2;  // occ 1, label -1

std::uint64_t fnv1a64(const char* p, std::size_t n) {
    std::uint64_t h = 14695981039346656037ull;
    for (std::size_t i = 0; i < n; ++i) {
        h ^= static_cast<unsigned char>(p[i]);
        h *= 1099511628211ull;
    }
    return h;
}

// ---- little-endian writer ------------------------------------------------
void put_u16(std::string& b, std::uint16_t v) {
    b.push_back(static_cast<char>(v & 0xff));
    b.push_back(static_cast<char>((v >> 8) & 0xff));
}
void put_u32(std::string& b, std::uint32_t v) {
    for (int i = 0; i < 4; ++i) b.push_back(static_cast<char>((v >> (8 * i)) & 0xff));
}
void put_u64(std::string& b, std::uint64_t v) {
    for (int i = 0; i < 8; ++i) b.push_back(static_cast<char>((v >> (8 * i)) & 0xff));
}
void put_i32(std::string& b, std::int32_t v) { put_u32(b, static_cast<std::uint32_t>(v)); }
void put_f32(std::string& b, float v) { put_u32(b, std::bit_cast<std::uint32_t>(v)); }
void put_vec3(std::string& b, const glm::vec3& v) {
    put_f32(b, v.x); put_f32(b, v.y); put_f32(b, v.z);
}

// ---- bounds-checked little-endian reader ---------------------------------
struct Reader {
    const std::string& b;
    std::size_t at = 0;
    std::size_t end;   // payload end (the checksum is not read through this)

    bool take(std::size_t n) {
        if (end - at < n) return false;
        at += n;
        return true;
    }
    bool u16(std::uint16_t& v) {
        if (!take(2)) return false;
        v = static_cast<std::uint16_t>(static_cast<unsigned char>(b[at - 2]) |
                                       (static_cast<unsigned char>(b[at - 1]) << 8));
        return true;
    }
    bool u32(std::uint32_t& v) {
        if (!take(4)) return false;
        v = 0;
        for (int i = 0; i < 4; ++i)
            v |= static_cast<std::uint32_t>(static_cast<unsigned char>(b[at - 4 + i])) << (8 * i);
        return true;
    }
    bool i32(std::int32_t& v) {
        std::uint32_t u = 0;
        if (!u32(u)) return false;
        v = static_cast<std::int32_t>(u);
        return true;
    }
    bool f32(float& v) {
        std::uint32_t u = 0;
        if (!u32(u)) return false;
        v = std::bit_cast<float>(u);
        return true;
    }
    bool vec3(glm::vec3& v) { return f32(v.x) && f32(v.y) && f32(v.z); }
};

std::uint64_t read_u64_le(const std::string& b, std::size_t at) {
    std::uint64_t v = 0;
    for (int i = 0; i < 8; ++i)
        v |= static_cast<std::uint64_t>(static_cast<unsigned char>(b[at + i])) << (8 * i);
    return v;
}

// Once per path per process, in the engine's own words (engine/paths.py
// report_write_failure prints the same line for Python-side writes; there is
// no native twin to share, so this is it).
void report_write_failure(const std::filesystem::path& path, const std::string& why) {
    static std::mutex mu;
    static std::set<std::string> reported;
    const std::string key = path.string();
    {
        std::lock_guard<std::mutex> lock(mu);
        if (!reported.insert(key).second) return;
    }
    std::fprintf(stderr, "[dauntless] could not write %s: %s\n", key.c_str(), why.c_str());
}

// A temp-file suffix no other writer holds: this process's id and a
// process-wide counter. Two writers of one path (same-bytes NIF copies hash to
// one cache file; two hull loads can race) each write their own temp file and
// rename it over the target -- the last rename wins with a whole file. A
// shared `<path>.tmp` made one of them fail its rename with a spurious "could
// not write", which also burned the once-per-path report.
std::string unique_tmp_suffix() {
    static std::atomic<std::uint64_t> counter{0};
#if defined(_WIN32)
    const long long pid = static_cast<long long>(_getpid());
#else
    const long long pid = static_cast<long long>(getpid());
#endif
    return "." + std::to_string(pid) + "-" + std::to_string(counter.fetch_add(1)) + ".tmp";
}

std::string encode(const StructureSegmentation& seg) {
    std::string b;
    b.append(kMagic, 4);
    put_u32(b, kStructurePartsVersion);
    put_i32(b, seg.vol.dims.x); put_i32(b, seg.vol.dims.y); put_i32(b, seg.vol.dims.z);
    put_vec3(b, seg.vol.origin);
    put_vec3(b, seg.vol.cell);
    const std::size_t n = seg.vol.occ.size();
    put_u32(b, static_cast<std::uint32_t>(n));
    auto code = [&](std::size_t i) -> std::int16_t {
        if (seg.vol.occ[i] == 0) return kEmpty;
        return seg.label[i] >= 0 ? seg.label[i] : kSolidNoPart;
    };
    for (std::size_t i = 0; i < n;) {
        const std::int16_t v = code(i);
        std::size_t j = i + 1;
        while (j < n && code(j) == v) ++j;
        put_u16(b, static_cast<std::uint16_t>(v));
        put_u32(b, static_cast<std::uint32_t>(j - i));
        i = j;
    }
    put_u32(b, static_cast<std::uint32_t>(seg.parts.size()));
    for (const StructurePart& p : seg.parts) {
        put_i32(b, static_cast<std::int32_t>(p.kind));
        put_vec3(b, p.centre);
        for (const glm::vec3& a : p.axis) put_vec3(b, a);
        put_vec3(b, p.half_extent);
        put_i32(b, p.voxels);
        put_f32(b, p.peak_depth);
        put_vec3(b, p.spread);
    }
    put_u64(b, fnv1a64(b.data(), b.size()));
    return b;
}

}  // namespace

bool write_structure_parts(const std::filesystem::path& path,
                           const StructureSegmentation& seg) {
    if (path.empty()) return false;
    const glm::ivec3 d = seg.vol.dims;
    if (d.x <= 0 || d.y <= 0 || d.z <= 0) return false;
    const std::uint64_t n = static_cast<std::uint64_t>(d.x) * static_cast<std::uint64_t>(d.y) *
                            static_cast<std::uint64_t>(d.z);
    if (n > kMaxCells || seg.vol.occ.size() != n || seg.label.size() != n) return false;

    const std::string bytes = encode(seg);

    std::error_code ec;
    if (path.has_parent_path()) {
        std::filesystem::create_directories(path.parent_path(), ec);
        if (ec) { report_write_failure(path, ec.message()); return false; }
    }
    // Appended on the path itself, never through path.string() (ANSI on MSVC;
    // see dvox.cc). Unique per write (unique_tmp_suffix).
    std::filesystem::path tmp = path;
    tmp += unique_tmp_suffix();
    {
        std::ofstream s(tmp, std::ios::binary | std::ios::trunc);
        if (!s) {
            report_write_failure(path, std::strerror(errno));
            return false;
        }
        s.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
        // Close and check: a late failure (ENOSPC) surfaces only here.
        s.close();
        if (s.fail()) {
            const std::string why = std::strerror(errno);
            std::filesystem::remove(tmp, ec);
            report_write_failure(path, why);
            return false;
        }
    }
    std::filesystem::rename(tmp, path, ec);
    if (ec) {
        const std::string why = ec.message();
        std::filesystem::remove(tmp, ec);
        report_write_failure(path, why);
        return false;
    }
    return true;
}

std::optional<StructureSegmentation> read_structure_parts(
    const std::filesystem::path& path) {
    const auto bytes = assets::read_binary_file(path);
    if (!bytes) return std::nullopt;
    const std::string b(bytes->begin(), bytes->end());
    if (b.size() < 4 + 8) return std::nullopt;
    const std::size_t payload = b.size() - 8;
    if (fnv1a64(b.data(), payload) != read_u64_le(b, payload)) return std::nullopt;

    Reader r{b, 0, payload};
    if (std::memcmp(b.data(), kMagic, 4) != 0 || !r.take(4)) return std::nullopt;
    std::uint32_t version = 0;
    if (!r.u32(version) || version != kStructurePartsVersion) return std::nullopt;

    StructureSegmentation seg;
    glm::ivec3& d = seg.vol.dims;
    if (!r.i32(d.x) || !r.i32(d.y) || !r.i32(d.z)) return std::nullopt;
    if (d.x <= 0 || d.y <= 0 || d.z <= 0) return std::nullopt;
    // Two-step bound: each dim is untrusted, the triple product could wrap.
    std::uint64_t cells = static_cast<std::uint64_t>(d.x) * static_cast<std::uint64_t>(d.y);
    if (cells > kMaxCells) return std::nullopt;
    cells *= static_cast<std::uint64_t>(d.z);
    if (cells > kMaxCells) return std::nullopt;
    if (!r.vec3(seg.vol.origin) || !r.vec3(seg.vol.cell)) return std::nullopt;

    std::uint32_t count = 0;
    if (!r.u32(count) || count != cells) return std::nullopt;
    seg.vol.occ.assign(cells, 0);
    seg.label.assign(cells, -1);
    int max_label = -1;
    for (std::uint64_t i = 0; i < cells;) {
        std::uint16_t raw = 0;
        std::uint32_t run = 0;
        if (!r.u16(raw) || !r.u32(run) || run == 0 || run > cells - i) return std::nullopt;
        const auto v = static_cast<std::int16_t>(raw);
        if (v < kSolidNoPart) return std::nullopt;
        if (v != kEmpty) {
            std::fill_n(seg.vol.occ.begin() + static_cast<std::ptrdiff_t>(i), run, 1);
            if (v >= 0) {
                std::fill_n(seg.label.begin() + static_cast<std::ptrdiff_t>(i), run, v);
                if (v > max_label) max_label = v;
            }
        }
        i += run;
    }

    std::uint32_t nparts = 0;
    if (!r.u32(nparts)) return std::nullopt;
    if (static_cast<int>(nparts) <= max_label || nparts > 32767) return std::nullopt;
    seg.parts.resize(nparts);
    for (StructurePart& p : seg.parts) {
        std::int32_t kind = 0;
        if (!r.i32(kind) || kind < 0 || kind > static_cast<int>(PartKind::Cylinder))
            return std::nullopt;
        p.kind = static_cast<PartKind>(kind);
        if (!r.vec3(p.centre)) return std::nullopt;
        for (glm::vec3& a : p.axis)
            if (!r.vec3(a)) return std::nullopt;
        if (!r.vec3(p.half_extent) || !r.i32(p.voxels) || !r.f32(p.peak_depth) ||
            !r.vec3(p.spread))
            return std::nullopt;
    }
    if (r.at != payload) return std::nullopt;   // trailing bytes: not our layout
    return seg;
}

}  // namespace voxel
