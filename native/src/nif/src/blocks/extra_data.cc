// native/src/nif/src/blocks/extra_data.cc
//
// NiStringExtraData parser for NIF v3.1.
//
// Per niflib (BSD), v3.1 NiExtraData reads only a `next_extra_data_link`
// uint32 (the per-extra-data linked-list pointer) — `name` is since
// v10.0.1.0 so absent in v3.1. NiStringExtraData adds bytes_remaining
// (uint32) + stringData (uint32 length + ASCII bytes).
#include "../dispatch.h"
#include "../reader.h"

#include <nif/block.h>

namespace nif {

NIF_REGISTER_BLOCK(NiStringExtraData, [](Reader& r) -> Block {
    NiStringExtraData d;
    d.next_extra_data_link = r.read_uint32();
    d.bytes_remaining = r.read_uint32();
    d.string_data = r.read_string_uint32();
    return d;
});

// NiBinaryVoxelExtraData v3.1: NiExtraData base + unknown_int + data_link.
// Used as the root block of every "_vox.nif" voxel-collision file.
NIF_REGISTER_BLOCK(NiBinaryVoxelExtraData, [](Reader& r) -> Block {
    NiBinaryVoxelExtraData d;
    d.next_extra_data_link = r.read_uint32();
    d.unknown_int = r.read_uint32();
    d.data_link = r.read_uint32();
    return d;
});

// NiBinaryVoxelData parser intentionally NOT registered. niflib's auto-gen
// Read expects an `unknownBytes1[7][12]` array followed by Vector4-typed
// unknownVectors and a trailing `unknown5Ints[5]`, but on real BC v3.x
// `_vox.nif` files this layout produces truncation errors and length-zero
// desyncs. Determining the real v3.x layout is its own investigation.
//
// Files that have an NiBinaryVoxelExtraData reach that block, then the
// walker reports "stuck on NiBinaryVoxelData" cleanly — useful coverage
// data for future work.

}  // namespace nif
