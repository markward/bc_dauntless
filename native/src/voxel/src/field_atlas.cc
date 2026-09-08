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

    // l.valid() (above) only proves width, height and slices are POSITIVE --
    // it says nothing about whether they are LARGE ENOUGH. A hand-built
    // layout can carry tile_w/tile_h/slices that agree with f (passing the
    // check just above) while tiles_x/tiles_y don't cover every slice, or
    // width/height are narrower than tiles_x*tile_w/tiles_y*tile_h demand.
    // Either lets the write loop below index past its own row stride or
    // past the tail of `out`. This check is independent of l.valid(), not a
    // restatement of it: every one of these conditions can be violated
    // while width, height and slices all stay strictly positive.
    if (l.tiles_x <= 0 || l.tiles_y <= 0 ||
        l.tiles_x * l.tiles_y < l.slices ||
        l.width < l.tile_w * l.tiles_x ||
        l.height < l.tile_h * l.tiles_y) {
        return {};
    }

    constexpr std::uint8_t kOutside = 128 + 127;   // unused tile: fully outside
    std::vector<std::uint8_t> out(
        static_cast<std::size_t>(l.width) * static_cast<std::size_t>(l.height),
        kOutside);

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

}  // namespace voxel
