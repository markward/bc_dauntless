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

// NiBinaryVoxelData v3.x — confirmed-header parser.
//
// Cleanroom analysis of all 84 *_vox.nif files in the BC asset corpus
// confirmed the header is exactly 34 bytes (documented in
// docs/original_game_reference/engine/nif-voxel-format.md):
//
//   3 × uint16  grid dimensions (dim_x, dim_y, dim_z)
//   1 × float   cell edge length (cell_size)
//   3 × float   AABB min corner (aabb_min)
//   3 × float   AABB max corner (aabb_max)
//
// After the header comes a variable-length opaque payload whose container
// layout is understood (bitmask[L] | numVectors | Vector4[] planes |
// numBytes2 | bytes2 | trailer u32[5]) but whose occupancy-bitmask codec
// is not yet resolved. The payload is therefore kept opaque in
// `raw_voxel_payload`.
//
// NiBinaryVoxelData is always the last block before the EOF sentinel across
// the entire corpus. We walk byte-by-byte after the header until the next
// 15 bytes match the EOF marker (`0b 00 00 00 "End Of File"`); the walker
// resumes on the marker and the file completes cleanly.
//
// NOTE: niflib's auto-gen schema described a different layout (3 uint16 +
// 7 floats + 7×12 bytes + numVectors + Vec3[] + numBytes2 + byte[] +
// uint32[5]). The 7×12-byte section is niflib's misparse of the variable-
// length bitmask; it does not exist. All niflib dead-field declarations
// have been removed from NiBinaryVoxelData.
namespace {
inline constexpr std::size_t kEofMarkerSize = 15;
inline constexpr unsigned char kEofMarker[kEofMarkerSize] = {
    0x0b, 0x00, 0x00, 0x00,
    'E','n','d',' ','O','f',' ','F','i','l','e',
};

NiBinaryVoxelData parse_NiBinaryVoxelData_body(Reader& r) {
    NiBinaryVoxelData d;
    d.dim_x = r.read_uint16();
    d.dim_y = r.read_uint16();
    d.dim_z = r.read_uint16();
    d.cell_size = r.read_float();
    for (auto& f : d.aabb_min) f = r.read_float();
    for (auto& f : d.aabb_max) f = r.read_float();
    // Reserve up to the remaining bytes (minus the marker we'll stop at)
    // so push_back doesn't trigger O(log n) reallocations on the 230KB-class
    // voxel payloads.
    auto remaining = r.bytes_remaining();
    if (remaining > kEofMarkerSize) {
        d.raw_voxel_payload.reserve(remaining - kEofMarkerSize);
    }
    // First-byte quick reject: only pay for the 15-byte memcmp when the next
    // byte is 0x0b (the EOF length-prefix's LSB). Cuts the per-byte cost on
    // the 84 _vox files dramatically — almost every byte fails the cheap
    // first-byte check.
    while (r.bytes_remaining() >= kEofMarkerSize) {
        if (r.peek_uint8() == kEofMarker[0]) {
            unsigned char buf[kEofMarkerSize];
            r.peek_bytes(buf, kEofMarkerSize);
            if (std::memcmp(buf, kEofMarker, kEofMarkerSize) == 0) {
                break;  // walker resumes on the marker
            }
        }
        d.raw_voxel_payload.push_back(r.read_uint8());
    }
    return d;
}
}  // namespace

NIF_REGISTER_BLOCK(NiBinaryVoxelData, [](Reader& r) -> Block {
    return parse_NiBinaryVoxelData_body(r);
});

}  // namespace nif
