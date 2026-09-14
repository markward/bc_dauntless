// native/src/voxel/src/field_atlas.cc
#include <voxel/field_atlas.h>

#include <algorithm>
#include <cmath>

namespace voxel {

AtlasLayout atlas_layout_for(const glm::ivec3& dims) {
    if (dims.x <= 0 || dims.y <= 0 || dims.z <= 0) return AtlasLayout{};

    AtlasLayout l;
    l.tile_w = dims.x + 2;
    l.tile_h = dims.y + 2;
    l.tiles_x = std::max(1, static_cast<int>(
        std::ceil(std::sqrt(static_cast<double>(dims.z)))));
    l.tiles_y = (dims.z + l.tiles_x - 1) / l.tiles_x;   // ceil(dims.z / tiles_x)
    l.width = l.tile_w * l.tiles_x;
    l.height = l.tile_h * l.tiles_y;
    l.slices = dims.z;
    return l;
}

std::vector<std::uint8_t> pack_field_to_atlas(const DistanceField& f,
                                              const AtlasLayout& l) {
    if (f.empty() || !l.valid()) return {};

    // f.dims must itself be non-degenerate: an empty f already caught most
    // ways this could go wrong, but empty() only reflects dist being empty,
    // not dims. A non-positive dims.x/y would make the std::clamp(ty, 0,
    // dims.y - 1) below undefined behaviour (its [lo, hi] would be inverted).
    if (f.dims.x <= 0 || f.dims.y <= 0 || f.dims.z <= 0) return {};

    // l must describe f's own shape. A mismatch (e.g. a layout built from a
    // different field, or hand-constructed) would otherwise index the atlas
    // with one field's tile geometry while reading another's cells --
    // reject rather than risk an out-of-bounds read or write.
    if (l.tile_w != f.dims.x + 2 || l.tile_h != f.dims.y + 2 ||
        l.slices != f.dims.z) {
        return {};
    }

    // l.valid() was already checked true at this function's entry (above),
    // which by itself guarantees width, height and slices are all POSITIVE
    // by the time we get here -- this guard is fully SUBSUMED by that check
    // for positivity, not independent of it. What valid() cannot express is
    // whether they are LARGE ENOUGH: a hand-built layout can carry tile_w/
    // tile_h/slices that agree with f (passing the shape-match check just
    // above) while tiles_x/tiles_y don't cover every slice, or width/height
    // are narrower than tiles_x*tile_w/tiles_y*tile_h demand. Either lets
    // the write loop below index past its own row stride or past the tail
    // of `out`.
    if (l.tiles_x <= 0 || l.tiles_y <= 0 ||
        l.tiles_x * l.tiles_y < l.slices ||
        l.width < l.tile_w * l.tiles_x ||
        l.height < l.tile_h * l.tiles_y) {
        return {};
    }

    // Unused tile fill: the per-instance field carries DAMAGE, not hull
    // shape (instance_field_cache.h) -- negative means "no damage", positive
    // means "carved/discard". 128 - 127 = 1 is the most-negative byte the
    // format can hold, i.e. "deepest no-damage", so a sampling bug that
    // reaches an unused tile reads as untouched hull rather than as a hole.
    // The OLD polarity here (128 + 127, "fully outside the hull") was
    // correct only while this atlas packed a hull SDF; under the damage
    // encoding that same byte would read as "deep inside a carve" --
    // exactly backwards -- so this is a deliberate flip, not a renaming.
    constexpr std::uint8_t kNoDamage = 128 - 127;
    std::vector<std::uint8_t> out(
        static_cast<std::size_t>(l.width) * static_cast<std::size_t>(l.height),
        kNoDamage);

    auto encode = [](std::int8_t d) -> std::uint8_t {
        return static_cast<std::uint8_t>(static_cast<int>(d) + 128);
    };

    for (int s = 0; s < l.slices; ++s) {
        const int tile_ox = (s % l.tiles_x) * l.tile_w;
        const int tile_oy = (s / l.tiles_x) * l.tile_h;

        // ty/tx range over [-1, dims] inclusive: -1 and dims are the 1-texel
        // border, everything between is interior. Clamping the source
        // coordinate into [0, dims-1] is the same rule GL_CLAMP_TO_EDGE
        // would apply within a slice, so the border always replicates the
        // nearest interior texel of THIS slice, never a neighbouring tile's.
        for (int ty = -1; ty <= f.dims.y; ++ty) {
            const int sy = std::clamp(ty, 0, f.dims.y - 1);
            const int ay = tile_oy + 1 + ty;
            for (int tx = -1; tx <= f.dims.x; ++tx) {
                const int sx = std::clamp(tx, 0, f.dims.x - 1);
                const int ax = tile_ox + 1 + tx;
                out[static_cast<std::size_t>(ay) * l.width + ax] =
                    encode(f.dist[f.index(sx, sy, s)]);
            }
        }
    }

    return out;
}

AtlasRect atlas_rect_for(const AtlasLayout& l, const glm::ivec3& dims,
                         const CellBox& box, int z) {
    const int tile_ox = (z % l.tiles_x) * l.tile_w;
    const int tile_oy = (z / l.tiles_x) * l.tile_h;
    // Texel coordinates run over [-1, dims] per slice (see pack_field_to_
    // atlas): widen by one on each side that sits on the lattice edge.
    const int tx0 = (box.lo.x == 0)          ? -1     : box.lo.x;
    const int tx1 = (box.hi.x == dims.x - 1) ? dims.x : box.hi.x;
    const int ty0 = (box.lo.y == 0)          ? -1     : box.lo.y;
    const int ty1 = (box.hi.y == dims.y - 1) ? dims.y : box.hi.y;
    AtlasRect r;
    r.x = tile_ox + 1 + tx0;
    r.y = tile_oy + 1 + ty0;
    r.w = tx1 - tx0 + 1;
    r.h = ty1 - ty0 + 1;
    return r;
}

bool pack_field_region_to_atlas(const DistanceField& f, const AtlasLayout& l,
                                const CellBox& box,
                                std::vector<std::uint8_t>& atlas) {
    if (f.empty() || !l.valid() || box.empty()) return false;
    if (f.dims.x <= 0 || f.dims.y <= 0 || f.dims.z <= 0) return false;
    if (l.tile_w != f.dims.x + 2 || l.tile_h != f.dims.y + 2 ||
        l.slices != f.dims.z) {
        return false;
    }
    if (l.tiles_x <= 0 || l.tiles_y <= 0 ||
        l.tiles_x * l.tiles_y < l.slices ||
        l.width < l.tile_w * l.tiles_x ||
        l.height < l.tile_h * l.tiles_y) {
        return false;
    }
    if (atlas.size() != static_cast<std::size_t>(l.width)
                        * static_cast<std::size_t>(l.height)) {
        return false;
    }
    if (box.lo.x < 0 || box.lo.y < 0 || box.lo.z < 0 ||
        box.hi.x >= f.dims.x || box.hi.y >= f.dims.y || box.hi.z >= f.dims.z) {
        return false;
    }

    auto encode = [](std::int8_t d) -> std::uint8_t {
        return static_cast<std::uint8_t>(static_cast<int>(d) + 128);
    };

    for (int s = box.lo.z; s <= box.hi.z; ++s) {
        const int tile_ox = (s % l.tiles_x) * l.tile_w;
        const int tile_oy = (s / l.tiles_x) * l.tile_h;
        // Same [-1, dims] texel range and clamp rule as the full pack, so
        // the border beside a touched edge cell is re-derived from it.
        const int ty0 = (box.lo.y == 0)            ? -1       : box.lo.y;
        const int ty1 = (box.hi.y == f.dims.y - 1) ? f.dims.y : box.hi.y;
        const int tx0 = (box.lo.x == 0)            ? -1       : box.lo.x;
        const int tx1 = (box.hi.x == f.dims.x - 1) ? f.dims.x : box.hi.x;
        for (int ty = ty0; ty <= ty1; ++ty) {
            const int sy = std::clamp(ty, 0, f.dims.y - 1);
            const int ay = tile_oy + 1 + ty;
            for (int tx = tx0; tx <= tx1; ++tx) {
                const int sx = std::clamp(tx, 0, f.dims.x - 1);
                const int ax = tile_ox + 1 + tx;
                atlas[static_cast<std::size_t>(ay) * l.width + ax] =
                    encode(f.dist[f.index(sx, sy, s)]);
            }
        }
    }
    return true;
}

}  // namespace voxel
