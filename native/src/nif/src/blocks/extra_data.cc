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

// NiBinaryVoxelData v3.x — partial parser.
//
// niflib's auto-gen Read describes a fixed-size header (3 uint16 + 7 floats
// + 7×12 bytes) followed by `Num Unknown Vectors` (uint32) + Vector4 array
// + `Num Unknown Bytes 2` (uint32) + byte array + 5 trailing uint32. That
// layout doesn't match real BC v3.x voxel files: the bytes after the
// 7-float bounds section are clearly RLE/bit-packed voxel grid data, not
// the schema's variable-length structure.
//
// Across all 84 _vox files in the BC asset corpus, NiBinaryVoxelData is
// always followed immediately by the End Of File sentinel (verified via
// list_nif_blocks.py inventory). So we use a pragmatic scan: read the
// fixed-size header (3 dimension shorts + 7 bound floats), then advance
// the cursor byte-by-byte until the next 15 bytes match the EOF marker
// (`0b 00 00 00 "End Of File"`). The walker resumes on the marker and
// the file completes cleanly. The opaque voxel-grid bytes between the
// header and the EOF marker are stored in `raw_voxel_payload` for future
// decoding work.
namespace {
inline constexpr std::size_t kEofMarkerSize = 15;
inline constexpr unsigned char kEofMarker[kEofMarkerSize] = {
    0x0b, 0x00, 0x00, 0x00,
    'E','n','d',' ','O','f',' ','F','i','l','e',
};

NiBinaryVoxelData parse_NiBinaryVoxelData_body(Reader& r) {
    NiBinaryVoxelData d;
    d.unknown_short1 = r.read_uint16();
    d.unknown_short2 = r.read_uint16();
    d.unknown_short3 = r.read_uint16();
    for (auto& f : d.unknown_7_floats) f = r.read_float();
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
