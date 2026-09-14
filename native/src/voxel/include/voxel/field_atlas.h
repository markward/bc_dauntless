// native/src/voxel/include/voxel/field_atlas.h
#pragma once

#include <cstdint>
#include <vector>

#include <glm/glm.hpp>

#include <voxel/distance_field.h>

namespace voxel {

/// Layout of a 2D atlas that tiles every Z-slice of a DistanceField into one
/// texture. A 3D field cannot reach opaque.frag as a sampler3D -- measured on
/// this machine, a sampler3D there corrupts shading across four test suites
/// even on a branch that never executes it -- so slices become tiles in a
/// sampler2D instead.
///
/// Each tile is `dims.x * dims.y` interior texels plus a 1-texel border that
/// REPLICATES its own nearest interior texel. The border exists because the
/// shader samples with hardware bilinear filtering: without it, a fragment
/// near a slice edge would blend in the neighbouring TILE's texels, which
/// belong to a different Z-slice entirely, and the hull would grow holes
/// along every tile seam.
struct AtlasLayout {
    int tile_w = 0, tile_h = 0;      // dims.x + 2, dims.y + 2 (1-texel border)
    int tiles_x = 0, tiles_y = 0;    // slice grid
    int width = 0, height = 0;       // tile_w * tiles_x, tile_h * tiles_y
    int slices = 0;                  // dims.z

    bool valid() const { return width > 0 && height > 0 && slices > 0; }
};

/// Compute the tile grid for a field of shape `dims`. Roughly square:
/// tiles_x = ceil(sqrt(dims.z)), tiles_y = ceil(dims.z / tiles_x), so the
/// atlas texture is never a single very-wide or very-tall strip. Any
/// non-positive component of `dims` yields a default-constructed (invalid)
/// layout.
AtlasLayout atlas_layout_for(const glm::ivec3& dims);

/// Pack every Z-slice of `f` into a GL_R8 atlas per `l`: interior texel
/// (x, y) of slice s (at atlas position `(tile_ox + 1 + x, tile_oy + 1 + y)`,
/// where `tile_ox/tile_oy` is tile s's origin) holds `d + 128`, so 128 is the
/// surface and the shader's `sample_hull_field` compares against
/// `texel - 128.0/255.0` (NOT `texel - 0.5`; opaque.frag's own comment at the
/// subtraction calls that out as load-bearing -- the two happen to be
/// numerically close but are not the same expression). The 1-texel
/// border around each tile is filled by clamping the source coordinate into
/// `[0, dims-1]` -- the same rule GL_CLAMP_TO_EDGE would apply within a
/// slice -- so it always replicates the nearest interior texel, never a
/// neighbouring tile's data.
///
/// Any tile beyond `dims.z` (when `tiles_x * tiles_y > dims.z`) is filled
/// with `128 - 127` (the most-negative byte the format holds, i.e. "no
/// damage" under the per-instance field's damage encoding -- see
/// renderer/instance_field_cache.h), so a sampling bug that reaches an
/// unused tile reads as untouched hull rather than as a hole.
///
/// Returns an empty vector when `f.empty()`, when `f.dims` has a
/// non-positive component, when `!l.valid()`, when `l`'s `tile_w`/`tile_h`/
/// `slices` do not match `f.dims`, or when `l`'s `tiles_x`/`tiles_y`/`width`/
/// `height` are not large enough to actually hold every one of `l.slices`
/// tiles (`tiles_x*tiles_y < slices`, or `width`/`height` narrower than
/// `tiles_x*tile_w`/`tiles_y*tile_h`). Any of these would otherwise index
/// the atlas buffer using tile geometry that doesn't match its own
/// dimensions -- `l.valid()` alone is not sufficient: it only proves width,
/// height and slices are positive, not that they are large enough.
std::vector<std::uint8_t> pack_field_to_atlas(const DistanceField& f,
                                              const AtlasLayout& l);

/// A texel rectangle of the atlas: the sub-image a region upload sends.
struct AtlasRect {
    int x = 0, y = 0, w = 0, h = 0;
};

/// The atlas rectangle that slice `z` of `box` occupies, INCLUDING the
/// replicated border texels on any side where the box touches the lattice
/// edge (the border copies the edge cell, so it changes when the edge cell
/// does). Caller guarantees `box` is non-empty, within `dims`, and that
/// `z` lies in [box.lo.z, box.hi.z].
AtlasRect atlas_rect_for(const AtlasLayout& l, const glm::ivec3& dims,
                         const CellBox& box, int z);

/// Re-encode only `box` into an atlas previously produced by
/// pack_field_to_atlas for the same field and layout, so that a carve costs
/// its own cell count rather than the whole lattice. Refreshes the border
/// texels beside any lattice edge the box touches. The result is byte-
/// identical to a fresh pack_field_to_atlas of the same field -- pinned by
/// field_atlas_test. Returns false (writing nothing) for an empty or
/// out-of-range box, a layout that does not match `f`, or an `atlas` whose
/// size is not width*height.
bool pack_field_region_to_atlas(const DistanceField& f, const AtlasLayout& l,
                                const CellBox& box,
                                std::vector<std::uint8_t>& atlas);

}  // namespace voxel
