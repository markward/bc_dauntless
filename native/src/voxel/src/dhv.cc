// native/src/voxel/src/dhv.cc
#include <voxel/dhv.h>

#include <cstring>
#include <fstream>
#include <system_error>
#include <vector>

namespace voxel {

namespace {

constexpr char  kMagic[4]        = {'D', 'H', 'V', '1'};
constexpr std::uint16_t kFormat  = 1;
// A hull volume is small (the whole stock fleet is ~7 MB at 2x quality). A
// header claiming more than this is corrupt, not ambitious.
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

bool write_dhv(const std::filesystem::path& path,
               const DistanceField& field,
               const HullVolumeMeta& meta) {
    std::error_code ec;
    if (path.has_parent_path())
        std::filesystem::create_directories(path.parent_path(), ec);

    const std::filesystem::path tmp = path.string() + ".tmp";
    bool write_ok = false;
    {
        std::ofstream s(tmp, std::ios::binary | std::ios::trunc);
        if (!s) return false;

        s.write(kMagic, 4);
        put(s, kFormat);
        put(s, meta.baker_version);
        put(s, meta.source_size);
        put(s, meta.source_mtime);
        put(s, field.dims.x); put(s, field.dims.y); put(s, field.dims.z);
        put(s, field.origin.x); put(s, field.origin.y); put(s, field.origin.z);
        put(s, field.cell.x); put(s, field.cell.y); put(s, field.cell.z);
        put(s, meta.authored_res);
        put(s, meta.quality);
        put(s, field.scale);

        const std::uint32_t plen =
            static_cast<std::uint32_t>(meta.source_path.size());
        put(s, plen);
        s.write(meta.source_path.data(), static_cast<std::streamsize>(plen));

        s.write(reinterpret_cast<const char*>(field.dist.data()),
                static_cast<std::streamsize>(field.dist.size()));

        // Explicitly close (which flushes) and check the result BEFORE
        // deciding write_ok. Our whole ~150-byte-plus-payload write easily
        // fits inside the filebuf's internal buffer, so the individual
        // s.write() calls above can all report success without a single
        // underlying write() syscall having happened yet -- a failure that
        // only surfaces at the real flush (e.g. ENOSPC landing on the last
        // buffered chunk) would otherwise be invisible until AFTER we had
        // already committed to write_ok = true, letting a short file get
        // renamed into place as if it were valid.
        s.close();
        write_ok = !s.fail();
    }
    if (!write_ok) {
        // Partial write: drop the temp file rather than leaving debris a
        // later run might mistake for a stale-but-otherwise-valid cache
        // entry (it never sits at `path`, so read_dhv would never see it
        // anyway, but there is no reason to leak it).
        std::error_code rm_ec;
        std::filesystem::remove(tmp, rm_ec);
        return false;
    }
    std::filesystem::rename(tmp, path, ec);
    if (ec) { std::filesystem::remove(tmp, ec); return false; }
    return true;
}

bool read_dhv(const std::filesystem::path& path,
              DistanceField& out_field,
              HullVolumeMeta& out_meta) {
    std::ifstream s(path, std::ios::binary);
    if (!s) return false;

    char magic[4] = {};
    s.read(magic, 4);
    if (!s || std::memcmp(magic, kMagic, 4) != 0) return false;

    std::uint16_t format = 0;
    HullVolumeMeta m;
    DistanceField f;
    if (!get(s, format) || format != kFormat) return false;
    if (!get(s, m.baker_version) || m.baker_version != kBakerVersion) return false;
    if (!get(s, m.source_size)) return false;
    if (!get(s, m.source_mtime)) return false;
    if (!get(s, f.dims.x) || !get(s, f.dims.y) || !get(s, f.dims.z)) return false;
    if (!get(s, f.origin.x) || !get(s, f.origin.y) || !get(s, f.origin.z)) return false;
    if (!get(s, f.cell.x) || !get(s, f.cell.y) || !get(s, f.cell.z)) return false;
    if (!get(s, m.authored_res)) return false;
    if (!get(s, m.quality)) return false;
    if (!get(s, f.scale)) return false;

    std::uint32_t plen = 0;
    if (!get(s, plen)) return false;
    if (plen > 4096) return false;             // implausible: corrupt
    m.source_path.assign(plen, '\0');
    if (plen > 0) {
        s.read(m.source_path.data(), static_cast<std::streamsize>(plen));
        if (!s) return false;
    }

    // dims==(0,0,0) is not corruption: it is the documented return of
    // distance_field_from_tris() for a hull with no triangles (missing
    // source, unparseable NIF, or a genuinely empty mesh) -- see
    // distance_field.h. That empty field is a legitimate bake result and
    // must round-trip through this container like any other, so only a
    // MIXED zero/negative combination (one axis zero or negative while
    // another is not) is rejected as a malformed grid.
    const bool all_zero = f.dims.x == 0 && f.dims.y == 0 && f.dims.z == 0;
    if (!all_zero && (f.dims.x <= 0 || f.dims.y <= 0 || f.dims.z <= 0)) return false;
    // Multiply and bounds-check in two steps rather than forming
    // dims.x*dims.y*dims.z in one expression. Each dim is an attacker-
    // controlled positive int32 (up to ~2^31); the full triple product can
    // overflow uint64 and wrap back under kMaxCells, which would let a
    // corrupt header past this guard with `dims` inconsistent with the
    // (small, wrapped) cell count actually allocated below. Checking after
    // the first multiply caps the running product at kMaxCells (~2^26)
    // before the second multiply, so that step's operands (<=2^26 and
    // <=2^31) can't overflow uint64 either.
    std::uint64_t cells = static_cast<std::uint64_t>(f.dims.x)
                         * static_cast<std::uint64_t>(f.dims.y);
    if (cells > kMaxCells) return false;
    cells *= static_cast<std::uint64_t>(f.dims.z);
    if (cells > kMaxCells) return false;

    f.dist.resize(static_cast<std::size_t>(cells));
    s.read(reinterpret_cast<char*>(f.dist.data()),
           static_cast<std::streamsize>(cells));
    // gcount, not the stream state: a payload SHORTER than the header claims
    // is the crash-mid-write case, and must be rejected rather than padded.
    if (static_cast<std::uint64_t>(s.gcount()) != cells) return false;

    out_field = std::move(f);
    out_meta  = std::move(m);
    return true;
}

}  // namespace voxel
