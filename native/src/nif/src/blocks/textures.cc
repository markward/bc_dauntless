// native/src/nif/src/blocks/textures.cc
//
// Texture-related parsers for NIF v3.1 (legacy pre-10.1 family):
//   - NiTextureModeProperty: NiObjectNET + flags(u16) + ps2_l(i16) + ps2_k(i16)
//   - NiImage: use_external(u8) + (file_name | image_data_link) + unknown_int + unknown_float
//   - NiTextureProperty: NiObjectNET + flags(u16) + image_link(u32)
//
// NiMultiTextureProperty inherits from NiTexturingProperty which has a much
// larger conditional body (texture descriptors per slot). Deferred until a
// later task — Galaxy.nif uses NiTextureProperty/NiImage which suffice for
// the walker's first pass through ship blocks.

#include "../dispatch.h"
#include "../reader.h"
#include "av_object_base.h"

#include <nif/block.h>

#include <cstdint>

namespace nif {

namespace {

NiTextureModeProperty parse_NiTextureModeProperty_body(Reader& r) {
    NiTextureModeProperty p;
    p.obj = parse_object_net_base(r);
    p.flags = r.read_uint16();
    // PS2 L / PS2 K are since 3.1 — absent in v3.0.
    if (r.version().value >= 0x03010000) {
        p.ps2_l = static_cast<std::int16_t>(r.read_uint16());
        p.ps2_k = static_cast<std::int16_t>(r.read_uint16());
    }
    return p;
}

NiImage parse_NiImage_body(Reader& r) {
    NiImage img;
    img.use_external = r.read_uint8();
    if (img.use_external != 0) {
        img.file_name = r.read_string_uint32();
    } else {
        img.image_data_link = r.read_uint32();
    }
    img.unknown_int = r.read_uint32();
    // unknown_float appeared since 3.1 — absent in v3.0.
    if (r.version().value >= 0x03010000) {
        img.unknown_float = r.read_float();
    }
    return img;
}

NiTextureProperty parse_NiTextureProperty_body(Reader& r) {
    NiTextureProperty p;
    p.obj = parse_object_net_base(r);
    p.flags = r.read_uint16();
    p.image_link = r.read_uint32();
    // Unknown Ints 2 (2 × uint32) — present in v3.0 only (since 3.0 until 3.03).
    // v3.0 = 0x03000000, v3.03 = 0x03000300, v3.1 = 0x03010000 > 3.03.
    if (r.version().value >= 0x03000000 && r.version().value <= 0x03000300) {
        r.read_uint32();
        r.read_uint32();
    }
    return p;
}

// Reads a single TexDesc body (no leading hasXxx bool — caller decides).
// Per niflib's TexDesc Read for v3.1: source_link + clamp + filter + uv_set
// + ps2_l + ps2_k + unknown1.
TexDesc read_tex_desc_body(Reader& r) {
    TexDesc t;
    t.has = true;
    t.source_link = r.read_uint32();
    t.clamp_mode = r.read_uint32();
    t.filter_mode = r.read_uint32();
    t.uv_set = r.read_uint32();
    t.ps2_l = static_cast<std::int16_t>(r.read_uint16());
    t.ps2_k = static_cast<std::int16_t>(r.read_uint16());
    t.unknown1 = r.read_uint16();
    return t;
}

bool read_bool32(Reader& r) { return r.read_uint32() != 0; }

void read_optional_tex_desc(Reader& r, TexDesc& out) {
    if (read_bool32(r)) {
        out = read_tex_desc_body(r);
    }
}

// NiTexturingProperty body for v3.1, per niflib's NiTexturingProperty::Read.
//   NiObjectNET base
//   flags        (uint16)         // version <= 0x0A000102
//   apply_mode   (uint32)         // version <= 0x14000005
//   texture_count(uint32)
//   base/dark/detail/gloss/glow texture descriptors (each: hasXxx bool + TexDesc)
//   bump_map: hasBump bool + (TexDesc + lumaScale + lumaOffset + Matrix22)
//   (normal/unknown2 textures are SKIPPED in v3.1 — version >= 14.2.0.7 only)
//   decal0: hasDecal0 bool + TexDesc
//   if texture_count >= 8: hasDecal1 bool + TexDesc
//   if texture_count >= 9: hasDecal2 bool + TexDesc
NiTexturingProperty parse_NiTexturingProperty_body(Reader& r) {
    NiTexturingProperty p;
    p.obj = parse_object_net_base(r);
    p.flags = r.read_uint16();
    p.apply_mode = r.read_uint32();
    p.texture_count = r.read_uint32();

    read_optional_tex_desc(r, p.base);
    read_optional_tex_desc(r, p.dark);
    read_optional_tex_desc(r, p.detail);
    read_optional_tex_desc(r, p.gloss);
    read_optional_tex_desc(r, p.glow);

    if (read_bool32(r)) {
        p.bump_map = read_tex_desc_body(r);
        p.bump_map_luma_scale = r.read_float();
        p.bump_map_luma_offset = r.read_float();
        for (auto& f : p.bump_map_matrix) f = r.read_float();
    }

    read_optional_tex_desc(r, p.decal0);
    if (p.texture_count >= 8) read_optional_tex_desc(r, p.decal1);
    if (p.texture_count >= 9) read_optional_tex_desc(r, p.decal2);

    return p;
}

}  // namespace

NIF_REGISTER_BLOCK(NiTextureModeProperty, [](Reader& r) -> Block {
    return parse_NiTextureModeProperty_body(r);
});

NIF_REGISTER_BLOCK(NiImage, [](Reader& r) -> Block {
    return parse_NiImage_body(r);
});

NIF_REGISTER_BLOCK(NiTextureProperty, [](Reader& r) -> Block {
    return parse_NiTextureProperty_body(r);
});

// NiRawImageData: legacy embedded-image data (referenced by NiImage when
// use_external == 0). width, height, image_type (1=RGB, 2=RGBA), then
// width × height × {3|4} bytes of pixel data. Per niflib's auto-gen Read.
NIF_REGISTER_BLOCK(NiRawImageData, [](Reader& r) -> Block {
    NiRawImageData d;
    d.width = r.read_uint32();
    d.height = r.read_uint32();
    d.image_type = r.read_uint32();
    std::size_t channels = 0;
    if (d.image_type == 1) channels = 3;
    else if (d.image_type == 2) channels = 4;
    if (channels > 0 && d.width > 0 && d.height > 0) {
        std::size_t total = static_cast<std::size_t>(d.width) *
                            static_cast<std::size_t>(d.height) * channels;
        d.pixels.resize(total);
        r.read_bytes(d.pixels.data(), total);
    }
    return d;
});

NIF_REGISTER_BLOCK(NiTexturingProperty, [](Reader& r) -> Block {
    return parse_NiTexturingProperty_body(r);
});

// NiMultiTextureProperty has its own body (NOT NiTexturingProperty's,
// despite the schema). 5 MultiTextureElement entries; per niflib for v3.1:
//   NiObjectNET base
//   flags (uint16), unknown_int (uint32)
//   for i in 0..4:
//     has_image (uint32 bool)
//     if has_image: image_link, clamp, filter, uv_set, (since 3.0.3) ps2L+K, unknown_short3
NIF_REGISTER_BLOCK(NiMultiTextureProperty, [](Reader& r) -> Block {
    NiMultiTextureProperty p;
    p.obj = parse_object_net_base(r);
    p.flags = r.read_uint16();
    p.unknown_int = r.read_uint32();
    for (auto& e : p.elements) {
        e.has_image = read_bool32(r);
        if (e.has_image) {
            e.image_link = r.read_uint32();
            e.clamp_mode = r.read_uint32();
            e.filter_mode = r.read_uint32();
            e.uv_set = r.read_uint32();
            // ps2L/K + unknown_short3 are present since 0x03000300 — applies
            // for v3.1 (0x03010000 > 0x03000300).
            e.ps2_l = static_cast<std::int16_t>(r.read_uint16());
            e.ps2_k = static_cast<std::int16_t>(r.read_uint16());
            e.unknown_short3 = r.read_uint16();
        }
    }
    return p;
});

}  // namespace nif
